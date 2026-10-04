"""FX-57A: fast, DB-free unit tests for `IngestNewsSourceOnce` against
an in-memory `FakeNewsRepository` -- mirrors `test_record_news_
observation.py`'s own fake (locally redefined here, following this
test suite's per-module fake convention)."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from forex_agent.application.ports.news_repository import (
    FirstObservationResult,
    NewsItemRegistrationOutcome,
    NewsVintageConflictError,
    NewsVintageWriteOutcome,
)
from forex_agent.application.ports.news_source import (
    NewsSourceChannelFetcher,
    NewsSourceFetchContractError,
    NewsSourceFetchOutcome,
    NewsSourceUnavailableError,
    NormalizedNewsObservation,
)
from forex_agent.application.use_cases.ingest_news_source_once import (
    CrossChannelIdentityCollisionError,
    IngestNewsSourceOnce,
    SourceKeyMismatchError,
)
from forex_agent.application.use_cases.record_news_observation import (
    NewsObservationOutOfOrderError,
    RecordNewsObservation,
)
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item import NewsItem
from forex_agent.domain.news_item_identity import mint_news_item_key
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp

_SOURCE_KEY = "FED"


class FakeNewsRepository:
    def __init__(self) -> None:
        self._items: dict[str, NewsItem] = {}
        self._mappings: dict[tuple[str, str], str] = {}
        self._vintages: dict[str, list[NewsItemVintage]] = {}

    async def register_source_item_with_first_vintage(
        self,
        identity: NewsSourceIdentity,
        observed_at: UtcTimestamp,
        observation_mode: NewsObservationMode,
        build_vintage: Callable[[str], NewsItemVintage],
    ) -> FirstObservationResult:
        key = (identity.source_key, identity.external_item_id)
        existing_key = self._mappings.get(key)
        if existing_key is not None:
            return FirstObservationResult(existing_key, NewsItemRegistrationOutcome.ALREADY_EXISTS)

        candidate_key = mint_news_item_key(identity.source_key)
        vintage = build_vintage(candidate_key)
        self._items[candidate_key] = NewsItem(candidate_key, observed_at, observation_mode)
        self._mappings[key] = candidate_key
        self._vintages[candidate_key] = [vintage]
        return FirstObservationResult(candidate_key, NewsItemRegistrationOutcome.CREATED)

    async def get_item(self, news_item_key: str) -> NewsItem | None:
        return self._items.get(news_item_key)

    async def get_item_by_source_identity(self, identity: NewsSourceIdentity) -> NewsItem | None:
        key = self._mappings.get((identity.source_key, identity.external_item_id))
        return None if key is None else self._items.get(key)

    async def add_vintage(self, vintage: NewsItemVintage) -> NewsVintageWriteOutcome:
        existing_list = self._vintages.setdefault(vintage.news_item_key, [])
        for existing in existing_list:
            if existing.revision_sequence == vintage.revision_sequence:
                if existing == vintage:
                    return NewsVintageWriteOutcome.ALREADY_PRESENT
                raise NewsVintageConflictError(existing, vintage)
        existing_list.append(vintage)
        return NewsVintageWriteOutcome.INSERTED

    async def list_vintages(self, news_item_key: str) -> tuple[NewsItemVintage, ...]:
        return tuple(self._vintages.get(news_item_key, []))

    async def latest_vintage_as_of(
        self, news_item_key: str, as_of: UtcTimestamp
    ) -> NewsItemVintage | None:
        candidates = [
            v for v in self._vintages.get(news_item_key, []) if v.availability.value <= as_of.value
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda v: (v.availability.value, v.revision_sequence))

    async def latest_evidence_eligible_vintage_as_of(
        self, news_item_key: str, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> NewsItemVintage | None:
        candidates = [
            v
            for v in self._vintages.get(news_item_key, [])
            if v.availability.value <= as_of.value
            and v.evidence_disposition is NewsEvidenceDisposition.EVIDENCE_ELIGIBLE
            and (include_backfill or v.observation_mode is not NewsObservationMode.BACKFILL)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda v: (v.availability.value, v.revision_sequence))


def _ts(hour: int = 12) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 10, 3, hour, 0, 0, tzinfo=UTC))


def _observation(
    external_item_id: str = "guid-1",
    headline: str = "A Headline",
    observed_at: UtcTimestamp | None = None,
    source_key: str = _SOURCE_KEY,
    source_channel: str = "press_monetary",
) -> NormalizedNewsObservation:
    return NormalizedNewsObservation(
        source_key=source_key,
        external_item_id=external_item_id,
        observed_at=observed_at or _ts(),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline=headline,
        source_channel=source_channel,
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    )


def _fetcher_returning(outcome: NewsSourceFetchOutcome) -> NewsSourceChannelFetcher:
    async def fetcher() -> NewsSourceFetchOutcome:
        return outcome

    return fetcher


def _fetcher_raising(exc: Exception) -> NewsSourceChannelFetcher:
    async def fetcher() -> NewsSourceFetchOutcome:
        raise exc

    return fetcher


@pytest.mark.asyncio
async def test_single_observation_is_created() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    outcome = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=_ts(),
        observations=(_observation(),),
        items_invalid=0,
    )
    result = await ingest((_fetcher_returning(outcome),))

    assert result.created == 1
    assert result.revisions_added == 0
    assert result.unchanged == 0
    assert result.items_fetched == 1
    assert result.items_normalized == 1
    assert result.items_processed == 1
    assert result.items_invalid == 0
    assert result.source_channels == ("press_monetary",)
    assert result.errors == ()


@pytest.mark.asyncio
async def test_repeated_identical_observation_is_unchanged() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    outcome = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=_ts(12),
        observations=(_observation(observed_at=_ts(12)),),
        items_invalid=0,
    )
    first = await ingest((_fetcher_returning(outcome),))
    outcome2 = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=_ts(13),
        observations=(_observation(observed_at=_ts(13)),),
        items_invalid=0,
    )
    second = await ingest((_fetcher_returning(outcome2),))

    assert first.created == 1
    assert second.created == 0
    assert second.unchanged == 1
    assert second.revisions_added == 0


@pytest.mark.asyncio
async def test_same_guid_changed_headline_adds_a_revision() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    first_outcome = NewsSourceFetchOutcome(
        source_channel="speeches",
        retrieved_at=_ts(12),
        observations=(_observation(headline="A", observed_at=_ts(12), source_channel="speeches"),),
        items_invalid=0,
    )
    await ingest((_fetcher_returning(first_outcome),))

    second_outcome = NewsSourceFetchOutcome(
        source_channel="speeches",
        retrieved_at=_ts(13),
        observations=(_observation(headline="B", observed_at=_ts(13), source_channel="speeches"),),
        items_invalid=0,
    )
    second = await ingest((_fetcher_returning(second_outcome),))

    assert second.revisions_added == 1
    assert second.created == 0


@pytest.mark.asyncio
async def test_one_channel_failure_does_not_abort_other_channels() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    good_outcome = NewsSourceFetchOutcome(
        source_channel="speeches",
        retrieved_at=_ts(),
        observations=(_observation(external_item_id="good-guid", source_channel="speeches"),),
        items_invalid=0,
    )
    result = await ingest(
        (
            _fetcher_raising(NewsSourceUnavailableError("feed unreachable")),
            _fetcher_returning(good_outcome),
        )
    )

    assert result.created == 1
    assert len(result.errors) == 1
    assert "unreachable" in result.errors[0]
    assert result.source_channels == ("speeches",)


@pytest.mark.asyncio
async def test_item_invalid_counts_and_reasons_are_aggregated() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    outcome = NewsSourceFetchOutcome(
        source_channel="testimony",
        retrieved_at=_ts(),
        observations=(),
        items_invalid=2,
        invalid_reasons=("item at index 0: missing guid", "item at index 1: missing title"),
    )
    result = await ingest((_fetcher_returning(outcome),))

    assert result.items_invalid == 2
    assert result.items_fetched == 2
    assert result.items_normalized == 0
    assert result.items_processed == 0
    assert "item at index 0: missing guid" in result.errors
    assert "item at index 1: missing title" in result.errors


@pytest.mark.asyncio
async def test_one_valid_plus_one_invalid_item_counters_match_worked_example() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    outcome = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=_ts(),
        observations=(_observation(external_item_id="valid-1"),),
        items_invalid=1,
        invalid_reasons=("item at index 1: missing title",),
    )
    result = await ingest((_fetcher_returning(outcome),))

    assert result.items_fetched == 2
    assert result.items_normalized == 1
    assert result.items_invalid == 1
    assert result.items_processed == 1
    assert result.created == 1


@pytest.mark.asyncio
async def test_identical_duplicate_guid_within_response_is_deduped_idempotently() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    observed_at = _ts()
    outcome = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=observed_at,
        observations=(
            _observation(external_item_id="dup", headline="Same", observed_at=observed_at),
            _observation(external_item_id="dup", headline="Same", observed_at=observed_at),
        ),
        items_invalid=0,
    )
    result = await ingest((_fetcher_returning(outcome),))

    assert result.items_fetched == 2
    assert result.items_normalized == 2
    assert result.items_processed == 1
    assert result.created == 1
    assert result.errors == ()


@pytest.mark.asyncio
async def test_conflicting_duplicate_guid_within_response_fails_closed_for_that_response() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    observed_at = _ts()
    conflicting_outcome = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=observed_at,
        observations=(
            _observation(external_item_id="dup", headline="A", observed_at=observed_at),
            _observation(external_item_id="dup", headline="B", observed_at=observed_at),
        ),
        items_invalid=0,
    )
    other_outcome = NewsSourceFetchOutcome(
        source_channel="speeches",
        retrieved_at=observed_at,
        observations=(
            _observation(
                external_item_id="unrelated", observed_at=observed_at, source_channel="speeches"
            ),
        ),
        items_invalid=0,
    )
    result = await ingest(
        (_fetcher_returning(conflicting_outcome), _fetcher_returning(other_outcome))
    )

    assert result.created == 1  # only the unrelated, non-conflicting channel persisted
    assert len(result.errors) == 1
    assert "dup" in result.errors[0]


@pytest.mark.asyncio
async def test_out_of_order_error_propagates_and_is_never_swallowed() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    first_outcome = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=_ts(14),
        observations=(_observation(observed_at=_ts(14)),),
        items_invalid=0,
    )
    await ingest((_fetcher_returning(first_outcome),))

    backdated_outcome = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=_ts(10),
        observations=(_observation(headline="Changed", observed_at=_ts(10)),),
        items_invalid=0,
    )
    with pytest.raises(NewsObservationOutOfOrderError):
        await ingest((_fetcher_returning(backdated_outcome),))


@pytest.mark.asyncio
async def test_matching_source_key_succeeds() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    outcome = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=_ts(),
        observations=(_observation(source_key=_SOURCE_KEY),),
        items_invalid=0,
    )
    result = await ingest((_fetcher_returning(outcome),))
    assert result.created == 1


@pytest.mark.asyncio
async def test_one_mismatched_source_key_observation_fails_closed() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    outcome = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=_ts(),
        observations=(_observation(source_key="ECB"),),
        items_invalid=0,
    )
    with pytest.raises(SourceKeyMismatchError):
        await ingest((_fetcher_returning(outcome),))


@pytest.mark.asyncio
async def test_no_mismatched_evidence_reaches_record_news_observation() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    outcome = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=_ts(),
        observations=(_observation(external_item_id="wrongly-wired", source_key="BOE"),),
        items_invalid=0,
    )
    with pytest.raises(SourceKeyMismatchError):
        await ingest((_fetcher_returning(outcome),))

    identity = NewsSourceIdentity(source_key="BOE", external_item_id="wrongly-wired")
    assert await repo.get_item_by_source_identity(identity) is None
    fed_identity = NewsSourceIdentity(source_key=_SOURCE_KEY, external_item_id="wrongly-wired")
    assert await repo.get_item_by_source_identity(fed_identity) is None


@pytest.mark.asyncio
async def test_result_source_key_never_disagrees_with_persisted_source_identity() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    outcome = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=_ts(),
        observations=(_observation(source_key=_SOURCE_KEY),),
        items_invalid=0,
    )
    result = await ingest((_fetcher_returning(outcome),))
    assert result.source_key == _SOURCE_KEY

    identity = NewsSourceIdentity(source_key=_SOURCE_KEY, external_item_id="guid-1")
    item = await repo.get_item_by_source_identity(identity)
    assert item is not None


@pytest.mark.asyncio
async def test_response_observation_channel_mismatch_never_reaches_record_news_observation() -> (
    None
):
    # FX-57BH Section 5.C: a fetcher that tries to build a response
    # whose own observation disagrees with the response's own
    # source_channel fails AT CONSTRUCTION TIME, before the fetcher
    # even returns -- so IngestNewsSourceOnce never sees a value to
    # catch, and the mismatch can never reach RecordNewsObservation.
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))

    async def bad_fetcher() -> NewsSourceFetchOutcome:
        return NewsSourceFetchOutcome(
            source_channel="ecb_press",
            retrieved_at=_ts(),
            observations=(_observation(source_channel="wrong_channel"),),
            items_invalid=0,
        )

    with pytest.raises(NewsSourceFetchContractError):
        await ingest((bad_fetcher,))

    identity = NewsSourceIdentity(source_key=_SOURCE_KEY, external_item_id="guid-1")
    assert await repo.get_item_by_source_identity(identity) is None


# --- FX-57CH Section 9: cross-channel identity collision matrix -----------


@pytest.mark.asyncio
async def test_a_single_identity_in_one_channel_succeeds() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    outcome = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=_ts(),
        observations=(_observation(external_item_id="guid-x", source_channel="press_monetary"),),
        items_invalid=0,
    )
    result = await ingest((_fetcher_returning(outcome),))
    assert result.created == 1
    assert result.errors == ()


@pytest.mark.asyncio
async def test_b_disjoint_identities_across_two_channels_both_succeed() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    outcome_a = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=_ts(),
        observations=(_observation(external_item_id="guid-x", source_channel="press_monetary"),),
        items_invalid=0,
    )
    outcome_b = NewsSourceFetchOutcome(
        source_channel="speeches",
        retrieved_at=_ts(),
        observations=(_observation(external_item_id="guid-y", source_channel="speeches"),),
        items_invalid=0,
    )
    result = await ingest((_fetcher_returning(outcome_a), _fetcher_returning(outcome_b)))

    assert result.created == 2
    assert result.errors == ()
    identity_x = NewsSourceIdentity(source_key=_SOURCE_KEY, external_item_id="guid-x")
    identity_y = NewsSourceIdentity(source_key=_SOURCE_KEY, external_item_id="guid-y")
    assert await repo.get_item_by_source_identity(identity_x) is not None
    assert await repo.get_item_by_source_identity(identity_y) is not None


@pytest.mark.asyncio
async def test_c_same_identity_in_two_channels_within_one_run_fails_closed_before_persistence() -> (
    None
):
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    outcome_a = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=_ts(),
        observations=(
            _observation(external_item_id="guid-shared", source_channel="press_monetary"),
        ),
        items_invalid=0,
    )
    outcome_b = NewsSourceFetchOutcome(
        source_channel="speeches",
        retrieved_at=_ts(),
        observations=(_observation(external_item_id="guid-shared", source_channel="speeches"),),
        items_invalid=0,
    )

    with pytest.raises(CrossChannelIdentityCollisionError) as exc_info:
        await ingest((_fetcher_returning(outcome_a), _fetcher_returning(outcome_b)))
    assert exc_info.value.external_item_id == "guid-shared"
    assert exc_info.value.channels == frozenset({"press_monetary", "speeches"})

    identity = NewsSourceIdentity(source_key=_SOURCE_KEY, external_item_id="guid-shared")
    assert await repo.get_item_by_source_identity(identity) is None


@pytest.mark.asyncio
async def test_d_one_channel_fetch_failure_plus_two_disjoint_successful_channels_still_ingest() -> (
    None
):
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    outcome_b = NewsSourceFetchOutcome(
        source_channel="speeches",
        retrieved_at=_ts(),
        observations=(_observation(external_item_id="guid-b", source_channel="speeches"),),
        items_invalid=0,
    )
    outcome_c = NewsSourceFetchOutcome(
        source_channel="testimony",
        retrieved_at=_ts(),
        observations=(_observation(external_item_id="guid-c", source_channel="testimony"),),
        items_invalid=0,
    )

    result = await ingest(
        (
            _fetcher_raising(NewsSourceUnavailableError("channel A unreachable")),
            _fetcher_returning(outcome_b),
            _fetcher_returning(outcome_c),
        )
    )

    assert result.created == 2
    assert len(result.errors) == 1
    assert "unreachable" in result.errors[0]


@pytest.mark.asyncio
async def test_e_fetch_failure_plus_colliding_successful_channels_persists_nothing() -> None:
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))
    outcome_b = NewsSourceFetchOutcome(
        source_channel="speeches",
        retrieved_at=_ts(),
        observations=(_observation(external_item_id="guid-shared", source_channel="speeches"),),
        items_invalid=0,
    )
    outcome_c = NewsSourceFetchOutcome(
        source_channel="testimony",
        retrieved_at=_ts(),
        observations=(_observation(external_item_id="guid-shared", source_channel="testimony"),),
        items_invalid=0,
    )

    with pytest.raises(CrossChannelIdentityCollisionError):
        await ingest(
            (
                _fetcher_raising(NewsSourceUnavailableError("channel A unreachable")),
                _fetcher_returning(outcome_b),
                _fetcher_returning(outcome_c),
            )
        )

    identity = NewsSourceIdentity(source_key=_SOURCE_KEY, external_item_id="guid-shared")
    assert await repo.get_item_by_source_identity(identity) is None


@pytest.mark.asyncio
async def test_f_same_identity_across_separate_ingestion_runs_remains_a_sequential_vintage() -> (
    None
):
    # Section 3: the collision guard is scoped to ONE `__call__`
    # invocation -- the SAME identity observed under a DIFFERENT
    # channel on a LATER, separate call remains an ordinary
    # provenance-change vintage, exactly as before FX-57CH.
    repo = FakeNewsRepository()
    ingest = IngestNewsSourceOnce(_SOURCE_KEY, RecordNewsObservation(repo))

    first_run = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=_ts(12),
        observations=(
            _observation(
                external_item_id="guid-sequential",
                observed_at=_ts(12),
                source_channel="press_monetary",
            ),
        ),
        items_invalid=0,
    )
    first_result = await ingest((_fetcher_returning(first_run),))

    second_run = NewsSourceFetchOutcome(
        source_channel="speeches",
        retrieved_at=_ts(13),
        observations=(
            _observation(
                external_item_id="guid-sequential",
                observed_at=_ts(13),
                source_channel="speeches",
            ),
        ),
        items_invalid=0,
    )
    second_result = await ingest((_fetcher_returning(second_run),))

    assert first_result.created == 1
    assert second_result.revisions_added == 1

    identity = NewsSourceIdentity(source_key=_SOURCE_KEY, external_item_id="guid-sequential")
    item = await repo.get_item_by_source_identity(identity)
    assert item is not None
    vintages = await repo.list_vintages(item.news_item_key)
    assert len(vintages) == 2

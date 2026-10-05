"""FX-56H.1: fast, DB-free unit tests for `RecordNewsObservation`
against an in-memory `FakeNewsRepository`.

Complements the existing live-Postgres integration suite in
`tests/integration/test_record_news_observation.py` -- these tests
exist specifically to pin the corrected PIT-ordering PRECEDENCE
(Section 1) quickly and in isolation, and to structurally prove
Section 3's own contract: `FakeNewsRepository` implements EXACTLY the
`NewsRepository` Protocol's own methods, with no bare, content-less
`register_source_item`. If `RecordNewsObservation` (or any future
change to it) ever called such a method, this fake would raise a
plain `AttributeError` immediately -- a direct regression guard for
"no production code path can create an item without its revision-0
vintage," independent of whatever the concrete `SqlAlchemyNews
Repository` happens to expose for its own test setup.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from forex_agent.application.ports.news_repository import (
    FirstObservationResult,
    NewsItemRegistrationOutcome,
    NewsRepository,
    NewsVintageConflictError,
    NewsVintageWriteOutcome,
)
from forex_agent.application.ports.news_source import NormalizedNewsObservation
from forex_agent.application.use_cases.record_news_observation import (
    NewsObservationOutOfOrderError,
    RecordNewsObservation,
    RecordNewsObservationOutcome,
)
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item import NewsItem
from forex_agent.domain.news_item_identity import mint_news_item_key
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp


class FakeNewsRepository:
    """Minimal in-memory implementation of `NewsRepository` --
    deliberately carries NO bare, content-less creating operation
    (see this module's own docstring)."""

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
        if (
            vintage.revision_sequence != 0
            or vintage.availability != observed_at
            or vintage.observation_mode != observation_mode
        ):
            raise ValueError("first vintage shape mismatch")

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


def test_fake_repository_satisfies_the_protocol() -> None:
    # Section 3/8's own structural proof: the fake above implements
    # exactly the Protocol's own methods -- no bare `register_source_
    # item` exists on it at all.
    repo: NewsRepository = FakeNewsRepository()
    assert not hasattr(repo, "register_source_item")


def _ts(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, minute, tzinfo=UTC))


def _observation(
    external_item_id: str, observed_at: UtcTimestamp, headline: str, **overrides: object
) -> NormalizedNewsObservation:
    defaults: dict[str, object] = {
        "source_key": "FAKE",
        "external_item_id": external_item_id,
        "observed_at": observed_at,
        "observation_mode": NewsObservationMode.PROSPECTIVE,
        "headline": headline,
        "source_channel": "test_channel",
        "source_status": NewsSourceStatus.ACTIVE,
        "evidence_disposition": NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    }
    defaults.update(overrides)
    return NormalizedNewsObservation(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def repo() -> FakeNewsRepository:
    return FakeNewsRepository()


@pytest.fixture
def use_case(repo: FakeNewsRepository) -> RecordNewsObservation:
    return RecordNewsObservation(repo)


async def test_first_observation_is_created(use_case: RecordNewsObservation) -> None:
    result = await use_case(_observation("x1", _ts(2026, 9, 29, 9, 0), "Headline"))
    assert result.outcome is RecordNewsObservationOutcome.CREATED
    assert result.revision_sequence == 0


async def test_identical_later_observation_is_unchanged(
    use_case: RecordNewsObservation,
) -> None:
    await use_case(_observation("x2", _ts(2026, 9, 29, 9, 0), "Same"))
    second = await use_case(_observation("x2", _ts(2026, 9, 29, 10, 0), "Same"))
    assert second.outcome is RecordNewsObservationOutcome.UNCHANGED
    assert second.revision_sequence == 0


async def test_identical_equal_timestamp_observation_is_unchanged(
    use_case: RecordNewsObservation,
) -> None:
    # FX-56H.1 Section 1: equal timestamps remain permitted -- the
    # ordering check is strictly "<", never "<=".
    same = _ts(2026, 9, 29, 9, 0)
    first = await use_case(_observation("x3", same, "Same"))
    second = await use_case(_observation("x3", same, "Same"))
    assert second.outcome is RecordNewsObservationOutcome.UNCHANGED
    assert second.revision_sequence == first.revision_sequence == 0


async def test_changed_later_observation_adds_revision(use_case: RecordNewsObservation) -> None:
    await use_case(_observation("x4", _ts(2026, 9, 29, 9, 0), "A"))
    second = await use_case(_observation("x4", _ts(2026, 9, 29, 10, 0), "B"))
    assert second.outcome is RecordNewsObservationOutcome.REVISION_ADDED
    assert second.revision_sequence == 1


async def test_new_channel_alone_adds_a_revision_not_a_new_item(
    use_case: RecordNewsObservation,
) -> None:
    # FX-57E0 Section 9/10 (Matrix B): observed_source_channels, not
    # the bare source_channel, now participates in modeled-fact
    # equality -- gaining a NEW channel for the SAME external identity
    # is a new vintage of the SAME item, never a new item, even when
    # the headline itself is unchanged, because FTA's own cumulative
    # channel knowledge genuinely grew.
    first = await use_case(
        _observation("x4b", _ts(2026, 9, 29, 9, 0), "Same headline", source_channel="channel_a")
    )
    second = await use_case(
        _observation("x4b", _ts(2026, 9, 29, 10, 0), "Same headline", source_channel="channel_b")
    )
    assert second.outcome is RecordNewsObservationOutcome.REVISION_ADDED
    assert second.news_item_key == first.news_item_key
    assert second.revision_sequence == 1
    assert second.channel_added is True


async def test_repeated_same_channel_is_unchanged(use_case: RecordNewsObservation) -> None:
    # FX-57E0 Matrix A: re-observing an ALREADY-known channel, with
    # otherwise identical content, must never mint a new revision.
    first = await use_case(
        _observation("x4c", _ts(2026, 9, 29, 9, 0), "Same headline", source_channel="channel_a")
    )
    second = await use_case(
        _observation("x4c", _ts(2026, 9, 29, 10, 0), "Same headline", source_channel="channel_a")
    )
    assert second.outcome is RecordNewsObservationOutcome.UNCHANGED
    assert second.revision_sequence == first.revision_sequence == 0
    assert second.channel_added is False


async def test_third_channel_adds_to_the_cumulative_set(use_case: RecordNewsObservation) -> None:
    await use_case(
        _observation("x4d", _ts(2026, 9, 29, 9, 0), "Same headline", source_channel="channel_a")
    )
    await use_case(
        _observation("x4d", _ts(2026, 9, 29, 10, 0), "Same headline", source_channel="channel_b")
    )
    third = await use_case(
        _observation("x4d", _ts(2026, 9, 29, 11, 0), "Same headline", source_channel="channel_c")
    )
    assert third.outcome is RecordNewsObservationOutcome.REVISION_ADDED
    assert third.revision_sequence == 2
    assert third.channel_added is True


async def test_later_observation_of_an_already_known_first_channel_adds_no_revision(
    use_case: RecordNewsObservation,
) -> None:
    await use_case(
        _observation("x4e", _ts(2026, 9, 29, 9, 0), "Same headline", source_channel="channel_a")
    )
    await use_case(
        _observation("x4e", _ts(2026, 9, 29, 10, 0), "Same headline", source_channel="channel_b")
    )
    # Re-observing channel_a again, with identical content, after
    # channel_b is already known must NOT create a third revision --
    # channel membership is monotonic and this adds nothing new.
    third = await use_case(
        _observation("x4e", _ts(2026, 9, 29, 11, 0), "Same headline", source_channel="channel_a")
    )
    assert third.outcome is RecordNewsObservationOutcome.UNCHANGED
    assert third.revision_sequence == 1
    assert third.channel_added is False


async def test_content_change_on_an_already_known_channel_preserves_cumulative_channels(
    use_case: RecordNewsObservation,
) -> None:
    # FX-57E0 Matrix D: a content change via an ALREADY-known channel
    # still adds a revision (for the content change itself), but the
    # cumulative channel set is unaffected -- channel_added is False.
    await use_case(
        _observation("x4f", _ts(2026, 9, 29, 9, 0), "Headline A", source_channel="channel_a")
    )
    await use_case(
        _observation("x4f", _ts(2026, 9, 29, 10, 0), "Headline A", source_channel="channel_b")
    )
    third = await use_case(
        _observation("x4f", _ts(2026, 9, 29, 11, 0), "Headline B", source_channel="channel_a")
    )
    assert third.outcome is RecordNewsObservationOutcome.REVISION_ADDED
    assert third.channel_added is False


async def test_first_observation_gets_singleton_observed_source_channels(
    use_case: RecordNewsObservation, repo: FakeNewsRepository
) -> None:
    result = await use_case(
        _observation("x4g", _ts(2026, 9, 29, 9, 0), "Headline", source_channel="channel_a")
    )
    vintages = await repo.list_vintages(result.news_item_key)
    assert vintages[0].observed_source_channels == ("channel_a",)


async def test_pit_before_second_channel_sees_only_first_channel(
    use_case: RecordNewsObservation, repo: FakeNewsRepository
) -> None:
    # FX-57E0 Section 25's own PIT worked example: T1 observes via
    # channel_a; T2 (later) observes via channel_b. A query strictly
    # between T1 and T2 must see ONLY channel_a; a query at/after T2
    # must see both.
    t1 = _ts(2026, 9, 29, 9, 0)
    t2 = _ts(2026, 9, 29, 10, 0)
    between = _ts(2026, 9, 29, 9, 30)

    first = await use_case(_observation("x4h", t1, "Same headline", source_channel="channel_a"))
    await use_case(_observation("x4h", t2, "Same headline", source_channel="channel_b"))

    as_of_between = await repo.latest_vintage_as_of(first.news_item_key, between)
    assert as_of_between is not None
    assert as_of_between.observed_source_channels == ("channel_a",)

    as_of_t2 = await repo.latest_vintage_as_of(first.news_item_key, t2)
    assert as_of_t2 is not None
    assert as_of_t2.observed_source_channels == ("channel_a", "channel_b")


async def test_identical_but_earlier_observation_fails_closed(
    use_case: RecordNewsObservation,
) -> None:
    # FX-56H.1 Section 1's own central correction: an earlier
    # observed_at must fail closed EVEN IF the facts are identical --
    # silently returning UNCHANGED would knowingly preserve an
    # availability history known to be wrong.
    await use_case(_observation("x5", _ts(2026, 9, 29, 10, 0), "Same"))
    with pytest.raises(NewsObservationOutOfOrderError):
        await use_case(_observation("x5", _ts(2026, 9, 29, 9, 0), "Same"))


async def test_changed_but_earlier_observation_fails_closed(
    use_case: RecordNewsObservation,
) -> None:
    await use_case(_observation("x6", _ts(2026, 9, 29, 10, 0), "A"))
    with pytest.raises(NewsObservationOutOfOrderError):
        await use_case(_observation("x6", _ts(2026, 9, 29, 9, 0), "B"))

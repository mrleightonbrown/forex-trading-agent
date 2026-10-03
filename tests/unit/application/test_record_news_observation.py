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
        "source_status": NewsSourceStatus.ACTIVE,
        "evidence_disposition": NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    }
    defaults.update(overrides)
    return NormalizedNewsObservation(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def use_case() -> RecordNewsObservation:
    return RecordNewsObservation(FakeNewsRepository())


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

"""FX-56: `RecordNewsObservation` against the real
`SqlAlchemyNewsRepository`/live Postgres.

Mirrors `tests/integration/test_ingest_official_calendar.py`'s own
precedent of testing an ingestion-shaped application use case against
a real repository rather than an in-memory fake -- `Ingest
OfficialCalendarSchedule` has no fake-repository unit test either.

Requires a live Postgres with the FX-56 migration applied -- run
`docker compose up -d db && alembic upgrade head` first.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.ports.news_source import NormalizedNewsObservation
from forex_agent.application.use_cases.record_news_observation import (
    RecordNewsObservation,
    RecordNewsObservationOutcome,
)
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine

TEST_SOURCE_KEY = "__test_record_source__"
TEST_ITEM_PREFIX = "__test_record_source__"


def _ts(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, minute, second, tzinfo=UTC))


def _observation(
    external_item_id: str,
    observed_at: UtcTimestamp,
    headline: str,
    **overrides: object,
) -> NormalizedNewsObservation:
    defaults: dict[str, object] = {
        "source_key": TEST_SOURCE_KEY,
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
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        await cleanup_session.execute(
            delete(NewsItemVintageRow).where(
                NewsItemVintageRow.news_item_key.startswith(TEST_ITEM_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(NewsSourceMappingRow).where(
                NewsSourceMappingRow.source_key.startswith(TEST_SOURCE_KEY)
            )
        )
        await cleanup_session.execute(
            delete(NewsItemRow).where(NewsItemRow.news_item_key.startswith(TEST_ITEM_PREFIX))
        )
        await cleanup_session.commit()


@pytest.fixture
def use_case(session: AsyncSession) -> RecordNewsObservation:
    return RecordNewsObservation(SqlAlchemyNewsRepository(session))


async def test_first_observation_creates_item_and_revision_zero(
    use_case: RecordNewsObservation,
) -> None:
    observed_at = _ts(2026, 9, 29, 9, 2)
    result = await use_case(_observation("item-1", observed_at, "Headline A"))
    assert result.outcome is RecordNewsObservationOutcome.CREATED
    assert result.revision_sequence == 0


async def test_repeated_identical_observation_is_unchanged(
    use_case: RecordNewsObservation,
) -> None:
    observed_at_1 = _ts(2026, 9, 29, 9, 2)
    observed_at_2 = _ts(2026, 9, 29, 9, 5)
    first = await use_case(_observation("item-2", observed_at_1, "Same headline"))
    second = await use_case(_observation("item-2", observed_at_2, "Same headline"))

    assert second.outcome is RecordNewsObservationOutcome.UNCHANGED
    assert second.news_item_key == first.news_item_key
    assert second.revision_sequence == first.revision_sequence == 0


async def test_changed_headline_adds_a_revision(use_case: RecordNewsObservation) -> None:
    await use_case(_observation("item-3", _ts(2026, 9, 29, 10, 0), "Headline A"))
    second = await use_case(_observation("item-3", _ts(2026, 9, 29, 10, 10), "Headline B"))

    assert second.outcome is RecordNewsObservationOutcome.REVISION_ADDED
    assert second.revision_sequence == 1


async def test_different_external_id_same_headline_creates_different_items(
    use_case: RecordNewsObservation,
) -> None:
    # FX-56 Section 36: no fuzzy/content deduplication at this layer.
    first = await use_case(
        _observation("item-4a", _ts(2026, 9, 29, 10, 0), "Central bank statement")
    )
    second = await use_case(
        _observation("item-4b", _ts(2026, 9, 29, 10, 0), "Central bank statement")
    )
    assert first.news_item_key != second.news_item_key


async def test_source_updated_at_before_fta_observation_does_not_backdate_revision(
    use_case: RecordNewsObservation,
) -> None:
    # FX-56 Section 18/48: a source-claimed update time earlier than
    # FTA's own observation must never move the new revision's own
    # availability backward.
    await use_case(_observation("item-5", _ts(2026, 9, 29, 9, 0), "Original"))
    result = await use_case(
        _observation(
            "item-5",
            _ts(2026, 9, 29, 9, 14),
            "Corrected",
            source_updated_at=_ts(2026, 9, 29, 9, 10),
        )
    )
    assert result.outcome is RecordNewsObservationOutcome.REVISION_ADDED
    assert result.revision_sequence == 1

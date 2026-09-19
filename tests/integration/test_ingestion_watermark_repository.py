"""FX-26: `SqlAlchemyIngestionWatermarkRepository` round-trip tests.

Requires a live Postgres with the FX-26 migration applied — run
`docker compose up -d db && uv run alembic upgrade head` first.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.ingestion_watermark_repository import (
    SqlAlchemyIngestionWatermarkRepository,
)
from forex_agent.infrastructure.db.models.ingestion_watermark import IngestionWatermarkRow
from forex_agent.infrastructure.db.session import get_engine

# A currency pair unlikely to ever be real, to keep test rows unambiguous.
TEST_INSTRUMENT = Instrument(base_currency="ZZZ", quote_currency="YYY")


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        await cleanup_session.execute(
            delete(IngestionWatermarkRow).where(
                IngestionWatermarkRow.instrument == TEST_INSTRUMENT.symbol
            )
        )
        await cleanup_session.commit()


@pytest.mark.asyncio
async def test_get_watermark_returns_none_when_nothing_ingested(session: AsyncSession) -> None:
    repo = SqlAlchemyIngestionWatermarkRepository(session)

    result = await repo.get_watermark(TEST_INSTRUMENT, Granularity.M1)

    assert result is None


@pytest.mark.asyncio
async def test_set_then_get_round_trips(session: AsyncSession) -> None:
    repo = SqlAlchemyIngestionWatermarkRepository(session)
    earliest = UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))
    latest = UtcTimestamp(datetime(2026, 1, 2, tzinfo=UTC))

    await repo.set_watermark(TEST_INSTRUMENT, Granularity.M1, earliest, latest)
    result = await repo.get_watermark(TEST_INSTRUMENT, Granularity.M1)

    assert result == (earliest, latest)


@pytest.mark.asyncio
async def test_set_watermark_replaces_the_previous_value(session: AsyncSession) -> None:
    repo = SqlAlchemyIngestionWatermarkRepository(session)
    first_earliest = UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))
    first_latest = UtcTimestamp(datetime(2026, 1, 2, tzinfo=UTC))
    second_earliest = UtcTimestamp(datetime(2025, 12, 31, tzinfo=UTC))
    second_latest = UtcTimestamp(datetime(2026, 1, 5, tzinfo=UTC))

    await repo.set_watermark(TEST_INSTRUMENT, Granularity.M1, first_earliest, first_latest)
    await repo.set_watermark(TEST_INSTRUMENT, Granularity.M1, second_earliest, second_latest)
    result = await repo.get_watermark(TEST_INSTRUMENT, Granularity.M1)

    assert result == (second_earliest, second_latest)


@pytest.mark.asyncio
async def test_watermarks_are_independent_per_granularity(session: AsyncSession) -> None:
    repo = SqlAlchemyIngestionWatermarkRepository(session)
    m1_earliest = UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))
    m1_latest = UtcTimestamp(datetime(2026, 1, 2, tzinfo=UTC))

    await repo.set_watermark(TEST_INSTRUMENT, Granularity.M1, m1_earliest, m1_latest)
    h1_result = await repo.get_watermark(TEST_INSTRUMENT, Granularity.H1)
    m1_result = await repo.get_watermark(TEST_INSTRUMENT, Granularity.M1)

    assert h1_result is None
    assert m1_result == (m1_earliest, m1_latest)

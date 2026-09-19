"""End-to-end check that FX-8's DetectDataGaps reads a stored candle range
and correctly reports missing expected candles.

Requires a live Postgres with the FX-5 migration applied.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.detect_data_gaps import DetectDataGaps
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.candle_repository import SqlAlchemyCandleRepository
from forex_agent.infrastructure.db.models.candle import CandleRow
from forex_agent.infrastructure.db.session import get_engine

TEST_INSTRUMENT = Instrument(base_currency="ZZZ", quote_currency="VVV")


def _ts(minute: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC))


def _m1(minute: int) -> Candle:
    flat = Ohlc(open=Decimal("1.1"), high=Decimal("1.1"), low=Decimal("1.1"), close=Decimal("1.1"))
    return Candle(
        instrument=TEST_INSTRUMENT,
        granularity=Granularity.M1,
        start_time=_ts(minute),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )


def _h1(hour: int) -> Candle:
    flat = Ohlc(open=Decimal("1.1"), high=Decimal("1.1"), low=Decimal("1.1"), close=Decimal("1.1"))
    return Candle(
        instrument=TEST_INSTRUMENT,
        granularity=Granularity.H1,
        start_time=UtcTimestamp(datetime(2026, 1, 1, hour, 0, 0, tzinfo=UTC)),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        await cleanup_session.execute(
            delete(CandleRow).where(CandleRow.instrument == TEST_INSTRUMENT.symbol)
        )
        await cleanup_session.commit()


@pytest.mark.asyncio
async def test_detects_gap_in_stored_range(session: AsyncSession) -> None:
    repo = SqlAlchemyCandleRepository(session)
    await repo.upsert_many([_m1(0), _m1(1), _m1(3), _m1(4)])  # minute 2 missing
    use_case = DetectDataGaps(candles=repo)

    gaps = await use_case(TEST_INSTRUMENT, Granularity.M1, _ts(0), _ts(5))

    assert gaps == [_ts(2)]


@pytest.mark.asyncio
async def test_no_gaps_when_fully_stored(session: AsyncSession) -> None:
    repo = SqlAlchemyCandleRepository(session)
    await repo.upsert_many([_m1(m) for m in range(5)])
    use_case = DetectDataGaps(candles=repo)

    gaps = await use_case(TEST_INSTRUMENT, Granularity.M1, _ts(0), _ts(5))

    assert gaps == []


@pytest.mark.asyncio
async def test_does_not_falsely_report_the_boundary_candle_as_missing(
    session: AsyncSession,
) -> None:
    """Regression, found live while gap-checking the FX-27 research
    dataset: a non-boundary-aligned `start` (e.g. a watermark's own
    wall-clock `earliest_ingested`) must not make `DetectDataGaps` claim
    its rounded-down boundary candle is missing when it's actually
    present. `find_gaps` rounds `start` down to the nearest H1 boundary
    (00:00) when building its expected list; `get_range`'s own
    `start_time >= start` filter previously used the *unrounded* `start`
    (00:14:00), excluding the genuinely-present 00:00 candle from
    `stored` -- a guaranteed false positive whenever `start` isn't
    already boundary-aligned."""
    repo = SqlAlchemyCandleRepository(session)
    await repo.upsert_many([_h1(0), _h1(1), _h1(2)])  # fully covered, no real gaps
    use_case = DetectDataGaps(candles=repo)

    misaligned_start = UtcTimestamp(datetime(2026, 1, 1, 0, 14, 0, tzinfo=UTC))
    end = UtcTimestamp(datetime(2026, 1, 1, 3, 0, 0, tzinfo=UTC))

    gaps = await use_case(TEST_INSTRUMENT, Granularity.H1, misaligned_start, end)

    assert gaps == []

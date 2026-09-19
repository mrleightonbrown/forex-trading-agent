"""FX-27: `FakeCandleRepository.get_range`'s `source` filtering must match
the real `SqlAlchemyCandleRepository`'s behaviour (see
tests/integration/test_candle_repository.py for the live-Postgres
equivalents) -- fast use-case tests rely on this fake being faithful."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.ports.candle_repository import CandleRepository
from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_source import CandleSource
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.candle_repository import FakeCandleRepository

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
START = UtcTimestamp(datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC))
END = UtcTimestamp(datetime(2026, 1, 1, 0, 1, 0, tzinfo=UTC))


def _candle(source: CandleSource) -> Candle:
    flat = Ohlc(
        open=Decimal("1.0000"),
        high=Decimal("1.0010"),
        low=Decimal("0.9990"),
        close=Decimal("1.0000"),
    )
    return Candle(
        instrument=EUR_USD,
        granularity=Granularity.M1,
        start_time=START,
        bid=flat,
        ask=flat,
        volume=10,
        is_finalized=True,
        source=source,
    )


def test_fake_satisfies_candle_repository_protocol() -> None:
    # Assignment alone is the check: mypy verifies FakeCandleRepository
    # matches the CandleRepository Protocol shape structurally.
    fake: CandleRepository = FakeCandleRepository()
    assert fake is not None


@pytest.mark.asyncio
async def test_get_range_source_none_returns_all_provenances() -> None:
    fake = FakeCandleRepository()
    await fake.upsert_many([_candle(CandleSource.NATIVE), _candle(CandleSource.AGGREGATED)])

    result = await fake.get_range(EUR_USD, Granularity.M1, START, END, source=None)

    assert {c.source for c in result} == {CandleSource.NATIVE, CandleSource.AGGREGATED}


@pytest.mark.asyncio
async def test_get_range_source_native_filters_to_native_only() -> None:
    fake = FakeCandleRepository()
    await fake.upsert_many([_candle(CandleSource.NATIVE), _candle(CandleSource.AGGREGATED)])

    result = await fake.get_range(EUR_USD, Granularity.M1, START, END, source=CandleSource.NATIVE)

    assert [c.source for c in result] == [CandleSource.NATIVE]


@pytest.mark.asyncio
async def test_get_range_source_aggregated_filters_to_aggregated_only() -> None:
    fake = FakeCandleRepository()
    await fake.upsert_many([_candle(CandleSource.NATIVE), _candle(CandleSource.AGGREGATED)])

    result = await fake.get_range(
        EUR_USD, Granularity.M1, START, END, source=CandleSource.AGGREGATED
    )

    assert [c.source for c in result] == [CandleSource.AGGREGATED]

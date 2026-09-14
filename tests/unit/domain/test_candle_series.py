from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_series import require_consistent_series
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
GBP_USD = Instrument(base_currency="GBP", quote_currency="USD")


def _ts(minute: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC))


def _candle(
    minute: int, instrument: Instrument = EUR_USD, granularity: Granularity = Granularity.M1
) -> Candle:
    flat = Ohlc(open=Decimal("1.1"), high=Decimal("1.1"), low=Decimal("1.1"), close=Decimal("1.1"))
    return Candle(
        instrument=instrument,
        granularity=granularity,
        start_time=_ts(minute),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )


def test_returns_instrument_and_granularity() -> None:
    candles = [_candle(0), _candle(1)]

    instrument, granularity = require_consistent_series(candles)

    assert instrument == EUR_USD
    assert granularity is Granularity.M1


def test_rejects_empty_candles() -> None:
    with pytest.raises(ValueError, match="empty"):
        require_consistent_series([])


def test_rejects_mixed_instruments() -> None:
    with pytest.raises(ValueError, match="instrument"):
        require_consistent_series([_candle(0), _candle(1, instrument=GBP_USD)])


def test_rejects_mixed_granularity() -> None:
    with pytest.raises(ValueError, match="granularity"):
        require_consistent_series([_candle(0), _candle(1, granularity=Granularity.M5)])


def test_rejects_non_ascending() -> None:
    with pytest.raises(ValueError, match="ascending"):
        require_consistent_series([_candle(1), _candle(0)])


def test_rejects_duplicate_timestamps() -> None:
    with pytest.raises(ValueError, match="ascending"):
        require_consistent_series([_candle(0), _candle(0)])

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
BID = Ohlc(
    open=Decimal("1.1000"), high=Decimal("1.1010"), low=Decimal("1.0990"), close=Decimal("1.1005")
)
ASK = Ohlc(
    open=Decimal("1.1002"), high=Decimal("1.1012"), low=Decimal("1.0992"), close=Decimal("1.1007")
)
START = UtcTimestamp(datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))


def _candle(**overrides: object) -> Candle:
    defaults: dict[str, object] = {
        "instrument": EUR_USD,
        "granularity": Granularity.M1,
        "start_time": START,
        "bid": BID,
        "ask": ASK,
        "volume": 100,
        "is_finalized": True,
    }
    defaults.update(overrides)
    return Candle(**defaults)  # type: ignore[arg-type]


def test_valid_candle() -> None:
    candle = _candle()

    assert candle.instrument == EUR_USD
    assert candle.granularity is Granularity.M1
    assert candle.start_time == START
    assert candle.bid == BID
    assert candle.ask == ASK
    assert candle.volume == 100
    assert candle.is_finalized is True


def test_rejects_wrong_type_for_granularity() -> None:
    with pytest.raises(TypeError, match="granularity"):
        _candle(granularity="M1")


def test_rejects_wrong_type_for_start_time() -> None:
    with pytest.raises(TypeError, match="start_time"):
        _candle(start_time=datetime(2026, 1, 1, tzinfo=UTC))


def test_rejects_wrong_type_for_bid() -> None:
    with pytest.raises(TypeError, match="bid"):
        _candle(bid=Decimal("1.1"))


def test_rejects_wrong_type_for_ask() -> None:
    with pytest.raises(TypeError, match="ask"):
        _candle(ask=Decimal("1.1"))


def test_rejects_negative_volume() -> None:
    with pytest.raises(ValueError, match="volume"):
        _candle(volume=-1)


def test_candle_is_immutable_and_hashable() -> None:
    candle = _candle()

    with pytest.raises(AttributeError):
        candle.volume = 200  # type: ignore[misc]

    assert hash(candle) == hash(_candle())

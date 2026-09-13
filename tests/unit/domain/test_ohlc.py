from decimal import Decimal

import pytest

from forex_agent.domain.ohlc import Ohlc


def test_valid_ohlc() -> None:
    ohlc = Ohlc(
        open=Decimal("1.1000"),
        high=Decimal("1.1010"),
        low=Decimal("1.0990"),
        close=Decimal("1.1005"),
    )

    assert ohlc.open == Decimal("1.1000")
    assert ohlc.high == Decimal("1.1010")
    assert ohlc.low == Decimal("1.0990")
    assert ohlc.close == Decimal("1.1005")


def test_flat_candle_is_valid() -> None:
    price = Decimal("1.1000")
    ohlc = Ohlc(open=price, high=price, low=price, close=price)

    assert ohlc.high == ohlc.low == ohlc.open == ohlc.close


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_rejects_float(field: str) -> None:
    values: dict[str, object] = {
        "open": Decimal("1.1"),
        "high": Decimal("1.1"),
        "low": Decimal("1.1"),
        "close": Decimal("1.1"),
    }
    values[field] = 1.1

    with pytest.raises(TypeError, match="Decimal"):
        Ohlc(**values)  # type: ignore[arg-type]


def test_rejects_high_that_is_not_the_maximum() -> None:
    with pytest.raises(ValueError, match="high"):
        Ohlc(
            open=Decimal("1.1000"),
            high=Decimal("1.1000"),  # should be >= open/low/close but isn't the true max below
            low=Decimal("1.0990"),
            close=Decimal("1.1005"),
        )


def test_rejects_low_that_is_not_the_minimum() -> None:
    with pytest.raises(ValueError, match="low"):
        Ohlc(
            open=Decimal("1.1000"),
            high=Decimal("1.1010"),
            low=Decimal("1.0995"),  # should be <= open/high/close but isn't the true min below
            close=Decimal("1.0990"),
        )

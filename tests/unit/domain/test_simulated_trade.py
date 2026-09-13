from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.instrument import Instrument
from forex_agent.domain.money import Money
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
T0 = UtcTimestamp(datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC))
T1 = UtcTimestamp(datetime(2026, 1, 1, 0, 1, 0, tzinfo=UTC))


def _trade(**overrides: object) -> SimulatedTrade:
    defaults: dict[str, object] = {
        "instrument": EUR_USD,
        "side": TradeSide.LONG,
        "entry_price": Decimal("1.1000"),
        "entry_time": T0,
        "exit_price": Decimal("1.1010"),
        "exit_time": T1,
        "pnl": Money(Decimal("0.0010"), "USD"),
    }
    defaults.update(overrides)
    return SimulatedTrade(**defaults)  # type: ignore[arg-type]


def test_valid_trade() -> None:
    trade = _trade()

    assert trade.entry_price == Decimal("1.1000")
    assert trade.pnl == Money(Decimal("0.0010"), "USD")


def test_rejects_exit_before_entry() -> None:
    with pytest.raises(ValueError, match="exit_time"):
        _trade(entry_time=T1, exit_time=T0)


def test_allows_equal_entry_and_exit_time() -> None:
    _trade(entry_time=T0, exit_time=T0)  # does not raise


def test_rejects_pnl_currency_mismatch() -> None:
    with pytest.raises(ValueError, match="currency"):
        _trade(pnl=Money(Decimal("0.0010"), "EUR"))


def test_rejects_non_decimal_entry_price() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        _trade(entry_price=1.1000)

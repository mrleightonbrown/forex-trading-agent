from decimal import Decimal

import pytest

from forex_agent.domain.price import Price
from forex_agent.domain.trade_side import TradeSide


def test_valid_price_holds_decimals() -> None:
    price = Price(bid=Decimal("1.2345"), ask=Decimal("1.2347"))

    assert price.bid == Decimal("1.2345")
    assert price.ask == Decimal("1.2347")


@pytest.mark.parametrize(
    ("bid", "ask"),
    [
        (1.2345, Decimal("1.2347")),  # float bid
        (Decimal("1.2345"), 1.2347),  # float ask
        ("1.2345", Decimal("1.2347")),  # str bid
    ],
)
def test_rejects_non_decimal_bid_or_ask(bid: object, ask: object) -> None:
    with pytest.raises(TypeError, match="Decimal"):
        Price(bid=bid, ask=ask)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("bid", "ask"), [(Decimal("0"), Decimal("1.0")), (Decimal("-1.0"), Decimal("1.0"))]
)
def test_rejects_non_positive_bid(bid: Decimal, ask: Decimal) -> None:
    with pytest.raises(ValueError, match="positive"):
        Price(bid=bid, ask=ask)


def test_rejects_ask_below_bid() -> None:
    with pytest.raises(ValueError, match="ask"):
        Price(bid=Decimal("1.2350"), ask=Decimal("1.2340"))


def test_spread_and_mid() -> None:
    price = Price(bid=Decimal("1.2000"), ask=Decimal("1.2004"))

    assert price.spread == Decimal("0.0004")
    assert price.mid == Decimal("1.2002")


# --- CLAUDE.md: "Long trades: enter at ask, exit at bid. Short trades: enter
# at bid, exit at ask." Regression tests protecting against invalid bid/ask
# execution — required per CLAUDE.md's testing rules.


def test_long_trade_enters_at_ask_and_exits_at_bid() -> None:
    price = Price(bid=Decimal("1.2000"), ask=Decimal("1.2002"))

    assert price.entry_price(TradeSide.LONG) == price.ask
    assert price.exit_price(TradeSide.LONG) == price.bid


def test_short_trade_enters_at_bid_and_exits_at_ask() -> None:
    price = Price(bid=Decimal("1.2000"), ask=Decimal("1.2002"))

    assert price.entry_price(TradeSide.SHORT) == price.bid
    assert price.exit_price(TradeSide.SHORT) == price.ask

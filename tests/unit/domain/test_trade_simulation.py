"""FX-11H: next-bar execution and defensive validation for simulate_trades.

See also src/forex_agent/domain/trade_simulation.py's module docstring for
the reasoning behind next-bar execution.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_hypothesis import TradeHypothesis
from forex_agent.domain.trade_side import TradeSide
from forex_agent.domain.trade_simulation import simulate_trades

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
GBP_USD = Instrument(base_currency="GBP", quote_currency="USD")


def _ts(minute: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC))


def _candle(
    minute: int,
    *,
    bid_open: str,
    bid_close: str,
    ask_open: str,
    ask_close: str,
    instrument: Instrument = EUR_USD,
    granularity: Granularity = Granularity.M1,
    is_finalized: bool = True,
) -> Candle:
    bo, bc = Decimal(bid_open), Decimal(bid_close)
    ao, ac = Decimal(ask_open), Decimal(ask_close)
    bid = Ohlc(open=bo, high=max(bo, bc), low=min(bo, bc), close=bc)
    ask = Ohlc(open=ao, high=max(ao, ac), low=min(ao, ac), close=ac)
    return Candle(
        instrument=instrument,
        granularity=granularity,
        start_time=_ts(minute),
        bid=bid,
        ask=ask,
        volume=1,
        is_finalized=is_finalized,
    )


def _flat(minute: int, bid: str, ask: str, **overrides: object) -> Candle:
    return _candle(minute, bid_open=bid, bid_close=bid, ask_open=ask, ask_close=ask, **overrides)  # type: ignore[arg-type]


def _hypothesis(
    minute: int, target_position: TargetPosition, instrument: Instrument = EUR_USD
) -> TradeHypothesis:
    return TradeHypothesis(
        instrument=instrument,
        target_position=target_position,
        generated_at=_ts(minute),
        timeframe=Granularity.M1,
        strategy_key="test_strategy",
        strategy_version="1",
        parameters=(),
        rationale="test",
    )


def test_empty_candles_and_empty_hypotheses_returns_empty_trades() -> None:
    assert simulate_trades([], []) == []


def test_empty_hypotheses_returns_empty_trades() -> None:
    candles = [_flat(0, "1.1000", "1.1002")]
    assert simulate_trades([], candles) == []


def test_rejects_non_empty_hypotheses_when_candles_is_empty() -> None:
    """FX-11H.1: a non-empty hypotheses list with no candles at all cannot
    be matched to any execution price — this must raise, not silently
    return an empty trade list that could mask a real caller bug."""
    with pytest.raises(ValueError, match="candles"):
        simulate_trades([_hypothesis(0, TargetPosition.LONG)], [])


# --- AC1/AC9: next-bar execution, not the decision bar's own close -----


def test_long_entry_uses_next_bar_ask_open_not_decision_bar_close() -> None:
    candles = [
        _candle(0, bid_open="1.1000", bid_close="1.1005", ask_open="1.1002", ask_close="1.1007"),
        _candle(1, bid_open="1.1010", bid_close="1.1015", ask_open="1.1012", ask_close="1.1017"),
    ]
    hypotheses = [_hypothesis(0, TargetPosition.LONG)]

    trades = simulate_trades(hypotheses, candles)

    trade = trades[0]
    assert trade.entry_price == Decimal("1.1012")  # bar 1's ask.open
    assert trade.entry_time == _ts(1)
    assert trade.entry_price != Decimal("1.1007")  # must not be bar 0's own ask.close


def test_short_entry_uses_next_bar_bid_open_not_decision_bar_close() -> None:
    candles = [
        _candle(0, bid_open="1.1000", bid_close="1.1005", ask_open="1.1002", ask_close="1.1007"),
        _candle(1, bid_open="1.1010", bid_close="1.1015", ask_open="1.1012", ask_close="1.1017"),
    ]
    hypotheses = [_hypothesis(0, TargetPosition.SHORT)]

    trades = simulate_trades(hypotheses, candles)

    trade = trades[0]
    assert trade.entry_price == Decimal("1.1010")  # bar 1's bid.open
    assert trade.entry_time == _ts(1)
    assert trade.entry_price != Decimal("1.1005")  # must not be bar 0's own bid.close


# --- AC2: reversal closes and reopens at the next bar -------------------


def test_reversal_closes_and_reopens_at_next_bar_open() -> None:
    candles = [
        _candle(0, bid_open="1.1000", bid_close="1.1005", ask_open="1.1002", ask_close="1.1007"),
        _candle(1, bid_open="1.1010", bid_close="1.1015", ask_open="1.1012", ask_close="1.1017"),
        _candle(2, bid_open="1.1020", bid_close="1.1025", ask_open="1.1022", ask_close="1.1027"),
    ]
    hypotheses = [
        _hypothesis(0, TargetPosition.LONG),  # executes at bar 1's open
        _hypothesis(1, TargetPosition.SHORT),  # reversal, executes at bar 2's open
    ]

    trades = simulate_trades(hypotheses, candles)

    assert len(trades) == 2
    first, second = trades
    assert first.side is TradeSide.LONG
    assert first.entry_price == Decimal("1.1012")  # bar 1 ask.open
    assert first.entry_time == _ts(1)
    assert first.exit_price == Decimal("1.1020")  # bar 2 bid.open
    assert first.exit_time == _ts(2)

    assert second.side is TradeSide.SHORT
    assert second.entry_price == Decimal("1.1020")  # bar 2 bid.open
    assert second.entry_time == _ts(2)
    # still open at the end -> force-closed using the LAST candle's close
    assert second.exit_price == Decimal("1.1027")  # bar 2 ask.close
    assert second.exit_time == _ts(2)


# --- AC3: final-bar signal cannot execute --------------------------------


def test_hypothesis_on_final_bar_produces_no_new_trade() -> None:
    candles = [
        _candle(0, bid_open="1.1000", bid_close="1.1005", ask_open="1.1002", ask_close="1.1007"),
        _candle(1, bid_open="1.1010", bid_close="1.1015", ask_open="1.1012", ask_close="1.1017"),
    ]
    hypotheses = [_hypothesis(1, TargetPosition.LONG)]  # signal on the LAST candle

    assert simulate_trades(hypotheses, candles) == []


def test_final_bar_reversal_signal_is_not_actionable() -> None:
    candles = [
        _candle(0, bid_open="1.1000", bid_close="1.1005", ask_open="1.1002", ask_close="1.1007"),
        _candle(1, bid_open="1.1010", bid_close="1.1015", ask_open="1.1012", ask_close="1.1017"),
        _candle(2, bid_open="1.1020", bid_close="1.1025", ask_open="1.1022", ask_close="1.1027"),
    ]
    hypotheses = [
        _hypothesis(0, TargetPosition.LONG),  # opens at bar 1's open
        _hypothesis(2, TargetPosition.SHORT),  # generated on the final bar: not actionable
    ]

    trades = simulate_trades(hypotheses, candles)

    assert len(trades) == 1  # only the original long, force-closed at the end
    trade = trades[0]
    assert trade.side is TradeSide.LONG
    assert trade.entry_price == Decimal("1.1012")
    assert trade.exit_price == Decimal("1.1025")  # last candle's bid.close
    assert trade.exit_time == _ts(2)


# --- AC4: end-of-dataset force-close uses the last candle's close --------


def test_still_open_position_force_closed_at_last_candle_close() -> None:
    candles = [
        _candle(0, bid_open="1.1000", bid_close="1.1005", ask_open="1.1002", ask_close="1.1007"),
        _candle(1, bid_open="1.1010", bid_close="1.1015", ask_open="1.1012", ask_close="1.1017"),
        _candle(2, bid_open="1.1020", bid_close="1.1025", ask_open="1.1022", ask_close="1.1027"),
    ]
    hypotheses = [_hypothesis(0, TargetPosition.LONG)]

    trades = simulate_trades(hypotheses, candles)

    trade = trades[0]
    assert trade.exit_price == Decimal("1.1025")  # last candle's (bar 2) bid.close
    assert trade.exit_time == _ts(2)


def test_same_direction_repeat_is_a_noop() -> None:
    candles = [
        _candle(0, bid_open="1.1000", bid_close="1.1005", ask_open="1.1002", ask_close="1.1007"),
        _candle(1, bid_open="1.1010", bid_close="1.1015", ask_open="1.1012", ask_close="1.1017"),
        _candle(2, bid_open="1.1020", bid_close="1.1025", ask_open="1.1022", ask_close="1.1027"),
    ]
    hypotheses = [
        _hypothesis(0, TargetPosition.LONG),
        _hypothesis(1, TargetPosition.LONG),  # already long: no-op
    ]

    trades = simulate_trades(hypotheses, candles)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_price == Decimal("1.1012")  # unchanged by the repeat
    assert trade.entry_time == _ts(1)
    assert trade.exit_price == Decimal("1.1025")
    assert trade.exit_time == _ts(2)


# --- FX-18: FLAT semantics -------------------------------------------------


def test_flat_with_no_open_position_is_a_noop() -> None:
    candles = [
        _candle(0, bid_open="1.1000", bid_close="1.1005", ask_open="1.1002", ask_close="1.1007"),
        _candle(1, bid_open="1.1010", bid_close="1.1015", ask_open="1.1012", ask_close="1.1017"),
    ]
    hypotheses = [_hypothesis(0, TargetPosition.FLAT)]  # never opened anything

    assert simulate_trades(hypotheses, candles) == []


def test_flat_closes_open_position_without_reopening() -> None:
    candles = [
        _candle(0, bid_open="1.1000", bid_close="1.1005", ask_open="1.1002", ask_close="1.1007"),
        _candle(1, bid_open="1.1010", bid_close="1.1015", ask_open="1.1012", ask_close="1.1017"),
        _candle(2, bid_open="1.1020", bid_close="1.1025", ask_open="1.1022", ask_close="1.1027"),
    ]
    hypotheses = [
        _hypothesis(0, TargetPosition.LONG),  # executes at bar 1's open
        _hypothesis(1, TargetPosition.FLAT),  # closes at bar 2's open, does not reopen
    ]

    trades = simulate_trades(hypotheses, candles)

    assert len(trades) == 1  # not 2 -- FLAT must not open a new position
    trade = trades[0]
    assert trade.side is TradeSide.LONG
    assert trade.entry_price == Decimal("1.1012")  # bar 1 ask.open
    assert trade.entry_time == _ts(1)
    assert trade.exit_price == Decimal("1.1020")  # bar 2 bid.open (LONG exits at bid)
    assert trade.exit_time == _ts(2)


def test_flat_as_first_hypothesis_is_a_noop() -> None:
    candles = [
        _candle(0, bid_open="1.1000", bid_close="1.1005", ask_open="1.1002", ask_close="1.1007"),
        _candle(1, bid_open="1.1010", bid_close="1.1015", ask_open="1.1012", ask_close="1.1017"),
    ]
    hypotheses = [_hypothesis(0, TargetPosition.FLAT)]

    assert simulate_trades(hypotheses, candles) == []


def test_long_after_flat_close_opens_a_fresh_position() -> None:
    candles = [
        _candle(0, bid_open="1.1000", bid_close="1.1005", ask_open="1.1002", ask_close="1.1007"),
        _candle(1, bid_open="1.1010", bid_close="1.1015", ask_open="1.1012", ask_close="1.1017"),
        _candle(2, bid_open="1.1020", bid_close="1.1025", ask_open="1.1022", ask_close="1.1027"),
        _candle(3, bid_open="1.1030", bid_close="1.1035", ask_open="1.1032", ask_close="1.1037"),
    ]
    hypotheses = [
        _hypothesis(0, TargetPosition.LONG),  # opens at bar 1's open
        _hypothesis(1, TargetPosition.FLAT),  # closes at bar 2's open
        _hypothesis(2, TargetPosition.LONG),  # opens fresh at bar 3's open
    ]

    trades = simulate_trades(hypotheses, candles)

    assert len(trades) == 2
    first, second = trades
    assert first.exit_price == Decimal("1.1020")  # bar 2 bid.open, from the FLAT close
    assert first.exit_time == _ts(2)
    assert second.entry_price == Decimal("1.1032")  # bar 3 ask.open, a genuinely fresh entry
    assert second.entry_time == _ts(3)
    # still open at the end -> force-closed at the last candle's close
    assert second.exit_price == Decimal("1.1035")  # bar 3 (last) bid.close
    assert second.exit_time == _ts(3)


def test_repeated_flat_while_already_flat_is_a_noop() -> None:
    candles = [
        _candle(0, bid_open="1.1000", bid_close="1.1005", ask_open="1.1002", ask_close="1.1007"),
        _candle(1, bid_open="1.1010", bid_close="1.1015", ask_open="1.1012", ask_close="1.1017"),
        _candle(2, bid_open="1.1020", bid_close="1.1025", ask_open="1.1022", ask_close="1.1027"),
    ]
    hypotheses = [
        _hypothesis(0, TargetPosition.LONG),  # opens at bar 1's open
        _hypothesis(1, TargetPosition.FLAT),  # closes at bar 2's open
        _hypothesis(2, TargetPosition.FLAT),  # already flat: no-op, but final bar anyway
    ]

    trades = simulate_trades(hypotheses, candles)

    assert len(trades) == 1
    assert trades[0].exit_price == Decimal("1.1020")  # bar 2 bid.open


def test_flat_short_position_closes_at_ask() -> None:
    candles = [
        _candle(0, bid_open="1.1000", bid_close="1.1005", ask_open="1.1002", ask_close="1.1007"),
        _candle(1, bid_open="1.1010", bid_close="1.1015", ask_open="1.1012", ask_close="1.1017"),
        _candle(2, bid_open="1.1020", bid_close="1.1025", ask_open="1.1022", ask_close="1.1027"),
    ]
    hypotheses = [
        _hypothesis(0, TargetPosition.SHORT),  # executes at bar 1's open
        _hypothesis(1, TargetPosition.FLAT),  # closes at bar 2's open
    ]

    trades = simulate_trades(hypotheses, candles)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.side is TradeSide.SHORT
    assert trade.exit_price == Decimal("1.1022")  # bar 2 ask.open (SHORT exits at ask)
    assert trade.exit_time == _ts(2)


# --- AC10: bid/ask-per-side rules preserved ------------------------------


def test_short_trade_profits_when_price_falls() -> None:
    candles = [
        _flat(0, "1.1000", "1.1002"),
        _flat(1, "1.1000", "1.1002"),
        _flat(2, "1.0990", "1.0992"),
    ]
    hypotheses = [_hypothesis(0, TargetPosition.SHORT)]

    trades = simulate_trades(hypotheses, candles)

    trade = trades[0]
    assert trade.entry_price == Decimal("1.1000")  # bar 1 bid.open
    assert trade.exit_price == Decimal("1.0992")  # force-close: bar 2 (last) ask.close
    assert trade.pnl.amount == Decimal("1.1000") - Decimal("1.0992")
    assert trade.pnl.amount > 0


def test_long_trade_loses_when_price_falls() -> None:
    candles = [
        _flat(0, "1.1000", "1.1002"),
        _flat(1, "1.1000", "1.1002"),
        _flat(2, "1.0990", "1.0992"),
    ]
    hypotheses = [_hypothesis(0, TargetPosition.LONG)]

    trades = simulate_trades(hypotheses, candles)

    assert trades[0].pnl.amount < 0


# --- AC6: candle validation -----------------------------------------------


def test_rejects_mixed_instrument_candles() -> None:
    candles = [_flat(0, "1.1", "1.1002"), _flat(1, "1.1", "1.1002", instrument=GBP_USD)]

    with pytest.raises(ValueError, match="instrument"):
        simulate_trades([], candles)


def test_rejects_mixed_granularity_candles() -> None:
    candles = [_flat(0, "1.1", "1.1002"), _flat(1, "1.1", "1.1002", granularity=Granularity.M5)]

    with pytest.raises(ValueError, match="granularity"):
        simulate_trades([], candles)


def test_rejects_non_ascending_candles() -> None:
    candles = [_flat(1, "1.1", "1.1002"), _flat(0, "1.1", "1.1002")]

    with pytest.raises(ValueError, match="ascending"):
        simulate_trades([], candles)


def test_rejects_duplicate_candle_timestamps() -> None:
    candles = [_flat(0, "1.1", "1.1002"), _flat(0, "1.1", "1.1002")]

    with pytest.raises(ValueError, match="ascending"):
        simulate_trades([], candles)


def test_rejects_non_finalized_candle() -> None:
    candles = [_flat(0, "1.1", "1.1002", is_finalized=False)]

    with pytest.raises(ValueError, match="finalized"):
        simulate_trades([], candles)


# --- AC7: hypothesis validation --------------------------------------------


def test_rejects_out_of_order_hypotheses() -> None:
    candles = [_flat(0, "1.1", "1.1002"), _flat(1, "1.1", "1.1002"), _flat(2, "1.1", "1.1002")]
    hypotheses = [_hypothesis(1, TargetPosition.LONG), _hypothesis(0, TargetPosition.SHORT)]

    with pytest.raises(ValueError, match="ascending"):
        simulate_trades(hypotheses, candles)


def test_rejects_duplicate_hypothesis_timestamps() -> None:
    candles = [_flat(0, "1.1", "1.1002"), _flat(1, "1.1", "1.1002")]
    hypotheses = [_hypothesis(0, TargetPosition.LONG), _hypothesis(0, TargetPosition.SHORT)]

    with pytest.raises(ValueError, match="ascending"):
        simulate_trades(hypotheses, candles)


def test_rejects_hypothesis_instrument_mismatch() -> None:
    candles = [_flat(0, "1.1", "1.1002")]
    hypotheses = [_hypothesis(0, TargetPosition.LONG, instrument=GBP_USD)]

    with pytest.raises(ValueError, match="instrument"):
        simulate_trades(hypotheses, candles)


def test_rejects_hypothesis_with_no_matching_candle() -> None:
    candles = [_flat(0, "1.1", "1.1002")]
    hypotheses = [_hypothesis(5, TargetPosition.LONG)]  # no candle at minute 5

    with pytest.raises(ValueError, match="does not"):
        simulate_trades(hypotheses, candles)


# --- AC11: determinism ------------------------------------------------------


def test_deterministic_given_identical_input() -> None:
    candles = [
        _candle(0, bid_open="1.1000", bid_close="1.1005", ask_open="1.1002", ask_close="1.1007"),
        _candle(1, bid_open="1.1010", bid_close="1.1015", ask_open="1.1012", ask_close="1.1017"),
        _candle(2, bid_open="1.1020", bid_close="1.1025", ask_open="1.1022", ask_close="1.1027"),
    ]
    hypotheses = [_hypothesis(0, TargetPosition.LONG), _hypothesis(1, TargetPosition.SHORT)]

    first_run = simulate_trades(hypotheses, candles)
    second_run = simulate_trades(hypotheses, candles)

    assert first_run == second_run

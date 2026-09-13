from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_hypothesis import TradeHypothesis
from forex_agent.domain.trade_side import TradeSide

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
GBP_USD = Instrument(base_currency="GBP", quote_currency="USD")


def _ts(minute: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC))


def _candle(
    minute: int,
    *,
    close: str = "1.1000",
    instrument: Instrument = EUR_USD,
    granularity: Granularity = Granularity.M1,
    is_finalized: bool = True,
) -> Candle:
    close_decimal = Decimal(close)
    flat = Ohlc(
        open=Decimal("1.1"),
        high=max(Decimal("1.1"), close_decimal),
        low=min(Decimal("1.1"), close_decimal),
        close=close_decimal,
    )
    return Candle(
        instrument=instrument,
        granularity=granularity,
        start_time=_ts(minute),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=is_finalized,
    )


class _RecordingStrategy:
    """Never fires; records the length of the window it was shown each
    call — proves the engine grows the window one bar at a time."""

    def __init__(self) -> None:
        self.received_lengths: list[int] = []

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        self.received_lengths.append(len(candles))
        return None


class _AlwaysFireStrategy:
    """Fires every step, correctly timestamped at the current bar."""

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        current = candles[-1]
        return TradeHypothesis(
            instrument=current.instrument,
            side=TradeSide.LONG,
            generated_at=current.start_time,
            rationale="always fires",
        )


class _StaleTimestampStrategy:
    """Bug: always timestamps its hypothesis with the very first candle it
    ever saw, not the current bar."""

    def __init__(self) -> None:
        self._first_seen: UtcTimestamp | None = None

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        if self._first_seen is None:
            self._first_seen = candles[0].start_time
        return TradeHypothesis(
            instrument=candles[-1].instrument,
            side=TradeSide.LONG,
            generated_at=self._first_seen,
            rationale="buggy",
        )


def test_empty_candles_returns_empty_list() -> None:
    assert run_backtest(_RecordingStrategy(), []) == []


def test_strategy_window_grows_one_bar_at_a_time() -> None:
    candles = [_candle(m) for m in range(5)]
    strategy = _RecordingStrategy()

    run_backtest(strategy, candles)

    assert strategy.received_lengths == [1, 2, 3, 4, 5]


def test_strategy_cannot_see_future_candles() -> None:
    """A strategy that immediately fails if it can see the final candle's
    distinguishing value before the last step — proves the engine doesn't
    hand over the whole list up front."""
    candles = [_candle(m, close=f"1.100{m}") for m in range(5)]
    poison_close = candles[-1].bid.close

    class _CheatingStrategy:
        def evaluate(self, cs: list[Candle]) -> TradeHypothesis | None:
            if len(cs) < len(candles) and any(c.bid.close == poison_close for c in cs):
                raise AssertionError("strategy was shown a future candle early")
            return None

    run_backtest(_CheatingStrategy(), candles)  # must not raise


def test_collects_hypotheses_across_the_run() -> None:
    candles = [_candle(m) for m in range(3)]

    hypotheses = run_backtest(_AlwaysFireStrategy(), candles)

    assert [h.generated_at for h in hypotheses] == [_ts(0), _ts(1), _ts(2)]


def test_rejects_mixed_instruments() -> None:
    candles = [_candle(0), _candle(1, instrument=GBP_USD)]

    with pytest.raises(ValueError, match="instrument"):
        run_backtest(_RecordingStrategy(), candles)


def test_rejects_mixed_granularity() -> None:
    candles = [_candle(0), _candle(1, granularity=Granularity.M5)]

    with pytest.raises(ValueError, match="granularity"):
        run_backtest(_RecordingStrategy(), candles)


def test_rejects_non_ascending_start_time() -> None:
    candles = [_candle(1), _candle(0)]

    with pytest.raises(ValueError, match="ascending"):
        run_backtest(_RecordingStrategy(), candles)


def test_rejects_duplicate_start_time() -> None:
    candles = [_candle(0), _candle(0)]

    with pytest.raises(ValueError, match="ascending"):
        run_backtest(_RecordingStrategy(), candles)


def test_rejects_hypothesis_with_stale_generated_at() -> None:
    candles = [_candle(0), _candle(1)]

    with pytest.raises(ValueError, match="generated_at"):
        run_backtest(_StaleTimestampStrategy(), candles)


def test_rejects_non_finalized_candle_via_reused_run_strategy() -> None:
    candles = [_candle(0), _candle(1, is_finalized=False)]

    with pytest.raises(ValueError, match="finalized"):
        run_backtest(_RecordingStrategy(), candles)

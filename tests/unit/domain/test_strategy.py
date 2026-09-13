from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategy import run_strategy
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_hypothesis import TradeHypothesis
from forex_agent.domain.trade_side import TradeSide

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")


def _candle(minute: int, is_finalized: bool) -> Candle:
    flat = Ohlc(open=Decimal("1.1"), high=Decimal("1.1"), low=Decimal("1.1"), close=Decimal("1.1"))
    return Candle(
        instrument=EUR_USD,
        granularity=Granularity.M1,
        start_time=UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC)),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=is_finalized,
    )


class _FakeStrategy:
    """Test double: records what it was called with, returns a fixed
    hypothesis (or None)."""

    def __init__(self, hypothesis: TradeHypothesis | None) -> None:
        self._hypothesis = hypothesis
        self.received_candles: list[Candle] | None = None

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        self.received_candles = candles
        return self._hypothesis


_HYPOTHESIS = TradeHypothesis(
    instrument=EUR_USD,
    side=TradeSide.LONG,
    generated_at=UtcTimestamp(datetime(2026, 1, 1, 0, 5, 0, tzinfo=UTC)),
    rationale="test",
)


def test_run_strategy_delegates_to_strategy_and_returns_its_result() -> None:
    candles = [_candle(0, is_finalized=True), _candle(1, is_finalized=True)]
    strategy = _FakeStrategy(_HYPOTHESIS)

    result = run_strategy(strategy, candles)

    assert result is _HYPOTHESIS
    assert strategy.received_candles == candles


def test_run_strategy_passes_through_none() -> None:
    candles = [_candle(0, is_finalized=True)]
    strategy = _FakeStrategy(None)

    assert run_strategy(strategy, candles) is None


def test_run_strategy_rejects_any_non_finalized_candle() -> None:
    candles = [_candle(0, is_finalized=True), _candle(1, is_finalized=False)]
    strategy = _FakeStrategy(_HYPOTHESIS)

    with pytest.raises(ValueError, match="finalized"):
        run_strategy(strategy, candles)

    assert strategy.received_candles is None  # never reached evaluate()


def test_run_strategy_with_empty_candles() -> None:
    strategy = _FakeStrategy(None)

    assert run_strategy(strategy, []) is None

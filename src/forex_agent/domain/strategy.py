"""FX-9: the strategy framework — no concrete strategy implementation here,
just the interface and the runner that enforces CLAUDE.md's "strategies
must only evaluate finalized candles" rule structurally.
"""

from typing import Protocol

from forex_agent.domain.candle import Candle
from forex_agent.domain.trade_hypothesis import TradeHypothesis


class Strategy(Protocol):
    """A pure computation over candle data — no I/O, no external system —
    which is why this lives in `domain/` rather than `application/ports/`
    alongside `BrokerPort`/`CandleRepository`/`MarketDataPort` (those cross
    a real boundary something in `infrastructure/` implements; this
    doesn't).
    """

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        """Produce a hypothesis from `candles`, or `None` if nothing warrants
        one. Implementations should assume every candle is already
        finalized — `run_strategy` enforces that before calling this."""
        ...


def run_strategy(strategy: Strategy, candles: list[Candle]) -> TradeHypothesis | None:
    """Enforces "strategies must only evaluate finalized candles" before
    delegating to `strategy.evaluate(candles)` — every concrete strategy
    gets this protection automatically rather than having to check it
    itself."""
    for candle in candles:
        if not candle.is_finalized:
            raise ValueError(
                "strategies must only evaluate finalized candles; candle at "
                f"{candle.start_time.value.isoformat()} is not finalized"
            )
    return strategy.evaluate(candles)

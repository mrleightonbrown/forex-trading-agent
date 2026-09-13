"""FX-11: turns a backtest's hypotheses into simulated round-trip trades.

Exit rule (a deliberate design decision — see docs/DECISIONS.md, since
there's no live risk/execution engine to drive exits yet): close-and-
reverse on an opposite-direction hypothesis; a same-direction repeat while
already in a position is a no-op; anything still open when the hypothesis
list ends is force-closed at the last candle's price.
"""

from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain.candle import Candle
from forex_agent.domain.money import Money
from forex_agent.domain.price import Price
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_hypothesis import TradeHypothesis
from forex_agent.domain.trade_side import TradeSide


@dataclass(frozen=True, slots=True)
class _OpenPosition:
    hypothesis: TradeHypothesis
    entry_price: Decimal

    def close(self, exit_price: Decimal, exit_time: UtcTimestamp) -> SimulatedTrade:
        side = self.hypothesis.side
        delta = (
            exit_price - self.entry_price
            if side is TradeSide.LONG
            else self.entry_price - exit_price
        )
        return SimulatedTrade(
            instrument=self.hypothesis.instrument,
            side=side,
            entry_price=self.entry_price,
            entry_time=self.hypothesis.generated_at,
            exit_price=exit_price,
            exit_time=exit_time,
            pnl=Money(delta, self.hypothesis.instrument.quote_currency),
        )


def simulate_trades(
    hypotheses: list[TradeHypothesis], candles: list[Candle]
) -> list[SimulatedTrade]:
    """Entry/exit prices come from each hypothesis's matching candle
    (`generated_at == candle.start_time`, guaranteed by `run_backtest`'s
    own invariant — FX-10) via `Price.entry_price`/`Price.exit_price`
    (FX-2), not reimplemented here.

    Raises `ValueError` if a hypothesis's `generated_at` doesn't match any
    candle's `start_time`.
    """
    if not candles:
        return []

    candles_by_time = {candle.start_time: candle for candle in candles}
    trades: list[SimulatedTrade] = []
    open_position: _OpenPosition | None = None

    for hypothesis in hypotheses:
        candle = candles_by_time.get(hypothesis.generated_at)
        if candle is None:
            raise ValueError(
                f"hypothesis at {hypothesis.generated_at.value.isoformat()} does not "
                "match any candle's start_time"
            )
        price = Price(bid=candle.bid.close, ask=candle.ask.close)

        if open_position is None:
            open_position = _OpenPosition(hypothesis, price.entry_price(hypothesis.side))
            continue

        if hypothesis.side == open_position.hypothesis.side:
            continue  # same-direction repeat while already in a position: no-op

        trades.append(
            open_position.close(
                exit_price=price.exit_price(open_position.hypothesis.side),
                exit_time=hypothesis.generated_at,
            )
        )
        open_position = _OpenPosition(hypothesis, price.entry_price(hypothesis.side))

    if open_position is not None:
        last_candle = candles[-1]
        exit_price_source = Price(bid=last_candle.bid.close, ask=last_candle.ask.close)
        trades.append(
            open_position.close(
                exit_price=exit_price_source.exit_price(open_position.hypothesis.side),
                exit_time=last_candle.start_time,
            )
        )

    return trades

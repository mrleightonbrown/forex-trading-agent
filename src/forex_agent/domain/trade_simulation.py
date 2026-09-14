"""FX-11 (execution timing hardened in FX-11H): turns a backtest's
hypotheses into simulated round-trip trades.

Next-bar execution (FX-11H): a hypothesis generated from bar N's finalized
close is only known once bar N has closed — by definition, that price is
already in the past. The earliest realistic execution is therefore the
FIRST price of bar N+1 (its open), not bar N's own close. Executing at bar
N's close (the previous behaviour) let a strategy "trade on a price it had
already seen close" — not a real fill.

Exit rule (see docs/DECISIONS.md — a deliberate design decision, since
there's no live risk/execution engine to drive exits yet): close-and-
reverse on an opposite-direction hypothesis, executed at bar N+1's open
same as opening; a same-direction repeat while already in a position is a
no-op; anything still open when the hypothesis list ends is force-closed
at the LAST candle's close (there is no bar beyond the end of the dataset
to get a next-bar open from).

A hypothesis generated on the final candle in the dataset cannot execute
at all — there is no N+1 candle to price it from — and is silently not
actionable; any already-open position simply carries through to the
end-of-dataset force-close.
"""

from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain.candle import Candle
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.money import Money
from forex_agent.domain.price import Price
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_hypothesis import TradeHypothesis
from forex_agent.domain.trade_side import TradeSide


@dataclass(frozen=True, slots=True)
class _OpenPosition:
    instrument: Instrument
    side: TradeSide
    entry_price: Decimal
    entry_time: UtcTimestamp

    def close(self, exit_price: Decimal, exit_time: UtcTimestamp) -> SimulatedTrade:
        delta = (
            exit_price - self.entry_price
            if self.side is TradeSide.LONG
            else self.entry_price - exit_price
        )
        return SimulatedTrade(
            instrument=self.instrument,
            side=self.side,
            entry_price=self.entry_price,
            entry_time=self.entry_time,
            exit_price=exit_price,
            exit_time=exit_time,
            pnl=Money(delta, self.instrument.quote_currency),
        )


def simulate_trades(
    hypotheses: list[TradeHypothesis], candles: list[Candle]
) -> list[SimulatedTrade]:
    """Validates both inputs defensively (FX-11H) rather than assuming
    `hypotheses` is only ever `run_backtest`'s own output:

    `candles` must be one instrument, one granularity, strictly ascending
    by `start_time`, and all finalized. `hypotheses` must match the
    candles' instrument, be strictly ascending by `generated_at`, and each
    `generated_at` must correspond to one of the candles' `start_time`.

    Raises `ValueError` on any violation, with a message identifying which
    — including (FX-11H.1) non-empty `hypotheses` with empty `candles`,
    since there is then no candle any hypothesis could possibly match.
    """
    if not candles:
        if hypotheses:
            raise ValueError(
                "hypotheses were provided but candles is empty; hypotheses cannot "
                "be matched to any candle's start_time"
            )
        return []

    instrument = candles[0].instrument
    granularity = candles[0].granularity
    time_to_index: dict[UtcTimestamp, int] = {}
    previous_candle_time: UtcTimestamp | None = None
    for i, candle in enumerate(candles):
        if candle.instrument != instrument:
            raise ValueError("all candles must share the same instrument")
        if candle.granularity != granularity:
            raise ValueError("all candles must share the same granularity")
        if not candle.is_finalized:
            raise ValueError(
                f"candle at {candle.start_time.value.isoformat()} is not finalized; "
                "backtests must only use finalized candles"
            )
        if (
            previous_candle_time is not None
            and candle.start_time.value <= previous_candle_time.value
        ):
            raise ValueError(
                "candles must be strictly ascending by start_time; "
                f"{candle.start_time.value.isoformat()} does not follow "
                f"{previous_candle_time.value.isoformat()}"
            )
        previous_candle_time = candle.start_time
        time_to_index[candle.start_time] = i

    trades: list[SimulatedTrade] = []
    open_position: _OpenPosition | None = None
    previous_hypothesis_time: UtcTimestamp | None = None

    for hypothesis in hypotheses:
        if hypothesis.instrument != instrument:
            raise ValueError(
                f"hypothesis instrument ({hypothesis.instrument.symbol}) does not match "
                f"the candle series' instrument ({instrument.symbol})"
            )
        if (
            previous_hypothesis_time is not None
            and hypothesis.generated_at.value <= previous_hypothesis_time.value
        ):
            raise ValueError(
                "hypotheses must be strictly ascending by generated_at; "
                f"{hypothesis.generated_at.value.isoformat()} does not follow "
                f"{previous_hypothesis_time.value.isoformat()}"
            )
        previous_hypothesis_time = hypothesis.generated_at

        decision_index = time_to_index.get(hypothesis.generated_at)
        if decision_index is None:
            raise ValueError(
                f"hypothesis at {hypothesis.generated_at.value.isoformat()} does not "
                "correspond to any candle's start_time"
            )

        execution_index = decision_index + 1
        if execution_index >= len(candles):
            # Generated on the final candle: no next-bar price exists to
            # execute at. Not actionable — do not invent a fill. Any
            # already-open position is untouched and simply carries
            # through to the end-of-dataset force-close below.
            continue

        execution_candle = candles[execution_index]
        execution_price = Price(bid=execution_candle.bid.open, ask=execution_candle.ask.open)

        if open_position is None:
            open_position = _OpenPosition(
                instrument=hypothesis.instrument,
                side=hypothesis.side,
                entry_price=execution_price.entry_price(hypothesis.side),
                entry_time=execution_candle.start_time,
            )
            continue

        if hypothesis.side == open_position.side:
            continue  # same-direction repeat while already in a position: no-op

        trades.append(
            open_position.close(
                exit_price=execution_price.exit_price(open_position.side),
                exit_time=execution_candle.start_time,
            )
        )
        open_position = _OpenPosition(
            instrument=hypothesis.instrument,
            side=hypothesis.side,
            entry_price=execution_price.entry_price(hypothesis.side),
            entry_time=execution_candle.start_time,
        )

    if open_position is not None:
        last_candle = candles[-1]
        end_of_data_price = Price(bid=last_candle.bid.close, ask=last_candle.ask.close)
        trades.append(
            open_position.close(
                exit_price=end_of_data_price.exit_price(open_position.side),
                # FX-11H.1: exit_time identifies WHICH candle produced this
                # exit price (its start_time, like every other timestamp in
                # this module) — it is not the precise instant the candle
                # closed (start_time + granularity's duration). Candle
                # carries no separate close-instant field to use instead.
                exit_time=last_candle.start_time,
            )
        )

    return trades

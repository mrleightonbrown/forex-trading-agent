"""Shared validation for a candle series — reused by `run_backtest`,
`simulate_trades`, and `classify_regime` (FX-12) rather than duplicated in
each.
"""

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp


def require_consistent_series(candles: list[Candle]) -> tuple[Instrument, Granularity]:
    """Validates `candles` share one instrument, one granularity, and are
    strictly ascending by `start_time`. Returns `(instrument, granularity)`.

    Does not check `is_finalized` — not every consumer requires
    finalized-only data at this layer (`run_backtest` gets that enforcement
    from `run_strategy` instead); callers that need it check it themselves.

    Raises `ValueError` if `candles` is empty or any invariant is violated.
    """
    if not candles:
        raise ValueError("candles must not be empty")

    instrument = candles[0].instrument
    granularity = candles[0].granularity
    previous_start_time: UtcTimestamp | None = None
    for candle in candles:
        if candle.instrument != instrument:
            raise ValueError("all candles must share the same instrument")
        if candle.granularity != granularity:
            raise ValueError("all candles must share the same granularity")
        if previous_start_time is not None and candle.start_time.value <= previous_start_time.value:
            raise ValueError(
                "candles must be strictly ascending by start_time; "
                f"{candle.start_time.value.isoformat()} does not follow "
                f"{previous_start_time.value.isoformat()}"
            )
        previous_start_time = candle.start_time

    return instrument, granularity

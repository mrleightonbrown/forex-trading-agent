"""FX-29: an O(1)-per-update incremental counterpart to every strategy
file's own `_sma_seeded_ema(closes, period)` helper (e.g.
`ema_crossover.py`, `multi_timeframe_trend.py`,
`ema_crossover_trend_regime_gated.py`).

Those helpers are O(len(closes)) *per call* — fine for a strategy handed
a fixed, already-fetched series once, but `run_backtest` calls
`evaluate()` with the full history-so-far on *every* bar, so a strategy
built on them is effectively O(n^2) over a full backtest. This class
holds just enough state (the running EMA value, and up to `period`
seed closes) to extend by exactly one bar per `update()` call, with no
recomputation of anything already seen.

Deliberately a shared, reusable module rather than duplicated per
strategy file (a departure from this codebase's usual per-strategy
self-containment convention) — this is performance/correctness-critical
shared infrastructure, and one well-tested incremental implementation is
safer than several near-duplicates that could each drift slightly.

Verified to reproduce `_sma_seeded_ema`'s exact math step for step (same
Decimal operations, same order) — see
`tests/unit/domain/test_incremental_ema.py`'s parity tests, which check
agreement at every step, not just the final value.
"""

from decimal import Decimal


class IncrementalSmaSeededEma:
    """SMA-seeded EMA, updated one close at a time.

    `update(close)` returns the EMA value as of and including this close,
    or `None` if fewer than `period` closes have been seen yet (matching
    every strategy's own `len(candles) < period` guard).
    """

    def __init__(self, period: int) -> None:
        if isinstance(period, bool) or not isinstance(period, int):
            raise TypeError(f"period must be an int, got {type(period).__name__}")
        if period < 1:
            raise ValueError(f"period must be at least 1, got {period}")

        self._period = period
        self._multiplier = Decimal(2) / Decimal(period + 1)
        self._seed_buffer: list[Decimal] = []
        self._value: Decimal | None = None

    def update(self, close: Decimal) -> Decimal | None:
        if self._value is None:
            self._seed_buffer.append(close)
            if len(self._seed_buffer) == self._period:
                self._value = sum(self._seed_buffer, Decimal(0)) / self._period
                self._seed_buffer = []  # no longer needed; free it
            return self._value

        self._value = close * self._multiplier + self._value * (1 - self._multiplier)
        return self._value

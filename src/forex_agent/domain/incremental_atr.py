"""FX-36: an O(1)-per-update incremental counterpart to
`volatility_expansion._atr` -- same reasoning as `incremental_ema`/
`incremental_adx` (FX-29): `_atr` is O(len(true_range)) per call, so a
strategy calling it every bar of a `run_backtest` replay is effectively
O(n^2) over a full backtest.

Wilder's ATR shares its smoothing shape with ADX's own smoothed TR
(`incremental_adx.IncrementalAdx`), but reports the actual divided-
through average (`_atr`'s own convention), not ADX's internal running-
sum form -- so this is its own primitive, not a thin wrapper around
`IncrementalAdx`.

Verified to reproduce `_atr`'s exact math step for step -- see
`tests/unit/domain/test_incremental_atr.py`'s parity tests, checking
agreement at every step, not just the final value.
"""

from decimal import Decimal


class IncrementalWilderAtr:
    def __init__(self, period: int) -> None:
        if isinstance(period, bool) or not isinstance(period, int):
            raise TypeError(f"period must be an int, got {type(period).__name__}")
        if period < 1:
            raise ValueError(f"period must be at least 1, got {period}")

        self._period = period
        self._prev_close: Decimal | None = None
        self._diff_count = 0
        self._seed_sum = Decimal(0)
        self._atr: Decimal | None = None

    def update(self, high: Decimal, low: Decimal, close: Decimal) -> Decimal | None:
        if self._prev_close is None:
            self._prev_close = close
            return None

        prev_close = self._prev_close
        true_range = max(high - low, abs(high - prev_close), abs(low - prev_close))
        self._prev_close = close
        self._diff_count += 1

        if self._atr is None:
            self._seed_sum += true_range
            if self._diff_count < self._period:
                return None
            self._atr = self._seed_sum / self._period
            return self._atr

        self._atr = ((self._period - 1) * self._atr + true_range) / self._period
        return self._atr

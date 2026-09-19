"""FX-29: an O(1)-per-update incremental counterpart to
`regime_detection._compute_adx` -- same reasoning as
`incremental_ema.IncrementalSmaSeededEma`: `classify_regime` is
O(len(candles)) per call, so a strategy calling it every bar of a
`run_backtest` replay is effectively O(n^2) over a full backtest.

Replicates Wilder's ADX exactly (same Decimal operations, same order),
just incrementally. Four phases as candles accumulate, mirroring
`_compute_adx`'s own two-loop structure exactly:

1. First candle: nothing to diff against yet.
2. Seeding TR/+DM/-DM (`period` diffs accumulated as a plain sum, not
   yet Wilder-smoothed) -- matches `sum(true_range[1:period+1])` etc.
3. Once seeded: Wilder-smooth TR/+DM/-DM one more step each new candle,
   compute a DX value from each -- matches the `dx_values` loop.
4. DX values themselves seed (simple average of the first `period`)
   then Wilder-smooth into the final ADX -- matches the `adx =` loop.

`update()` returns the ADX value as of and including this candle, or
`None` until `2 * period` candles have been seen (matching
`classify_regime`'s own `2 * period` minimum) -- exactly the same
threshold, not a coincidence.

Verified to reproduce `_compute_adx`'s exact math step for step -- see
`tests/unit/domain/test_incremental_adx.py`'s parity tests, checking
agreement at every step, not just the final value.
"""

from decimal import Decimal


class IncrementalAdx:
    def __init__(self, period: int) -> None:
        if isinstance(period, bool) or not isinstance(period, int):
            raise TypeError(f"period must be an int, got {type(period).__name__}")
        if period < 1:
            raise ValueError(f"period must be at least 1, got {period}")

        self._period = period
        self._prev_high: Decimal | None = None
        self._prev_low: Decimal | None = None
        self._prev_close: Decimal | None = None

        self._diff_count = 0
        self._seed_tr_sum = Decimal(0)
        self._seed_plus_dm_sum = Decimal(0)
        self._seed_minus_dm_sum = Decimal(0)

        self._smoothed_tr: Decimal | None = None
        self._smoothed_plus_dm: Decimal | None = None
        self._smoothed_minus_dm: Decimal | None = None

        self._dx_seed_sum = Decimal(0)
        self._dx_seed_count = 0
        self._adx: Decimal | None = None

    def update(self, high: Decimal, low: Decimal, close: Decimal) -> Decimal | None:
        if self._prev_high is None or self._prev_low is None or self._prev_close is None:
            self._prev_high, self._prev_low, self._prev_close = high, low, close
            return None

        prev_high, prev_low, prev_close = self._prev_high, self._prev_low, self._prev_close
        up_move = high - prev_high
        down_move = prev_low - low
        plus_dm = up_move if (up_move > down_move and up_move > 0) else Decimal(0)
        minus_dm = down_move if (down_move > up_move and down_move > 0) else Decimal(0)
        true_range = max(high - low, abs(high - prev_close), abs(low - prev_close))
        self._prev_high, self._prev_low, self._prev_close = high, low, close
        self._diff_count += 1

        if self._smoothed_tr is None:
            self._seed_tr_sum += true_range
            self._seed_plus_dm_sum += plus_dm
            self._seed_minus_dm_sum += minus_dm
            if self._diff_count < self._period:
                return None
            smoothed_tr = self._seed_tr_sum
            smoothed_plus_dm = self._seed_plus_dm_sum
            smoothed_minus_dm = self._seed_minus_dm_sum
        else:
            assert self._smoothed_plus_dm is not None
            assert self._smoothed_minus_dm is not None
            smoothed_tr = self._smoothed_tr - (self._smoothed_tr / self._period) + true_range
            smoothed_plus_dm = (
                self._smoothed_plus_dm - (self._smoothed_plus_dm / self._period) + plus_dm
            )
            smoothed_minus_dm = (
                self._smoothed_minus_dm - (self._smoothed_minus_dm / self._period) + minus_dm
            )
        self._smoothed_tr = smoothed_tr
        self._smoothed_plus_dm = smoothed_plus_dm
        self._smoothed_minus_dm = smoothed_minus_dm

        dx = _directional_index(smoothed_tr, smoothed_plus_dm, smoothed_minus_dm)

        if self._adx is None:
            self._dx_seed_sum += dx
            self._dx_seed_count += 1
            if self._dx_seed_count == self._period:
                self._adx = self._dx_seed_sum / self._period
        else:
            self._adx = (self._adx * (self._period - 1) + dx) / self._period

        return self._adx


def _directional_index(
    smoothed_tr: Decimal, smoothed_plus_dm: Decimal, smoothed_minus_dm: Decimal
) -> Decimal:
    """Identical to `regime_detection._directional_index` -- duplicated,
    not imported, so this module has no dependency on the slow reference
    implementation it's meant to be independently verified against."""
    if smoothed_tr == 0:
        return Decimal(0)
    plus_di = Decimal(100) * smoothed_plus_dm / smoothed_tr
    minus_di = Decimal(100) * smoothed_minus_dm / smoothed_tr
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return Decimal(0)
    return Decimal(100) * abs(plus_di - minus_di) / di_sum

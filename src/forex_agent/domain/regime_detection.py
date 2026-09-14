"""FX-12: trend-vs-range regime classification via Wilder's ADX (Average
Directional Index) — the standard, deterministic technical-analysis
measure of trend strength. No ML: consistent with the current phase's
exclusion of AI/ML decision-making.

ADX is computed from MID prices (the bid/ask average of each OHLC point).
Trend/regime is a market-structure question, not an execution-price one —
picking one side (bid or ask) would introduce an arbitrary directional
bias that has nothing to do with the actual indicator.
"""

from decimal import Decimal

from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_series import require_consistent_series
from forex_agent.domain.trend_regime import TrendRegime

_DEFAULT_PERIOD = 14
_DEFAULT_THRESHOLD = Decimal("25")


def classify_regime(
    candles: list[Candle],
    *,
    period: int = _DEFAULT_PERIOD,
    threshold: Decimal = _DEFAULT_THRESHOLD,
) -> TrendRegime:
    """Classify the most recent state of `candles` as `TRENDING` (ADX at
    or above `threshold`) or `RANGING` (below it) — a binary call, no
    third "developing trend" state.

    `threshold=25` is Wilder's own traditional convention.

    Requires at least `2 * period` candles: Wilder's smoothing needs
    `period` bars to seed the first smoothed +DM/-DM/TR, then another
    `period` DX values to smooth into the first ADX. Raises `ValueError`
    with fewer, rather than computing ADX on data too thin to mean
    anything. Also raises via `require_consistent_series` (one
    instrument, one granularity, strictly ascending) and if any candle
    isn't finalized — regime detection, like backtesting, only makes
    sense over settled history.
    """
    minimum_required = period * 2
    if len(candles) < minimum_required:
        raise ValueError(
            f"classify_regime requires at least {minimum_required} candles "
            f"(2 x period={period}) to produce a meaningful ADX, got {len(candles)}"
        )

    require_consistent_series(candles)
    for candle in candles:
        if not candle.is_finalized:
            raise ValueError(
                f"candle at {candle.start_time.value.isoformat()} is not finalized; "
                "regime detection must only use finalized candles"
            )

    adx = _compute_adx(candles, period)
    return TrendRegime.TRENDING if adx >= threshold else TrendRegime.RANGING


def _compute_adx(candles: list[Candle], period: int) -> Decimal:
    """Wilder's ADX, as of the last candle in `candles`. Assumes
    `len(candles) >= 2 * period` — checked by the caller."""
    highs = [(c.bid.high + c.ask.high) / 2 for c in candles]
    lows = [(c.bid.low + c.ask.low) / 2 for c in candles]
    closes = [(c.bid.close + c.ask.close) / 2 for c in candles]
    n = len(candles)

    plus_dm = [Decimal(0)] * n
    minus_dm = [Decimal(0)] * n
    true_range = [Decimal(0)] * n
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else Decimal(0)
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else Decimal(0)
        true_range[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    # Wilder smoothing: seed = sum of the first `period` raw values, then
    # smoothed[i] = smoothed[i-1] - smoothed[i-1]/period + raw[i].
    smoothed_tr = sum(true_range[1 : period + 1], Decimal(0))
    smoothed_plus_dm = sum(plus_dm[1 : period + 1], Decimal(0))
    smoothed_minus_dm = sum(minus_dm[1 : period + 1], Decimal(0))

    dx_values = [_directional_index(smoothed_tr, smoothed_plus_dm, smoothed_minus_dm)]
    for i in range(period + 1, n):
        smoothed_tr = smoothed_tr - (smoothed_tr / period) + true_range[i]
        smoothed_plus_dm = smoothed_plus_dm - (smoothed_plus_dm / period) + plus_dm[i]
        smoothed_minus_dm = smoothed_minus_dm - (smoothed_minus_dm / period) + minus_dm[i]
        dx_values.append(_directional_index(smoothed_tr, smoothed_plus_dm, smoothed_minus_dm))

    # ADX itself is a Wilder-smoothed *average* of DX, not a sum-based
    # accumulator: seed = simple average of the first `period` DX values,
    # then adx[i] = (adx[i-1] * (period - 1) + dx[i]) / period.
    adx = sum(dx_values[:period], Decimal(0)) / period
    for dx in dx_values[period:]:
        adx = (adx * (period - 1) + dx) / period

    return adx


def _directional_index(
    smoothed_tr: Decimal, smoothed_plus_dm: Decimal, smoothed_minus_dm: Decimal
) -> Decimal:
    if smoothed_tr == 0:
        return Decimal(0)
    plus_di = Decimal(100) * smoothed_plus_dm / smoothed_tr
    minus_di = Decimal(100) * smoothed_minus_dm / smoothed_tr
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return Decimal(0)
    return Decimal(100) * abs(plus_di - minus_di) / di_sum

"""FX-29: `IncrementalAdx` parity tests against the already-independently-
verified `_compute_adx` (FX-12's own reference-value cross-check covers
the arithmetic itself; this only needs to prove the incremental version
agrees with it step for step, not re-derive ADX correctness).
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.incremental_adx import IncrementalAdx
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.regime_detection import _compute_adx
from forex_agent.domain.timestamps import UtcTimestamp

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")

# A varied, non-monotonic series -- exercises up moves, down moves, and
# inside/outside bars, not just a clean trend (which could hide an
# indexing bug that a always-up series wouldn't expose).
_CLOSES = [
    "100", "102", "101", "105", "103", "108", "106", "104", "109", "112",
    "110", "115", "111", "108", "113", "117", "114", "119", "116", "121",
    "118", "123", "120", "125", "122", "127", "124", "129", "126", "131",
]  # fmt: skip


def _candle(i: int, close: str) -> Candle:
    p = Decimal(close)
    # Give each candle a bit of range so high/low/close differ, exercising
    # the true-range/DM math properly (a flat candle degenerates it).
    flat = Ohlc(open=p - Decimal("0.5"), high=p + Decimal("1"), low=p - Decimal("1"), close=p)
    return Candle(
        instrument=EUR_USD,
        granularity=Granularity.M1,
        start_time=UtcTimestamp(datetime(2026, 1, 1, 0, i, 0, tzinfo=UTC)),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )


_CANDLES = [_candle(i, c) for i, c in enumerate(_CLOSES)]


def _mid_hlc(candle: Candle) -> tuple[Decimal, Decimal, Decimal]:
    high = (candle.bid.high + candle.ask.high) / 2
    low = (candle.bid.low + candle.ask.low) / 2
    close = (candle.bid.close + candle.ask.close) / 2
    return high, low, close


@pytest.mark.parametrize("period", [2, 3, 5])
def test_matches_reference_compute_adx_at_every_step(period: int) -> None:
    incremental = IncrementalAdx(period)
    actual: list[Decimal | None] = []
    for candle in _CANDLES:
        high, low, close = _mid_hlc(candle)
        actual.append(incremental.update(high, low, close))

    minimum_required = period * 2
    for k in range(1, len(_CANDLES) + 1):
        if k < minimum_required:
            assert actual[k - 1] is None, f"period={period} k={k}: expected None"
            continue
        expected = _compute_adx(_CANDLES[:k], period)
        assert actual[k - 1] == expected, f"period={period} k={k}"


def test_returns_none_before_two_times_period_candles_seen() -> None:
    incremental = IncrementalAdx(3)  # needs 6 candles

    results = [incremental.update(*_mid_hlc(c)) for c in _CANDLES[:5]]
    assert all(r is None for r in results)

    sixth = incremental.update(*_mid_hlc(_CANDLES[5]))
    assert sixth is not None


def test_rejects_bool_period() -> None:
    with pytest.raises(TypeError, match="period"):
        IncrementalAdx(True)


def test_rejects_period_below_one() -> None:
    with pytest.raises(ValueError, match="period"):
        IncrementalAdx(0)

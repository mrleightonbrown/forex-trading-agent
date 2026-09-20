"""FX-36: `IncrementalWilderAtr` parity tests against the reference
`volatility_expansion._atr`/`_true_range_series` (already exercised
indirectly by FX-20's own strategy tests; this checks the incremental
version agrees with the from-scratch recompute step for step, not just
at the end).
"""

from decimal import Decimal

import pytest

from forex_agent.domain.incremental_atr import IncrementalWilderAtr
from forex_agent.domain.strategies.volatility_expansion import _atr, _true_range_series

# A varied, non-monotonic series of (high, low, close) triples.
_BARS = [
    (Decimal(h), Decimal(low), Decimal(c))
    for h, low, c in [
        (101, 99, 100), (103, 100, 102), (102, 99, 100), (106, 101, 105),
        (105, 102, 103), (109, 104, 108), (107, 103, 105), (105, 101, 103),
        (110, 105, 109), (113, 108, 112), (111, 107, 109), (116, 110, 115),
        (112, 107, 109), (109, 104, 108), (114, 109, 113), (118, 113, 117),
        (115, 110, 114), (120, 115, 119), (117, 112, 116), (122, 117, 121),
        (119, 114, 118), (124, 119, 123), (121, 116, 120), (126, 121, 125),
        (123, 118, 122), (128, 123, 127), (125, 120, 124), (130, 125, 129),
        (127, 122, 126), (132, 127, 131),
    ]
]  # fmt: skip


@pytest.mark.parametrize("period", [2, 3, 5, 14])
def test_matches_reference_atr_at_every_step(period: int) -> None:
    incremental = IncrementalWilderAtr(period)
    actual: list[Decimal | None] = [incremental.update(h, low, c) for h, low, c in _BARS]

    highs = [h for h, _low, _c in _BARS]
    lows = [low for _h, low, _c in _BARS]
    closes = [c for _h, _low, c in _BARS]

    for k in range(1, len(_BARS) + 1):
        if k < period + 1:
            assert actual[k - 1] is None, f"period={period} k={k}: expected None"
            continue
        true_range = _true_range_series(highs[:k], lows[:k], closes[:k])
        expected = _atr(true_range, period)
        assert actual[k - 1] == expected, f"period={period} k={k}"


def test_returns_none_before_period_plus_one_bars_seen() -> None:
    incremental = IncrementalWilderAtr(3)  # needs 4 bars (3 diffs)

    results = [incremental.update(h, low, c) for h, low, c in _BARS[:3]]
    assert all(r is None for r in results)

    fourth = incremental.update(*_BARS[3])
    assert fourth is not None


def test_rejects_bool_period() -> None:
    with pytest.raises(TypeError, match="period"):
        IncrementalWilderAtr(True)


def test_rejects_period_below_one() -> None:
    with pytest.raises(ValueError, match="period"):
        IncrementalWilderAtr(0)

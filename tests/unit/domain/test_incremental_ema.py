"""FX-29: `IncrementalSmaSeededEma` parity tests.

The critical property: fed one close at a time, it must reproduce
exactly (bit-for-bit Decimal equality) what a fresh from-scratch
SMA-seeded EMA recompute over the full prefix-so-far would give at
EVERY step -- not just at the end. Checked step by step, since a subtle
divergence that only shows up occasionally would be exactly the kind of
bug this class exists to prevent from silently entering the research
pipeline.
"""

from decimal import Decimal

import pytest

from forex_agent.domain.incremental_ema import IncrementalSmaSeededEma

_CLOSES = [
    Decimal(v) for v in ["100", "101", "99", "103", "107", "104", "110", "108", "112", "115"]
]


def _reference_ema_at_each_step(closes: list[Decimal], period: int) -> list[Decimal | None]:
    """A direct, independent (not copy-pasted from the strategy files'
    `_sma_seeded_ema`) implementation of the same SMA-seeded EMA
    definition, evaluated fresh from scratch at every prefix length --
    the reference this test checks `IncrementalSmaSeededEma` against."""
    results: list[Decimal | None] = []
    for k in range(1, len(closes) + 1):
        prefix = closes[:k]
        if len(prefix) < period:
            results.append(None)
            continue
        multiplier = Decimal(2) / Decimal(period + 1)
        seed = sum(prefix[:period], Decimal(0)) / period
        value = seed
        for close in prefix[period:]:
            value = close * multiplier + value * (1 - multiplier)
        results.append(value)
    return results


@pytest.mark.parametrize("period", [1, 2, 3, 5])
def test_matches_from_scratch_recompute_at_every_step(period: int) -> None:
    expected = _reference_ema_at_each_step(_CLOSES, period)
    incremental = IncrementalSmaSeededEma(period)

    actual = [incremental.update(close) for close in _CLOSES]

    assert actual == expected


def test_returns_none_before_period_closes_seen() -> None:
    incremental = IncrementalSmaSeededEma(3)

    assert incremental.update(Decimal("100")) is None
    assert incremental.update(Decimal("101")) is None
    assert incremental.update(Decimal("102")) is not None


def test_seed_is_simple_average_of_first_period_closes() -> None:
    incremental = IncrementalSmaSeededEma(3)

    incremental.update(Decimal("100"))
    incremental.update(Decimal("110"))
    seed = incremental.update(Decimal("120"))

    assert seed == Decimal("110")  # (100+110+120)/3


def test_rejects_bool_period() -> None:
    with pytest.raises(TypeError, match="period"):
        IncrementalSmaSeededEma(True)


def test_rejects_period_below_one() -> None:
    with pytest.raises(ValueError, match="period"):
        IncrementalSmaSeededEma(0)

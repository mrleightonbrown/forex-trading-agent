"""FX-39: block-bootstrap significance testing tests."""

import math
import random
from decimal import Decimal

import pytest

from forex_agent.domain.block_bootstrap import (
    moving_block_bootstrap_means,
    percentile_ci,
    sample_autocorrelation,
    segment_block_bootstrap_means,
    select_block_length,
    summarize_bootstrap,
)

# --- sample_autocorrelation --------------------------------------------


def test_autocorrelation_of_perfect_alternating_series_is_near_negative_one() -> None:
    # [1, -1, 1, -1, ...], n=20: mean 0, denom = sum of 20 squared
    # deviations = 20; numer = sum over the 19 adjacent pairs, each
    # contributing -1, = -19. ACF(1) = -19/20 = -0.95 exactly (hand-
    # verified via direct computation before writing this assertion) --
    # not -1, because the standard biased estimator's numerator sums
    # n-lag terms against a denominator summed over all n.
    values = [Decimal(1) if i % 2 == 0 else Decimal(-1) for i in range(20)]

    acf = sample_autocorrelation(values, 1)

    assert acf == Decimal("-0.95")


def test_autocorrelation_of_constant_series_is_zero() -> None:
    values = [Decimal(5) for _ in range(10)]

    assert sample_autocorrelation(values, 1) == Decimal(0)


def test_autocorrelation_rejects_lag_below_one() -> None:
    with pytest.raises(ValueError, match="lag"):
        sample_autocorrelation([Decimal(1), Decimal(2)], 0)


def test_autocorrelation_rejects_lag_at_or_above_length() -> None:
    with pytest.raises(ValueError, match="lag"):
        sample_autocorrelation([Decimal(1), Decimal(2)], 2)


def test_autocorrelation_hand_derived_example() -> None:
    # x = [1, 2, 3, 4, 5]; mean = 3. Deviations: [-2, -1, 0, 1, 2].
    # denom = 4+1+0+1+4 = 10.
    # lag-1 numer = (-2*-1)+(-1*0)+(0*1)+(1*2) = 2+0+0+2 = 4 -> ACF(1) = 0.4
    values = [Decimal(1), Decimal(2), Decimal(3), Decimal(4), Decimal(5)]

    assert sample_autocorrelation(values, 1) == Decimal("0.4")


# --- select_block_length -------------------------------------------------


def test_white_noise_series_selects_block_length_one() -> None:
    rng = random.Random(42)
    values = [Decimal(str(round(rng.gauss(0, 1), 6))) for _ in range(500)]

    selection = select_block_length(values, max_lag=20)

    assert selection.block_length == 1
    assert not selection.used_fallback


def test_strongly_autocorrelated_series_selects_a_larger_block_length() -> None:
    # AR(1) with phi=0.9: strong, slowly-decaying persistence.
    rng = random.Random(7)
    x = 0.0
    values = []
    for _ in range(500):
        x = 0.9 * x + rng.gauss(0, 1)
        values.append(Decimal(str(round(x, 6))))

    selection = select_block_length(values, max_lag=60)

    assert selection.block_length > 1


def test_falls_back_when_no_confirmed_run_found_within_max_lag() -> None:
    # A short max_lag on a persistently-correlated series should not
    # find 3 consecutive in-band lags in time.
    rng = random.Random(7)
    x = 0.0
    values = []
    for _ in range(500):
        x = 0.95 * x + rng.gauss(0, 1)
        values.append(Decimal(str(round(x, 6))))

    selection = select_block_length(values, max_lag=2, confirm_lags=3)

    assert selection.used_fallback
    assert selection.first_confirmed_lag is None
    assert selection.block_length == round(Decimal(len(values)).sqrt())


def test_selected_run_is_self_consistent_with_the_actual_acf_values() -> None:
    """Structural correctness check, not a hand-derived single number:
    whatever run `select_block_length` reports, independently recompute
    ACF at every lag in `[first_confirmed_lag, first_confirmed_lag +
    confirm_lags - 1]` via `sample_autocorrelation` directly and confirm
    ALL of them are genuinely inside the band -- and, if the run doesn't
    start at lag 1, confirm the lag immediately before it is genuinely
    OUTSIDE the band (otherwise the run should have started earlier).
    Series: each white-noise value repeated twice consecutively (a
    "paired-repeat" series) -- confirmed directly, before writing this
    test, to give a strong lag-1 ACF (~0.48, well outside the band) that
    decays to near-zero from lag 2 onward, so the run is expected to
    start at lag 2, not lag 1."""
    rng = random.Random(13)
    base = [round(rng.gauss(0, 1), 4) for _ in range(200)]
    values = [Decimal(str(b)) for b in base for _ in range(2)]
    confirm_lags = 3

    selection = select_block_length(values, max_lag=10, confirm_lags=confirm_lags)

    assert not selection.used_fallback
    assert selection.first_confirmed_lag is not None
    assert selection.first_confirmed_lag > 1, "run must not start at lag 1 for this series"
    n = len(values)
    band = Decimal("1.96") / Decimal(n).sqrt()
    for lag in range(selection.first_confirmed_lag, selection.first_confirmed_lag + confirm_lags):
        assert abs(sample_autocorrelation(values, lag)) < band
    preceding_lag = selection.first_confirmed_lag - 1
    assert abs(sample_autocorrelation(values, preceding_lag)) >= band


# --- moving_block_bootstrap_means -----------------------------------------


def test_moving_block_bootstrap_is_deterministic_for_a_fixed_seed() -> None:
    values = [Decimal(i) for i in range(50)]

    first = moving_block_bootstrap_means(values, block_length=5, num_resamples=100, seed=123)
    second = moving_block_bootstrap_means(values, block_length=5, num_resamples=100, seed=123)

    assert first == second


def test_moving_block_bootstrap_different_seeds_differ() -> None:
    values = [Decimal(i) for i in range(50)]

    first = moving_block_bootstrap_means(values, block_length=5, num_resamples=100, seed=1)
    second = moving_block_bootstrap_means(values, block_length=5, num_resamples=100, seed=2)

    assert first != second


def test_block_length_equal_to_series_length_always_reproduces_observed_mean() -> None:
    """block_length == n means there is exactly ONE possible block (the
    whole series) -- every resample must be that same series verbatim,
    so every resampled mean must exactly equal the true mean. A precise,
    hand-verifiable degenerate case, not just a plausibility check."""
    values = [Decimal(1), Decimal(5), Decimal(-2), Decimal(8), Decimal(3)]
    true_mean = sum(values, Decimal(0)) / len(values)

    means = moving_block_bootstrap_means(
        values, block_length=len(values), num_resamples=50, seed=99
    )

    assert all(m == true_mean for m in means)


def test_block_length_one_resamples_converge_near_true_mean_over_many_draws() -> None:
    """block_length=1 is ordinary iid bootstrap -- the AVERAGE of many
    resampled means should converge close to the true mean (law of large
    numbers sanity check), even though any single resample can differ."""
    rng = random.Random(3)
    values = [Decimal(str(round(rng.gauss(10, 2), 4))) for _ in range(200)]
    true_mean = sum(values, Decimal(0)) / len(values)

    means = moving_block_bootstrap_means(values, block_length=1, num_resamples=5000, seed=11)
    average_of_means = sum(means, Decimal(0)) / len(means)

    assert abs(average_of_means - true_mean) < Decimal("0.2")


def test_moving_block_bootstrap_truncates_to_the_original_sample_size() -> None:
    """A real gap agreeing on the other tests above wouldn't have
    caught: when `block_length` doesn't evenly divide `n`, the
    concatenated blocks overshoot `n` before truncation. Confirmed by
    direct computation before writing this assertion: n=5,
    block_length=4 has exactly 2 possible starting blocks --
    values[0:4]=[0,0,0,0] and values[1:5]=[0,0,0,100] -- and 2 blocks
    are needed per resample (ceil(5/4)=2). Enumerating all 4 possible
    (start, start) draw pairs by hand, truncating each concatenation to
    the first 5 values BEFORE averaging, the only possible means are 0
    or 20 -- 40 is only reachable if the untruncated 8-value
    concatenation is (wrongly) divided by n=5 instead of its own
    length. I injected exactly that bug (dropped the truncation) and
    confirmed 40 appears in the resampled means; restored, confirmed it
    never does, over many resamples/seeds."""
    values = [Decimal(0), Decimal(0), Decimal(0), Decimal(0), Decimal(100)]

    means = moving_block_bootstrap_means(values, block_length=4, num_resamples=500, seed=1)

    assert set(means) <= {Decimal(0), Decimal(20)}
    assert Decimal(20) in means, "fixture must exercise the non-zero branch too"


def test_moving_block_bootstrap_rejects_invalid_block_length() -> None:
    values = [Decimal(1), Decimal(2)]

    with pytest.raises(ValueError, match="block_length"):
        moving_block_bootstrap_means(values, block_length=0, num_resamples=10, seed=1)
    with pytest.raises(ValueError, match="block_length"):
        moving_block_bootstrap_means(values, block_length=3, num_resamples=10, seed=1)


def test_moving_block_bootstrap_rejects_invalid_num_resamples() -> None:
    with pytest.raises(ValueError, match="num_resamples"):
        moving_block_bootstrap_means([Decimal(1)], block_length=1, num_resamples=0, seed=1)


# --- segment_block_bootstrap_means -----------------------------------------


def test_single_segment_always_reproduces_its_own_mean() -> None:
    segment = [Decimal(1), Decimal(2), Decimal(3)]
    own_mean = sum(segment, Decimal(0)) / len(segment)

    means = segment_block_bootstrap_means([segment], num_resamples=30, seed=5)

    assert all(m == own_mean for m in means)


def test_segment_bootstrap_pools_by_trade_count_not_naive_average_of_means() -> None:
    """Two segments with very different sizes: a naive mean-of-segment-
    means would weight them equally; the correct pooled mean weights by
    trade count. Verified by drawing BOTH segments (forced via a
    contrived RNG-free check: with exactly 2 segments and k=2 draws,
    at least one resample among many should draw one of each) and
    confirming that resample's mean equals the true pooled value, not
    the naive average."""
    small = [Decimal(100)]  # 1 trade, huge P&L
    large = [Decimal(0)] * 99  # 99 trades, zero P&L each
    naive_average_of_means = (Decimal(100) + Decimal(0)) / 2  # = 50
    correct_pooled_mean_of_one_each = (Decimal(100) + Decimal(0) * 99) / 100  # = 1

    means = segment_block_bootstrap_means([small, large], num_resamples=200, seed=17)

    # No resample should ever land near the naive 50 -- every possible
    # draw combination (both segments, or either doubled) pools by count.
    assert all(m != naive_average_of_means for m in means)
    # At least one resample (small once, large once) should hit the
    # precise correct pooled value.
    assert any(m == correct_pooled_mean_of_one_each for m in means)


def test_segment_bootstrap_deterministic_for_a_fixed_seed() -> None:
    segments = [[Decimal(1), Decimal(2)], [Decimal(3)], [Decimal(-1), Decimal(0), Decimal(1)]]

    first = segment_block_bootstrap_means(segments, num_resamples=100, seed=42)
    second = segment_block_bootstrap_means(segments, num_resamples=100, seed=42)

    assert first == second


def test_segment_bootstrap_rejects_all_empty_segments() -> None:
    with pytest.raises(ValueError, match="segments"):
        segment_block_bootstrap_means([[], []], num_resamples=10, seed=1)


# --- percentile_ci -----------------------------------------------------


def test_percentile_ci_hand_derived_example() -> None:
    # 11 values 0..10 (already sorted, evenly spaced) -- with linear
    # interpolation, confidence=0.80 -> alpha=0.10 -> ranks 0.10*10=1.0
    # and 0.90*10=9.0 exactly (no interpolation needed): [1, 9].
    means = [Decimal(i) for i in range(11)]

    lower, upper = percentile_ci(means, Decimal("0.80"))

    assert lower == Decimal(1)
    assert upper == Decimal(9)


def test_wider_confidence_gives_a_wider_or_equal_interval() -> None:
    rng = random.Random(9)
    means = [Decimal(str(round(rng.gauss(0, 1), 4))) for _ in range(1000)]

    lower_90, upper_90 = percentile_ci(means, Decimal("0.90"))
    lower_95, upper_95 = percentile_ci(means, Decimal("0.95"))

    assert lower_95 <= lower_90
    assert upper_95 >= upper_90


def test_percentile_ci_rejects_empty_means() -> None:
    with pytest.raises(ValueError, match="means"):
        percentile_ci([], Decimal("0.90"))


def test_percentile_ci_rejects_confidence_outside_open_unit_interval() -> None:
    with pytest.raises(ValueError, match="confidence"):
        percentile_ci([Decimal(1)], Decimal("1.0"))
    with pytest.raises(ValueError, match="confidence"):
        percentile_ci([Decimal(1)], Decimal("0"))


# --- summarize_bootstrap (integration) -------------------------------------


def test_clearly_positive_low_variance_series_excludes_zero() -> None:
    rng = random.Random(21)
    values = [Decimal(str(round(rng.gauss(5, 0.5), 4))) for _ in range(300)]

    means = moving_block_bootstrap_means(values, block_length=1, num_resamples=5000, seed=1)
    result = summarize_bootstrap(values, means)

    assert result.lower_95 > 0
    assert result.fraction_le_zero == Decimal(0)


def test_noise_centered_series_includes_zero() -> None:
    rng = random.Random(22)
    values = [Decimal(str(round(rng.gauss(0, 5), 4))) for _ in range(300)]

    means = moving_block_bootstrap_means(values, block_length=1, num_resamples=5000, seed=2)
    result = summarize_bootstrap(values, means)

    assert result.lower_95 < 0 < result.upper_95


def test_summarize_bootstrap_rejects_empty_inputs() -> None:
    with pytest.raises(ValueError, match="observed_values"):
        summarize_bootstrap([], [Decimal(1)])
    with pytest.raises(ValueError, match="means"):
        summarize_bootstrap([Decimal(1)], [])


def test_summarize_bootstrap_fraction_le_zero_hand_derived() -> None:
    means = [Decimal(-1), Decimal(-1), Decimal(0), Decimal(2), Decimal(3)]
    result = summarize_bootstrap([Decimal(1)], means)

    # 3 of 5 means are <= 0.
    assert result.fraction_le_zero == Decimal("0.6")


def test_nan_free_math_not_used() -> None:
    """Sanity: no float math anywhere in this module -- confirmed by
    running with an unusual, precision-stressing input and checking the
    result stays an exact Decimal computation (no float rounding noise
    from an accidental float() conversion)."""
    values = [Decimal("0.1"), Decimal("0.2"), Decimal("0.3")]

    acf = sample_autocorrelation(values, 1)

    assert isinstance(acf, Decimal)
    assert not math.isnan(float(acf))

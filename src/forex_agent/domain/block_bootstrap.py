"""FX-39: block-bootstrap significance testing for backtest expectancy.

Motivated by external review of FX-38/FX-38H: two of this project's
four holdout candidates have profit factors only around 1.05-1.07 --
close enough to breakeven that the real question is whether they are
statistically distinguishable from a strategy with no real edge, once
TRADE DEPENDENCE (autocorrelated consecutive trades, since a strategy's
own state carries from one trade to the next) and REGIME CLUSTERING
(multi-year strong/weak stretches, already found in FX-38's own Part F)
are accounted for -- not just an ordinary, independence-assuming
confidence interval on the mean.

Deliberately domain-layer: pure functions over `Decimal` P&L sequences,
no infrastructure/strategy/candle dependencies -- reusable for any
strategy's trade list, not tied to this specific research story.

Two complementary resampling schemes, both implemented here:

1. **Moving-block bootstrap** (Kunsch 1989): the standard fix for
   testing a sample mean's significance when consecutive observations
   are autocorrelated. Resamples overlapping CONSECUTIVE blocks (not
   individual points) with replacement, preserving local dependence
   within each block. Block length is chosen OBJECTIVELY from the
   series' own sample autocorrelation function (`select_block_length`)
   -- the first lag from which the ACF stays inside the approximate
   white-noise 95% band for several consecutive lags -- not guessed or
   tuned to produce a particular answer.

2. **Segment (regime) block bootstrap**: resamples WHOLE pre-defined
   segments (e.g. calendar-period buckets) with replacement, directly
   addressing "regime clustering" by construction rather than hoping a
   fixed block length happens to be long enough to span a regime.

Both produce percentile confidence intervals on the mean (expectancy);
a CI that excludes zero is evidence the population mean is likely
non-zero even after accounting for the relevant dependence structure --
NOT proof of a durable, tradeable edge, and not evidence about any
period other than the one tested.
"""

import random
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class BlockLengthSelection:
    block_length: int
    used_fallback: bool
    first_confirmed_lag: int | None
    acf_by_lag: dict[int, Decimal]
    band: Decimal
    capped_by_max_block_length: bool


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    observed_mean: Decimal
    lower_90: Decimal
    upper_90: Decimal
    lower_95: Decimal
    upper_95: Decimal
    fraction_le_zero: Decimal
    num_resamples: int
    sample_size: int


def sample_autocorrelation(values: list[Decimal], lag: int) -> Decimal:
    """Lag-`lag` sample autocorrelation of `values` (normalized by the
    full-sample variance, the standard ACF estimator convention).
    Raises `ValueError` if `lag < 1` or `lag >= len(values)`. Returns 0
    if the series has zero variance (a constant series has no
    meaningful correlation structure)."""
    n = len(values)
    if lag < 1:
        raise ValueError(f"lag must be at least 1, got {lag}")
    if lag >= n:
        raise ValueError(f"lag ({lag}) must be less than len(values) ({n})")
    mean = sum(values, Decimal(0)) / n
    denom = sum((v - mean) ** 2 for v in values)
    if denom == 0:
        return Decimal(0)
    numer = sum((values[t] - mean) * (values[t + lag] - mean) for t in range(n - lag))
    return numer / denom


def select_block_length(
    values: list[Decimal],
    max_lag: int,
    confirm_lags: int = 3,
    min_block_length: int = 1,
    max_block_length: int | None = None,
) -> BlockLengthSelection:
    """The smallest lag `k` such that `sample_autocorrelation(values, j)`
    for `j` in `[k, k + confirm_lags - 1]` are ALL within the
    approximate white-noise 95% confidence band (+/- 1.96/sqrt(n)) --
    not just one lag, so a single lag landing inside the band by chance
    before genuine correlation resumes doesn't stop the search early.
    If ACF(1) itself is already inside the band for `confirm_lags`
    lags, `block_length` is 1 -- no detectable LINEAR trade-to-trade
    dependence, so the moving-block bootstrap correctly degenerates to
    an ordinary (individual-point) bootstrap. (Zero linear
    autocorrelation does not by itself prove independence -- volatility/
    regime-level dependence can remain even when the ACF is flat; that
    is exactly why a separate regime-block bootstrap over pre-defined
    periods is a useful complement to this series-level rule, not a
    redundant one.)

    Falls back to `round(sqrt(n))` (a standard block-bootstrap rule of
    thumb) if no such run is found within `max_lag`; `used_fallback`
    tells the caller this happened, since it usually means either
    unusually persistent dependence or `max_lag` was too small -- not
    something to silently trust. If `max_block_length` is given, both
    the confirmed-run result and the fallback are capped at it (never
    below `min_block_length`) -- a hard ceiling so pathological ACF
    behavior can't select an absurdly large block;
    `capped_by_max_block_length` tells the caller if the cap actually
    bound.

    `acf_by_lag` (every lag from 1 to `max_lag`, independent of which
    one was selected) and `band` are always returned for full
    auditability -- callers should record them, not just the final
    `block_length`.
    """
    n = len(values)
    band = Decimal("1.96") / Decimal(n).sqrt()
    acf_by_lag = {lag: sample_autocorrelation(values, lag) for lag in range(1, max_lag + 1)}
    consecutive = 0
    run_start: int | None = None
    for lag in range(1, max_lag + 1):
        if abs(acf_by_lag[lag]) < band:
            if consecutive == 0:
                run_start = lag
            consecutive += 1
            if consecutive >= confirm_lags:
                assert run_start is not None
                chosen = max(run_start, min_block_length)
                capped = max_block_length is not None and chosen > max_block_length
                if capped:
                    assert max_block_length is not None
                    chosen = max(max_block_length, min_block_length)
                return BlockLengthSelection(
                    block_length=chosen,
                    used_fallback=False,
                    first_confirmed_lag=run_start,
                    acf_by_lag=acf_by_lag,
                    band=band,
                    capped_by_max_block_length=capped,
                )
        else:
            consecutive = 0
            run_start = None
    fallback = max(round(Decimal(n).sqrt()), min_block_length)
    capped = max_block_length is not None and fallback > max_block_length
    if capped:
        assert max_block_length is not None
        fallback = max(max_block_length, min_block_length)
    return BlockLengthSelection(
        block_length=fallback,
        used_fallback=True,
        first_confirmed_lag=None,
        acf_by_lag=acf_by_lag,
        band=band,
        capped_by_max_block_length=capped,
    )


def moving_block_bootstrap_means(
    values: list[Decimal],
    block_length: int,
    num_resamples: int,
    seed: int,
) -> list[Decimal]:
    """`num_resamples` resampled means via the moving-block bootstrap:
    each resample concatenates `ceil(n / block_length)` overlapping
    CONSECUTIVE blocks of `block_length` values (start positions drawn
    with replacement from all `n - block_length + 1` possible starts),
    then truncates to the original length `n` before taking the mean --
    preserving sample size so resampled means are directly comparable
    to the observed one. `block_length == n` degenerates to always
    resampling the single possible block (the whole series verbatim),
    so every resampled mean exactly equals the observed mean.
    Deterministic for a fixed `seed`.
    """
    n = len(values)
    if block_length < 1 or block_length > n:
        raise ValueError(f"block_length ({block_length}) must be in [1, {n}]")
    if num_resamples < 1:
        raise ValueError(f"num_resamples must be at least 1, got {num_resamples}")
    rng = random.Random(seed)
    num_possible_starts = n - block_length + 1
    blocks_needed = -(-n // block_length)  # ceil division
    means: list[Decimal] = []
    for _ in range(num_resamples):
        resampled: list[Decimal] = []
        for _ in range(blocks_needed):
            start = rng.randrange(num_possible_starts)
            resampled.extend(values[start : start + block_length])
        resampled = resampled[:n]
        means.append(sum(resampled, Decimal(0)) / n)
    return means


def segment_block_bootstrap_means(
    segments: list[list[Decimal]],
    num_resamples: int,
    seed: int,
) -> list[Decimal]:
    """`num_resamples` resampled means via the segment (regime) block
    bootstrap: each resample draws `len(segments)` segments WITH
    replacement from `segments` (e.g. each segment a calendar period's
    own trade P&Ls -- possibly different lengths), pools every value
    from the drawn segments together, and takes the POOLED mean (total
    P&L / total count across the drawn segments) -- the same
    weight-by-trade-count convention this project's own `expectancy`
    metric already uses elsewhere, not a naive mean-of-segment-means.
    A single non-empty segment degenerates to always drawing that same
    segment, so every resampled mean exactly equals its own mean.
    Deterministic for a fixed `seed`.
    """
    if not segments or all(len(s) == 0 for s in segments):
        raise ValueError("segments must contain at least one non-empty segment")
    if num_resamples < 1:
        raise ValueError(f"num_resamples must be at least 1, got {num_resamples}")
    rng = random.Random(seed)
    k = len(segments)
    means: list[Decimal] = []
    for _ in range(num_resamples):
        pooled: list[Decimal] = []
        for _ in range(k):
            idx = rng.randrange(k)
            pooled.extend(segments[idx])
        means.append(sum(pooled, Decimal(0)) / len(pooled) if pooled else Decimal(0))
    return means


def percentile_ci(means: list[Decimal], confidence: Decimal) -> tuple[Decimal, Decimal]:
    """Percentile-method confidence interval: e.g. `confidence=0.90`
    gives the `[5th, 95th]` percentile of `means`. Linear interpolation
    between the two nearest order statistics (the standard percentile-
    method convention), not nearest-rank, so results aren't overly
    sensitive to `num_resamples`. Raises `ValueError` if `means` is
    empty or `confidence` isn't in `(0, 1)`.
    """
    if not means:
        raise ValueError("means must not be empty")
    if not (Decimal(0) < confidence < Decimal(1)):
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    ordered = sorted(means)
    alpha = (Decimal(1) - confidence) / 2
    lower = _interpolated_percentile(ordered, alpha)
    upper = _interpolated_percentile(ordered, Decimal(1) - alpha)
    return lower, upper


def _interpolated_percentile(ordered: list[Decimal], p: Decimal) -> Decimal:
    n = len(ordered)
    if n == 1:
        return ordered[0]
    rank = p * (n - 1)
    lower_idx = int(rank)
    upper_idx = min(lower_idx + 1, n - 1)
    frac = rank - lower_idx
    return ordered[lower_idx] + frac * (ordered[upper_idx] - ordered[lower_idx])


def summarize_bootstrap(observed_values: list[Decimal], means: list[Decimal]) -> BootstrapResult:
    """Builds a `BootstrapResult` from an already-computed list of
    resampled means (from either bootstrap scheme above) against the
    original `observed_values`.

    `fraction_le_zero` doubles as an approximate ONE-SIDED bootstrap
    p-value for `H0: population mean <= 0` vs. `H1: population mean >
    0` (the fraction of the bootstrap's own estimate of the sampling
    distribution that falls at or below zero -- equivalently, the
    one-sided confidence level at which the percentile CI's lower bound
    would land exactly on zero). `1 - fraction_le_zero` is the more
    intuitive complementary reading: "this fraction of resamples showed
    positive expectancy" -- useful DESCRIPTIVE information, but not a
    Bayesian posterior probability that the true expectancy is
    positive; don't conflate the two.
    """
    if not observed_values:
        raise ValueError("observed_values must not be empty")
    if not means:
        raise ValueError("means must not be empty")
    observed_mean = sum(observed_values, Decimal(0)) / len(observed_values)
    lower_90, upper_90 = percentile_ci(means, Decimal("0.90"))
    lower_95, upper_95 = percentile_ci(means, Decimal("0.95"))
    fraction_le_zero = Decimal(sum(1 for m in means if m <= 0)) / Decimal(len(means))
    return BootstrapResult(
        observed_mean=observed_mean,
        lower_90=lower_90,
        upper_90=upper_90,
        lower_95=lower_95,
        upper_95=upper_95,
        fraction_le_zero=fraction_le_zero,
        num_resamples=len(means),
        sample_size=len(observed_values),
    )


def holm_bonferroni_adjusted_p_values(p_values: list[Decimal]) -> list[Decimal]:
    """Holm-Bonferroni step-down adjustment for a FAMILY of `m`
    simultaneous hypothesis tests -- controls the family-wise error
    rate (the chance of at least one false positive across the whole
    family) under arbitrary dependence between the tests (no
    independence assumption needed, unlike some alternatives), and is
    uniformly at least as powerful as plain Bonferroni.

    Returns adjusted p-values in the SAME order as the input `p_values`
    (not sorted) -- the standard "adjusted p-value" convention: reject
    hypothesis `i` at family-wise level `alpha` iff
    `adjusted[i] <= alpha`.

    Procedure: sort p-values ascending; the `k`-th smallest (1-indexed)
    is multiplied by `m - k + 1`, capped at 1, then each is replaced by
    the running maximum seen so far (so adjusted p-values are
    non-decreasing in rank, the standard monotonization step) before
    being mapped back to their original positions.

    Raises `ValueError` if `p_values` is empty.
    """
    m = len(p_values)
    if m == 0:
        raise ValueError("p_values must not be empty")
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted_by_rank: list[Decimal] = []
    running_max = Decimal(0)
    for rank, idx in enumerate(order):
        multiplier = Decimal(m - rank)
        candidate = min(Decimal(1), multiplier * p_values[idx])
        running_max = max(running_max, candidate)
        adjusted_by_rank.append(running_max)
    result = [Decimal(0)] * m
    for rank, idx in enumerate(order):
        result[idx] = adjusted_by_rank[rank]
    return result

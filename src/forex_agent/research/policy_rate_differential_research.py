"""FX-46: pure, deterministic building blocks for the historical
policy-rate differential research EXPERIMENT -- level vs. subsequent
return, and differential-change vs. subsequent return -- using the
existing, hardened `ComputePolicyRateDifferential` (FX-45/FX-45H/
FX-45H.1) as the ONLY source of policy-rate state. This module never
reconstructs policy-rate state from raw macro rows itself; `evaluate_
feature` below is the single place it touches that use case at all.

This is a RESEARCH experiment, not a trading strategy: no thresholds,
no scoring, no signal, no execution logic, no tradability claims.
Returns computed here are `mid_open`-to-`mid_open` RESEARCH returns
(FX-46 section 4) -- never executable P&L: no spread subtraction (a
research return does not re-subtract what the mid price already
nets out), no slippage, no financing.

See `scripts/run_fx46_policy_rate_differential_research.py` for the
actual async orchestration (real DB reads via `ComputePolicyRateDifferential`,
real candle fetches via `CandleRepository`) that calls `evaluate_
feature` below and feeds its results through the rest of this
module's pure functions, plus the aggregation/statistics/reporting
layer that turns many `ForwardReturn`/`ChangeEvent` records into the
story's required per-cell statistics.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from forex_agent.application.use_cases.compute_policy_rate_differential import (
    ComputePolicyRateDifferential,
)
from forex_agent.domain.block_bootstrap import interpolated_percentile
from forex_agent.domain.candle import Candle
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.policy_rate_differential import DifferentialUnavailable, RateSemantics
from forex_agent.domain.research_readiness import ResearchIntervalNotReadyError
from forex_agent.domain.timestamps import UtcTimestamp

#: FX-46 section 5: exactly these three, pre-registered before any
#: result was seen. No other horizon may be added after the fact.
FORWARD_HORIZONS_TRADING_DAYS: tuple[int, ...] = (1, 5, 20)

#: FX-46 section 12: fixed calendar eras, pre-registered, never moved
#: after seeing results. `None` end means "through the data cutoff".
ERAS: tuple[tuple[str, date, date | None], ...] = (
    ("2005-2011", date(2005, 1, 1), date(2011, 12, 31)),
    ("2012-2018", date(2012, 1, 1), date(2018, 12, 31)),
    ("2019-cutoff", date(2019, 1, 1), None),
)


class Disposition(Enum):
    """The outcome of one `evaluate_feature` call, normalized from
    `ComputePolicyRateDifferential`'s own raise-vs-return split
    (FX-45H) into one uniform result FX-46's own pipeline can classify
    and count."""

    USABLE = "USABLE"
    BLOCKED = "BLOCKED"  # ResearchIntervalNotReadyError was raised
    UNAVAILABLE = "UNAVAILABLE"  # DifferentialUnavailable was returned


class LevelGroup(Enum):
    """FX-46 section 6 -- purely mechanical, no threshold/band."""

    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    ZERO = "ZERO"


class ChangeGroup(Enum):
    """FX-46 section 7. Deliberately NOT WIDENING/NARROWING -- FX-46's
    own section 1 forbids that vocabulary here as ambiguous around
    zero; INCREASED/DECREASED/UNCHANGED instead."""

    INCREASED = "INCREASED"
    DECREASED = "DECREASED"
    UNCHANGED = "UNCHANGED"


class TransitionStatus(Enum):
    """What `build_change_events` could determine about the transition
    INTO one USABLE daily observation, relative to the immediately
    preceding trading day (FX-46 section 7)."""

    ADMISSIBLE = "ADMISSIBLE"  # both this day and the prior day were USABLE
    GAP = "GAP"  # this day is USABLE but the immediately preceding day was not
    NO_PRIOR_DAY = "NO_PRIOR_DAY"  # first day in the evaluated range -- nothing precedes it


@dataclass(frozen=True, slots=True)
class FeatureEvaluation:
    """One normalized `(pair, semantics, as_of)` result. `differential`
    is populated iff `disposition is Disposition.USABLE`; `reason` iff
    BLOCKED or UNAVAILABLE -- never both, never neither. `blocked_dates`
    (only ever non-empty for BLOCKED with `reason == "provisional_
    timing"`) carries the offending vintages' own `observation_period`
    dates, for diagnostics only."""

    as_of: UtcTimestamp
    disposition: Disposition
    differential: Decimal | None
    reason: str | None
    blocked_dates: tuple[date, ...] = ()


async def evaluate_feature(
    use_case: ComputePolicyRateDifferential,
    instrument: Instrument,
    as_of: UtcTimestamp,
    semantics: RateSemantics,
) -> FeatureEvaluation:
    """Calls `use_case` exactly once and normalizes its outcome -- the
    ONLY place in FX-46 that touches `ComputePolicyRateDifferential`
    directly (FX-46's own explicit requirement: no reconstruction of
    policy-rate state from raw macro rows anywhere else in this
    module). Never falls back from EFFECTIVE to ANNOUNCED, or from
    BLOCKED/UNAVAILABLE to any guessed value -- `differential` is
    `None` whenever `disposition` is not `USABLE`, unconditionally;
    that is `ComputePolicyRateDifferential`'s own fail-closed guarantee
    (FX-45/FX-45H/FX-45H.1), simply observed and recorded here, never
    second-guessed or imputed around.
    """
    try:
        result = await use_case(instrument, as_of, semantics)
    except ResearchIntervalNotReadyError as exc:
        reason = "missing_baseline" if exc.no_baseline else "provisional_timing"
        dates = tuple(sorted({v.observation_period.value.date() for v in exc.provisional_vintages}))
        return FeatureEvaluation(
            as_of=as_of,
            disposition=Disposition.BLOCKED,
            differential=None,
            reason=reason,
            blocked_dates=dates,
        )
    if isinstance(result, DifferentialUnavailable):
        return FeatureEvaluation(
            as_of=as_of,
            disposition=Disposition.UNAVAILABLE,
            differential=None,
            reason=result.reason,
        )
    return FeatureEvaluation(
        as_of=as_of,
        disposition=Disposition.USABLE,
        differential=result.current.differential,
        reason=None,
    )


def select_weekly_bars(d_candles: Sequence[Candle]) -> list[Candle]:
    """FX-46 section 6: one `Candle` per ISO calendar week -- the FIRST
    available D-bar open in that week, a pre-registered anti-
    pseudoreplication measure against treating every unchanged daily
    rate state as an independent observation. Sorts defensively by
    `start_time` first (FX-46 section 18's own "output stable under
    input ordering" requirement) rather than assuming caller order.
    Uses ISO week (`date.isocalendar()`), not a plain calendar
    year/week pairing, so a year-boundary week (e.g. late December
    belonging to ISO week 1 of the following year) is grouped
    correctly rather than split.
    """
    ordered = sorted(d_candles, key=lambda c: c.start_time.value)
    seen: set[tuple[int, int]] = set()
    selected: list[Candle] = []
    for candle in ordered:
        iso = candle.start_time.value.date().isocalendar()
        key = (iso.year, iso.week)
        if key not in seen:
            seen.add(key)
            selected.append(candle)
    return selected


def classify_level(differential: Decimal) -> LevelGroup:
    """FX-46 section 6 -- purely mechanical, no threshold/band."""
    if differential > 0:
        return LevelGroup.POSITIVE
    if differential < 0:
        return LevelGroup.NEGATIVE
    return LevelGroup.ZERO


def classify_change(delta: Decimal) -> ChangeGroup:
    """FX-46 section 7 -- purely mechanical, no threshold/band."""
    if delta > 0:
        return ChangeGroup.INCREASED
    if delta < 0:
        return ChangeGroup.DECREASED
    return ChangeGroup.UNCHANGED


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    """One USABLE daily evaluation's transition status, relative to
    the immediately preceding trading day (FX-46 section 7). `group`/
    `delta` are populated iff `status is TransitionStatus.ADMISSIBLE`
    -- a GAP or NO_PRIOR_DAY observation is never assigned an inferred
    group, even though `differential` itself (this day's OWN computed
    value) is always populated for every `ChangeEvent` regardless of
    status -- only what it should be compared AGAINST is ever in
    doubt, never the day's own value."""

    as_of: UtcTimestamp
    differential: Decimal
    status: TransitionStatus
    group: ChangeGroup | None
    delta: Decimal | None


def build_change_events(daily: Sequence[FeatureEvaluation]) -> list[ChangeEvent]:
    """FX-46 section 7: walks `daily` (one `FeatureEvaluation` per
    canonical D-bar open -- sorted defensively by `as_of` here, not
    assumed) and classifies each USABLE day's transition relative to
    the IMMEDIATELY PRECEDING trading day in this same sequence -- not
    the most recent USABLE one. A BLOCKED/UNAVAILABLE day in between
    means the true path of the differential across that gap is
    unknown, so no transition may be inferred across it (`status is
    TransitionStatus.GAP`, `group`/`delta` both `None`) -- this is the
    "do not manufacture event timing across PIT/readiness gaps"
    requirement, enforced structurally rather than left to a caller's
    own care.

    A day that is itself not USABLE contributes no `ChangeEvent` at all
    (its own BLOCKED/UNAVAILABLE disposition is counted separately,
    from the same `daily` sequence, elsewhere) -- this function's
    output only ever concerns USABLE days.

    If BOTH base and quote legs change on the same evaluation day, this
    naturally produces exactly ONE `ChangeEvent` for that day (FX-46
    section 7's own explicit requirement): `differential` is always the
    single derived `base_rate - quote_rate` value FX-45 itself
    computes for that instant, never two separate per-leg deltas that
    would need merging.
    """
    ordered = sorted(daily, key=lambda e: e.as_of.value)
    events: list[ChangeEvent] = []
    previous: FeatureEvaluation | None = None
    for current in ordered:
        if current.disposition is not Disposition.USABLE:
            previous = current
            continue
        assert current.differential is not None  # USABLE guarantees this
        if previous is None:
            events.append(
                ChangeEvent(
                    as_of=current.as_of,
                    differential=current.differential,
                    status=TransitionStatus.NO_PRIOR_DAY,
                    group=None,
                    delta=None,
                )
            )
        elif previous.disposition is not Disposition.USABLE:
            events.append(
                ChangeEvent(
                    as_of=current.as_of,
                    differential=current.differential,
                    status=TransitionStatus.GAP,
                    group=None,
                    delta=None,
                )
            )
        else:
            assert previous.differential is not None  # USABLE guarantees this
            delta = current.differential - previous.differential
            events.append(
                ChangeEvent(
                    as_of=current.as_of,
                    differential=current.differential,
                    status=TransitionStatus.ADMISSIBLE,
                    group=classify_change(delta),
                    delta=delta,
                )
            )
        previous = current
    return events


def mid_open(candle: Candle) -> Decimal:
    """FX-46 section 4: `(bid_open + ask_open) / 2` -- a RESEARCH
    return price, never executable P&L (no spread subtraction, no
    slippage, no financing)."""
    return (candle.bid.open + candle.ask.open) / 2


def find_entry_index(d_candles: Sequence[Candle], as_of: UtcTimestamp) -> int | None:
    """FX-46 section 4/5: the index (into `d_candles`, which must
    already be sorted ascending by `start_time` -- this does not sort
    defensively, since callers need a STABLE, shared index space with
    `compute_forward_return` below) of the first D bar whose `start_
    time` is STRICTLY after `as_of`. Entry uses the NEXT bar's open,
    never the feature-evaluation bar's own close or any earlier price
    (this project's established no-lookahead discipline -- CLAUDE.md:
    "Strategies must only evaluate finalized candles" -- applied here
    to a research return rather than a trade). `None` if no such bar
    exists (`as_of` is at or after the last available D bar).
    """
    for index, candle in enumerate(d_candles):
        if candle.start_time.value > as_of.value:
            return index
    return None


@dataclass(frozen=True, slots=True)
class ForwardReturn:
    """One (entry, horizon) forward-return computation (FX-46 section
    4/5). `censored` is True (and `future_time`/`future_mid`/`return_
    value` all `None`) when fewer than `horizon_days` D bars exist
    after entry -- CENSORED_NO_FUTURE_DATA, never a guessed/truncated
    value."""

    entry_index: int
    entry_time: UtcTimestamp
    entry_mid: Decimal
    horizon_days: int
    future_time: UtcTimestamp | None
    future_mid: Decimal | None
    return_value: Decimal | None
    censored: bool


def compute_forward_return(
    d_candles: Sequence[Candle], entry_index: int, horizon_days: int
) -> ForwardReturn:
    """FX-46 section 4/5: `return_value = future_mid_open /
    entry_mid_open - 1`, where `entry` is `d_candles[entry_index]` and
    `future` is `d_candles[entry_index + horizon_days]` -- i.e.
    `horizon_days` TRADING days (D-bar positions) forward from entry,
    not calendar days. `d_candles` must already be sorted ascending by
    `start_time` and index-aligned with whatever produced `entry_index`
    (see `find_entry_index`). Return orientation is whatever `d_
    candles`' own pair is: positive means the BASE currency of that
    pair appreciated versus the QUOTE currency (a rising mid price, by
    construction of how a currency pair is quoted) -- this function
    never flips or reinterprets orientation itself, it only ever
    computes a plain ratio on the price series it is given.
    """
    entry = d_candles[entry_index]
    entry_mid = mid_open(entry)
    future_index = entry_index + horizon_days
    if future_index >= len(d_candles):
        return ForwardReturn(
            entry_index=entry_index,
            entry_time=entry.start_time,
            entry_mid=entry_mid,
            horizon_days=horizon_days,
            future_time=None,
            future_mid=None,
            return_value=None,
            censored=True,
        )
    future = d_candles[future_index]
    future_mid = mid_open(future)
    return ForwardReturn(
        entry_index=entry_index,
        entry_time=entry.start_time,
        entry_mid=entry_mid,
        horizon_days=horizon_days,
        future_time=future.start_time,
        future_mid=future_mid,
        return_value=(future_mid / entry_mid) - 1,
        censored=False,
    )


def assign_era(as_of: UtcTimestamp) -> str | None:
    """FX-46 section 12: which of the fixed, pre-registered calendar
    eras (`ERAS`) `as_of` falls in -- `None` if `as_of` predates every
    defined era (before 2005-01-01). Boundary dates are inclusive at
    both ends of each era, exactly as `ERAS` states them."""
    d = as_of.value.date()
    for label, start, end in ERAS:
        if d < start:
            continue
        if end is not None and d > end:
            continue
        return label
    return None


@dataclass(frozen=True, slots=True)
class DescriptiveStats:
    """FX-46 section 9's own required per-cell statistics. Every field
    but `count` is `None` when `values` was empty (never a fabricated
    zero); `stdev` is specifically `None` with fewer than 2 values
    (sample standard deviation is undefined with n=1), matching this
    project's own established convention (`domain.backtest_metrics`'s
    `_sharpe`/`_sortino`)."""

    count: int
    mean: Decimal | None
    median: Decimal | None
    stdev: Decimal | None
    p25: Decimal | None
    p75: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None
    positive_fraction: Decimal | None


def describe(values: Sequence[Decimal]) -> DescriptiveStats:
    """FX-46 section 9. Percentiles use `domain.block_bootstrap.
    interpolated_percentile` -- the same linear-interpolation
    convention `percentile_ci` itself uses for confidence intervals,
    reused rather than redefined a second, potentially-divergent way.
    """
    if not values:
        return DescriptiveStats(0, None, None, None, None, None, None, None, None)
    ordered = sorted(values)
    n = len(ordered)
    mean = sum(ordered, Decimal(0)) / n
    median = interpolated_percentile(ordered, Decimal("0.5"))
    p25 = interpolated_percentile(ordered, Decimal("0.25"))
    p75 = interpolated_percentile(ordered, Decimal("0.75"))
    if n >= 2:
        variance = sum(((v - mean) ** 2 for v in ordered), Decimal(0)) / (n - 1)
        stdev = variance.sqrt()
    else:
        stdev = None
    positive_fraction = Decimal(sum(1 for v in ordered if v > 0)) / n
    return DescriptiveStats(
        count=n,
        mean=mean,
        median=median,
        stdev=stdev,
        p25=p25,
        p75=p75,
        minimum=ordered[0],
        maximum=ordered[-1],
        positive_fraction=positive_fraction,
    )

"""FX-46: the first real research experiment run against the hardened
policy-rate differential feature (FX-45/FX-45H/FX-45H.1). This is a
RESEARCH EXPERIMENT, not a trading strategy -- no thresholds, scoring,
signal, execution logic, or tradability claim anywhere in this script
or its outputs.

Two pre-registered experiments, run separately for EUR/USD, GBP/USD,
USD/CAD and separately for ANNOUNCED/EFFECTIVE semantics (never
pooled, never one falling back to the other):

  Experiment A ("LEVEL"): does the SIGN of the policy-rate differential
    (base rate > quote rate, or the reverse) associate with subsequent
    base-currency return? One observation per ISO calendar week (the
    first available D-bar open that week) -- a pre-registered
    anti-pseudoreplication measure against treating an unchanged daily
    rate state as independent evidence day after day.

  Experiment B ("CHANGE"): does a differential INCREASE vs. DECREASE
    (never "widening"/"narrowing" -- ambiguous at zero, forbidden by
    this story's own section 1) associate with subsequent base-currency
    return? Evaluated at EVERY canonical D-bar open; a change is only
    ever inferred between two CONSECUTIVE research-usable daily
    observations -- a blocked/unavailable day in between yields
    TRANSITION_UNKNOWN_DUE_TO_GAP, never a guessed transition.

LOCKED PROTOCOL (decided before this script was ever run against real
data -- see docs/DECISIONS.md's FX-46 entry for the full record):

  Instruments: EUR/USD, GBP/USD, USD/CAD only. No JPY, no XAU.
  Forward horizons: exactly 1, 5, 20 trading days. No others, ever.
  Return: mid_open-to-mid_open, entry = next D-bar open STRICTLY after
    feature evaluation (never the feature bar's own close) -- a
    RESEARCH return, not executable P&L (no spread, no slippage, no
    financing).
  Eras (time-stability check): 2005-01-01..2011-12-31,
    2012-01-01..2018-12-31, 2019-01-01..cutoff. Fixed, never moved
    after seeing performance.
  Primary contrasts: mean(POSITIVE) - mean(NEGATIVE) [LEVEL],
    mean(INCREASED) - mean(DECREASED) [CHANGE], per pair, per
    semantics, per horizon. Pair-level results are PRIMARY; any pooled
    number is secondary, equal-pair-weighted, and separately labeled.
  Uncertainty: deterministic calendar-year cluster bootstrap
    (`domain.block_bootstrap.calendar_year_cluster_bootstrap_
    differences`), NUM_RESAMPLES=10_000 (this project's own FX-39
    convention, reused unchanged), seed=46, 95% percentile CI.
  Sparse-era threshold: fewer than 10 usable observations in an era
    cell is reported in full (count + mean) and labeled "sparse" --
    never suppressed, never used to exclude the era.

  FORBIDDEN, unconditionally, regardless of outcome: threshold/
  parameter optimization, best-pair/horizon/era selection, discarding
  a weakening instrument, adding horizons post-hoc, technical/regime
  filters, carry or rate-expectations framing, transaction-cost
  modeling. If a contrast doesn't show the pre-registered direction,
  that is the answer.

Every policy-rate value used here comes from EXACTLY ONE place:
`ComputePolicyRateDifferential`, called through `research.policy_rate_
differential_research.evaluate_feature` -- this script never
reconstructs rate state from raw macro rows itself. `_CachingMacro
ObservationRepository` below only memoizes `list_all_for_series`
(there are only 4 distinct currencies in play; that history cannot
change mid-run since this script never writes) -- it changes nothing
about what data reaches the use case, only how many times the same
complete history is fetched over the wire.

Run:
    uv run python scripts/run_fx46_policy_rate_differential_research.py

Requires:
    - `docker compose up -d db`, `uv run alembic upgrade head`
    - `uv run python scripts/aggregate_d_candles.py` (materializes the
      D candles this script reads -- no native D data is ever ingested)
    - the real policy-rate backfill/verification/remediation already
      run (see tests/integration/test_compute_policy_rate_differential.py)

Writes:
    - research_results/fx46/policy_rate_differential_research.json
    - research_results/fx46/policy_rate_differential_samples.csv
    - research_results/fx46/policy_rate_differential_summary.md

FX-46H correction (see docs/DECISIONS.md's FX-46H entry): FX-46's
original bootstrap fabricated a zero mean for a calendar-year cluster
contrast's arm whenever a bootstrap replication's drawn years left
that arm empty -- `domain.block_bootstrap.calendar_year_cluster_
bootstrap_differences` now redraws such a replication instead, and
reports a whole contrast NOT_ESTIMABLE (see `_contrast`'s own `note`)
rather than fabricate anything when an arm has fewer than 2 distinct
year clusters to begin with. FX-46H also corrected this script's own
provenance metadata: `git_commit`/`git_commit_dirty` now reflect
whether the working tree actually matched the recorded commit when
this ran, `candle_end_actual_by_instrument` records the real max
D-candle timestamp used per pair (distinct from `candle_end_bound`,
which remains only the query bound passed to `get_range`), and
`macro_data_fingerprint` records a deterministic hash of the exact
policy-rate vintage history actually read, so a rerun against the
same source commit can detect whether the underlying data changed.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.ports.macro_observation_repository import (
    MacroObservationRepository,
    VintageWriteOutcome,
)
from forex_agent.application.use_cases.compute_policy_rate_differential import (
    ComputePolicyRateDifferential,
)
from forex_agent.domain.block_bootstrap import (
    calendar_year_cluster_bootstrap_differences,
    percentile_ci,
)
from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_source import CandleSource
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.policy_rate_differential import RateSemantics
from forex_agent.domain.release_timing_rule import ReleaseTimingConfidence
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.candle_repository import SqlAlchemyCandleRepository
from forex_agent.infrastructure.db.macro_observation_repository import (
    SqlAlchemyMacroObservationRepository,
)
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.research.policy_rate_differential_research import (
    ERAS,
    FORWARD_HORIZONS_TRADING_DAYS,
    Disposition,
    FeatureEvaluation,
    TransitionStatus,
    assign_era,
    build_change_events,
    classify_level,
    compute_forward_return,
    describe,
    evaluate_feature,
    find_entry_index,
    select_weekly_bars,
)

assert FORWARD_HORIZONS_TRADING_DAYS == (1, 5, 20), (
    "this script's CSV/JSON schema hardcodes 1d/5d/20d field names -- if the "
    "pre-registered horizons in the pure module ever changed, this script "
    "must be revisited deliberately, not silently mismatch them"
)

PAIRS: tuple[Instrument, ...] = (
    Instrument(base_currency="EUR", quote_currency="USD"),
    Instrument(base_currency="GBP", quote_currency="USD"),
    Instrument(base_currency="USD", quote_currency="CAD"),
)
SEMANTICS: tuple[RateSemantics, ...] = (RateSemantics.ANNOUNCED, RateSemantics.EFFECTIVE)
LEVEL_GROUPS: tuple[str, ...] = ("POSITIVE", "NEGATIVE", "ZERO")
CHANGE_GROUPS: tuple[str, ...] = ("INCREASED", "DECREASED", "UNCHANGED")

#: Wide enough to comfortably bound every pair's real D-candle history
#: (materialized 2005-01-02 onward by scripts/aggregate_d_candles.py)
#: through the present; get_range's own [start, end) bounds do the
#: real clipping per pair.
_CANDLE_START = UtcTimestamp(datetime(2000, 1, 1, tzinfo=UTC))
_CANDLE_END = UtcTimestamp(datetime.now(UTC))

#: This project's own FX-39 bootstrap convention, reused unchanged
#: (FX-46 section 10's own instruction: reuse an existing project-wide
#: standard rather than invent a competing one). Seed is this story's
#: own number, matching the established seed=story-number convention.
NUM_RESAMPLES = 10_000
SEED = 46

#: FX-46 section 12: pre-registered BEFORE this script was ever run
#: against real data. An era cell below this many usable observations
#: is still reported in full (count + mean) -- only ANNOTATED sparse,
#: never suppressed or excluded.
SPARSE_ERA_THRESHOLD = 10

OUT_DIR = Path("research_results/fx46")


# --- Read-through cache over the real macro-observation repository ---------


class _CachingMacroObservationRepository:
    """Wraps a real `MacroObservationRepository`, memoizing ONLY
    `list_all_for_series` -- a pure orchestration-performance concern,
    not a change to any port or production adapter. Every other method
    delegates unchanged.

    Safe ONLY because this script never writes: no `add_vintage`/
    `replace_provisional_release_timing`/`correct_verified_release_
    timing` call ever happens in this process, so a series' stored
    history cannot change out from under the cache mid-run. Exists to
    avoid O(evaluations) redundant round-trips to the SAME 4
    currencies' (EUR/GBP/CAD/USD) complete history --
    `ComputePolicyRateDifferential`'s own FX-45H.1 contract already
    requires it be handed that COMPLETE, unfiltered history on every
    single call (never a narrower, pre-filtered view); this wrapper
    caches exactly what that contract already asks for, verbatim, per
    series_key -- it does not change what the use case sees.
    """

    def __init__(self, delegate: MacroObservationRepository) -> None:
        self._delegate = delegate
        self._cache: dict[str, tuple[MacroObservationVintage, ...]] = {}

    async def list_all_for_series(self, series_key: str) -> tuple[MacroObservationVintage, ...]:
        if series_key not in self._cache:
            self._cache[series_key] = await self._delegate.list_all_for_series(series_key)
        return self._cache[series_key]

    async def add_vintage(self, vintage: MacroObservationVintage) -> VintageWriteOutcome:
        return await self._delegate.add_vintage(vintage)

    async def replace_provisional_release_timing(
        self,
        series_key: str,
        observation_period: UtcTimestamp,
        revision_sequence: int,
        released_at: UtcTimestamp,
        effective_at: UtcTimestamp | None,
        confidence: ReleaseTimingConfidence,
    ) -> None:
        await self._delegate.replace_provisional_release_timing(
            series_key,
            observation_period,
            revision_sequence,
            released_at,
            effective_at,
            confidence,
        )

    async def correct_verified_release_timing(
        self,
        series_key: str,
        observation_period: UtcTimestamp,
        revision_sequence: int,
        expected_current_released_at: UtcTimestamp,
        expected_current_effective_at: UtcTimestamp | None,
        corrected_released_at: UtcTimestamp,
        corrected_effective_at: UtcTimestamp | None,
    ) -> None:
        await self._delegate.correct_verified_release_timing(
            series_key,
            observation_period,
            revision_sequence,
            expected_current_released_at,
            expected_current_effective_at,
            corrected_released_at,
            corrected_effective_at,
        )

    async def latest_available_as_of(
        self, series_key: str, as_of: UtcTimestamp
    ) -> MacroObservationVintage | None:
        return await self._delegate.latest_available_as_of(series_key, as_of)

    async def observation_as_known_at(
        self, series_key: str, observation_period: UtcTimestamp, as_of: UtcTimestamp
    ) -> MacroObservationVintage | None:
        return await self._delegate.observation_as_known_at(series_key, observation_period, as_of)

    def macro_data_fingerprint(self) -> dict[str, Any]:
        """FX-46H: a deterministic fingerprint of every series' vintage
        history actually fetched during this run (only ever populated
        by `list_all_for_series` above, the SAME complete history
        `ComputePolicyRateDifferential`'s own contract requires) --
        callers rerunning against the same source commit later can
        compare this to detect whether the underlying macro data
        (a later backfill, remediation, or correction) changed, since
        neither the commit SHA nor the generation timestamp alone can
        tell them that.
        """
        per_series: dict[str, str] = {}
        max_released_at: UtcTimestamp | None = None
        total_vintages = 0
        for series_key in sorted(self._cache):
            vintages = self._cache[series_key]
            total_vintages += len(vintages)
            rows = sorted(
                (
                    v.observation_period.value.isoformat(),
                    str(v.value),
                    v.released_at.value.isoformat(),
                    v.revision_sequence,
                    v.source,
                    v.effective_at.value.isoformat() if v.effective_at is not None else None,
                    v.released_at_is_verified,
                    v.released_at_is_conservative_bound,
                )
                for v in vintages
            )
            per_series[series_key] = hashlib.sha256(
                json.dumps(rows, sort_keys=True).encode()
            ).hexdigest()
            for v in vintages:
                if max_released_at is None or v.released_at.value > max_released_at.value:
                    max_released_at = v.released_at
        combined = hashlib.sha256(json.dumps(per_series, sort_keys=True).encode()).hexdigest()
        return {
            "combined_fingerprint": combined,
            "per_series_fingerprint": per_series,
            "max_released_at": max_released_at.value.isoformat() if max_released_at else None,
            "total_vintages_read": total_vintages,
        }


# --- Sample records (one row per attempted observation, usable or not) -----


@dataclass(frozen=True, slots=True)
class SampleRecord:
    """One attempted (pair, semantics, experiment, as_of) observation --
    ALWAYS recorded, whether it ended up USABLE or excluded, and if
    excluded, WHY (FX-46 section 15: never just a bare exclusion
    count). Mirrors exactly the CSV schema FX-46 section 17 requires.
    """

    instrument: str
    semantics: str
    experiment: str  # "LEVEL" | "CHANGE"
    as_of: UtcTimestamp
    differential: Decimal | None
    previous_differential: Decimal | None
    delta: Decimal | None
    group: str | None
    entry_timestamp: UtcTimestamp | None
    entry_mid: Decimal | None
    future_timestamp_1d: UtcTimestamp | None
    future_timestamp_5d: UtcTimestamp | None
    future_timestamp_20d: UtcTimestamp | None
    return_1d: Decimal | None
    return_5d: Decimal | None
    return_20d: Decimal | None
    disposition: str
    exclusion_reason: str | None


@dataclass(frozen=True, slots=True)
class _ReturnFields:
    entry_timestamp: UtcTimestamp | None
    entry_mid: Decimal | None
    future_timestamp_1d: UtcTimestamp | None
    future_timestamp_5d: UtcTimestamp | None
    future_timestamp_20d: UtcTimestamp | None
    return_1d: Decimal | None
    return_5d: Decimal | None
    return_20d: Decimal | None
    disposition: str
    exclusion_reason: str | None


def _blocked_return_fields(disposition: str, reason: str | None) -> _ReturnFields:
    return _ReturnFields(None, None, None, None, None, None, None, None, disposition, reason)


def _compute_return_fields(d_candles: list[Candle], as_of: UtcTimestamp) -> _ReturnFields:
    """FX-46 section 4/5: entry = next D-bar open STRICTLY after
    `as_of`; 1d/5d/20d forward returns from that entry. `NO_ENTRY_
    AVAILABLE` (distinct from CENSORED, which is a per-horizon
    "insufficient future bars AFTER a real entry" outcome) only ever
    happens right at the tail of the whole dataset, where no D-bar
    exists strictly after `as_of` at all.
    """
    entry_index = find_entry_index(d_candles, as_of)
    if entry_index is None:
        return _blocked_return_fields(
            "NO_ENTRY_AVAILABLE", "no D-bar available strictly after as_of"
        )
    r1 = compute_forward_return(d_candles, entry_index, 1)
    r5 = compute_forward_return(d_candles, entry_index, 5)
    r20 = compute_forward_return(d_candles, entry_index, 20)
    return _ReturnFields(
        entry_timestamp=r1.entry_time,
        entry_mid=r1.entry_mid,
        future_timestamp_1d=r1.future_time,
        future_timestamp_5d=r5.future_time,
        future_timestamp_20d=r20.future_time,
        return_1d=r1.return_value,
        return_5d=r5.return_value,
        return_20d=r20.return_value,
        disposition="USABLE",
        exclusion_reason=None,
    )


def _level_records(
    instrument: Instrument,
    semantics: RateSemantics,
    d_candles: list[Candle],
    weekly_candles: list[Candle],
    eval_by_as_of: dict[datetime, FeatureEvaluation],
) -> list[SampleRecord]:
    """FX-46 section 6 (Experiment A): one record per ISO-week sample."""
    records: list[SampleRecord] = []
    for candle in weekly_candles:
        ev = eval_by_as_of[candle.start_time.value]
        if ev.disposition is not Disposition.USABLE:
            fields = _blocked_return_fields(ev.disposition.value, ev.reason)
            differential: Decimal | None = None
            group: str | None = None
        else:
            assert ev.differential is not None
            differential = ev.differential
            group = classify_level(differential).value
            fields = _compute_return_fields(d_candles, ev.as_of)
        records.append(
            SampleRecord(
                instrument=instrument.symbol,
                semantics=semantics.value,
                experiment="LEVEL",
                as_of=ev.as_of,
                differential=differential,
                previous_differential=None,
                delta=None,
                group=group,
                entry_timestamp=fields.entry_timestamp,
                entry_mid=fields.entry_mid,
                future_timestamp_1d=fields.future_timestamp_1d,
                future_timestamp_5d=fields.future_timestamp_5d,
                future_timestamp_20d=fields.future_timestamp_20d,
                return_1d=fields.return_1d,
                return_5d=fields.return_5d,
                return_20d=fields.return_20d,
                disposition=fields.disposition,
                exclusion_reason=fields.exclusion_reason,
            )
        )
    return records


def _change_record(
    instrument: Instrument,
    semantics: RateSemantics,
    as_of: UtcTimestamp,
    differential: Decimal | None,
    previous_differential: Decimal | None,
    delta: Decimal | None,
    group: str | None,
    fields: _ReturnFields,
) -> SampleRecord:
    return SampleRecord(
        instrument=instrument.symbol,
        semantics=semantics.value,
        experiment="CHANGE",
        as_of=as_of,
        differential=differential,
        previous_differential=previous_differential,
        delta=delta,
        group=group,
        entry_timestamp=fields.entry_timestamp,
        entry_mid=fields.entry_mid,
        future_timestamp_1d=fields.future_timestamp_1d,
        future_timestamp_5d=fields.future_timestamp_5d,
        future_timestamp_20d=fields.future_timestamp_20d,
        return_1d=fields.return_1d,
        return_5d=fields.return_5d,
        return_20d=fields.return_20d,
        disposition=fields.disposition,
        exclusion_reason=fields.exclusion_reason,
    )


def _change_records(
    instrument: Instrument,
    semantics: RateSemantics,
    d_candles: list[Candle],
    daily_evals: list[FeatureEvaluation],
) -> list[SampleRecord]:
    """FX-46 section 7 (Experiment B): one record per canonical D-bar
    open, INCLUDING blocked/unavailable days (FX-46 section 15) -- not
    just the ADMISSIBLE change events `build_change_events` itself
    returns. A GAP/NO_PRIOR_DAY day's own differential is still known
    and recorded; only the transition INTO it is undetermined, so no
    return is attempted for it (there is no group to attribute it to).
    """
    events_by_as_of = {e.as_of.value: e for e in build_change_events(daily_evals)}
    records: list[SampleRecord] = []
    for ev in daily_evals:
        if ev.disposition is not Disposition.USABLE:
            fields = _blocked_return_fields(ev.disposition.value, ev.reason)
            records.append(
                _change_record(instrument, semantics, ev.as_of, None, None, None, None, fields)
            )
            continue
        event = events_by_as_of[ev.as_of.value]
        if event.status is TransitionStatus.ADMISSIBLE:
            assert event.group is not None and event.delta is not None
            fields = _compute_return_fields(d_candles, ev.as_of)
            previous_differential = event.differential - event.delta
            records.append(
                _change_record(
                    instrument,
                    semantics,
                    ev.as_of,
                    event.differential,
                    previous_differential,
                    event.delta,
                    event.group.value,
                    fields,
                )
            )
        else:
            reason = (
                "transition_unknown_due_to_gap"
                if event.status is TransitionStatus.GAP
                else "no_prior_day"
            )
            fields = _blocked_return_fields(event.status.value, reason)
            records.append(
                _change_record(
                    instrument, semantics, ev.as_of, event.differential, None, None, None, fields
                )
            )
    return records


async def _collect_pair_records(
    candle_repo: SqlAlchemyCandleRepository,
    use_case: ComputePolicyRateDifferential,
    instrument: Instrument,
) -> tuple[list[SampleRecord], UtcTimestamp | None]:
    d_candles = await candle_repo.get_range(
        instrument, Granularity.D, _CANDLE_START, _CANDLE_END, source=CandleSource.AGGREGATED
    )
    actual_end = d_candles[-1].start_time if d_candles else None
    records: list[SampleRecord] = []
    for semantics in SEMANTICS:
        daily_evals = [
            await evaluate_feature(use_case, instrument, candle.start_time, semantics)
            for candle in d_candles
        ]
        eval_by_as_of = {e.as_of.value: e for e in daily_evals}
        weekly_candles = select_weekly_bars(d_candles)
        records.extend(
            _level_records(instrument, semantics, d_candles, weekly_candles, eval_by_as_of)
        )
        records.extend(_change_records(instrument, semantics, d_candles, daily_evals))
    return records, actual_end


# --- Aggregation / statistics -----------------------------------------------


def _return_for_horizon(record: SampleRecord, horizon_days: int) -> Decimal | None:
    if horizon_days == 1:
        return record.return_1d
    if horizon_days == 5:
        return record.return_5d
    if horizon_days == 20:
        return record.return_20d
    raise ValueError(f"unsupported horizon_days: {horizon_days}")


def _usable_values(
    records: Sequence[SampleRecord], experiment: str, group: str, horizon_days: int
) -> list[Decimal]:
    values: list[Decimal] = []
    for r in records:
        if r.experiment == experiment and r.group == group and r.disposition == "USABLE":
            v = _return_for_horizon(r, horizon_days)
            if v is not None:
                values.append(v)
    return values


def _usable_values_by_year(
    records: Sequence[SampleRecord], experiment: str, group: str, horizon_days: int
) -> dict[int, list[Decimal]]:
    by_year: dict[int, list[Decimal]] = {}
    for r in records:
        if r.experiment == experiment and r.group == group and r.disposition == "USABLE":
            v = _return_for_horizon(r, horizon_days)
            if v is not None:
                by_year.setdefault(r.as_of.value.year, []).append(v)
    return by_year


@dataclass(frozen=True, slots=True)
class ContrastResult:
    horizon_days: int
    group_a: str
    group_b: str
    n_a: int
    n_b: int
    n_years_a: int
    n_years_b: int
    observed_diff: Decimal | None
    lower_95: Decimal | None
    upper_95: Decimal | None
    fraction_le_zero: Decimal | None
    note: str | None


def _contrast(
    records: Sequence[SampleRecord], experiment: str, group_a: str, group_b: str, horizon_days: int
) -> ContrastResult:
    """FX-46 section 9/10: primary contrast `mean(group_a) -
    mean(group_b)` plus a deterministic calendar-year cluster bootstrap
    95% CI. Deliberately returns a "not computable" result (no crash,
    no fabricated zero) rather than run a bootstrap when either group
    has zero usable observations at this horizon -- both are needed
    for a real "A vs B" comparison to mean anything.

    FX-46H: the bootstrap itself can also come back `estimable=False`
    (see `domain.block_bootstrap.calendar_year_cluster_bootstrap_
    differences`) when a group has fewer than 2 distinct calendar-year
    clusters, or when every redraw attempt for some replication still
    left an arm empty -- reported here via `note`, same as the
    "not computable" case, with the observed point estimate and each
    arm's cluster count still populated so the reader can see WHY.
    """
    values_a = _usable_values(records, experiment, group_a, horizon_days)
    values_b = _usable_values(records, experiment, group_b, horizon_days)
    if not values_a or not values_b:
        return ContrastResult(
            horizon_days=horizon_days,
            group_a=group_a,
            group_b=group_b,
            n_a=len(values_a),
            n_b=len(values_b),
            n_years_a=0,
            n_years_b=0,
            observed_diff=None,
            lower_95=None,
            upper_95=None,
            fraction_le_zero=None,
            note="not computable: one or both groups have zero usable observations at this horizon",
        )
    by_year_a = _usable_values_by_year(records, experiment, group_a, horizon_days)
    by_year_b = _usable_values_by_year(records, experiment, group_b, horizon_days)
    observed_diff = (sum(values_a, Decimal(0)) / len(values_a)) - (
        sum(values_b, Decimal(0)) / len(values_b)
    )
    outcome = calendar_year_cluster_bootstrap_differences(
        by_year_a, by_year_b, num_resamples=NUM_RESAMPLES, seed=SEED
    )
    if not outcome.estimable:
        return ContrastResult(
            horizon_days=horizon_days,
            group_a=group_a,
            group_b=group_b,
            n_a=len(values_a),
            n_b=len(values_b),
            n_years_a=outcome.group_a_cluster_count,
            n_years_b=outcome.group_b_cluster_count,
            observed_diff=observed_diff,
            lower_95=None,
            upper_95=None,
            fraction_le_zero=None,
            note=f"NOT_ESTIMABLE: {outcome.reason}",
        )
    diffs = outcome.differences
    assert diffs is not None
    lower_95, upper_95 = percentile_ci(diffs, Decimal("0.95"))
    fraction_le_zero = Decimal(sum(1 for d in diffs if d <= 0)) / Decimal(len(diffs))
    return ContrastResult(
        horizon_days=horizon_days,
        group_a=group_a,
        group_b=group_b,
        n_a=len(values_a),
        n_b=len(values_b),
        n_years_a=outcome.group_a_cluster_count,
        n_years_b=outcome.group_b_cluster_count,
        observed_diff=observed_diff,
        lower_95=lower_95,
        upper_95=upper_95,
        fraction_le_zero=fraction_le_zero,
        note=None,
    )


def _era_breakdown(
    records: Sequence[SampleRecord], group: str, horizon_days: int
) -> dict[str, Any]:
    era_values: dict[str, list[Decimal]] = {label: [] for label, _, _ in ERAS}
    era_values["pre-2005"] = []
    for r in records:
        if r.group != group or r.disposition != "USABLE":
            continue
        v = _return_for_horizon(r, horizon_days)
        if v is None:
            continue
        era = assign_era(r.as_of) or "pre-2005"
        era_values.setdefault(era, []).append(v)
    out: dict[str, Any] = {}
    for era, values in era_values.items():
        n = len(values)
        mean = (sum(values, Decimal(0)) / n) if n else None
        out[era] = {
            "count": n,
            "mean": str(mean) if mean is not None else None,
            "sparse": n < SPARSE_ERA_THRESHOLD,
        }
    return out


def _normalize_reason_category(disposition: str, reason: str | None) -> str | None:
    """Collapses a raw per-row `exclusion_reason` into a small, STABLE
    category for the disposition-count summary (JSON/markdown) only --
    the CSV's own `exclusion_reason` column keeps the full, unmodified
    per-row text regardless of this function. `DifferentialUnavailable`
    (`ComputePolicyRateDifferential`) legitimately embeds the specific
    currency and `as_of` instant in its `reason` text -- correct and
    useful at row granularity, but it would make every UNAVAILABLE row
    its own singleton "reason" in a summary that groups by the raw
    string verbatim. BLOCKED's two reasons (`missing_baseline`/
    `provisional_timing`) and CHANGE's own two (`transition_unknown_
    due_to_gap`/`no_prior_day`), and `NO_ENTRY_AVAILABLE`'s single fixed
    reason, are already stable fixed strings and pass through unchanged.
    """
    if reason is None:
        return None
    if disposition != "UNAVAILABLE":
        return reason
    if "is not a currency with a canonical policy rate" in reason:
        return "currency_not_canonical"
    if "effective_at has not been populated" in reason:
        return "no_effective_state_established"
    return "no_announced_state_exists"


def _disposition_counts(records: Sequence[SampleRecord]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    reasons: dict[str, dict[str, int]] = {}
    for r in records:
        counts[r.disposition] = counts.get(r.disposition, 0) + 1
        category = _normalize_reason_category(r.disposition, r.exclusion_reason)
        if category:
            bucket = reasons.setdefault(r.disposition, {})
            bucket[category] = bucket.get(category, 0) + 1
    return {"by_disposition": counts, "by_disposition_and_reason": reasons, "total": len(records)}


def _serialize_stats(stats: Any) -> dict[str, Any]:
    return {
        "count": stats.count,
        "mean": str(stats.mean) if stats.mean is not None else None,
        "median": str(stats.median) if stats.median is not None else None,
        "stdev": str(stats.stdev) if stats.stdev is not None else None,
        "p25": str(stats.p25) if stats.p25 is not None else None,
        "p75": str(stats.p75) if stats.p75 is not None else None,
        "min": str(stats.minimum) if stats.minimum is not None else None,
        "max": str(stats.maximum) if stats.maximum is not None else None,
        "positive_fraction": (
            str(stats.positive_fraction) if stats.positive_fraction is not None else None
        ),
    }


def _serialize_contrast(c: ContrastResult) -> dict[str, Any]:
    return {
        "group_a": c.group_a,
        "group_b": c.group_b,
        "n_a": c.n_a,
        "n_b": c.n_b,
        "n_years_a": c.n_years_a,
        "n_years_b": c.n_years_b,
        "observed_diff": str(c.observed_diff) if c.observed_diff is not None else None,
        "lower_95": str(c.lower_95) if c.lower_95 is not None else None,
        "upper_95": str(c.upper_95) if c.upper_95 is not None else None,
        "fraction_le_zero": str(c.fraction_le_zero) if c.fraction_le_zero is not None else None,
        "note": c.note,
    }


def _cell_report(
    all_records: list[SampleRecord],
    instrument: Instrument,
    semantics: RateSemantics,
    experiment: str,
) -> dict[str, Any]:
    records = [
        r
        for r in all_records
        if r.instrument == instrument.symbol
        and r.semantics == semantics.value
        and r.experiment == experiment
    ]
    groups = LEVEL_GROUPS if experiment == "LEVEL" else CHANGE_GROUPS
    by_group: dict[str, Any] = {}
    for group in groups:
        by_horizon: dict[str, Any] = {}
        for h in FORWARD_HORIZONS_TRADING_DAYS:
            values = _usable_values(records, experiment, group, h)
            censored = sum(
                1
                for r in records
                if r.group == group
                and r.disposition == "USABLE"
                and _return_for_horizon(r, h) is None
            )
            by_horizon[str(h)] = {
                "stats": _serialize_stats(describe(values)),
                "censored_count": censored,
                "by_era": _era_breakdown(records, group, h),
            }
        by_group[group] = by_horizon

    primary_a, primary_b = (
        ("POSITIVE", "NEGATIVE") if experiment == "LEVEL" else ("INCREASED", "DECREASED")
    )
    contrasts = {
        str(h): _serialize_contrast(_contrast(records, experiment, primary_a, primary_b, h))
        for h in FORWARD_HORIZONS_TRADING_DAYS
    }

    return {
        "disposition_counts": _disposition_counts(records),
        "groups": by_group,
        "primary_contrast": {"group_a": primary_a, "group_b": primary_b, "by_horizon": contrasts},
    }


def _secondary_pooled(all_records: list[SampleRecord]) -> dict[str, Any]:
    """FX-46 section 11: a SECONDARY, clearly-labeled, equal-pair-
    weighted summary -- the simple unweighted mean of the 3 pairs' own
    observed contrast point estimates (each pair counted once,
    regardless of its own sample size). Deliberately does NOT compute
    a pooled confidence interval (that would require inventing a new,
    unreviewed statistical procedure under this story's own time
    pressure) -- the per-pair results above, each with its own proper
    cluster-bootstrap CI, remain the primary, authoritative results;
    this section is descriptive only.
    """
    out: dict[str, Any] = {}
    for semantics in SEMANTICS:
        experiment_out: dict[str, Any] = {}
        for experiment in ("LEVEL", "CHANGE"):
            group_a, group_b = (
                ("POSITIVE", "NEGATIVE") if experiment == "LEVEL" else ("INCREASED", "DECREASED")
            )
            horizon_out: dict[str, Any] = {}
            for h in FORWARD_HORIZONS_TRADING_DAYS:
                pair_diffs: list[Decimal] = []
                for instrument in PAIRS:
                    pair_records = [
                        r
                        for r in all_records
                        if r.instrument == instrument.symbol and r.semantics == semantics.value
                    ]
                    contrast = _contrast(pair_records, experiment, group_a, group_b, h)
                    if contrast.observed_diff is not None:
                        pair_diffs.append(contrast.observed_diff)
                equal_weighted_mean = (
                    sum(pair_diffs, Decimal(0)) / len(pair_diffs) if pair_diffs else None
                )
                horizon_out[str(h)] = {
                    "pairs_contributing": len(pair_diffs),
                    "pairs_total": len(PAIRS),
                    "equal_weighted_mean_diff": (
                        str(equal_weighted_mean) if equal_weighted_mean is not None else None
                    ),
                }
            experiment_out[experiment] = horizon_out
        out[semantics.value] = experiment_out
    return out


# --- Output writers ----------------------------------------------------------

_CSV_FIELDS = [
    "instrument",
    "semantics",
    "experiment",
    "as_of",
    "differential",
    "previous_differential",
    "delta",
    "group",
    "entry_timestamp",
    "entry_mid",
    "future_timestamp_1d",
    "future_timestamp_5d",
    "future_timestamp_20d",
    "return_1d",
    "return_5d",
    "return_20d",
    "disposition",
    "exclusion_reason",
]


def _dec(v: Decimal | None) -> str:
    return "" if v is None else str(v)


def _ts(v: UtcTimestamp | None) -> str:
    return "" if v is None else v.value.isoformat()


def _write_csv(records: list[SampleRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".csv.tmp")
    with tmp_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_CSV_FIELDS)
        for r in records:
            writer.writerow(
                [
                    r.instrument,
                    r.semantics,
                    r.experiment,
                    r.as_of.value.isoformat(),
                    _dec(r.differential),
                    _dec(r.previous_differential),
                    _dec(r.delta),
                    r.group or "",
                    _ts(r.entry_timestamp),
                    _dec(r.entry_mid),
                    _ts(r.future_timestamp_1d),
                    _ts(r.future_timestamp_5d),
                    _ts(r.future_timestamp_20d),
                    _dec(r.return_1d),
                    _dec(r.return_5d),
                    _dec(r.return_20d),
                    r.disposition,
                    r.exclusion_reason or "",
                ]
            )
    tmp_path.replace(path)


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n")
    tmp_path.replace(path)


def _fmt(v: str | None) -> str:
    return v if v is not None else "n/a"


def _render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# FX-46: Historical Policy-Rate Differential Research")
    lines.append("")
    lines.append(f"Generated: {report['generated_at']}  ")
    dirty = report.get("git_commit_dirty")
    if dirty is True:
        dirty_suffix = " (DIRTY -- see git_dirty_paths)"
    elif dirty is False:
        dirty_suffix = " (clean)"
    else:
        dirty_suffix = " (unknown)"
    lines.append(f"Git commit: {report['git_commit']}{dirty_suffix}  ")
    lines.append(f"Config hash: {report['config_hash']}  ")
    fp = report.get("macro_data_fingerprint") or {}
    lines.append(
        f"Macro data fingerprint: {fp.get('combined_fingerprint', 'n/a')} "
        f"({fp.get('total_vintages_read', 'n/a')} vintages, "
        f"max released_at {fp.get('max_released_at', 'n/a')})"
    )
    lines.append("")
    lines.append(
        "Research experiment only -- no thresholds, scoring, signal, execution logic, or "
        "tradability claim. Returns are mid_open-to-mid_open RESEARCH returns, not "
        "executable P&L. A positive result below is evidence of statistical association "
        "at the tested horizon, era, and pair -- never proof of a durable, tradeable edge, "
        "and CI crossing zero does not prove the feature useless (see Limitations)."
    )
    lines.append("")

    for instrument in PAIRS:
        lines.append(f"## {instrument.symbol}")
        for semantics in SEMANTICS:
            for experiment in ("LEVEL", "CHANGE"):
                cell = report["pairs"][instrument.symbol][semantics.value][experiment]
                lines.append("")
                lines.append(f"### {semantics.value} / {experiment}")
                dc = cell["disposition_counts"]
                lines.append("")
                lines.append(f"Total attempted observations: {dc['total']}")
                lines.append("")
                lines.append("| Disposition | Count |")
                lines.append("|---|---|")
                for disposition, count in sorted(dc["by_disposition"].items()):
                    lines.append(f"| {disposition} | {count} |")
                if dc["by_disposition_and_reason"]:
                    lines.append("")
                    lines.append("| Disposition | Reason | Count |")
                    lines.append("|---|---|---|")
                    for disposition, reasons in sorted(dc["by_disposition_and_reason"].items()):
                        for reason, count in sorted(reasons.items()):
                            lines.append(f"| {disposition} | {reason} | {count} |")

                groups = LEVEL_GROUPS if experiment == "LEVEL" else CHANGE_GROUPS
                lines.append("")
                lines.append(
                    "| Group | Horizon | n | mean | median | stdev | positive_frac | censored |"
                )
                lines.append("|---|---|---|---|---|---|---|---|")
                for group in groups:
                    for h in FORWARD_HORIZONS_TRADING_DAYS:
                        s = cell["groups"][group][str(h)]["stats"]
                        censored = cell["groups"][group][str(h)]["censored_count"]
                        lines.append(
                            f"| {group} | {h}d | {s['count']} | {_fmt(s['mean'])} | "
                            f"{_fmt(s['median'])} | {_fmt(s['stdev'])} | "
                            f"{_fmt(s['positive_fraction'])} | {censored} |"
                        )

                pc = cell["primary_contrast"]
                lines.append("")
                lines.append(
                    f"**Primary contrast: mean({pc['group_a']}) - mean({pc['group_b']})** "
                    "(deterministic calendar-year cluster bootstrap, 95% CI, "
                    f"seed={report['config']['seed']}, "
                    f"resamples={report['config']['num_resamples']})"
                )
                lines.append("")
                lines.append(
                    "| Horizon | n_a | n_b | years_a | years_b | diff | 95% CI | frac<=0 | note |"
                )
                lines.append("|---|---|---|---|---|---|---|---|---|")
                for h in FORWARD_HORIZONS_TRADING_DAYS:
                    c = pc["by_horizon"][str(h)]
                    ci = (
                        f"[{c['lower_95']}, {c['upper_95']}]"
                        if c["lower_95"] is not None
                        else "n/a"
                    )
                    lines.append(
                        f"| {h}d | {c['n_a']} | {c['n_b']} | {c['n_years_a']} | "
                        f"{c['n_years_b']} | {_fmt(c['observed_diff'])} | "
                        f"{ci} | {_fmt(c['fraction_le_zero'])} | {c['note'] or ''} |"
                    )

                lines.append("")
                lines.append('Time stability by era (mean return, count; "sparse" if n<10):')
                lines.append("")
                era_labels = [label for label, _, _ in ERAS]
                header = "| Group | Horizon | " + " | ".join(era_labels) + " |"
                lines.append(header)
                lines.append("|---|---|" + "---|" * len(era_labels))
                for group in groups:
                    for h in FORWARD_HORIZONS_TRADING_DAYS:
                        by_era = cell["groups"][group][str(h)]["by_era"]
                        cells = []
                        for label in era_labels:
                            e = by_era.get(label, {"count": 0, "mean": None, "sparse": True})
                            marker = " (sparse)" if e["sparse"] else ""
                            cells.append(f"{_fmt(e['mean'])} n={e['count']}{marker}")
                        lines.append(f"| {group} | {h}d | " + " | ".join(cells) + " |")
        lines.append("")

    lines.append("## Secondary: equal-pair-weighted pooled summary (NOT primary)")
    lines.append("")
    lines.append(
        "Simple unweighted mean of the 3 pairs' own observed contrast point estimates -- "
        "each pair counted once regardless of sample size. No pooled confidence interval "
        "is computed here; the per-pair results above, each with its own proper "
        "cluster-bootstrap CI, are the primary, authoritative results."
    )
    lines.append("")
    lines.append(
        "| Semantics | Experiment | Horizon | Pairs contributing | Equal-weighted mean diff |"
    )
    lines.append("|---|---|---|---|---|")
    for semantics in SEMANTICS:
        for experiment in ("LEVEL", "CHANGE"):
            for h in FORWARD_HORIZONS_TRADING_DAYS:
                s = report["secondary_pooled"][semantics.value][experiment][str(h)]
                lines.append(
                    f"| {semantics.value} | {experiment} | {h}d | "
                    f"{s['pairs_contributing']}/{s['pairs_total']} | "
                    f"{_fmt(s['equal_weighted_mean_diff'])} |"
                )

    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "- Statistical association is not economic magnitude, temporal stability, sample "
        "coverage, or tradability -- each is a separate question this report does not "
        "collapse into a single verdict. Tradability (spread, slippage, financing, "
        "execution) is explicitly out of scope.\n"
        "- A CI crossing zero means this data cannot distinguish the contrast from noise "
        "at this horizon/pair/semantics -- it does not mean the feature is proven "
        "useless.\n"
        "- A positive point estimate or a CI excluding zero is evidence of association in "
        "the tested sample -- not proof of alpha, profitability, or causation.\n"
        "- EFFECTIVE-semantics coverage is smaller than ANNOUNCED by construction (FX-45/"
        "FX-45H): GBP and CAD currently have no verified effective-date coverage at all, "
        "so EFFECTIVE results for any pair involving them are UNAVAILABLE for the whole "
        "history, not a weak or noisy result -- see disposition counts above.\n"
        "- No imputation, no EFFECTIVE->ANNOUNCED fallback, and no post-hoc changes to "
        "instruments, horizons, eras, or grouping were made after this script was run "
        "against real data.\n"
        "- 10,000-resample bootstraps drawn from a small number of distinct calendar-year "
        "clusters (see each contrast's own n_years_a/n_years_b and the era table's own "
        "per-era counts) are not 10,000 independent historical years -- interpret CI width "
        "accordingly, the same caveat this project's own FX-39 bootstrap work already "
        "carries.\n"
        "- A contrast reporting NOT_ESTIMABLE (see its own note) means the calendar-year "
        "cluster bootstrap could not compute a confidence interval at all -- either an arm "
        "has fewer than 2 distinct year clusters in the full sample, or the bootstrap's "
        "redraw cap was exhausted for a structurally pathological cluster imbalance "
        "(FX-46H). This is reported explicitly rather than as a wide-but-computed CI or a "
        "fabricated value -- do not read the observed point estimate alone as evidence of "
        "association when its own contrast is NOT_ESTIMABLE."
    )
    lines.append("")
    return "\n".join(lines)


# --- Main --------------------------------------------------------------------


async def main() -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    all_records: list[SampleRecord] = []
    candle_end_actual_by_instrument: dict[str, str | None] = {}
    async with session_factory() as session:
        candle_repo = SqlAlchemyCandleRepository(session)
        raw_repo = SqlAlchemyMacroObservationRepository(session)
        cached_repo = _CachingMacroObservationRepository(raw_repo)
        use_case = ComputePolicyRateDifferential(repository=cached_repo)
        for instrument in PAIRS:
            print(f"{instrument.symbol}: evaluating ...")
            records, actual_end = await _collect_pair_records(candle_repo, use_case, instrument)
            all_records.extend(records)
            candle_end_actual_by_instrument[instrument.symbol] = (
                actual_end.value.isoformat() if actual_end is not None else None
            )
            print(f"  {len(records)} sample rows")
        macro_data_fingerprint = cached_repo.macro_data_fingerprint()

    all_records.sort(key=lambda r: (r.instrument, r.semantics, r.experiment, r.as_of.value))

    try:
        commit_hash = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        commit_hash = "unknown"

    try:
        dirty_output = subprocess.check_output(["git", "status", "--porcelain"]).decode().strip()
        git_commit_dirty: bool | None = bool(dirty_output)
        git_dirty_paths = dirty_output.splitlines() if dirty_output else []
    except Exception:
        git_commit_dirty = None
        git_dirty_paths = []

    config = {
        "instruments": [i.symbol for i in PAIRS],
        "rate_semantics": [s.value for s in SEMANTICS],
        "forward_horizons_trading_days": list(FORWARD_HORIZONS_TRADING_DAYS),
        "eras": [
            {"label": label, "start": start.isoformat(), "end": end.isoformat() if end else None}
            for label, start, end in ERAS
        ],
        "sparse_era_threshold": SPARSE_ERA_THRESHOLD,
        "num_resamples": NUM_RESAMPLES,
        "seed": SEED,
        "bootstrap_method": "calendar_year_cluster_bootstrap_differences",
        "confidence_level": "0.95",
        "return_definition": "mid_open-to-mid_open, entry = next D-bar open strictly after as_of",
        "weekly_sampling": "one ISO-calendar-week observation, first available D-bar open",
        "candle_start_bound": _CANDLE_START.value.isoformat(),
        "candle_end_bound": _CANDLE_END.value.isoformat(),
    }
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()

    report: dict[str, Any] = {
        "story": "FX-46",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "git_commit": commit_hash,
        "git_commit_dirty": git_commit_dirty,
        "git_dirty_paths": git_dirty_paths,
        "candle_end_actual_by_instrument": candle_end_actual_by_instrument,
        "macro_data_fingerprint": macro_data_fingerprint,
        "config_hash": config_hash,
        "config": config,
        "pairs": {
            instrument.symbol: {
                semantics.value: {
                    experiment: _cell_report(all_records, instrument, semantics, experiment)
                    for experiment in ("LEVEL", "CHANGE")
                }
                for semantics in SEMANTICS
            }
            for instrument in PAIRS
        },
        "secondary_pooled": _secondary_pooled(all_records),
        "total_sample_rows": len(all_records),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(report, OUT_DIR / "policy_rate_differential_research.json")
    _write_csv(all_records, OUT_DIR / "policy_rate_differential_samples.csv")
    markdown = _render_markdown(report)
    tmp_md = OUT_DIR / "policy_rate_differential_summary.md.tmp"
    tmp_md.write_text(markdown)
    tmp_md.replace(OUT_DIR / "policy_rate_differential_summary.md")

    print(f"\n{len(all_records)} total sample rows across all pairs/semantics/experiments.")
    print(f"Wrote {OUT_DIR / 'policy_rate_differential_research.json'}")
    print(f"Wrote {OUT_DIR / 'policy_rate_differential_samples.csv'}")
    print(f"Wrote {OUT_DIR / 'policy_rate_differential_summary.md'}")
    print(
        "\nNo threshold, parameter, instrument, horizon, or era changes occur as a result "
        "of any outcome above -- this script's own protocol forbids it regardless of result."
    )


if __name__ == "__main__":
    asyncio.run(main())

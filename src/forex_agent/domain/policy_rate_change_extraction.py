"""Pure change-point extraction for policy-rate backfill (FX-43).

The core anti-interpolation guarantee for this story lives here, not in
any infrastructure adapter: `extract_change_points` NEVER fabricates a
value for a date it wasn't given, and only ever emits an observation
when the canonical value genuinely differs from the immediately
preceding one. A provider's raw daily series (FRED, the ECB Data
Portal, the BoE database, and the BoC Valet API all publish this way)
typically repeats the same value across every day it stayed in effect
-- feeding that directly into `MacroObservationVintage` would produce
thousands of near-duplicate "observations" that misrepresent daily
repetition as daily decision-making. This function instead reduces a
raw daily series down to genuine policy CHANGES: one observation per
date the value actually moved.

Pure, no I/O -- a provider adapter's job is only to turn its own HTTP
response into `(UtcTimestamp, Decimal)` pairs; this function turns
those pairs into what `MacroObservationVintage` needs, independent of
any specific provider.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from forex_agent.domain.rate_transformation import RateTransformation
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ExtractedPolicyRateChange:
    """One genuine change point: the canonical value became `value` on
    `observation_period`, having differed from whatever value (if any)
    was in effect the previous day this function saw data for."""

    observation_period: UtcTimestamp
    value: Decimal


@dataclass(frozen=True, slots=True)
class ChangePointExtractionResult:
    """`changes`: the extracted change points, ascending by
    `observation_period`. `skipped_dates`: dates present in at least
    one raw series but not ALL of them (only possible when
    `transformation` needs more than one raw series, e.g.
    `TARGET_RANGE_MIDPOINT`'s upper/lower bound) -- never guessed at or
    filled in; recorded here so a caller can report them as a
    data-quality anomaly instead of silently dropping them."""

    changes: tuple[ExtractedPolicyRateChange, ...]
    skipped_dates: tuple[UtcTimestamp, ...]


def extract_change_points(
    raw_series: tuple[tuple[tuple[UtcTimestamp, Decimal], ...], ...],
    transformation: RateTransformation,
) -> ChangePointExtractionResult:
    """Reduce one or more raw daily (date, value) series into genuine
    policy-rate change points.

    `raw_series` holds one tuple per raw provider series, in the exact
    order `transformation.apply` expects them (matching
    `ProviderSeriesMapping.provider_series_ids`'s own ordering
    convention -- e.g. (upper, lower) for `TARGET_RANGE_MIDPOINT`).
    Each inner series need not be pre-sorted or pre-deduplicated by the
    caller; this function sorts and, for a date appearing more than
    once within one series, keeps the LAST occurrence (a provider
    adapter should never produce duplicates, but this function does not
    trust that blindly).

    A date only produces a canonical value if EVERY raw series has an
    entry for it -- a date present in the upper-bound series but not
    the lower-bound series (or vice versa) is never paired with a
    fabricated counterpart; it is recorded in `skipped_dates` instead.
    """
    if not raw_series:
        raise ValueError("raw_series must contain at least one series")

    series_by_date: list[dict[datetime, Decimal]] = []
    all_dates: set[datetime] = set()
    for series in raw_series:
        one_series: dict[datetime, Decimal] = {}
        for timestamp, value in series:
            one_series[timestamp.value] = value
        series_by_date.append(one_series)
        all_dates.update(one_series.keys())

    changes: list[ExtractedPolicyRateChange] = []
    skipped: list[UtcTimestamp] = []
    previous_value: Decimal | None = None

    for date in sorted(all_dates):
        if not all(date in one_series for one_series in series_by_date):
            skipped.append(UtcTimestamp(date))
            continue

        raw_values = tuple(one_series[date] for one_series in series_by_date)
        canonical_value = transformation.apply(*raw_values)

        if previous_value is None or canonical_value != previous_value:
            changes.append(ExtractedPolicyRateChange(UtcTimestamp(date), canonical_value))
            previous_value = canonical_value

    return ChangePointExtractionResult(changes=tuple(changes), skipped_dates=tuple(skipped))

"""FX-47: ATTRIBUTION, not gating, of the existing policy-rate
differential feature (FX-42-FX-46H) against trades an EXISTING,
already-committed strategy generates unconditionally. Exactly the same
shape as `domain.regime_segmentation.segment_trades_by_regime` (FX-21/
FX-21H): buckets trades that would occur regardless by a classification
external to the strategy, changes no strategy logic or parameters, and
never suppresses a trade. This module never re-derives policy-rate
state itself -- every `FeatureEvaluation`/`ChangeEvent` it consumes was
already produced through FX-46's own single seam
(`research.policy_rate_differential_research.evaluate_feature` ->
`ComputePolicyRateDifferential`); this module only classifies and joins
already-computed results, exactly the same division of labour FX-46's
own script already established for its own aggregation layer.

Two independent axes per trade, reported separately (never combined
into one bucket), per FX-47's own explicit design:

  LEVEL: does the differential's sign, AT THE TRADE'S OWN ENTRY TIME,
    support or oppose the trade's own direction? `evaluate_feature` is
    called once per trade at its exact `entry_time` (not snapped to any
    candle grid) -- `ComputePolicyRateDifferential` is already a plain
    point-in-time query, so this needs no D-bar alignment at all.
  CHANGE: reuses FX-46's own precomputed per-D-bar `ChangeEvent`
    sequence (INCREASED/DECREASED/UNCHANGED, or GAP/NO_PRIOR_DAY when a
    transition can't be inferred) for whichever D-bar governs the
    trade's entry -- the most recent D-bar at or before `entry_time`.
    Policy rates are daily data; the governing D-bar's own change
    status was already fully determined at that D-bar's own open,
    strictly before any H1/H4 entry later that same trading day or
    after it, so this join introduces no look-ahead.

Every branch that cannot classify a trade (the differential was
BLOCKED/UNAVAILABLE at entry, or no D-bar exists yet at all before
entry) is its own explicit, reported outcome -- never silently dropped
or folded into `NEUTRAL`, matching this project's standing discipline
since FX-44H.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from itertools import pairwise

from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.trade_side import TradeSide
from forex_agent.research.policy_rate_differential_research import (
    ChangeEvent,
    ChangeGroup,
    Disposition,
    FeatureEvaluation,
    LevelGroup,
    TransitionStatus,
    classify_level,
)


class LevelAttribution(Enum):
    """FX-47: purely mechanical relationship between a trade's own
    `side` and the differential's `LevelGroup` at entry -- no threshold,
    no economic judgment about whether "supporting" carry logic is
    actually correct (that is precisely the open question FX-47 tests,
    not an assumption baked into the classification)."""

    SUPPORTS = "SUPPORTS"
    OPPOSES = "OPPOSES"
    NEUTRAL = "NEUTRAL"


def classify_level_attribution(side: TradeSide, group: LevelGroup) -> LevelAttribution:
    """LONG + POSITIVE (base rate > quote rate), or SHORT + NEGATIVE ->
    `SUPPORTS` (the classic "long the higher-yielding currency" carry
    logic). LONG + NEGATIVE, or SHORT + POSITIVE -> `OPPOSES`. Either
    side + `ZERO` -> `NEUTRAL`, unconditionally."""
    if group is LevelGroup.ZERO:
        return LevelAttribution.NEUTRAL
    is_long = side is TradeSide.LONG
    is_positive = group is LevelGroup.POSITIVE
    if is_long == is_positive:
        return LevelAttribution.SUPPORTS
    return LevelAttribution.OPPOSES


@dataclass(frozen=True, slots=True)
class TradeLevelAttribution:
    """`attribution`/`reason` are mutually exclusive and exactly one is
    populated, mirroring `FeatureEvaluation`'s own `differential`/
    `reason` split: `attribution` iff `disposition is Disposition.
    USABLE`, `reason` otherwise."""

    disposition: Disposition
    attribution: LevelAttribution | None
    reason: str | None


def attribute_trade_level(
    trade: SimulatedTrade, evaluation: FeatureEvaluation
) -> TradeLevelAttribution:
    """`evaluation` must be the result of evaluating the feature at
    EXACTLY `trade.entry_time` -- raises `ValueError` otherwise, the
    same defensive mismatch-checking convention `segment_trades_by_
    regime`/`simulate_trades` already use for a mismatched trade/candle
    pairing."""
    if evaluation.as_of != trade.entry_time:
        raise ValueError(
            f"evaluation.as_of ({evaluation.as_of.value.isoformat()}) does not match "
            f"trade.entry_time ({trade.entry_time.value.isoformat()})"
        )
    if evaluation.disposition is not Disposition.USABLE:
        return TradeLevelAttribution(
            disposition=evaluation.disposition, attribution=None, reason=evaluation.reason
        )
    assert evaluation.differential is not None  # USABLE guarantees this
    group = classify_level(evaluation.differential)
    return TradeLevelAttribution(
        disposition=Disposition.USABLE,
        attribution=classify_level_attribution(trade.side, group),
        reason=None,
    )


def level_bucket_label(attribution: TradeLevelAttribution) -> str:
    """One flat string for reporting -- `SUPPORTS`/`OPPOSES`/`NEUTRAL`
    when usable, else the raw `Disposition` name (`BLOCKED`/
    `UNAVAILABLE`)."""
    if attribution.attribution is not None:
        return attribution.attribution.value
    return attribution.disposition.value


@dataclass(frozen=True, slots=True)
class TradeChangeAttribution:
    """`disposition` mirrors whether the GOVERNING D-bar's own
    differential evaluation succeeded (`USABLE`/`BLOCKED`/
    `UNAVAILABLE`, or `Disposition.BLOCKED` with reason
    `"no_governing_day_before_entry"` when no D-bar exists yet at all
    before the trade's `entry_time`). `status`/`group` are populated
    only when `disposition is USABLE` -- a GOVERNING day can be USABLE
    while its own TRANSITION is still unknown (`status is
    TransitionStatus.GAP` or `NO_PRIOR_DAY`), in which case `group`
    stays `None` -- these are two different layers of "no answer",
    exactly as FX-46 itself already distinguishes."""

    disposition: Disposition
    status: TransitionStatus | None
    group: ChangeGroup | None
    reason: str | None


_NO_GOVERNING_DAY_REASON = "no_governing_day_before_entry"


def find_governing_daily_evaluation(
    daily_sorted: Sequence[FeatureEvaluation], entry_time_value: datetime
) -> FeatureEvaluation | None:
    """The last evaluation in `daily_sorted` (one per canonical D-bar
    open, one per calendar day) with `as_of <= entry_time_value` -- the
    trading day in effect when a trade was entered. `None` if
    `entry_time_value` predates every evaluation in `daily_sorted`.

    Requires `daily_sorted` to already be strictly ascending by
    `as_of` -- raises `ValueError` otherwise, the same "caller supplies
    a stable, pre-sorted index space" contract `find_entry_index`/
    `compute_forward_return` already use in this same research module.
    """
    for previous, current in pairwise(daily_sorted):
        if current.as_of.value <= previous.as_of.value:
            raise ValueError(
                "daily_sorted must be strictly ascending by as_of; "
                f"{current.as_of.value.isoformat()} does not follow "
                f"{previous.as_of.value.isoformat()}"
            )
    as_of_values = [e.as_of.value for e in daily_sorted]
    index = bisect_right(as_of_values, entry_time_value) - 1
    if index < 0:
        return None
    return daily_sorted[index]


def attribute_trade_change(
    entry_time_value: datetime,
    daily_sorted: Sequence[FeatureEvaluation],
    change_events_by_as_of: Mapping[datetime, ChangeEvent],
) -> TradeChangeAttribution:
    governing = find_governing_daily_evaluation(daily_sorted, entry_time_value)
    if governing is None:
        return TradeChangeAttribution(
            disposition=Disposition.BLOCKED,
            status=None,
            group=None,
            reason=_NO_GOVERNING_DAY_REASON,
        )
    if governing.disposition is not Disposition.USABLE:
        return TradeChangeAttribution(
            disposition=governing.disposition,
            status=None,
            group=None,
            reason=governing.reason,
        )
    event = change_events_by_as_of[governing.as_of.value]
    return TradeChangeAttribution(
        disposition=Disposition.USABLE,
        status=event.status,
        group=event.group,
        reason=None,
    )


def change_bucket_label(attribution: TradeChangeAttribution) -> str:
    """One flat string for reporting -- `INCREASED`/`DECREASED`/
    `UNCHANGED` when the transition is admissible, `TRANSITION_UNKNOWN_
    DUE_TO_GAP`/`NO_PRIOR_DAY` when the governing day is USABLE but its
    own transition isn't, else the raw `Disposition` name (`BLOCKED`/
    `UNAVAILABLE`) -- or `NO_GOVERNING_DAY` specifically when `reason`
    is `_NO_GOVERNING_DAY_REASON`, distinguished from an ordinary
    BLOCKED evaluation so a reader isn't left guessing which one it
    was."""
    if attribution.group is not None:
        return attribution.group.value
    if attribution.status is TransitionStatus.GAP:
        return "TRANSITION_UNKNOWN_DUE_TO_GAP"
    if attribution.status is TransitionStatus.NO_PRIOR_DAY:
        return "NO_PRIOR_DAY"
    if attribution.reason == _NO_GOVERNING_DAY_REASON:
        return "NO_GOVERNING_DAY"
    return attribution.disposition.value


@dataclass(frozen=True, slots=True)
class TradeAttribution:
    trade: SimulatedTrade
    level: TradeLevelAttribution
    change: TradeChangeAttribution


def attribute_trades(
    trades: Sequence[SimulatedTrade],
    level_evaluations: Sequence[FeatureEvaluation],
    daily_sorted: Sequence[FeatureEvaluation],
    change_events_by_as_of: Mapping[datetime, ChangeEvent],
) -> list[TradeAttribution]:
    """`level_evaluations` must be positionally aligned with `trades`
    (`level_evaluations[i]` is the feature evaluated at exactly
    `trades[i].entry_time`) -- raises `ValueError` on a length mismatch,
    the same defensive style as every other joining function in this
    module and its FX-46 sibling."""
    if len(trades) != len(level_evaluations):
        raise ValueError(
            f"trades ({len(trades)}) and level_evaluations ({len(level_evaluations)}) "
            "must be the same length, positionally aligned"
        )
    return [
        TradeAttribution(
            trade=trade,
            level=attribute_trade_level(trade, evaluation),
            change=attribute_trade_change(
                trade.entry_time.value, daily_sorted, change_events_by_as_of
            ),
        )
        for trade, evaluation in zip(trades, level_evaluations, strict=True)
    ]

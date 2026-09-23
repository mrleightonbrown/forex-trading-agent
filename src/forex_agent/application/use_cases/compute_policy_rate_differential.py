"""FX-45: orchestrates `domain.policy_rate_state`/`domain.policy_rate_
differential`'s pure functions against real repository history to
produce a `PolicyRateDifferentialFeature` -- the deterministic,
auditable, monetary-policy feature this story builds. Never called
"carry" (see `domain.policy_rate_differential`'s own module
docstring); no trading rule, no scoring, no thresholds.

Every historical read goes through `domain.research_readiness.
require_research_ready_interval` before its result is trusted (FX-45
section 4) -- this use case fetches a currency's COMPLETE stored
history via `MacroObservationRepository.list_all_for_series` and lets
the readiness gate examine it, rather than hand-selecting which rows
"should" matter; a single provisional observation anywhere in the
window this feature actually needs (current state, the previous policy
observation, and the ~3/~6 month lookbacks, all at once) fails the
WHOLE request -- there is no partial result. Two distinct kinds of "no
answer" exist, deliberately not conflated:
  - unsafe/insufficient DATA -> `ResearchIntervalNotReadyError` is
    RAISED (the existing FX-44H mechanism, unmodified);
  - a structurally unsupported request (a currency with no canonical
    policy rate at all, or `EFFECTIVE` semantics for a currency/vintage
    that has never had a verified effective date) -> `Differential
    Unavailable` is RETURNED, not raised.

`require_research_ready_interval`/`select_research_candidates` window
on `observation_period` (FX-44H), while state selection here windows
on `released_at`/`effective_at` (FX-45) -- two axes that are usually
close (per FX-44H.1's own research, at most a few days apart for any
currency in this registry) but never assumed identical. `_AXIS_
SAFETY_MARGIN` pads every readiness window well past the largest
offset this codebase has ever found (EUR's historical six-day
announcement/effective gap), so the vintage a state-selection query
actually returns is always provably covered by the readiness check
that ran for it -- not merely "usually" covered.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from forex_agent.application.ports.macro_observation_repository import MacroObservationRepository
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.policy_rate_differential import (
    CurrencyRateState,
    DifferentialUnavailable,
    PolicyRateDifferentialFeature,
    PolicyRateDifferentialSnapshot,
    RateSemantics,
    classify_direction,
    format_pair,
    pair_differential_change_since_previous,
    rate_differential,
)
from forex_agent.domain.policy_rate_registry import canonical_series_for_currency
from forex_agent.domain.policy_rate_state import (
    announced_state_as_of,
    effective_state_as_of,
    previous_announced_state,
    previous_effective_state,
)
from forex_agent.domain.research_readiness import require_research_ready_interval
from forex_agent.domain.timestamps import UtcTimestamp

#: FX-45 section 8: "approximately 3 months" / "approximately 6
#: months" -- fixed day-count approximations, not exact calendar-month
#: arithmetic (this codebase has no calendar-month-aware date library
#: dependency, and the story's own wording says "approximately").
THREE_MONTHS = timedelta(days=91)
SIX_MONTHS = timedelta(days=182)

#: See this module's own docstring: pads every readiness window well
#: past the largest known observation_period/released_at/effective_at
#: offset in this registry (EUR's six-day historical gap), so a
#: state-selection result is always provably inside the window that
#: was actually validated for it.
_AXIS_SAFETY_MARGIN = timedelta(days=14)

#: `require_research_ready_interval`'s interval is half-open
#: (`[start, end)`); this converts an intended INCLUSIVE upper bound
#: into that exclusive one.
_INCLUSIVE_END_EPSILON = timedelta(microseconds=1)

_StateLookup = Callable[
    [Sequence[MacroObservationVintage], UtcTimestamp], "MacroObservationVintage | None"
]
_PreviousLookup = Callable[
    [Sequence[MacroObservationVintage], MacroObservationVintage], "MacroObservationVintage | None"
]


@dataclass(frozen=True, slots=True)
class ComputePolicyRateDifferential:
    """FX-45's single use case: `(instrument, as_of, rate_semantics)`
    -> a fully-provenanced `PolicyRateDifferentialFeature`, or an
    explicit `DifferentialUnavailable`. See this module's own
    docstring for the raise-vs-return split."""

    repository: MacroObservationRepository

    async def __call__(
        self, instrument: Instrument, as_of: UtcTimestamp, rate_semantics: RateSemantics
    ) -> PolicyRateDifferentialFeature | DifferentialUnavailable:
        pair = format_pair(instrument.base_currency, instrument.quote_currency)

        base_series = canonical_series_for_currency(instrument.base_currency)
        if base_series is None:
            return DifferentialUnavailable(
                pair=pair,
                as_of=as_of,
                rate_semantics=rate_semantics,
                reason=(
                    f"{instrument.base_currency} is not a currency with a canonical "
                    "policy rate in this registry"
                ),
            )
        quote_series = canonical_series_for_currency(instrument.quote_currency)
        if quote_series is None:
            return DifferentialUnavailable(
                pair=pair,
                as_of=as_of,
                rate_semantics=rate_semantics,
                reason=(
                    f"{instrument.quote_currency} is not a currency with a canonical "
                    "policy rate in this registry"
                ),
            )

        # FX-45 section 3: a currency CAN be a registered canonical concept
        # (JPY has PolicyRateDefinition entries, per FX-42H/FX-42H.1) while
        # having zero ingested history (JPY provider ingestion remains
        # unresolved, per FX-43/FX-43H) -- list_all_for_series returns an
        # empty tuple for it, and require_research_ready_interval below
        # correctly raises (no_baseline=True) rather than this use case
        # needing its own separate "is JPY supported" special case.
        base_history = await self.repository.list_all_for_series(base_series.key)
        quote_history = await self.repository.list_all_for_series(quote_series.key)

        state_as_of: _StateLookup = (
            announced_state_as_of
            if rate_semantics is RateSemantics.ANNOUNCED
            else effective_state_as_of
        )
        previous_state: _PreviousLookup = (
            previous_announced_state
            if rate_semantics is RateSemantics.ANNOUNCED
            else previous_effective_state
        )

        current_base_vintage = state_as_of(base_history, as_of)
        current_quote_vintage = state_as_of(quote_history, as_of)
        previous_base_vintage = (
            None
            if current_base_vintage is None
            else previous_state(base_history, current_base_vintage)
        )
        previous_quote_vintage = (
            None
            if current_quote_vintage is None
            else previous_state(quote_history, current_quote_vintage)
        )

        base_window = _readiness_window(as_of, current_base_vintage, previous_base_vintage)
        quote_window = _readiness_window(as_of, current_quote_vintage, previous_quote_vintage)

        # Raises ResearchIntervalNotReadyError (unmodified FX-44H mechanism)
        # if anything in either currency's needed window is unsafe or
        # missing entirely -- deliberately NOT caught here; this use case's
        # whole point is to let that fail closed all the way to the caller.
        require_research_ready_interval(base_history, base_window[0], base_window[1])
        require_research_ready_interval(quote_history, quote_window[0], quote_window[1])

        if current_base_vintage is None or current_quote_vintage is None:
            # The readiness checks above already proved SOMETHING safe
            # exists in-window for both currencies (they did not raise) --
            # reaching here means that safe evidence still does not amount
            # to a governing CURRENT state under rate_semantics specifically.
            # Only possible for EFFECTIVE: e.g. every currently-relevant
            # vintage is exact/conservative on released_at but has no
            # effective_at at all (GBP and CAD, entirely, as of this story
            # -- see docs/DECISIONS.md's FX-45 entry).
            missing = (
                instrument.base_currency
                if current_base_vintage is None
                else instrument.quote_currency
            )
            reason = (
                f"no {rate_semantics.value} policy-rate state is defensibly established for "
                f"{missing} as of {as_of.value.isoformat()} (effective_at not populated for the "
                "governing vintage)"
                if rate_semantics is RateSemantics.EFFECTIVE
                else f"no {rate_semantics.value} policy-rate state exists for {missing} as of "
                f"{as_of.value.isoformat()}"
            )
            return DifferentialUnavailable(
                pair=pair, as_of=as_of, rate_semantics=rate_semantics, reason=reason
            )

        current_base = CurrencyRateState.from_vintage(
            instrument.base_currency, current_base_vintage
        )
        current_quote = CurrencyRateState.from_vintage(
            instrument.quote_currency, current_quote_vintage
        )
        current_differential = rate_differential(current_base.rate, current_quote.rate)
        current_snapshot = PolicyRateDifferentialSnapshot(
            pair=pair,
            as_of=as_of,
            rate_semantics=rate_semantics,
            base=current_base,
            quote=current_quote,
            differential=current_differential,
        )

        previous_base = (
            None
            if previous_base_vintage is None
            else CurrencyRateState.from_vintage(instrument.base_currency, previous_base_vintage)
        )
        previous_quote = (
            None
            if previous_quote_vintage is None
            else CurrencyRateState.from_vintage(instrument.quote_currency, previous_quote_vintage)
        )
        change_since_previous = pair_differential_change_since_previous(
            current_differential,
            rate_semantics,
            current_base,
            current_quote,
            previous_base,
            previous_quote,
        )

        change_3m = _change_over(
            base_history, quote_history, state_as_of, current_differential, as_of, THREE_MONTHS
        )
        change_6m = _change_over(
            base_history, quote_history, state_as_of, current_differential, as_of, SIX_MONTHS
        )

        return PolicyRateDifferentialFeature(
            current=current_snapshot,
            change_since_previous=change_since_previous,
            direction_since_previous=classify_direction(change_since_previous),
            change_3m=change_3m,
            direction_3m=classify_direction(change_3m),
            change_6m=change_6m,
            direction_6m=classify_direction(change_6m),
        )


def _readiness_window(
    as_of: UtcTimestamp,
    current: MacroObservationVintage | None,
    previous: MacroObservationVintage | None,
) -> tuple[UtcTimestamp, UtcTimestamp]:
    """The `[start, end)` window `require_research_ready_interval` must
    validate to cover everything ONE currency's differential-feature
    computation could possibly use: the fixed ~6-month lookback,
    PLUS -- if it reaches further back than that -- the actual
    `previous` policy observation found, PLUS a safety margin on every
    bound (see this module's own docstring) absorbing the
    observation_period/released_at/effective_at axis difference."""
    start = as_of.value - SIX_MONTHS - _AXIS_SAFETY_MARGIN
    end = as_of.value + _AXIS_SAFETY_MARGIN
    if current is not None:
        start = min(start, current.observation_period.value - _AXIS_SAFETY_MARGIN)
        end = max(end, current.observation_period.value + _AXIS_SAFETY_MARGIN)
    if previous is not None:
        start = min(start, previous.observation_period.value - _AXIS_SAFETY_MARGIN)
    return UtcTimestamp(start), UtcTimestamp(end + _INCLUSIVE_END_EPSILON)


def _change_over(
    base_history: Sequence[MacroObservationVintage],
    quote_history: Sequence[MacroObservationVintage],
    state_as_of: _StateLookup,
    current_differential: Decimal,
    as_of: UtcTimestamp,
    lag: timedelta,
) -> Decimal | None:
    """FX-45 section 8's ~3/~6 month lookback changes -- `None` (never
    a guess) when either leg has no defensible state that far back,
    e.g. near the start of a currency's history. Both lags are `<=
    SIX_MONTHS`, so any vintage this can possibly return was already
    covered by `_readiness_window`'s own fixed ~6-month baseline --
    no separate readiness check is needed here."""
    lagged_as_of = UtcTimestamp(as_of.value - lag)
    lagged_base = state_as_of(base_history, lagged_as_of)
    lagged_quote = state_as_of(quote_history, lagged_as_of)
    if lagged_base is None or lagged_quote is None:
        return None
    lagged_differential = rate_differential(lagged_base.value, lagged_quote.value)
    return current_differential - lagged_differential

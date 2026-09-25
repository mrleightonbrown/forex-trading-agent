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
the readiness gate examine THAT COMPLETE history directly, never a
pre-filtered view (FX-45H.1 section 3: a provisional vintage's own
`released_at` may be an uncorroborated proxy, not a verified
knowability instant -- pre-narrowing the readiness check's input by it
would let a genuinely relevant provisional vintage silently vanish
from consideration instead of correctly failing the interval closed).
State selection (`domain.policy_rate_state.announced_state_as_of`/
`effective_state_as_of`/`previous_*`) is handed this SAME complete
history too and does its own internal point-in-time filtering -- a
single provisional observation anywhere in the window this feature
actually needs (current state, the previous policy observation, and
the ~3/~6 month lookbacks, all at once) fails the WHOLE request; there
is no partial result. Two distinct kinds of "no answer" exist,
deliberately not conflated:
  - unsafe/insufficient DATA -> `ResearchIntervalNotReadyError` is
    RAISED (the existing FX-44H mechanism, unmodified);
  - a structurally unsupported request (a currency with no canonical
    policy rate at all, `EFFECTIVE` semantics for a currency/vintage
    that has never had a verified effective date, or `EFFECTIVE`
    semantics where a newer decision's -- or a same-observation higher
    revision's, FX-45H.1 section 5 -- effective timing is not yet
    established) -> `DifferentialUnavailable` is RETURNED, not raised.

**Two axes, and the correctness mechanism for their mismatch (FX-45H
section 3/4, refined FX-45H.1).** `require_research_ready_interval`/
`select_research_candidates` (FX-44H) window on `observation_period`,
while state selection (`domain.policy_rate_state`) windows on
`released_at`/`effective_at` (FX-45) -- axes that are usually close but
never assumed identical. `_AXIS_SAFETY_MARGIN` (14 days) pads every
readiness window bound past the largest such gap this registry's real
data has ever shown (about six days, EUR), so a legitimately PIT-safe
`current`/`previous` vintage's own `observation_period` is always
provably examined by the readiness check, even when it falls a few
days on either side of `as_of`. The margin is not, and must not be
read as, a mathematical proof that no future currency or regime will
ever exceed it -- it is defensive padding, re-examined whenever a new
currency or timing regime is added to this registry, layered on top of
the readiness check always receiving the COMPLETE history (never a
narrower one) as the actual correctness guarantee against a not-yet-
established vintage being silently pruned before it can be judged.
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

#: Defensive padding only -- NOT the primary correctness mechanism for
#: the observation_period/released_at/effective_at axis mismatch; see
#: this module's own docstring (FX-45H section 4, refined FX-45H.1).
#: Sized comfortably past the largest such gap this registry's real
#: data has ever shown (about six days, EUR); the readiness check
#: always receiving the COMPLETE history (`domain.policy_rate_state`'s
#: own state-selection functions handle PIT-filtering internally, on
#: that same complete history, never a pre-narrowed one) is what
#: actually guarantees a not-yet-established vintage cannot be silently
#: pruned away before it can be judged.
_AXIS_SAFETY_MARGIN = timedelta(days=14)

#: `require_research_ready_interval`'s interval is half-open
#: (`[start, end)`); this converts an intended INCLUSIVE upper bound
#: into that exclusive one.
_INCLUSIVE_END_EPSILON = timedelta(microseconds=1)

_StateLookup = Callable[
    [Sequence[MacroObservationVintage], UtcTimestamp], "MacroObservationVintage | None"
]
_PreviousLookup = Callable[
    [Sequence[MacroObservationVintage], MacroObservationVintage, UtcTimestamp],
    "MacroObservationVintage | None",
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
        #
        # FX-45H.1 section 3: this COMPLETE history is handed, unmodified,
        # to BOTH state selection AND the readiness check below -- never a
        # view pre-filtered by any single vintage's own released_at. State
        # selection performs its own internal point-in-time filtering
        # (domain.policy_rate_state); the readiness check needs the whole
        # series to correctly fail closed on a relevant provisional vintage
        # rather than have it silently pruned by an unverified proxy first.
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
            else previous_state(base_history, current_base_vintage, as_of)
        )
        previous_quote_vintage = (
            None
            if current_quote_vintage is None
            else previous_state(quote_history, current_quote_vintage, as_of)
        )

        base_window = _readiness_window(as_of, current_base_vintage, previous_base_vintage)
        quote_window = _readiness_window(as_of, current_quote_vintage, previous_quote_vintage)

        # Raises ResearchIntervalNotReadyError (unmodified FX-44H mechanism)
        # if anything in either currency's needed window is unsafe or
        # missing entirely -- deliberately NOT caught here; this use case's
        # whole point is to let that fail closed all the way to the caller.
        # base_history/quote_history (the COMPLETE, unfiltered series
        # history) is passed -- see this module's own docstring for why
        # narrowing this input by any vintage's own released_at, even
        # FX-45H's PIT filter, is exactly the bug FX-45H.1 fixed.
        require_research_ready_interval(base_history, base_window[0], base_window[1])
        require_research_ready_interval(quote_history, quote_window[0], quote_window[1])

        if current_base_vintage is None or current_quote_vintage is None:
            # The readiness checks above already proved SOMETHING safe
            # exists in-window for both currencies (they did not raise) --
            # reaching here means that safe evidence still does not amount
            # to a governing CURRENT state under rate_semantics specifically.
            # Only possible for EFFECTIVE (FX-45 section 6 / FX-45H section
            # 2 / FX-45H.1 section 5): every currently-relevant vintage is
            # exact/conservative on released_at but has no effective_at at
            # all (GBP and CAD, entirely, as of this story -- see docs/
            # DECISIONS.md's FX-45 entry); a newer decision has already been
            # released by as_of whose own effective_at is not yet
            # established; or a higher revision of the SAME observation as
            # the would-be candidate has been released with its own
            # effective_at unestablished.
            missing = (
                instrument.base_currency
                if current_base_vintage is None
                else instrument.quote_currency
            )
            reason = (
                f"no {rate_semantics.value} policy-rate state is defensibly established for "
                f"{missing} as of {as_of.value.isoformat()} (effective_at has not been "
                "populated for the governing vintage, a newer decision has already been "
                "released whose own effective_at is not yet established, or a newer revision "
                "of the same observation has been released whose own effective_at is not yet "
                "established)"
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
    computation could possibly use: the fixed ~6-month lookback ending
    at `as_of` itself, PLUS -- only if `current`/`previous` actually
    reach further out -- their own `observation_period`, each padded by
    `_AXIS_SAFETY_MARGIN` (see this module's own docstring: defensive
    padding for the observation_period axis, layered on top of the
    readiness check always receiving the complete history).

    Deliberately does NOT pad `end` forward from `as_of` unconditionally
    (FX-45H section 3/4): doing so let genuinely irrelevant future
    `observation_period`s inflate the checked window well past what
    `current`/`previous` actually need, for no correctness benefit --
    correctness against a not-yet-established vintage comes from the
    readiness check always receiving the complete history (FX-45H.1
    section 3), not from this window's own bounds.
    """
    start = as_of.value - SIX_MONTHS - _AXIS_SAFETY_MARGIN
    end = as_of.value
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
    covered by `_readiness_window`'s own fixed ~6-month baseline -- no
    separate readiness check is needed here. `base_history`/`quote_
    history` are each series' complete history; `state_as_of` narrows
    them internally to `released_at <= lagged_as_of` for the earlier
    instant this function actually queries.
    """
    lagged_as_of = UtcTimestamp(as_of.value - lag)
    lagged_base = state_as_of(base_history, lagged_as_of)
    lagged_quote = state_as_of(quote_history, lagged_as_of)
    if lagged_base is None or lagged_quote is None:
        return None
    lagged_differential = rate_differential(lagged_base.value, lagged_quote.value)
    return current_differential - lagged_differential

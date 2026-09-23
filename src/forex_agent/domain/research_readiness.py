"""FX-44 section 8's critical invariant, enforced as code: "before
FX-45 research may run: every rate observation visible to the
experiment must either have a verified market-availability timestamp
or belong to an explicitly defined research-safe timing policy that
cannot reveal it early. A single provisional observation in the
selected research interval must fail closed."

This is the mandatory pre-flight check a future FX-45 (or any other
historical-research consumer of `MacroObservationVintage` data) MUST
call before running against a selected interval. It is deliberately
NOT specific to policy rates or to FX-44's own registry -- it operates
on whatever vintages the caller already fetched, so it works
regardless of which use case produced them.

FX-44H hardening: `require_research_ready_interval` originally judged
only vintages whose `observation_period` fell INSIDE `[interval_start,
interval_end)`. That is insufficient -- a query anywhere in the
interval that finds no change AT or AFTER `interval_start` still
returns whatever vintage was CARRIED IN from before it (`latest_
available_as_of`/`observation_as_known_at`'s own semantics), so an
interval with zero in-interval changes is not vacuously safe: if the
observation that actually governs the whole interval is provisional,
the interval is unsafe even though nothing "inside" it looks wrong.
`select_research_candidates` derives BOTH the carry-in state and the
in-interval observations from a series' COMPLETE stored history, so a
caller cannot get this wrong by hand-selecting the wrong candidate
set -- and an interval with no baseline and no in-interval data at all
(an empty candidate set) fails closed rather than silently passing.
"""

from collections.abc import Sequence

from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.timestamps import UtcTimestamp


class ResearchIntervalNotReadyError(ValueError):
    """Raised by `require_research_ready_interval` when the interval
    cannot be certified research-ready -- either because at least one
    candidate vintage is neither verified nor a conservative-safe
    bound, or because there was no candidate at all (see `no_baseline`).

    Carries every offending vintage (`provisional_vintages`), not just
    the first, so a caller can report the whole set of what still
    blocks research readiness in one pass rather than discovering them
    one fail-rerun-fail cycle at a time.
    """

    def __init__(
        self,
        provisional_vintages: Sequence[MacroObservationVintage],
        *,
        no_baseline: bool = False,
    ) -> None:
        self.provisional_vintages = tuple(provisional_vintages)
        self.no_baseline = no_baseline
        if no_baseline:
            message = (
                "no carry-in state and no in-interval observation exists for this "
                "series at all -- an interval with zero evidence is not vacuously "
                "research-ready; refusing to proceed"
            )
        else:
            offending = ", ".join(
                f"{v.series_key}@{v.observation_period.value.isoformat()}"
                f"(rev={v.revision_sequence})"
                for v in self.provisional_vintages
            )
            message = (
                f"{len(self.provisional_vintages)} vintage(s) relevant to the selected "
                f"research interval (carry-in state and/or in-interval observations) "
                f"are still provisional (neither released_at_is_verified nor "
                f"released_at_is_conservative_bound) -- refusing to treat this interval "
                f"as research-ready: {offending}"
            )
        super().__init__(message)


def is_research_safe(vintage: MacroObservationVintage) -> bool:
    """Whether one vintage's `released_at` is safe to filter a
    point-in-time query on: either a genuinely verified timestamp, or a
    deliberately conservative bound guaranteed no earlier than the true
    release (FX-44 section 3) -- never a plain, unverified proxy."""
    return vintage.released_at_is_verified or vintage.released_at_is_conservative_bound


def _latest_state_before_or_at(
    full_series_history: Sequence[MacroObservationVintage], as_of: UtcTimestamp
) -> MacroObservationVintage | None:
    """The vintage that "sets the state" in force at `as_of`: the
    latest `observation_period` at or before `as_of`, tie-broken by
    `revision_sequence` descending -- the same tie-break convention
    FX-41H established for the repository's own point-in-time query
    methods. `None` if the series has no history at or before `as_of`
    at all (the series simply didn't exist yet)."""
    candidates = [v for v in full_series_history if v.observation_period.value <= as_of.value]
    if not candidates:
        return None
    return max(candidates, key=lambda v: (v.observation_period.value, v.revision_sequence))


def select_research_candidates(
    full_series_history: Sequence[MacroObservationVintage],
    interval_start: UtcTimestamp,
    interval_end: UtcTimestamp,
) -> tuple[MacroObservationVintage, ...]:
    """Derives the exact set of vintages research readiness must judge
    for `[interval_start, interval_end)`, from a series' COMPLETE
    stored history (FX-44H) -- e.g. `MacroObservationRepository.
    list_all_for_series`'s return value, unfiltered.

    Two groups, unioned:
      - the CARRY-IN state: the single vintage that governs the
        instant `interval_start` itself (see `_latest_state_before_or_
        at`) -- even if it lies chronologically before the interval,
        because it is exactly what a point-in-time query at `interval_
        start` (and every instant after it, until the next in-interval
        change) would actually return.
      - every vintage whose `observation_period` falls inside `[
        interval_start, interval_end)`.

    Prefer this over hand-selecting a candidate list: the caller does
    not have to know in advance whether a change happened inside the
    interval, or reason about which prior vintage would be carried in
    -- passing the full history is enough.
    """
    carry_in = _latest_state_before_or_at(full_series_history, interval_start)
    in_interval = [
        v
        for v in full_series_history
        if interval_start.value <= v.observation_period.value < interval_end.value
    ]
    candidates = list(in_interval)
    if carry_in is not None and carry_in not in candidates:
        candidates.append(carry_in)
    return tuple(candidates)


def require_research_ready_interval(
    full_series_history: Sequence[MacroObservationVintage],
    interval_start: UtcTimestamp,
    interval_end: UtcTimestamp,
) -> None:
    """Fail closed (FX-44 section 8, hardened FX-44H): raise
    `ResearchIntervalNotReadyError` unless EVERY vintage `select_
    research_candidates` derives for `[interval_start, interval_end)`
    -- carry-in state included -- is `is_research_safe`, AND at least
    one candidate exists at all.

    `full_series_history` must be the series' COMPLETE stored history,
    not a pre-filtered subset -- this function derives the relevant
    candidate set itself (`select_research_candidates`) rather than
    trusting a caller to have already hand-selected the right rows;
    handing it an already-interval-filtered list would silently drop
    the carry-in state and defeat the whole point of this hardening.

    A single unsafe (or entirely missing) candidate fails the whole
    call -- there is no partial-pass, no percentage threshold, and no
    way to silently proceed with an interval that is mostly, but not
    entirely, research-safe, or with an interval this series has no
    evidence about at all.
    """
    candidates = select_research_candidates(full_series_history, interval_start, interval_end)
    if not candidates:
        raise ResearchIntervalNotReadyError((), no_baseline=True)
    offenders = [vintage for vintage in candidates if not is_research_safe(vintage)]
    if offenders:
        raise ResearchIntervalNotReadyError(offenders)

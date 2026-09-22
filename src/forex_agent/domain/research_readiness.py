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
"""

from collections.abc import Sequence

from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.timestamps import UtcTimestamp


class ResearchIntervalNotReadyError(ValueError):
    """Raised by `require_research_ready_interval` when at least one
    vintage in the selected interval is neither verified nor a
    conservative-safe bound -- i.e. still fully provisional.

    Carries every offending vintage (`provisional_vintages`), not just
    the first, so a caller can report the whole set of what still
    blocks research readiness in one pass rather than discovering them
    one fail-rerun-fail cycle at a time.
    """

    def __init__(self, provisional_vintages: Sequence[MacroObservationVintage]) -> None:
        self.provisional_vintages = tuple(provisional_vintages)
        offending = ", ".join(
            f"{v.series_key}@{v.observation_period.value.isoformat()}(rev={v.revision_sequence})"
            for v in self.provisional_vintages
        )
        super().__init__(
            f"{len(self.provisional_vintages)} vintage(s) in the selected research "
            f"interval are still provisional (neither released_at_is_verified nor "
            f"released_at_is_conservative_bound) -- refusing to treat this interval as "
            f"research-ready: {offending}"
        )


def is_research_safe(vintage: MacroObservationVintage) -> bool:
    """Whether one vintage's `released_at` is safe to filter a
    point-in-time query on: either a genuinely verified timestamp, or a
    deliberately conservative bound guaranteed no earlier than the true
    release (FX-44 section 3) -- never a plain, unverified proxy."""
    return vintage.released_at_is_verified or vintage.released_at_is_conservative_bound


def require_research_ready_interval(
    vintages: Sequence[MacroObservationVintage],
    interval_start: UtcTimestamp,
    interval_end: UtcTimestamp,
) -> None:
    """Fail closed (FX-44 section 8): raise `ResearchIntervalNotReadyError`
    if ANY vintage whose `observation_period` falls within `[interval_
    start, interval_end)` is not `is_research_safe`.

    `vintages` is the caller's own already-fetched candidate set for
    the interval -- this function does not reach into a repository
    itself, so it has no opinion on how completely that set was
    fetched; it only judges the timing safety of what it is given. A
    single unsafe vintage anywhere in the interval fails the whole
    call -- there is no partial-pass, no percentage threshold, and no
    way to silently proceed with an interval that is mostly, but not
    entirely, research-safe.
    """
    offenders = [
        vintage
        for vintage in vintages
        if interval_start.value <= vintage.observation_period.value < interval_end.value
        and not is_research_safe(vintage)
    ]
    if offenders:
        raise ResearchIntervalNotReadyError(offenders)

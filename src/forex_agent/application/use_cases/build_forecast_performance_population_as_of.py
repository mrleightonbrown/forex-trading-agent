"""FX-66 Section 6/7: `BuildForecastPerformancePopulationAsOf` --
constructs the EXACT, PIT-eligible evaluation population for ONE
pinned cohort, as of ONE explicit knowledge cutoff. Every candidate is
either ACCEPTED (with its exact forecast/outcome vintage references
resolved and attached) or EXCLUDED (with a named, audited reason,
Section 6's own "an excluded evaluation must remain visible in the
audit trail" rule) -- never silently dropped.

**Discovery (unbounded by PIT) + an explicit, caller-applied PIT
filter**: candidates are fetched via `ForecastEvaluationRepository.
list_latest_evaluations_for_protocol`, which is deliberately UNBOUNDED
by `as_of` -- mirroring `latest_outcome_vintage`'s own "administrative,
unbounded; the caller applies its own PIT check" convention. This is
WHY a too-new evaluation can be classified `NOT_YET_AVAILABLE` in the
audit trail here, rather than silently never being seen at all (which
is what using one of the repository's OWN already-PIT-bounded methods
would have produced).

**Structural compatibility checks, in order**: protocol version,
known-duplicate list, target, forecast type, originator, issue
window. `horizon_category` is NOT checked against forecast data --
see `ForecastPerformanceExclusionReason.INCOMPATIBLE_HORIZON`'s own
docstring for why that is currently structurally unreachable (no
FX-64 field exists to compare it against), a limitation surfaced
honestly rather than approximated.

**Duplicate/overlap resolution (Section 7) runs LAST**, over
candidates that already passed every structural check, grouped by
their own SHARED `outcome_key` (FX-65H.2's own durable target-event
identity) -- the originator is already fixed cohort-wide by
construction, so no separate originator grouping key is needed. Only
the cohort's own `duplicate_selection_policy` decides which ONE
member of a group survives; every other member of that group is
excluded as `SUPERSEDED_BY_EARLIER_QUALIFYING_ISSUE`, NEVER chosen by
realized error (Section 7's own explicit prohibition)."""

from dataclasses import dataclass

from forex_agent.application.ports.forecast_evaluation_repository import (
    ForecastEvaluationRepository,
)
from forex_agent.application.ports.forecast_outcome_repository import ForecastOutcomeRepository
from forex_agent.application.ports.structured_forecast_repository import (
    StructuredForecastRepository,
)
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.forecast_performance_cohort_definition import (
    ForecastPerformanceCohortDefinition,
)
from forex_agent.domain.forecast_performance_exclusion_reason import (
    ForecastPerformanceExclusionReason,
)
from forex_agent.domain.structured_forecast_evaluation_vintage import (
    StructuredForecastEvaluationVintage,
)
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp


class MissingForecastVintageError(Exception):
    """An evaluation pins a `(forecast_claim_key, forecast_revision_
    sequence)` that does not exist -- a data-integrity defect, never a
    normal exclusion (an evaluation can only ever be recorded against
    a forecast vintage that DID exist at evaluation time, so this
    should never actually be raised by correct upstream data)."""

    def __init__(self, evaluation_key: str, claim_key: str, revision_sequence: int) -> None:
        self.evaluation_key = evaluation_key
        self.claim_key = claim_key
        self.revision_sequence = revision_sequence
        super().__init__(
            f"evaluation_key={evaluation_key!r} pins forecast ({claim_key!r}, revision_sequence="
            f"{revision_sequence}), which does not exist"
        )


class MissingOutcomeVintageError(Exception):
    """Mirrors `MissingForecastVintageError`, for the outcome side."""

    def __init__(self, evaluation_key: str, outcome_key: str, revision_sequence: int) -> None:
        self.evaluation_key = evaluation_key
        self.outcome_key = outcome_key
        self.revision_sequence = revision_sequence
        super().__init__(
            f"evaluation_key={evaluation_key!r} pins outcome ({outcome_key!r}, revision_sequence="
            f"{revision_sequence}), which does not exist"
        )


@dataclass(frozen=True, slots=True)
class ForecastPerformancePopulationMember:
    evaluation: StructuredForecastEvaluationVintage
    forecast_vintage: StructuredForecastVintage
    outcome_vintage: ForecastOutcomeVintage


@dataclass(frozen=True, slots=True)
class ForecastPerformancePopulation:
    cohort: ForecastPerformanceCohortDefinition
    knowledge_cutoff: UtcTimestamp
    raw_candidate_count: int
    accepted: tuple[ForecastPerformancePopulationMember, ...]
    exclusions: tuple[tuple[str, ForecastPerformanceExclusionReason], ...]
    """`(evaluation_key, reason)` pairs, in no particular order."""


def _issue_instant(forecast_vintage: StructuredForecastVintage) -> UtcTimestamp:
    """Section 4's own "forecast issue date" dimension: the TRUE
    original-publication instant when known, falling back to FTA's
    own acquisition instant (`availability`) only when the forecast
    carries no `original_publication_at` -- never the reverse."""
    return forecast_vintage.original_publication_at or forecast_vintage.availability


def _originator_matches(
    forecast_vintage: StructuredForecastVintage, cohort: ForecastPerformanceCohortDefinition
) -> bool:
    attribution = forecast_vintage.attribution
    if attribution.kind is not cohort.attribution_kind:
        return False
    if attribution.publisher_source_key != cohort.originator_publisher_source_key:
        return False
    if cohort.attribution_kind is ForecastAttributionKind.NAMED_INSTITUTION:
        return attribution.forecaster_source_key == cohort.originator_forecaster_source_key
    return True


class BuildForecastPerformancePopulationAsOf:
    def __init__(
        self,
        evaluation_repository: ForecastEvaluationRepository,
        forecast_repository: StructuredForecastRepository,
        outcome_repository: ForecastOutcomeRepository,
    ) -> None:
        self._evaluation_repository = evaluation_repository
        self._forecast_repository = forecast_repository
        self._outcome_repository = outcome_repository

    async def __call__(
        self, cohort: ForecastPerformanceCohortDefinition, as_of: UtcTimestamp
    ) -> ForecastPerformancePopulation:
        candidates = await self._evaluation_repository.list_latest_evaluations_for_protocol(
            cohort.protocol_key, cohort.evaluation_mode
        )
        raw_candidate_count = len(candidates)
        exclusions: list[tuple[str, ForecastPerformanceExclusionReason]] = []
        structurally_eligible: list[ForecastPerformancePopulationMember] = []

        for evaluation in candidates:
            reason, forecast_vintage = await self._classify(evaluation, cohort, as_of)
            if reason is not None:
                exclusions.append((evaluation.evaluation_key, reason))
                continue
            assert forecast_vintage is not None
            outcome_vintage = await self._resolve_outcome_vintage(evaluation)
            structurally_eligible.append(
                ForecastPerformancePopulationMember(evaluation, forecast_vintage, outcome_vintage)
            )

        accepted, superseded = _resolve_duplicates(structurally_eligible)
        for evaluation_key in superseded:
            exclusions.append(
                (
                    evaluation_key,
                    ForecastPerformanceExclusionReason.SUPERSEDED_BY_EARLIER_QUALIFYING_ISSUE,
                )
            )

        return ForecastPerformancePopulation(
            cohort=cohort,
            knowledge_cutoff=as_of,
            raw_candidate_count=raw_candidate_count,
            accepted=tuple(accepted),
            exclusions=tuple(exclusions),
        )

    async def _classify(
        self,
        evaluation: StructuredForecastEvaluationVintage,
        cohort: ForecastPerformanceCohortDefinition,
        as_of: UtcTimestamp,
    ) -> tuple[ForecastPerformanceExclusionReason | None, StructuredForecastVintage | None]:
        """Returns `(None, forecast_vintage)` when the candidate
        passes every structural check (the resolved forecast vintage
        is returned too, so the caller never re-fetches it), or
        `(reason, None)` on the FIRST failing check."""
        if evaluation.availability.value > as_of.value:
            return ForecastPerformanceExclusionReason.NOT_YET_AVAILABLE, None
        if evaluation.protocol_version_sequence != cohort.protocol_version_sequence:
            return ForecastPerformanceExclusionReason.INCOMPATIBLE_PROTOCOL, None
        if evaluation.evaluation_key in cohort.known_duplicate_evaluation_keys:
            return ForecastPerformanceExclusionReason.KNOWN_DUPLICATE_SYNDICATED, None

        forecast_vintage = await self._resolve_forecast_vintage(evaluation)
        if forecast_vintage.target_key != cohort.target_key:
            return ForecastPerformanceExclusionReason.INCOMPATIBLE_TARGET, None
        if forecast_vintage.forecast_type is not cohort.forecast_type:
            return ForecastPerformanceExclusionReason.INCOMPATIBLE_FORECAST_TYPE, None
        if not _originator_matches(forecast_vintage, cohort):
            return ForecastPerformanceExclusionReason.INCOMPATIBLE_ORIGINATOR, None
        issue_instant = _issue_instant(forecast_vintage)
        if (
            cohort.issue_window_start is not None
            and issue_instant.value < cohort.issue_window_start.value
        ) or (
            cohort.issue_window_end is not None
            and issue_instant.value > cohort.issue_window_end.value
        ):
            return ForecastPerformanceExclusionReason.OUTSIDE_ISSUE_WINDOW, None
        return None, forecast_vintage

    async def _resolve_forecast_vintage(
        self, evaluation: StructuredForecastEvaluationVintage
    ) -> StructuredForecastVintage:
        history = await self._forecast_repository.list_vintages_for_claim(
            evaluation.forecast_claim_key
        )
        match = next(
            (v for v in history if v.revision_sequence == evaluation.forecast_revision_sequence),
            None,
        )
        if match is None:
            raise MissingForecastVintageError(
                evaluation.evaluation_key,
                evaluation.forecast_claim_key,
                evaluation.forecast_revision_sequence,
            )
        return match

    async def _resolve_outcome_vintage(
        self, evaluation: StructuredForecastEvaluationVintage
    ) -> ForecastOutcomeVintage:
        history = await self._outcome_repository.list_vintages_for_outcome(evaluation.outcome_key)
        match = next(
            (v for v in history if v.revision_sequence == evaluation.outcome_revision_sequence),
            None,
        )
        if match is None:
            raise MissingOutcomeVintageError(
                evaluation.evaluation_key,
                evaluation.outcome_key,
                evaluation.outcome_revision_sequence,
            )
        return match


def _resolve_duplicates(
    members: list[ForecastPerformancePopulationMember],
) -> tuple[list[ForecastPerformancePopulationMember], list[str]]:
    """FX-66 Section 7: `EARLIEST_QUALIFYING_ISSUE` -- within each
    group sharing the SAME `outcome_key`, keep only the member whose
    own forecast vintage reports the earliest issue instant; every
    other member of that group is superseded."""
    groups: dict[str, list[ForecastPerformancePopulationMember]] = {}
    for member in members:
        groups.setdefault(member.evaluation.outcome_key, []).append(member)

    accepted: list[ForecastPerformancePopulationMember] = []
    superseded: list[str] = []
    for group in groups.values():
        if len(group) == 1:
            accepted.append(group[0])
            continue
        winner = min(group, key=lambda m: _issue_instant(m.forecast_vintage).value)
        accepted.append(winner)
        superseded.extend(m.evaluation.evaluation_key for m in group if m is not winner)
    return accepted, superseded

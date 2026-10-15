"""FX-66 Section 15/16: `RecordForecastPerformanceSnapshot` -- append-
only persistence of ONE performance calculation, mirroring `Evaluate
StructuredForecast`'s own basis/payload-split historical-determinism
pattern exactly. The determinism BASIS is `(cohort_key, cohort_
version_sequence, methodology_key, methodology_version_sequence,
evaluation_mode, knowledge_cutoff, algorithm_version)` -- because ANY
genuine change (a new methodology version, a different knowledge
cutoff) changes this basis, a basis match implies the SAME inputs
were supplied twice, so the determinism check guards only against a
non-deterministic bug in the calculation itself, never against a
legitimate data change (Section 16's own "if any material input or
derived property changes, it must not silently return UNCHANGED" --
satisfied here because the COMPLETE payload below, not merely a
headline metric, is what gets compared).

The PAYLOAD is the snapshot's own complete evidence basis: exact
member references, exact exclusions with reasons, whichever summary
shape applies, the benchmark comparison, and full sample diagnostics.

**Precedence**: PIT ordering against this snapshot's OWN history
(`availability`, the THIRD distinct timeline) is checked BEFORE
determinism, mirroring every other append-only use case in this
codebase.

**`revision_sequence` is determined HERE, not by the caller**: the
caller supplies a "candidate" snapshot (any placeholder `revision_
sequence`, conventionally `0`); this use case replaces it with the
correct next value via `dataclasses.replace` before comparing or
persisting -- mirroring every other append-only use case's own "the
use case decides the real revision number" convention, adapted for a
type with too many fields to pass as loose constructor arguments.

**FX-66H (H3) addition -- snapshot temporal integrity.** A caller-
supplied `candidate` is no longer trusted merely because its OWN
fields are structurally valid: `population`, `methodology`, and
(when pinned) `benchmark` -- the SAME authoritative objects the
caller must have genuinely obtained via `BuildForecastPerformance
PopulationAsOf`/`latest_methodology_version`/`latest_benchmark_
version` -- are now REQUIRED parameters, and this use case computes
the minimum `availability` every one of their own `availability`/
review timestamps implies, rejecting `candidate.availability` values
earlier than that minimum BEFORE any repository access (so a
rejected attempt makes no database changes). This mirrors FX-65H's
own "remove the trust boundary, don't verify around it" lesson:
rather than trusting a caller-supplied `availability` and hoping it
is late enough, the use case recomputes the REQUIRED bound itself
from the authoritative evidence the caller must already hold.

**FX-66H.1 (H2/F66-05) addition -- bind the candidate's own payload
to the authoritative population.** FX-66H's own H3 fix validated
candidate.availability against authoritative evidence, but still
trusted `candidate.members`/`exclusions`/`diagnostics`/`numeric_
summary`/`categorical_summary`/`benchmark_comparison`/`evaluation_
mode`/`knowledge_cutoff` merely because they were structurally valid
and referenced the right cohort/methodology/benchmark IDENTITY --
nothing confirmed the candidate's own CONTENT actually matches what
the authoritative `population` produces. This is fixed by
RECONSTRUCTING every one of those fields from `population` (and, when
pinned, `benchmark`/`benchmark_population`) via the SAME existing
`AssessForecastPerformanceEvidence`/`CalculateForecastPerformance`
services every legitimate caller already uses -- never a second,
duplicate metric-calculation path -- and rejecting the candidate if
ANY field differs from what was independently derived. This also
transitively fixes a latent inconsistency risk: `diagnostics.
benchmark_paired_count` is now always derived from the SAME `benchmark_
comparison.paired_count` this reconstruction computes, so the two can
never silently diverge. Checked BEFORE the temporal-integrity check
and BEFORE any repository access, so a rejected attempt still makes
no database changes."""

from dataclasses import dataclass, replace
from enum import Enum

from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceRepository,
)
from forex_agent.application.use_cases.assess_forecast_performance_evidence import (
    AssessForecastPerformanceEvidence,
)
from forex_agent.application.use_cases.build_forecast_performance_population_as_of import (
    ForecastPerformancePopulation,
)
from forex_agent.application.use_cases.calculate_forecast_performance import (
    CalculateForecastPerformance,
)
from forex_agent.domain.forecast_performance_benchmark_comparison import (
    ForecastPerformanceBenchmarkComparison,
)
from forex_agent.domain.forecast_performance_benchmark_comparison_status import (
    ForecastPerformanceBenchmarkComparisonStatus,
)
from forex_agent.domain.forecast_performance_benchmark_definition import (
    ForecastPerformanceBenchmarkDefinition,
)
from forex_agent.domain.forecast_performance_categorical_summary import (
    ForecastPerformanceCategoricalSummary,
)
from forex_agent.domain.forecast_performance_methodology import ForecastPerformanceMethodology
from forex_agent.domain.forecast_performance_numeric_summary import (
    ForecastPerformanceNumericSummary,
)
from forex_agent.domain.forecast_performance_sample_diagnostics import (
    ForecastPerformanceSampleDiagnostics,
)
from forex_agent.domain.forecast_performance_snapshot import (
    ForecastPerformanceSnapshot,
    ForecastPerformanceSnapshotMember,
)
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.timestamps import UtcTimestamp

_Basis = tuple[str, int, str, int, ForecastProvenanceMode, object, str]
_Payload = tuple[
    tuple[ForecastPerformanceSnapshotMember, ...],
    tuple[tuple[str, object], ...],
    ForecastPerformanceNumericSummary | None,
    ForecastPerformanceCategoricalSummary | None,
    ForecastPerformanceBenchmarkComparison,
    ForecastPerformanceSampleDiagnostics,
]


def _basis_of(s: ForecastPerformanceSnapshot) -> _Basis:
    return (
        s.cohort_key,
        s.cohort_version_sequence,
        s.methodology_key,
        s.methodology_version_sequence,
        s.evaluation_mode,
        s.knowledge_cutoff.value,
        s.algorithm_version,
    )


def _payload_of(s: ForecastPerformanceSnapshot) -> _Payload:
    return (
        s.members,
        s.exclusions,
        s.numeric_summary,
        s.categorical_summary,
        s.benchmark_comparison,
        s.diagnostics,
    )


class ForecastPerformanceSnapshotOutcome(Enum):
    CREATED = "CREATED"
    REVISION_ADDED = "REVISION_ADDED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True, slots=True)
class ForecastPerformanceSnapshotRecordResult:
    snapshot_key: str
    outcome: ForecastPerformanceSnapshotOutcome
    snapshot: ForecastPerformanceSnapshot


class OutOfOrderForecastPerformanceSnapshotError(Exception):
    def __init__(
        self,
        snapshot_key: str,
        latest_availability: UtcTimestamp,
        incoming_availability: UtcTimestamp,
    ) -> None:
        self.snapshot_key = snapshot_key
        self.latest_availability = latest_availability
        self.incoming_availability = incoming_availability
        super().__init__(
            f"snapshot for snapshot_key={snapshot_key!r} claims availability="
            f"{incoming_availability.value.isoformat()}, earlier than the latest recorded "
            f"vintage's own availability={latest_availability.value.isoformat()} -- refusing "
            "to append a backdated assertion"
        )


class ForecastPerformanceSnapshotDeterminismError(Exception):
    def __init__(
        self,
        snapshot_key: str,
        basis: _Basis,
        existing_payload: _Payload,
        incoming_payload: _Payload,
    ) -> None:
        self.snapshot_key = snapshot_key
        self.basis = basis
        self.existing_payload = existing_payload
        self.incoming_payload = incoming_payload
        super().__init__(
            f"snapshot_key={snapshot_key!r}, basis={basis!r} already produced a DIFFERENT "
            f"result: existing={existing_payload!r}, incoming={incoming_payload!r} -- the SAME "
            "complete basis must never produce two different results"
        )


class ForecastPerformanceSnapshotTemporalIntegrityError(Exception):
    """FX-66H (H3): `candidate.availability` is EARLIER than the
    minimum `availability` implied by the cohort/methodology/
    benchmark definitions and every accepted member's own forecast/
    outcome authentication-review evidence -- a snapshot can never
    claim to have been recorded before FTA actually knew everything
    it is built from. `required_minimum`/`what` identify exactly
    WHICH authoritative input forced that bound."""

    def __init__(
        self,
        snapshot_key: str,
        candidate_availability: UtcTimestamp,
        required_minimum: UtcTimestamp,
        what: str,
    ) -> None:
        self.snapshot_key = snapshot_key
        self.candidate_availability = candidate_availability
        self.required_minimum = required_minimum
        self.what = what
        super().__init__(
            f"snapshot_key={snapshot_key!r} claims availability="
            f"{candidate_availability.value.isoformat()}, earlier than {what}'s own "
            f"availability={required_minimum.value.isoformat()} -- a snapshot cannot be "
            "recorded before the evidence it is built from was actually known"
        )


class ForecastPerformanceSnapshotIdentityMismatchError(Exception):
    """FX-66H (H3): `candidate`'s own `cohort_key`/`methodology_key`/
    `benchmark_key` (via `benchmark_comparison`) does not match the
    authoritative `population`/`methodology`/`benchmark` objects
    actually supplied -- refuses to compute a temporal bound from
    evidence that does not even claim to belong to this snapshot."""

    def __init__(self, snapshot_key: str, field: str) -> None:
        self.snapshot_key = snapshot_key
        self.field = field
        super().__init__(
            f"snapshot_key={snapshot_key!r}: candidate's own {field} does not match the "
            "authoritative object supplied for it"
        )


class ForecastPerformanceSnapshotConsistencyError(Exception):
    """FX-66H.1 (H2/F66-05): `candidate`'s own claimed membership,
    exclusions, diagnostics, numeric/categorical summary, or benchmark
    comparison does not match what `AssessForecastPerformanceEvidence`/
    `CalculateForecastPerformance` independently derive from the SAME
    authoritative `population` -- a caller can no longer persist an
    arbitrary, self-assembled result merely because it references
    valid cohort/methodology/benchmark identifiers."""

    def __init__(self, snapshot_key: str, mismatched_fields: tuple[str, ...]) -> None:
        self.snapshot_key = snapshot_key
        self.mismatched_fields = mismatched_fields
        super().__init__(
            f"snapshot_key={snapshot_key!r}: candidate's own {', '.join(mismatched_fields)} "
            "do not match what is independently derived from the authoritative population"
        )


def _expected_members(
    population: ForecastPerformancePopulation,
) -> tuple[ForecastPerformanceSnapshotMember, ...]:
    return tuple(
        ForecastPerformanceSnapshotMember(
            evaluation_key=m.evaluation.evaluation_key,
            evaluation_revision_sequence=m.evaluation.revision_sequence,
            forecast_claim_key=m.evaluation.forecast_claim_key,
            forecast_revision_sequence=m.evaluation.forecast_revision_sequence,
            outcome_key=m.evaluation.outcome_key,
            outcome_revision_sequence=m.evaluation.outcome_revision_sequence,
        )
        for m in population.accepted
    )


def _required_minimum_availability(
    population: ForecastPerformancePopulation,
    methodology: ForecastPerformanceMethodology,
    benchmark: ForecastPerformanceBenchmarkDefinition | None,
) -> tuple[UtcTimestamp, str]:
    """Returns `(minimum, what)` -- the LATEST `availability` among
    every piece of authoritative evidence a snapshot is built from,
    and a human-readable label for whichever one is latest (purely
    for the error message; ties resolve to whichever is found first,
    which is immaterial since all that matters is the value)."""
    candidates: list[tuple[UtcTimestamp, str]] = [
        (population.cohort.availability, "the cohort definition"),
        (methodology.availability, "the methodology definition"),
        (population.knowledge_cutoff, "the requested knowledge cutoff"),
    ]
    if benchmark is not None:
        candidates.append((benchmark.availability, "the benchmark definition"))
    for member in population.accepted:
        candidates.append((member.evaluation.availability, "a selected evaluation vintage"))
        candidates.append(
            (
                member.evaluation.forecast_authentication_review.reviewed_at,
                "a forecast's own authentication review",
            )
        )
        candidates.append(
            (
                member.outcome_vintage.authentication_review.reviewed_at,
                "an outcome's own authentication review",
            )
        )
    return max(candidates, key=lambda pair: pair[0].value)


class RecordForecastPerformanceSnapshot:
    def __init__(self, repository: ForecastPerformanceRepository) -> None:
        self._repository = repository

    async def __call__(
        self,
        candidate: ForecastPerformanceSnapshot,
        *,
        population: ForecastPerformancePopulation,
        methodology: ForecastPerformanceMethodology,
        benchmark: ForecastPerformanceBenchmarkDefinition | None = None,
        benchmark_population: ForecastPerformancePopulation | None = None,
        dry_run: bool = False,
    ) -> ForecastPerformanceSnapshotRecordResult:
        if (
            candidate.cohort_key != population.cohort.cohort_key
            or candidate.cohort_version_sequence != population.cohort.version_sequence
        ):
            raise ForecastPerformanceSnapshotIdentityMismatchError(candidate.snapshot_key, "cohort")
        if (
            candidate.methodology_key != methodology.methodology_key
            or candidate.methodology_version_sequence != methodology.version_sequence
        ):
            raise ForecastPerformanceSnapshotIdentityMismatchError(
                candidate.snapshot_key, "methodology"
            )
        if (
            candidate.benchmark_comparison.status
            is ForecastPerformanceBenchmarkComparisonStatus.COMPARED
            and (
                benchmark is None
                or candidate.benchmark_comparison.benchmark_key != benchmark.benchmark_key
                or candidate.benchmark_comparison.benchmark_version_sequence
                != benchmark.version_sequence
            )
        ):
            raise ForecastPerformanceSnapshotIdentityMismatchError(
                candidate.snapshot_key, "benchmark"
            )
        if candidate.evaluation_mode is not population.cohort.evaluation_mode:
            raise ForecastPerformanceSnapshotIdentityMismatchError(
                candidate.snapshot_key, "evaluation_mode"
            )
        if candidate.knowledge_cutoff.value != population.knowledge_cutoff.value:
            raise ForecastPerformanceSnapshotIdentityMismatchError(
                candidate.snapshot_key, "knowledge_cutoff"
            )

        expected_numeric, expected_categorical, expected_comparison = (
            CalculateForecastPerformance()(
                population, benchmark=benchmark, benchmark_population=benchmark_population
            )
        )
        expected_diagnostics = AssessForecastPerformanceEvidence()(
            population, benchmark_paired_count=expected_comparison.paired_count
        )
        mismatched_fields = tuple(
            name
            for name, matches in (
                ("members", set(candidate.members) == set(_expected_members(population))),
                ("exclusions", set(candidate.exclusions) == set(population.exclusions)),
                ("diagnostics", candidate.diagnostics == expected_diagnostics),
                ("numeric_summary", candidate.numeric_summary == expected_numeric),
                ("categorical_summary", candidate.categorical_summary == expected_categorical),
                ("benchmark_comparison", candidate.benchmark_comparison == expected_comparison),
            )
            if not matches
        )
        if mismatched_fields:
            raise ForecastPerformanceSnapshotConsistencyError(
                candidate.snapshot_key, mismatched_fields
            )

        required_minimum, what = _required_minimum_availability(population, methodology, benchmark)
        if candidate.availability.value < required_minimum.value:
            raise ForecastPerformanceSnapshotTemporalIntegrityError(
                candidate.snapshot_key, candidate.availability, required_minimum, what
            )

        latest = await self._repository.latest_snapshot_vintage(candidate.snapshot_key)
        if latest is not None and candidate.availability.value < latest.availability.value:
            raise OutOfOrderForecastPerformanceSnapshotError(
                candidate.snapshot_key, latest.availability, candidate.availability
            )

        next_revision = 0 if latest is None else latest.revision_sequence + 1
        snapshot = replace(candidate, revision_sequence=next_revision)
        incoming_basis = _basis_of(snapshot)
        incoming_payload = _payload_of(snapshot)

        history = await self._repository.list_vintages_for_snapshot(snapshot.snapshot_key)
        for historical in history:
            if _basis_of(historical) != incoming_basis:
                continue
            if _payload_of(historical) != incoming_payload:
                raise ForecastPerformanceSnapshotDeterminismError(
                    snapshot.snapshot_key, incoming_basis, _payload_of(historical), incoming_payload
                )

        if (
            latest is not None
            and _basis_of(latest) == incoming_basis
            and _payload_of(latest) == incoming_payload
        ):
            return ForecastPerformanceSnapshotRecordResult(
                snapshot_key=snapshot.snapshot_key,
                outcome=ForecastPerformanceSnapshotOutcome.UNCHANGED,
                snapshot=latest,
            )

        outcome_label = (
            ForecastPerformanceSnapshotOutcome.CREATED
            if latest is None
            else ForecastPerformanceSnapshotOutcome.REVISION_ADDED
        )
        if dry_run:
            return ForecastPerformanceSnapshotRecordResult(
                snapshot_key=snapshot.snapshot_key, outcome=outcome_label, snapshot=snapshot
            )
        write_result = await self._repository.add_snapshot_vintage(snapshot)
        final_outcome = (
            outcome_label if write_result.inserted else ForecastPerformanceSnapshotOutcome.UNCHANGED
        )
        return ForecastPerformanceSnapshotRecordResult(
            snapshot_key=snapshot.snapshot_key, outcome=final_outcome, snapshot=snapshot
        )

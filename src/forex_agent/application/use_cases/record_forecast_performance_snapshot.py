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
type with too many fields to pass as loose constructor arguments."""

from dataclasses import dataclass, replace
from enum import Enum

from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceRepository,
)
from forex_agent.domain.forecast_performance_benchmark_comparison import (
    ForecastPerformanceBenchmarkComparison,
)
from forex_agent.domain.forecast_performance_categorical_summary import (
    ForecastPerformanceCategoricalSummary,
)
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


class RecordForecastPerformanceSnapshot:
    def __init__(self, repository: ForecastPerformanceRepository) -> None:
        self._repository = repository

    async def __call__(
        self, candidate: ForecastPerformanceSnapshot, *, dry_run: bool = False
    ) -> ForecastPerformanceSnapshotRecordResult:
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

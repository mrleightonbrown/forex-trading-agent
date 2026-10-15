"""FX-66 Section 4: append-only registration of ONE performance-cohort
version -- mirrors `RecordForecastOutcomeDefinition`'s own low-volume,
curated, strictly-sequential-`version_sequence` registration pattern
exactly (never PIT-ordered against `availability`, since a cohort's
own `version_sequence` IS its explicit, caller-declared sequencing).

The "is this an exact repeat" comparison deliberately excludes
`availability`, mirroring `RecordForecastOutcomeDefinition`'s own
documented reason: a re-run of an idempotent bootstrap script supplies
a fresh `now()` each time, which is not a substantive content change."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceRepository,
)
from forex_agent.domain.forecast_performance_cohort_definition import (
    ForecastPerformanceCohortDefinition,
)

_ContentKey = tuple[object, ...]


def _content_of(cohort: ForecastPerformanceCohortDefinition) -> _ContentKey:
    return (
        cohort.attribution_kind,
        cohort.originator_publisher_source_key,
        cohort.originator_forecaster_source_key,
        cohort.target_key,
        cohort.forecast_type,
        cohort.horizon_category,
        cohort.protocol_key,
        cohort.protocol_version_sequence,
        cohort.evaluation_mode,
        cohort.duplicate_selection_policy,
        cohort.issue_window_start,
        cohort.issue_window_end,
        cohort.known_duplicate_evaluation_keys,
        cohort.rationale,
    )


class ForecastPerformanceCohortOutcome(Enum):
    CREATED = "CREATED"
    REVISION_ADDED = "REVISION_ADDED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True, slots=True)
class ForecastPerformanceCohortRecordResult:
    cohort_key: str
    outcome: ForecastPerformanceCohortOutcome
    cohort: ForecastPerformanceCohortDefinition


class OutOfSequenceCohortError(Exception):
    def __init__(self, cohort_key: str, expected: int, got: int) -> None:
        self.cohort_key = cohort_key
        self.expected = expected
        self.got = got
        super().__init__(
            f"cohort_key={cohort_key!r} expected the next version_sequence={expected}, got "
            f"{got} -- versions must be registered strictly sequentially"
        )


class ForecastPerformanceCohortConflictError(Exception):
    def __init__(
        self,
        cohort_key: str,
        version_sequence: int,
        existing: ForecastPerformanceCohortDefinition,
        incoming: ForecastPerformanceCohortDefinition,
    ) -> None:
        self.cohort_key = cohort_key
        self.version_sequence = version_sequence
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            f"cohort_key={cohort_key!r}, version_sequence={version_sequence} already exists "
            f"with different content: existing={existing!r}, incoming={incoming!r}"
        )


class DefineForecastPerformanceCohort:
    def __init__(self, repository: ForecastPerformanceRepository) -> None:
        self._repository = repository

    async def __call__(
        self, cohort: ForecastPerformanceCohortDefinition, *, dry_run: bool = False
    ) -> ForecastPerformanceCohortRecordResult:
        existing_versions = await self._repository.list_cohort_versions(cohort.cohort_key)
        matching = next(
            (c for c in existing_versions if c.version_sequence == cohort.version_sequence), None
        )
        if matching is not None:
            if _content_of(matching) == _content_of(cohort):
                return ForecastPerformanceCohortRecordResult(
                    cohort_key=cohort.cohort_key,
                    outcome=ForecastPerformanceCohortOutcome.UNCHANGED,
                    cohort=matching,
                )
            raise ForecastPerformanceCohortConflictError(
                cohort.cohort_key, cohort.version_sequence, matching, cohort
            )

        expected_next = max((c.version_sequence for c in existing_versions), default=-1) + 1
        if cohort.version_sequence != expected_next:
            raise OutOfSequenceCohortError(
                cohort.cohort_key, expected_next, cohort.version_sequence
            )

        outcome = (
            ForecastPerformanceCohortOutcome.CREATED
            if cohort.version_sequence == 0
            else ForecastPerformanceCohortOutcome.REVISION_ADDED
        )
        if dry_run:
            return ForecastPerformanceCohortRecordResult(
                cohort_key=cohort.cohort_key, outcome=outcome, cohort=cohort
            )
        write_result = await self._repository.add_cohort_version(cohort)
        final_outcome = (
            outcome if write_result.inserted else ForecastPerformanceCohortOutcome.UNCHANGED
        )
        return ForecastPerformanceCohortRecordResult(
            cohort_key=cohort.cohort_key, outcome=final_outcome, cohort=cohort
        )

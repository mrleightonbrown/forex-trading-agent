"""FX-66 Section 14: append-only registration of ONE performance-
methodology version -- mirrors `DefineForecastPerformanceCohort`'s own
pattern exactly."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceRepository,
)
from forex_agent.domain.forecast_performance_methodology import ForecastPerformanceMethodology

_ContentKey = tuple[object, ...]


def _content_of(methodology: ForecastPerformanceMethodology) -> _ContentKey:
    return (
        methodology.cohort_key,
        methodology.cohort_version_sequence,
        methodology.missing_data_policy,
        methodology.algorithm_version,
        methodology.benchmark_key,
        methodology.benchmark_version_sequence,
        methodology.rationale,
    )


class ForecastPerformanceMethodologyOutcome(Enum):
    CREATED = "CREATED"
    REVISION_ADDED = "REVISION_ADDED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True, slots=True)
class ForecastPerformanceMethodologyRecordResult:
    methodology_key: str
    outcome: ForecastPerformanceMethodologyOutcome
    methodology: ForecastPerformanceMethodology


class OutOfSequenceMethodologyError(Exception):
    def __init__(self, methodology_key: str, expected: int, got: int) -> None:
        self.methodology_key = methodology_key
        self.expected = expected
        self.got = got
        super().__init__(
            f"methodology_key={methodology_key!r} expected the next version_sequence="
            f"{expected}, got {got} -- versions must be registered strictly sequentially"
        )


class ForecastPerformanceMethodologyConflictError(Exception):
    def __init__(
        self,
        methodology_key: str,
        version_sequence: int,
        existing: ForecastPerformanceMethodology,
        incoming: ForecastPerformanceMethodology,
    ) -> None:
        self.methodology_key = methodology_key
        self.version_sequence = version_sequence
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            f"methodology_key={methodology_key!r}, version_sequence={version_sequence} already "
            f"exists with different content: existing={existing!r}, incoming={incoming!r}"
        )


class DefineForecastPerformanceMethodology:
    def __init__(self, repository: ForecastPerformanceRepository) -> None:
        self._repository = repository

    async def __call__(
        self, methodology: ForecastPerformanceMethodology, *, dry_run: bool = False
    ) -> ForecastPerformanceMethodologyRecordResult:
        existing_versions = await self._repository.list_methodology_versions(
            methodology.methodology_key
        )
        matching = next(
            (m for m in existing_versions if m.version_sequence == methodology.version_sequence),
            None,
        )
        if matching is not None:
            if _content_of(matching) == _content_of(methodology):
                return ForecastPerformanceMethodologyRecordResult(
                    methodology_key=methodology.methodology_key,
                    outcome=ForecastPerformanceMethodologyOutcome.UNCHANGED,
                    methodology=matching,
                )
            raise ForecastPerformanceMethodologyConflictError(
                methodology.methodology_key, methodology.version_sequence, matching, methodology
            )

        expected_next = max((m.version_sequence for m in existing_versions), default=-1) + 1
        if methodology.version_sequence != expected_next:
            raise OutOfSequenceMethodologyError(
                methodology.methodology_key, expected_next, methodology.version_sequence
            )

        outcome = (
            ForecastPerformanceMethodologyOutcome.CREATED
            if methodology.version_sequence == 0
            else ForecastPerformanceMethodologyOutcome.REVISION_ADDED
        )
        if dry_run:
            return ForecastPerformanceMethodologyRecordResult(
                methodology_key=methodology.methodology_key,
                outcome=outcome,
                methodology=methodology,
            )
        write_result = await self._repository.add_methodology_version(methodology)
        final_outcome = (
            outcome if write_result.inserted else ForecastPerformanceMethodologyOutcome.UNCHANGED
        )
        return ForecastPerformanceMethodologyRecordResult(
            methodology_key=methodology.methodology_key,
            outcome=final_outcome,
            methodology=methodology,
        )

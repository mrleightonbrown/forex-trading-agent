"""FX-65 Section 7: append-only registration of ONE evaluation-
protocol version -- mirrors `RecordForecastOutcomeDefinition` exactly
(curated, administrative, strictly-sequential `version_sequence`,
never selected or revised merely to make a particular forecast look
accurate). The "is this an exact repeat" comparison excludes
`availability` for the same reason `RecordForecastOutcomeDefinition`'s
own does -- a fresh `now()` on an idempotent re-run is not a
substantive content change."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.forecast_evaluation_repository import (
    ForecastEvaluationRepository,
)
from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol

_ContentKey = tuple[object, str, str, int, object, int | None, object, str]


def _content_of(protocol: ForecastEvaluationProtocol) -> _ContentKey:
    return (
        protocol.supported_forecast_type,
        protocol.target_key,
        protocol.outcome_definition_key,
        protocol.outcome_definition_version_sequence,
        protocol.outcome_vintage_selection_policy,
        protocol.fixed_outcome_revision_sequence,
        protocol.metric,
        protocol.rationale,
    )


class ForecastEvaluationProtocolOutcome(Enum):
    CREATED = "CREATED"
    REVISION_ADDED = "REVISION_ADDED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True, slots=True)
class ForecastEvaluationProtocolRecordResult:
    protocol_key: str
    outcome: ForecastEvaluationProtocolOutcome
    protocol: ForecastEvaluationProtocol | None = None


class OutOfSequenceEvaluationProtocolError(Exception):
    def __init__(self, protocol_key: str, expected: int, got: int) -> None:
        self.protocol_key = protocol_key
        self.expected = expected
        self.got = got
        super().__init__(
            f"protocol_key={protocol_key!r} expected the next version_sequence={expected}, "
            f"got {got} -- versions must be registered strictly sequentially"
        )


class ForecastEvaluationProtocolConflictError(Exception):
    def __init__(
        self,
        protocol_key: str,
        version_sequence: int,
        existing: ForecastEvaluationProtocol,
        incoming: ForecastEvaluationProtocol,
    ) -> None:
        self.protocol_key = protocol_key
        self.version_sequence = version_sequence
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            f"protocol_key={protocol_key!r}, version_sequence={version_sequence} already "
            f"exists with different content: existing={existing!r}, incoming={incoming!r}"
        )


class RecordForecastEvaluationProtocol:
    def __init__(self, repository: ForecastEvaluationRepository) -> None:
        self._repository = repository

    async def __call__(
        self, protocol: ForecastEvaluationProtocol, *, dry_run: bool = False
    ) -> ForecastEvaluationProtocolRecordResult:
        existing_versions = await self._repository.list_protocol_versions(protocol.protocol_key)
        matching = next(
            (p for p in existing_versions if p.version_sequence == protocol.version_sequence),
            None,
        )
        if matching is not None:
            if _content_of(matching) == _content_of(protocol):
                return ForecastEvaluationProtocolRecordResult(
                    protocol_key=protocol.protocol_key,
                    outcome=ForecastEvaluationProtocolOutcome.UNCHANGED,
                    protocol=matching,
                )
            raise ForecastEvaluationProtocolConflictError(
                protocol.protocol_key, protocol.version_sequence, matching, protocol
            )

        expected_next = max((p.version_sequence for p in existing_versions), default=-1) + 1
        if protocol.version_sequence != expected_next:
            raise OutOfSequenceEvaluationProtocolError(
                protocol.protocol_key, expected_next, protocol.version_sequence
            )

        outcome = (
            ForecastEvaluationProtocolOutcome.CREATED
            if protocol.version_sequence == 0
            else ForecastEvaluationProtocolOutcome.REVISION_ADDED
        )
        if dry_run:
            return ForecastEvaluationProtocolRecordResult(
                protocol_key=protocol.protocol_key, outcome=outcome, protocol=protocol
            )
        write_result = await self._repository.add_protocol_version(protocol)
        final_outcome = (
            outcome if write_result.inserted else ForecastEvaluationProtocolOutcome.UNCHANGED
        )
        return ForecastEvaluationProtocolRecordResult(
            protocol_key=protocol.protocol_key, outcome=final_outcome, protocol=protocol
        )

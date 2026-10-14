"""FX-65 Section 4: append-only registration of ONE outcome-definition
version. Definitions are low-volume, curated, administrative
registrations (mirroring how this codebase's own small curated
registries -- `economic_indicator_registry`/`forecast_target_
registry` -- are admitted), so `version_sequence` is caller-supplied
and must be STRICTLY SEQUENTIAL (`0, 1, 2, ...`) for a given
`definition_key` -- never PIT-ordered against `availability` the way
a forecast/outcome vintage is, since a definition's own `version_
sequence` IS its explicit, caller-declared sequencing.

The "is this an exact repeat" comparison deliberately excludes
`availability` -- a re-run of an idempotent bootstrap/pilot script
naturally supplies a fresh `now()` on each run, and that is NOT a
substantive content change (unlike a forecast/outcome vintage, a
definition's own `availability` is not part of what later determinism
checks compare either). Comparing full dataclass equality here would
make every such re-run raise a spurious conflict instead of reporting
`UNCHANGED`."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.forecast_outcome_repository import ForecastOutcomeRepository
from forex_agent.domain.forecast_outcome_definition import ForecastOutcomeDefinition

_ContentKey = tuple[str, object, str, str, object, str]


def _content_of(definition: ForecastOutcomeDefinition) -> _ContentKey:
    return (
        definition.target_key,
        definition.outcome_type,
        definition.provider_source_key,
        definition.required_source_series_identifier,
        definition.outcome_vintage_selection_policy,
        definition.supporting_definition_reference,
    )


class ForecastOutcomeDefinitionOutcome(Enum):
    CREATED = "CREATED"
    REVISION_ADDED = "REVISION_ADDED"
    UNCHANGED = "UNCHANGED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ForecastOutcomeDefinitionRecordResult:
    definition_key: str
    outcome: ForecastOutcomeDefinitionOutcome
    reason: str | None = None
    definition: ForecastOutcomeDefinition | None = None


class OutOfSequenceOutcomeDefinitionError(Exception):
    def __init__(self, definition_key: str, expected: int, got: int) -> None:
        self.definition_key = definition_key
        self.expected = expected
        self.got = got
        super().__init__(
            f"definition_key={definition_key!r} expected the next version_sequence={expected}, "
            f"got {got} -- versions must be registered strictly sequentially"
        )


class ForecastOutcomeDefinitionConflictError(Exception):
    def __init__(
        self,
        definition_key: str,
        version_sequence: int,
        existing: ForecastOutcomeDefinition,
        incoming: ForecastOutcomeDefinition,
    ) -> None:
        self.definition_key = definition_key
        self.version_sequence = version_sequence
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            f"definition_key={definition_key!r}, version_sequence={version_sequence} already "
            f"exists with different content: existing={existing!r}, incoming={incoming!r}"
        )


class RecordForecastOutcomeDefinition:
    def __init__(self, repository: ForecastOutcomeRepository) -> None:
        self._repository = repository

    async def __call__(
        self, definition: ForecastOutcomeDefinition, *, dry_run: bool = False
    ) -> ForecastOutcomeDefinitionRecordResult:
        existing_versions = await self._repository.list_outcome_definition_versions(
            definition.definition_key
        )
        matching = next(
            (d for d in existing_versions if d.version_sequence == definition.version_sequence),
            None,
        )
        if matching is not None:
            if _content_of(matching) == _content_of(definition):
                return ForecastOutcomeDefinitionRecordResult(
                    definition_key=definition.definition_key,
                    outcome=ForecastOutcomeDefinitionOutcome.UNCHANGED,
                    definition=matching,
                )
            raise ForecastOutcomeDefinitionConflictError(
                definition.definition_key, definition.version_sequence, matching, definition
            )

        expected_next = max((d.version_sequence for d in existing_versions), default=-1) + 1
        if definition.version_sequence != expected_next:
            raise OutOfSequenceOutcomeDefinitionError(
                definition.definition_key, expected_next, definition.version_sequence
            )

        outcome = (
            ForecastOutcomeDefinitionOutcome.CREATED
            if definition.version_sequence == 0
            else ForecastOutcomeDefinitionOutcome.REVISION_ADDED
        )
        if dry_run:
            return ForecastOutcomeDefinitionRecordResult(
                definition_key=definition.definition_key, outcome=outcome, definition=definition
            )
        write_result = await self._repository.add_outcome_definition_version(definition)
        final_outcome = (
            outcome if write_result.inserted else ForecastOutcomeDefinitionOutcome.UNCHANGED
        )
        return ForecastOutcomeDefinitionRecordResult(
            definition_key=definition.definition_key, outcome=final_outcome, definition=definition
        )

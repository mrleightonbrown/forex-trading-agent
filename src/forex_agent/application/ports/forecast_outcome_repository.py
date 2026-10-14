"""FX-65: port for storing and reading FTA's own outcome definitions
and outcome observations -- two related but distinct append-only
concepts (HOW to measure an outcome, versus WHAT was actually
observed), mirroring FX-64's own cohesive-repository-per-concept
scale."""

from dataclasses import dataclass
from typing import Protocol

from forex_agent.domain.forecast_outcome_definition import ForecastOutcomeDefinition
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage


@dataclass(frozen=True, slots=True)
class ForecastOutcomeDefinitionWriteResult:
    inserted: bool


@dataclass(frozen=True, slots=True)
class ForecastOutcomeVintageWriteResult:
    inserted: bool


class ForecastOutcomeRepository(Protocol):
    async def latest_outcome_definition(
        self, definition_key: str
    ) -> ForecastOutcomeDefinition | None:
        """The highest `version_sequence` row for `definition_key`, or
        `None` if it has never been registered."""
        ...

    async def list_outcome_definition_versions(
        self, definition_key: str
    ) -> tuple[ForecastOutcomeDefinition, ...]:
        """Every stored version of this definition, in no particular
        guaranteed order -- used by the full-history determinism
        check."""
        ...

    async def add_outcome_definition_version(
        self, definition: ForecastOutcomeDefinition
    ) -> ForecastOutcomeDefinitionWriteResult:
        """Append-only insert keyed on `(definition_key, version_
        sequence)` -- `ON CONFLICT DO NOTHING` semantics."""
        ...

    async def latest_outcome_vintage(self, outcome_key: str) -> ForecastOutcomeVintage | None:
        """The outcome's own latest vintage by `(availability,
        revision_sequence)`, REGARDLESS of `provenance_mode` -- an
        administrative read used only by `RecordForecastOutcome`'s own
        PIT-ordering/idempotency checks."""
        ...

    async def list_vintages_for_outcome(
        self, outcome_key: str
    ) -> tuple[ForecastOutcomeVintage, ...]:
        """Every stored vintage of this outcome, in no particular
        guaranteed order -- used by the full-history determinism
        check and by `ResolveForecastOutcomeAsOf`."""
        ...

    async def list_outcome_vintages_for_definition(
        self, definition_key: str
    ) -> tuple[ForecastOutcomeVintage, ...]:
        """FX-65H.1: every stored vintage captured under `definition_
        key`, across EVERY `outcome_key` -- used ONLY by `RecordForecast
        Outcome`'s own outcome-identity-binding check (Section 2): no
        two DIFFERENT `outcome_key`s may share the same `(definition_
        key, target_period, unit)` identity, since that would let an
        evaluation caller silently substitute one for the other."""
        ...

    async def add_outcome_vintage(
        self, vintage: ForecastOutcomeVintage
    ) -> ForecastOutcomeVintageWriteResult:
        """Append-only insert keyed on `(outcome_key, revision_
        sequence)` -- `ON CONFLICT DO NOTHING` semantics."""
        ...

"""FX-65: an in-memory fake implementing `ForecastOutcomeRepository`,
mirroring the real `SqlAlchemyForecastOutcomeRepository`'s own exact
latest-by-(availability, revision_sequence) selection and idempotent-
write semantics."""

from forex_agent.application.ports.forecast_outcome_repository import (
    ForecastOutcomeDefinitionWriteResult,
    ForecastOutcomeVintageWriteResult,
    OutcomeIdentityClaimResult,
)
from forex_agent.domain.forecast_outcome_definition import ForecastOutcomeDefinition
from forex_agent.domain.forecast_outcome_identity import ForecastOutcomeIdentityBinding
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.forecast_type import ForecastType


def _sort_key(vintage: ForecastOutcomeVintage) -> tuple[object, int]:
    return (vintage.availability.value, vintage.revision_sequence)


class FakeForecastOutcomeRepository:
    def __init__(self) -> None:
        self.definitions: dict[str, list[ForecastOutcomeDefinition]] = {}
        self.vintages: dict[str, list[ForecastOutcomeVintage]] = {}
        self.identity_bindings: dict[str, ForecastOutcomeIdentityBinding] = {}

    async def latest_outcome_definition(
        self, definition_key: str
    ) -> ForecastOutcomeDefinition | None:
        versions = self.definitions.get(definition_key, [])
        if not versions:
            return None
        return max(versions, key=lambda d: d.version_sequence)

    async def list_outcome_definition_versions(
        self, definition_key: str
    ) -> tuple[ForecastOutcomeDefinition, ...]:
        return tuple(self.definitions.get(definition_key, ()))

    async def add_outcome_definition_version(
        self, definition: ForecastOutcomeDefinition
    ) -> ForecastOutcomeDefinitionWriteResult:
        existing = self.definitions.setdefault(definition.definition_key, [])
        if any(d.version_sequence == definition.version_sequence for d in existing):
            return ForecastOutcomeDefinitionWriteResult(inserted=False)
        existing.append(definition)
        return ForecastOutcomeDefinitionWriteResult(inserted=True)

    async def latest_outcome_vintage(self, outcome_key: str) -> ForecastOutcomeVintage | None:
        vintages = self.vintages.get(outcome_key, ())
        if not vintages:
            return None
        return max(vintages, key=_sort_key)

    async def list_vintages_for_outcome(
        self, outcome_key: str
    ) -> tuple[ForecastOutcomeVintage, ...]:
        return tuple(self.vintages.get(outcome_key, ()))

    async def claim_outcome_identity_and_add_first_vintage(
        self, binding: ForecastOutcomeIdentityBinding, first_vintage: ForecastOutcomeVintage
    ) -> OutcomeIdentityClaimResult:
        if binding.outcome_key in self.identity_bindings:
            return OutcomeIdentityClaimResult(claimed=False)
        if any(other.shares_identity_with(binding) for other in self.identity_bindings.values()):
            return OutcomeIdentityClaimResult(claimed=False)
        self.identity_bindings[binding.outcome_key] = binding
        self.vintages.setdefault(first_vintage.outcome_key, []).append(first_vintage)
        return OutcomeIdentityClaimResult(claimed=True)

    async def get_identity_binding_for_key(
        self, outcome_key: str
    ) -> ForecastOutcomeIdentityBinding | None:
        return self.identity_bindings.get(outcome_key)

    async def get_identity_binding_for_identity(
        self, definition_key: str, target_period_key: str, outcome_type: ForecastType, unit: str
    ) -> ForecastOutcomeIdentityBinding | None:
        probe = ForecastOutcomeIdentityBinding(
            definition_key=definition_key,
            target_period_key=target_period_key,
            outcome_type=outcome_type,
            unit=unit,
            outcome_key="__probe__",
        )
        for other in self.identity_bindings.values():
            if other.shares_identity_with(probe):
                return other
        return None

    async def add_outcome_vintage(
        self, vintage: ForecastOutcomeVintage
    ) -> ForecastOutcomeVintageWriteResult:
        existing = self.vintages.setdefault(vintage.outcome_key, [])
        if any(v.revision_sequence == vintage.revision_sequence for v in existing):
            return ForecastOutcomeVintageWriteResult(inserted=False)
        existing.append(vintage)
        return ForecastOutcomeVintageWriteResult(inserted=True)

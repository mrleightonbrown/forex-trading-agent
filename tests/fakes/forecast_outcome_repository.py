"""FX-65: an in-memory fake implementing `ForecastOutcomeRepository`,
mirroring the real `SqlAlchemyForecastOutcomeRepository`'s own exact
latest-by-(availability, revision_sequence) selection and idempotent-
write semantics."""

from forex_agent.application.ports.forecast_outcome_repository import (
    ForecastOutcomeDefinitionWriteResult,
    ForecastOutcomeVintageWriteResult,
)
from forex_agent.domain.forecast_outcome_definition import ForecastOutcomeDefinition
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage


def _sort_key(vintage: ForecastOutcomeVintage) -> tuple[object, int]:
    return (vintage.availability.value, vintage.revision_sequence)


class FakeForecastOutcomeRepository:
    def __init__(self) -> None:
        self.definitions: dict[str, list[ForecastOutcomeDefinition]] = {}
        self.vintages: dict[str, list[ForecastOutcomeVintage]] = {}

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

    async def list_outcome_vintages_for_definition(
        self, definition_key: str
    ) -> tuple[ForecastOutcomeVintage, ...]:
        return tuple(
            v
            for vintages in self.vintages.values()
            for v in vintages
            if v.definition_key == definition_key
        )

    async def add_outcome_vintage(
        self, vintage: ForecastOutcomeVintage
    ) -> ForecastOutcomeVintageWriteResult:
        existing = self.vintages.setdefault(vintage.outcome_key, [])
        if any(v.revision_sequence == vintage.revision_sequence for v in existing):
            return ForecastOutcomeVintageWriteResult(inserted=False)
        existing.append(vintage)
        return ForecastOutcomeVintageWriteResult(inserted=True)

"""FX-65: an in-memory fake implementing `ForecastEvaluationRepository`,
mirroring the real `SqlAlchemyForecastEvaluationRepository`'s own
exact selection/idempotency semantics, including the production-vs-
research provenance filtering boundary (Section 7/9)."""

from forex_agent.application.ports.forecast_evaluation_repository import (
    ForecastEvaluationProtocolWriteResult,
    StructuredForecastEvaluationWriteResult,
)
from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.structured_forecast_evaluation_vintage import (
    StructuredForecastEvaluationVintage,
)
from forex_agent.domain.timestamps import UtcTimestamp


def _sort_key(vintage: StructuredForecastEvaluationVintage) -> tuple[object, int]:
    return (vintage.availability.value, vintage.revision_sequence)


class FakeForecastEvaluationRepository:
    def __init__(self) -> None:
        self.protocols: dict[str, list[ForecastEvaluationProtocol]] = {}
        self.vintages: dict[str, list[StructuredForecastEvaluationVintage]] = {}

    async def latest_protocol_version(self, protocol_key: str) -> ForecastEvaluationProtocol | None:
        versions = self.protocols.get(protocol_key, [])
        if not versions:
            return None
        return max(versions, key=lambda p: p.version_sequence)

    async def list_protocol_versions(
        self, protocol_key: str
    ) -> tuple[ForecastEvaluationProtocol, ...]:
        return tuple(self.protocols.get(protocol_key, ()))

    async def add_protocol_version(
        self, protocol: ForecastEvaluationProtocol
    ) -> ForecastEvaluationProtocolWriteResult:
        existing = self.protocols.setdefault(protocol.protocol_key, [])
        if any(p.version_sequence == protocol.version_sequence for p in existing):
            return ForecastEvaluationProtocolWriteResult(inserted=False)
        existing.append(protocol)
        return ForecastEvaluationProtocolWriteResult(inserted=True)

    async def latest_evaluation_vintage(
        self, evaluation_key: str
    ) -> StructuredForecastEvaluationVintage | None:
        vintages = self.vintages.get(evaluation_key, ())
        if not vintages:
            return None
        return max(vintages, key=_sort_key)

    async def list_vintages_for_evaluation(
        self, evaluation_key: str
    ) -> tuple[StructuredForecastEvaluationVintage, ...]:
        return tuple(self.vintages.get(evaluation_key, ()))

    async def add_evaluation_vintage(
        self, vintage: StructuredForecastEvaluationVintage
    ) -> StructuredForecastEvaluationWriteResult:
        existing = self.vintages.setdefault(vintage.evaluation_key, [])
        if any(v.revision_sequence == vintage.revision_sequence for v in existing):
            return StructuredForecastEvaluationWriteResult(inserted=False)
        existing.append(vintage)
        return StructuredForecastEvaluationWriteResult(inserted=True)

    async def latest_production_observed_evaluation_as_of(
        self, evaluation_key: str, as_of: UtcTimestamp
    ) -> StructuredForecastEvaluationVintage | None:
        eligible = [
            v
            for v in self.vintages.get(evaluation_key, ())
            if v.evaluation_mode is ForecastProvenanceMode.PRODUCTION_OBSERVED
            and v.availability.value <= as_of.value
        ]
        return max(eligible, key=_sort_key) if eligible else None

    async def latest_evaluation_as_of_for_research(
        self, evaluation_key: str, research_as_of: UtcTimestamp
    ) -> StructuredForecastEvaluationVintage | None:
        eligible = [
            v
            for v in self.vintages.get(evaluation_key, ())
            if v.availability.value <= research_as_of.value
        ]
        return max(eligible, key=_sort_key) if eligible else None

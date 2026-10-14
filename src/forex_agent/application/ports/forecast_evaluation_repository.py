"""FX-65: port for storing and PIT-querying FTA's own evaluation
protocols and recorded evaluations -- mirrors FX-64's `Structured
ForecastRepository` shape exactly, INCLUDING its Section 7 production-
versus-research read-path separation: `latest_production_observed_
evaluation_as_of` and `latest_evaluation_as_of_for_research` are
differently-named on purpose, so no caller can reach a RETROSPECTIVE_
RESEARCH evaluation through an ordinary production query."""

from dataclasses import dataclass
from typing import Protocol

from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol
from forex_agent.domain.structured_forecast_evaluation_vintage import (
    StructuredForecastEvaluationVintage,
)
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastEvaluationProtocolWriteResult:
    inserted: bool


@dataclass(frozen=True, slots=True)
class StructuredForecastEvaluationWriteResult:
    inserted: bool


class ForecastEvaluationRepository(Protocol):
    async def latest_protocol_version(self, protocol_key: str) -> ForecastEvaluationProtocol | None:
        """The highest `version_sequence` row for `protocol_key`, or
        `None` if it has never been registered."""
        ...

    async def list_protocol_versions(
        self, protocol_key: str
    ) -> tuple[ForecastEvaluationProtocol, ...]: ...

    async def add_protocol_version(
        self, protocol: ForecastEvaluationProtocol
    ) -> ForecastEvaluationProtocolWriteResult:
        """Append-only insert keyed on `(protocol_key, version_
        sequence)` -- `ON CONFLICT DO NOTHING` semantics."""
        ...

    async def latest_evaluation_vintage(
        self, evaluation_key: str
    ) -> StructuredForecastEvaluationVintage | None:
        """The evaluation's own latest vintage by `(availability,
        revision_sequence)`, REGARDLESS of `evaluation_mode` -- an
        administrative read used only by `EvaluateStructuredForecast`'s
        own PIT-ordering/idempotency checks."""
        ...

    async def list_vintages_for_evaluation(
        self, evaluation_key: str
    ) -> tuple[StructuredForecastEvaluationVintage, ...]:
        """Every stored vintage of this evaluation -- used by the
        full-history determinism check."""
        ...

    async def add_evaluation_vintage(
        self, vintage: StructuredForecastEvaluationVintage
    ) -> StructuredForecastEvaluationWriteResult:
        """Append-only insert keyed on `(evaluation_key, revision_
        sequence)` -- `ON CONFLICT DO NOTHING` semantics."""
        ...

    async def latest_production_observed_evaluation_as_of(
        self, evaluation_key: str, as_of: UtcTimestamp
    ) -> StructuredForecastEvaluationVintage | None:
        """The ONLY production PIT read this port offers. Returns the
        latest vintage with `evaluation_mode == PRODUCTION_OBSERVED`
        and `availability <= as_of` -- a `RETROSPECTIVE_RESEARCH`
        evaluation is NEVER returned here."""
        ...

    async def latest_evaluation_as_of_for_research(
        self, evaluation_key: str, research_as_of: UtcTimestamp
    ) -> StructuredForecastEvaluationVintage | None:
        """The latest vintage with `availability <= research_as_of`,
        of EITHER evaluation mode -- deliberately named differently
        from the production method above."""
        ...

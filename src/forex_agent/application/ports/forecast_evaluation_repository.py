"""FX-65: port for storing and PIT-querying FTA's own evaluation
protocols and recorded evaluations -- mirrors FX-64's `Structured
ForecastRepository` shape exactly, INCLUDING its Section 7 production-
versus-research read-path separation: `latest_production_observed_
evaluation_as_of` and `latest_evaluation_as_of_for_research` are
differently-named on purpose, so no caller can reach a RETROSPECTIVE_
RESEARCH evaluation through an ordinary production query.

FX-66 addition: `list_latest_evaluations_for_protocol` -- a purely
additive, administrative read (no existing method's own behavior
changes). See its own docstring for why it is deliberately UNBOUNDED
by any PIT instant.

FX-66H (H1) addition: `list_latest_evaluations_for_protocol_as_of` --
the CORRECT per-key, PIT-bounded selection `BuildForecastPerformance
PopulationAsOf` actually needs for historical population membership.
The original FX-66 design used the unbounded method above plus a
manual `availability <= as_of` check on the OVERALL latest revision,
which incorrectly excluded an entire evaluation_key whenever ANY
later revision existed beyond the cutoff, even when an EARLIER
revision was genuinely available at that cutoff -- this new method
selects the correct per-key revision directly, so a later correction
can never substitute for, or exclude, what was actually known as of
an earlier historical instant."""

from dataclasses import dataclass
from typing import Protocol

from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
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

    async def list_latest_evaluations_for_protocol(
        self, protocol_key: str, evaluation_mode: ForecastProvenanceMode
    ) -> tuple[StructuredForecastEvaluationVintage, ...]:
        """FX-66: every DISTINCT `evaluation_key` ever recorded under
        `protocol_key` AND `evaluation_mode`, each reduced to its own
        latest vintage by `(availability, revision_sequence)` --
        deliberately UNBOUNDED by any PIT instant, mirroring `latest_
        outcome_vintage`'s own "administrative, unbounded" convention.
        `BuildForecastPerformancePopulationAsOf` uses this ONLY to
        discover which `evaluation_key`s exist at all (for `raw_
        candidate_count`) and to flag, purely informationally, that a
        revision newer than the one actually selected exists (FX-66H
        H1's own "separate administrative diagnostic" requirement) --
        it is NEVER used to pick which revision enters the historical
        population; see `list_latest_evaluations_for_protocol_as_of`
        for that."""
        ...

    async def list_latest_evaluations_for_protocol_as_of(
        self, protocol_key: str, evaluation_mode: ForecastProvenanceMode, as_of: UtcTimestamp
    ) -> tuple[StructuredForecastEvaluationVintage, ...]:
        """FX-66H (H1): every DISTINCT `evaluation_key` ever recorded
        under `protocol_key` AND `evaluation_mode`, each reduced to
        its own latest vintage with `availability <= as_of` -- the
        CORRECT, PIT-bounded selection for historical population
        membership. A key with NO vintage available by `as_of` is
        simply absent from the result (never substituted with a
        later, not-yet-available revision); a key with ONLY an
        earlier revision available by `as_of` returns THAT revision,
        never the later one, even if a newer revision has since been
        recorded."""
        ...

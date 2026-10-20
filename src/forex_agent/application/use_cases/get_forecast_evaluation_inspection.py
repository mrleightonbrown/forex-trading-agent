"""FX-67 Section 6/8: `GetForecastEvaluationInspection` -- traces ONE
individually-selected evaluation to its EXACT pinned forecast and
outcome evidence, plus its originator's attribution resolved to a
display identity.

Every lookup is by EXACT `(key, revision_sequence)` -- never "the
current/latest vintage" (Section 6's own explicit "do not substitute
current/latest forecast or outcome values when inspecting an older
snapshot" rule). If any pinned reference cannot be resolved, an
`UnresolvedEvidenceReference` diagnostic is returned in its place
rather than raising or silently falling back to something else
(Section 6's own "do not silently hide unresolved references" rule)
-- this use case therefore never raises for a missing reference; it
is read-only and total over its own input domain.

Attribution is resolved via `ResolveSourceIdentityAsOf` (FX-62), as of
an EXPLICIT, caller-supplied `attribution_as_of` -- never `now()` --
so a LATER identity correction never silently changes an earlier
inspection's own displayed name (Section 8's own "do not silently
update an earlier PIT inspection using later knowledge" rule). An
`ANONYMOUS_RESPONDENT`/`AGGREGATE_SURVEY_CONSENSUS` attribution is
NEVER given an invented display name -- `publisher_display_name`/
`forecaster_display_name` are `None` whenever no FX-62 identity
applies, or whenever that identity was simply not yet KNOWN as of
`attribution_as_of`."""

from dataclasses import dataclass

from forex_agent.application.ports.forecast_evaluation_repository import (
    ForecastEvaluationRepository,
)
from forex_agent.application.ports.forecast_outcome_repository import ForecastOutcomeRepository
from forex_agent.application.ports.source_registry_repository import SourceRegistryRepository
from forex_agent.application.ports.structured_forecast_repository import (
    StructuredForecastRepository,
)
from forex_agent.application.use_cases.forecast_performance_inspection_support import (
    UnresolvedEvidenceReference,
    find_exact_version,
)
from forex_agent.application.use_cases.resolve_source_identity_as_of import (
    ResolveSourceIdentityAsOf,
    SourceIdentityResolution,
)
from forex_agent.domain.forecast_attribution import ForecastAttribution
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.structured_forecast_evaluation_vintage import (
    StructuredForecastEvaluationVintage,
)
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ResolvedOriginatorIdentity:
    attribution: ForecastAttribution
    publisher_display_name: str | None
    """`None` whenever the publisher's own FX-62 identity was not yet
    KNOWN as of `attribution_as_of` -- never fabricated."""
    forecaster_display_name: str | None
    """Always `None` for `AGGREGATE_SURVEY_CONSENSUS`/`ANONYMOUS_
    RESPONDENT` (neither carries a named FX-62 forecaster identity at
    all); for `NAMED_INSTITUTION`, `None` only if that identity was
    not yet known as of `attribution_as_of`."""


@dataclass(frozen=True, slots=True)
class ForecastEvaluationInspection:
    evaluation: StructuredForecastEvaluationVintage
    forecast_vintage: StructuredForecastVintage | UnresolvedEvidenceReference
    outcome_vintage: ForecastOutcomeVintage | UnresolvedEvidenceReference
    originator: ResolvedOriginatorIdentity | None
    """`None` only when `forecast_vintage` itself could not be
    resolved (there is then no attribution to resolve at all)."""


async def resolve_originator_identity(
    registry_repository: SourceRegistryRepository,
    attribution: ForecastAttribution,
    attribution_as_of: UtcTimestamp,
) -> ResolvedOriginatorIdentity:
    resolve = ResolveSourceIdentityAsOf(registry_repository)
    publisher_result = await resolve(attribution.publisher_source_key, attribution_as_of)
    publisher_display_name = (
        publisher_result.identity_vintage.display_name
        if publisher_result.resolution is SourceIdentityResolution.KNOWN
        and publisher_result.identity_vintage is not None
        else None
    )
    forecaster_display_name: str | None = None
    if attribution.forecaster_source_key is not None:
        forecaster_result = await resolve(attribution.forecaster_source_key, attribution_as_of)
        if (
            forecaster_result.resolution is SourceIdentityResolution.KNOWN
            and forecaster_result.identity_vintage is not None
        ):
            forecaster_display_name = forecaster_result.identity_vintage.display_name
    return ResolvedOriginatorIdentity(
        attribution=attribution,
        publisher_display_name=publisher_display_name,
        forecaster_display_name=forecaster_display_name,
    )


class GetForecastEvaluationInspection:
    def __init__(
        self,
        evaluation_repository: ForecastEvaluationRepository,
        forecast_repository: StructuredForecastRepository,
        outcome_repository: ForecastOutcomeRepository,
        registry_repository: SourceRegistryRepository,
    ) -> None:
        self._evaluation_repository = evaluation_repository
        self._forecast_repository = forecast_repository
        self._outcome_repository = outcome_repository
        self._registry_repository = registry_repository

    async def __call__(
        self,
        evaluation_key: str,
        revision_sequence: int,
        *,
        attribution_as_of: UtcTimestamp,
    ) -> ForecastEvaluationInspection | UnresolvedEvidenceReference:
        evaluation_history = await self._evaluation_repository.list_vintages_for_evaluation(
            evaluation_key
        )
        evaluation = find_exact_version(
            evaluation_history, revision_sequence, version_field="revision_sequence"
        )
        if evaluation is None:
            return UnresolvedEvidenceReference("evaluation", evaluation_key, revision_sequence)

        forecast_history = await self._forecast_repository.list_vintages_for_claim(
            evaluation.forecast_claim_key
        )
        forecast_vintage = find_exact_version(
            forecast_history,
            evaluation.forecast_revision_sequence,
            version_field="revision_sequence",
        )
        if forecast_vintage is None:
            return ForecastEvaluationInspection(
                evaluation=evaluation,
                forecast_vintage=UnresolvedEvidenceReference(
                    "forecast", evaluation.forecast_claim_key, evaluation.forecast_revision_sequence
                ),
                outcome_vintage=UnresolvedEvidenceReference(
                    "outcome", evaluation.outcome_key, evaluation.outcome_revision_sequence
                ),
                originator=None,
            )

        outcome_history = await self._outcome_repository.list_vintages_for_outcome(
            evaluation.outcome_key
        )
        outcome_vintage: ForecastOutcomeVintage | UnresolvedEvidenceReference = find_exact_version(
            outcome_history, evaluation.outcome_revision_sequence, version_field="revision_sequence"
        ) or UnresolvedEvidenceReference(
            "outcome", evaluation.outcome_key, evaluation.outcome_revision_sequence
        )

        originator = await resolve_originator_identity(
            self._registry_repository, forecast_vintage.attribution, attribution_as_of
        )
        return ForecastEvaluationInspection(
            evaluation=evaluation,
            forecast_vintage=forecast_vintage,
            outcome_vintage=outcome_vintage,
            originator=originator,
        )

from dataclasses import dataclass

from forex_agent.domain._guards import require_revision_sequence
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_performance_duplicate_selection_policy import (
    ForecastPerformanceDuplicateSelectionPolicy,
)
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_registry import target_by_key
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastPerformanceCohortDefinition:
    """FX-66 Section 4: ONE append-only version of an immutable
    cohort -- `(cohort_key, version_sequence)` is the row's own
    identity, mirroring `ForecastOutcomeDefinition`/`ForecastEvaluation
    Protocol`'s own append-only-version shape exactly. Identifies a
    genuinely comparable population of forecast evaluations: every
    field below is a REQUIRED eligibility/comparability dimension
    (Section 4's own explicit list), pinned BEFORE any realized error
    is known (Section 4's own "must be fixed independently of realized
    error values").

    `target_key` transitively pins jurisdiction, unit, variable
    family, and measurement convention (via `forecast_target_registry`
    -- never restated here, exactly mirroring `ForecastOutcomeDefinition`'s
    own "reached only via target_key" discipline, so these facts can
    never drift between two places). `(protocol_key, protocol_version_
    sequence)` transitively pins the evaluation metric and the outcome-
    vintage-selection policy (via `ForecastEvaluationProtocol`).

    `horizon_category` is a free-form, EXACT-match-only label the
    cohort author supplies (e.g. `"FAD-SAME-MEETING"`) -- NEVER
    computed from elapsed calendar days (Section 4's own explicit
    prohibition against day-count bucketing); two cohorts with
    different labels are never merged, and a candidate with a
    different label is excluded, never approximated.

    Originator identity reuses FX-64's own `ForecastAttribution`
    fields directly (Section 5's own "use FX-62/64's existing
    originator semantics") rather than inventing a new identity
    concept: `originator_forecaster_source_key` is required if and
    only if `attribution_kind` is `NAMED_INSTITUTION` (an aggregate
    survey consensus belongs to its own publisher/distributor
    identity, Section 5's own Bank-of-Canada example, never to an
    individual forecaster).

    There is deliberately NO `evaluation_knowledge_cutoff` field here:
    the PIT bound is always a CALL-TIME parameter to `BuildForecast
    PerformancePopulationAsOf` (mirroring every other PIT read in this
    codebase, e.g. `ResolveForecastOutcomeAsOf`'s own `as_of`), never
    baked into the cohort's own identity -- a cohort's own eligibility
    RULES are fixed; the instant at which they are APPLIED is not."""

    cohort_key: str
    version_sequence: int
    attribution_kind: ForecastAttributionKind
    originator_publisher_source_key: str
    target_key: str
    forecast_type: ForecastType
    horizon_category: str
    protocol_key: str
    protocol_version_sequence: int
    evaluation_mode: ForecastProvenanceMode
    duplicate_selection_policy: ForecastPerformanceDuplicateSelectionPolicy
    availability: UtcTimestamp
    rationale: str
    originator_forecaster_source_key: str | None = None
    issue_window_start: UtcTimestamp | None = None
    issue_window_end: UtcTimestamp | None = None
    known_duplicate_evaluation_keys: tuple[str, ...] = ()
    correction_reason: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("cohort_key", self.cohort_key),
            ("originator_publisher_source_key", self.originator_publisher_source_key),
            ("target_key", self.target_key),
            ("horizon_category", self.horizon_category),
            ("protocol_key", self.protocol_key),
            ("rationale", self.rationale),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string, got {value!r}")
        require_revision_sequence(self.version_sequence)
        require_revision_sequence(self.protocol_version_sequence)
        if not isinstance(self.attribution_kind, ForecastAttributionKind):
            raise TypeError(
                f"attribution_kind must be a ForecastAttributionKind, got "
                f"{type(self.attribution_kind).__name__}"
            )
        if not isinstance(self.forecast_type, ForecastType):
            raise TypeError(
                f"forecast_type must be a ForecastType, got {type(self.forecast_type).__name__}"
            )
        if not isinstance(self.evaluation_mode, ForecastProvenanceMode):
            raise TypeError(
                f"evaluation_mode must be a ForecastProvenanceMode, got "
                f"{type(self.evaluation_mode).__name__}"
            )
        if not isinstance(
            self.duplicate_selection_policy, ForecastPerformanceDuplicateSelectionPolicy
        ):
            raise TypeError(
                "duplicate_selection_policy must be a ForecastPerformanceDuplicateSelectionPolicy, "
                f"got {type(self.duplicate_selection_policy).__name__}"
            )
        if not isinstance(self.availability, UtcTimestamp):
            raise TypeError(
                f"availability must be a UtcTimestamp, got {type(self.availability).__name__}"
            )
        for name, ts in (
            ("issue_window_start", self.issue_window_start),
            ("issue_window_end", self.issue_window_end),
        ):
            if ts is not None and not isinstance(ts, UtcTimestamp):
                raise TypeError(f"{name} must be a UtcTimestamp or None, got {type(ts).__name__}")
        if (
            self.issue_window_start is not None
            and self.issue_window_end is not None
            and self.issue_window_start.value > self.issue_window_end.value
        ):
            raise ValueError("issue_window_start must not be later than issue_window_end")
        if not isinstance(self.known_duplicate_evaluation_keys, tuple):
            raise TypeError(
                "known_duplicate_evaluation_keys must be a tuple, got "
                f"{type(self.known_duplicate_evaluation_keys).__name__}"
            )
        for key in self.known_duplicate_evaluation_keys:
            if not isinstance(key, str) or not key.strip():
                raise ValueError(
                    f"every known_duplicate_evaluation_keys entry must be a non-empty string, "
                    f"got {key!r}"
                )
        if self.correction_reason is not None and (
            not isinstance(self.correction_reason, str) or not self.correction_reason.strip()
        ):
            raise ValueError(
                f"correction_reason must be a non-empty string or None, got "
                f"{self.correction_reason!r}"
            )

        target = target_by_key(self.target_key)
        if target is None:
            raise ValueError(
                f"target_key={self.target_key!r} is not in the admitted forecast target registry"
            )
        if self.forecast_type not in target.supported_forecast_types:
            raise ValueError(
                f"forecast_type={self.forecast_type.value!r} is not supported by "
                f"target_key={self.target_key!r}"
            )

        if self.attribution_kind is ForecastAttributionKind.NAMED_INSTITUTION:
            if (
                not isinstance(self.originator_forecaster_source_key, str)
                or not self.originator_forecaster_source_key.strip()
            ):
                raise ValueError(
                    "originator_forecaster_source_key is required for NAMED_INSTITUTION"
                )
        elif self.originator_forecaster_source_key is not None:
            raise ValueError(
                "originator_forecaster_source_key must be None unless attribution_kind is "
                "NAMED_INSTITUTION -- an aggregate/anonymous originator has no individual "
                "forecaster identity to pin"
            )

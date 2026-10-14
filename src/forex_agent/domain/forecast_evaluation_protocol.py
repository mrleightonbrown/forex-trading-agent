from dataclasses import dataclass

from forex_agent.domain._guards import require_revision_sequence
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_target_registry import target_by_key
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.outcome_vintage_selection_policy import OutcomeVintageSelectionPolicy
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastEvaluationProtocol:
    """FX-65 Section 7: ONE append-only version of an immutable
    evaluation specification -- `(protocol_key, version_sequence)` is
    the row's own identity; a protocol correction is a NEW, higher
    `version_sequence` row (Section 7's own "must be append-only"
    rule), never a mutation.

    Every field here is FROZEN before evaluation and never selected
    to make a particular forecast look accurate (Section 6/7's own
    explicit prohibition) -- `outcome_vintage_selection_policy`/
    `fixed_outcome_revision_sequence` are the SAME inputs `Resolve
    ForecastOutcomeAsOf` uses, pinned here so a protocol's own
    evaluation question never drifts between calls. `metric` is
    structurally tied to `supported_forecast_type` (never a free
    choice): `NUMERIC_POINT` protocols always compute `NUMERIC_ERROR`,
    `CATEGORICAL_EVENT` protocols always compute `CATEGORICAL_MATCH`.
    `rationale` is this protocol version's own required evidence/
    justification (Section 7's own "evidence or rationale documenting
    the protocol")."""

    protocol_key: str
    version_sequence: int
    supported_forecast_type: ForecastType
    target_key: str
    outcome_definition_key: str
    outcome_definition_version_sequence: int
    outcome_vintage_selection_policy: OutcomeVintageSelectionPolicy
    metric: ForecastEvaluationMetric
    availability: UtcTimestamp
    rationale: str
    fixed_outcome_revision_sequence: int | None = None
    correction_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.protocol_key, str) or not self.protocol_key.strip():
            raise ValueError(f"protocol_key must be a non-empty string, got {self.protocol_key!r}")
        require_revision_sequence(self.version_sequence)
        if not isinstance(self.supported_forecast_type, ForecastType):
            raise TypeError(
                "supported_forecast_type must be a ForecastType, got "
                f"{type(self.supported_forecast_type).__name__}"
            )
        if (
            not isinstance(self.outcome_definition_key, str)
            or not self.outcome_definition_key.strip()
        ):
            raise ValueError(
                "outcome_definition_key must be a non-empty string, got "
                f"{self.outcome_definition_key!r}"
            )
        require_revision_sequence(self.outcome_definition_version_sequence)
        if not isinstance(self.outcome_vintage_selection_policy, OutcomeVintageSelectionPolicy):
            raise TypeError(
                "outcome_vintage_selection_policy must be an OutcomeVintageSelectionPolicy, got "
                f"{type(self.outcome_vintage_selection_policy).__name__}"
            )
        if not isinstance(self.metric, ForecastEvaluationMetric):
            raise TypeError(
                f"metric must be a ForecastEvaluationMetric, got {type(self.metric).__name__}"
            )
        if not isinstance(self.availability, UtcTimestamp):
            raise TypeError(
                f"availability must be a UtcTimestamp, got {type(self.availability).__name__}"
            )
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError(f"rationale must be a non-empty string, got {self.rationale!r}")
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
        if self.supported_forecast_type not in target.supported_forecast_types:
            raise ValueError(
                f"supported_forecast_type={self.supported_forecast_type.value!r} is not "
                f"supported by target_key={self.target_key!r}"
            )
        if (
            self.supported_forecast_type is ForecastType.NUMERIC_POINT
            and self.metric is not ForecastEvaluationMetric.NUMERIC_ERROR
        ):
            raise ValueError("metric must be NUMERIC_ERROR for a NUMERIC_POINT protocol")
        if (
            self.supported_forecast_type is ForecastType.CATEGORICAL_EVENT
            and self.metric is not ForecastEvaluationMetric.CATEGORICAL_MATCH
        ):
            raise ValueError("metric must be CATEGORICAL_MATCH for a CATEGORICAL_EVENT protocol")

        if (
            self.outcome_vintage_selection_policy
            is OutcomeVintageSelectionPolicy.FIXED_RELEASE_VINTAGE
        ):
            if self.fixed_outcome_revision_sequence is None:
                raise ValueError(
                    "fixed_outcome_revision_sequence is required for FIXED_RELEASE_VINTAGE"
                )
            require_revision_sequence(self.fixed_outcome_revision_sequence)
        elif self.fixed_outcome_revision_sequence is not None:
            raise ValueError(
                "fixed_outcome_revision_sequence must be None unless "
                "outcome_vintage_selection_policy is FIXED_RELEASE_VINTAGE"
            )

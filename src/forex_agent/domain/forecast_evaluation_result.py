from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain._guards import require_decimal
from forex_agent.domain.categorical_evaluation_result import CategoricalEvaluationResult
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric


@dataclass(frozen=True, slots=True)
class ForecastEvaluationResult:
    """FX-65 Section 7: the computed result of evaluating ONE
    admissible forecast against its resolved outcome. `metric`
    structurally determines which other fields are populated (never
    both numeric and categorical, never neither) -- mirrors every
    other FX-64/65 payload-shape rule exactly.

    For `NUMERIC_ERROR`: `signed_error = observed - forecast` and
    `absolute_error = abs(signed_error)`, both `Decimal` (CLAUDE.md:
    never `float` for a value like this); `unit` is the outcome's own
    unit, carried here so a stored result is self-describing without
    a join. Never a source-level average or standardized across
    incompatible variables (Section 7's own explicit prohibition)."""

    metric: ForecastEvaluationMetric
    signed_error: Decimal | None = None
    absolute_error: Decimal | None = None
    unit: str | None = None
    categorical_result: CategoricalEvaluationResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.metric, ForecastEvaluationMetric):
            raise TypeError(
                f"metric must be a ForecastEvaluationMetric, got {type(self.metric).__name__}"
            )

        if self.metric is ForecastEvaluationMetric.NUMERIC_ERROR:
            require_decimal("signed_error", self.signed_error)
            require_decimal("absolute_error", self.absolute_error)
            if not isinstance(self.unit, str) or not self.unit.strip():
                raise ValueError("unit must be a non-empty string for NUMERIC_ERROR")
            if self.categorical_result is not None:
                raise ValueError("categorical_result must be None for NUMERIC_ERROR")
            assert self.signed_error is not None and self.absolute_error is not None
            if self.absolute_error < 0:
                raise ValueError(f"absolute_error must not be negative, got {self.absolute_error}")
            if self.absolute_error != abs(self.signed_error):
                raise ValueError(
                    f"absolute_error ({self.absolute_error}) must equal "
                    f"abs(signed_error) ({abs(self.signed_error)})"
                )
        elif self.metric is ForecastEvaluationMetric.CATEGORICAL_MATCH:
            if not isinstance(self.categorical_result, CategoricalEvaluationResult):
                raise TypeError(
                    "categorical_result must be a CategoricalEvaluationResult for CATEGORICAL_MATCH"
                )
            if self.signed_error is not None or self.absolute_error is not None:
                raise ValueError("signed_error/absolute_error must be None for CATEGORICAL_MATCH")
            if self.unit is not None:
                raise ValueError("unit must be None for CATEGORICAL_MATCH")

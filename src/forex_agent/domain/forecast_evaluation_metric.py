from enum import Enum


class ForecastEvaluationMetric(Enum):
    """FX-65 Section 7: which comparison an evaluation protocol
    computes -- tied structurally to the protocol's own `supported_
    forecast_type` (`NUMERIC_POINT` -> `NUMERIC_ERROR`, `CATEGORICAL_
    EVENT` -> `CATEGORICAL_MATCH`), never a free choice."""

    NUMERIC_ERROR = "NUMERIC_ERROR"
    """Computes BOTH the signed error (observed minus forecast) and
    its absolute value, using `Decimal` arithmetic -- never a source-
    level average, and never standardized across incompatible
    variables."""

    CATEGORICAL_MATCH = "CATEGORICAL_MATCH"
    """Compares the forecast's own predicted category against the
    observed category under an exact meeting/event definition,
    yielding `MATCH` or `MISMATCH` -- never derived from a numeric
    rate without an approved categorization rule."""

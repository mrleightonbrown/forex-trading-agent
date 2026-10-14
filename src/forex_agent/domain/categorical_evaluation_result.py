from enum import Enum


class CategoricalEvaluationResult(Enum):
    """FX-65 Section 7: the result of comparing a `CATEGORICAL_EVENT`
    forecast's own predicted category against a source-backed observed
    category under an exact meeting/event definition."""

    MATCH = "MATCH"
    MISMATCH = "MISMATCH"

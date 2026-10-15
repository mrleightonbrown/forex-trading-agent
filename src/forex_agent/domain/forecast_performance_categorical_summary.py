from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ForecastPerformanceCategoricalSummary:
    """FX-66 Section 10: descriptive categorical-forecast performance
    over `n` paired `(predicted, observed)` members. `confusion_counts`
    and `realized_class_distribution` are plain tuples of tuples (this
    codebase's own convention for an immutable, order-independent-by-
    construction mapping on a frozen dataclass) rather than a `dict`,
    sorted by the caller for deterministic equality/testing.

    Deliberately carries NO probabilistic score (Brier score, log
    loss, ...) -- Section 10's own explicit "do not create predicted
    probabilities the source did not publish" rule; every FX-64
    `CATEGORICAL_EVENT` forecast is a single predicted class, never a
    probability distribution."""

    n: int
    match_count: int
    mismatch_count: int
    accuracy: Decimal
    confusion_counts: tuple[tuple[str, str, int], ...]
    """`(predicted_class, observed_class, count)` triples."""
    realized_class_distribution: tuple[tuple[str, int], ...]
    """`(observed_class, count)` pairs."""

    def __post_init__(self) -> None:
        if not isinstance(self.n, int) or isinstance(self.n, bool) or self.n < 1:
            raise ValueError(f"n must be a positive int, got {self.n!r}")
        if self.match_count + self.mismatch_count != self.n:
            raise ValueError(
                f"match_count ({self.match_count}) + mismatch_count ({self.mismatch_count}) "
                f"must equal n ({self.n})"
            )
        if not isinstance(self.accuracy, Decimal):
            raise TypeError(f"accuracy must be a Decimal, got {type(self.accuracy).__name__}")
        if not (Decimal("0") <= self.accuracy <= Decimal("1")):
            raise ValueError(f"accuracy must be between 0 and 1, got {self.accuracy}")
        if sum(count for _, _, count in self.confusion_counts) != self.n:
            raise ValueError("confusion_counts entries must sum to n")
        if sum(count for _, count in self.realized_class_distribution) != self.n:
            raise ValueError("realized_class_distribution entries must sum to n")

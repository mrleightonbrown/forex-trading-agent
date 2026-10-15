from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain._guards import require_decimal


@dataclass(frozen=True, slots=True)
class ForecastPerformanceNumericSummary:
    """FX-66 Section 9: descriptive numeric-forecast performance over
    `n` paired `(observed, forecast)` members, computed with `Decimal`
    throughout (CLAUDE.md: never `float` where `Decimal` is
    appropriate) -- `unit` is always carried alongside every value
    (Section 9's own "all numeric summaries must preserve their
    measurement units" rule), since a bare number is meaningless
    without it. Never constructed for `n == 0` -- see `Calculate
    ForecastPerformance`'s own docstring for why an empty numeric
    population yields `None` instead of a degenerate zero/undefined
    summary."""

    n: int
    unit: str
    mean_absolute_error: Decimal
    mean_signed_error: Decimal
    root_mean_squared_error: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.n, int) or isinstance(self.n, bool) or self.n < 1:
            raise ValueError(f"n must be a positive int, got {self.n!r}")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError(f"unit must be a non-empty string, got {self.unit!r}")
        for name, value in (
            ("mean_absolute_error", self.mean_absolute_error),
            ("mean_signed_error", self.mean_signed_error),
            ("root_mean_squared_error", self.root_mean_squared_error),
        ):
            require_decimal(name, value)
        if self.mean_absolute_error < 0:
            raise ValueError(
                f"mean_absolute_error must not be negative, got {self.mean_absolute_error}"
            )
        if self.root_mean_squared_error < 0:
            raise ValueError(
                f"root_mean_squared_error must not be negative, got {self.root_mean_squared_error}"
            )

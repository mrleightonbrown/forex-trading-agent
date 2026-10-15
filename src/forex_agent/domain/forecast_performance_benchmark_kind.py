from enum import Enum


class ForecastPerformanceBenchmarkKind(Enum):
    """FX-66 Section 11: the three initial admissible benchmark
    shapes -- a closed set, deliberately small (Section 11's own "do
    not invent actual benchmark forecasts from later revised
    outcomes")."""

    AUTHENTICATED_SERIES = "AUTHENTICATED_SERIES"
    """Reuses ANOTHER, already-registered `ForecastPerformanceCohort
    Definition`'s own real evaluations as the benchmark series --
    never a fabricated series. Pairing is by SHARED `outcome_key`
    (FX-65H.2's own durable target-event identity), never by date
    proximity."""

    NAIVE_CATEGORICAL = "NAIVE_CATEGORICAL"
    """A fixed, explicitly declared predicted class (e.g. `"HOLD"`),
    applied uniformly to every member's own target event -- never
    computed from the realized outcome distribution itself."""

    NAIVE_NUMERIC = "NAIVE_NUMERIC"
    """A fixed, explicitly declared reference numeric value with its
    own documented evidence -- NOT a dynamically computed "no-change"
    forecast, since this codebase has no established historical-input
    pipeline for that yet (Section 11's own "permitted only where its
    required inputs and historical availability are established")."""

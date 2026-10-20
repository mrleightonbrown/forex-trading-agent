from enum import Enum


class ForecastPerformanceInspectionMode(Enum):
    """FX-67 Section 12: which PIT read path a forecast-performance
    inspection means -- makes the mode selection UNMISSABLE at every
    call site (Section 12's own "require an unmistakable mode
    selection" requirement; there is no default anywhere in this
    story). Lives in `domain`, not `application`, so BOTH the
    `ForecastPerformanceRepository` port and every inspection use case
    can reference it without either depending on the other (mirrors
    `ForecastProvenanceMode`'s own cross-cutting placement exactly) --
    FX-67H's own correction, after `list_distinct_snapshot_keys` needed
    this type on the port itself."""

    PRODUCTION = "PRODUCTION"
    """Only recorded `PRODUCTION_OBSERVED` snapshots -- resolved via
    `latest_production_observed_snapshot_as_of`, mirroring FX-66's own
    production-read boundary exactly."""

    RETROSPECTIVE_RESEARCH = "RETROSPECTIVE_RESEARCH"
    """Resolved via `latest_snapshot_as_of_for_research`, which sees
    EITHER evaluation mode (FX-66's own existing research-read
    semantics) -- named here to make clear this is the RESEARCH view,
    never implicitly substituted for a production query."""

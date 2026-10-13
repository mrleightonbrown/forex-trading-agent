from enum import Enum


class ForecastProvenanceMode(Enum):
    """FX-64 Section 7 -- the single most important architectural
    feature of this story. Every `StructuredForecastVintage` carries
    EXACTLY one of these, and production PIT reads (`GetForecastClaim
    AsOf`/`ListForecastClaimsAsOf`) filter to `PRODUCTION_OBSERVED`
    ONLY -- there is NO implicit fallback from production PIT to
    retrospective research anywhere in this codebase."""

    PRODUCTION_OBSERVED = "PRODUCTION_OBSERVED"
    """Forecast evidence FTA actually acquired during its own normal,
    contemporaneous observation history. `availability` is the real
    instant FTA actually acquired it; historical production replay
    includes this vintage only from that instant onward."""

    RETROSPECTIVE_RESEARCH = "RETROSPECTIVE_RESEARCH"
    """An authenticated historical forecast subsequently recovered for
    research, long after its own original publication. `availability`
    is still FTA's OWN actual research-discovery/registration instant
    (never backdated to the original publication date) -- but this
    vintage is NEVER visible through an ordinary production PIT query,
    regardless of `as_of`. It is visible ONLY through the explicit,
    separately-selected `GetRetrospectiveForecastResearchView`."""

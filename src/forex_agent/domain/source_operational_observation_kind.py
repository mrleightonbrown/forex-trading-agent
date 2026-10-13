from enum import Enum


class SourceOperationalObservationKind(Enum):
    """FX-63: what conceptual category one `SourceOperationalObservation`
    row describes. Deliberately a single member today -- content-level
    observations (new item/revision/withdrawal) are NOT separately
    recorded as rows of this kind; they are derived directly, at read
    time, from FX-56/57's own already-durable `NewsItem`/`NewsItemVintage`
    evidence (a successful parse is exactly what produces a stored
    vintage, so it needs no second, independently-maintained record).
    This enum stays open for a future story to add a genuinely new
    recorded kind without widening this one's own meaning."""

    ACQUISITION_ATTEMPT = "ACQUISITION_ATTEMPT"

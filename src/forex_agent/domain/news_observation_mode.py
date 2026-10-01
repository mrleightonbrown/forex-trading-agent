from enum import Enum


class NewsObservationMode(Enum):
    """How a `NewsItemVintage` came to be known to FTA (FX-56 Section 27).

    `PROSPECTIVE` is the ONLY mode any current adapter can produce --
    FX-55/FX-55H adopted no historical news source at all. `BACKFILL`
    exists purely as a structural guard against a future mistake: if a
    later story ever imports historical material, its revisions must
    be explicitly tagged `BACKFILL` so a PIT query can tell "FTA
    observed this in real time" apart from "FTA imported this
    after the fact," and so a prospective-only evidence query can
    exclude it without needing to infer anything from timestamps (FX-56
    Section 28). No code in this story constructs a `BACKFILL` vintage.
    """

    PROSPECTIVE = "PROSPECTIVE"
    BACKFILL = "BACKFILL"

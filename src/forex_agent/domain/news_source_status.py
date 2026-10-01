from enum import Enum


class NewsSourceStatus(Enum):
    """The source's own claimed lifecycle status for a news item, AT
    THAT VINTAGE'S OWN POINT IN TIME (FX-56 Section 23/65) --
    deliberately independent of `NewsEvidenceDisposition` (see that
    enum's own docstring).

    `WITHDRAWN` requires POSITIVE provider evidence of a retraction/
    withdrawal -- never inferred from an item simply disappearing from
    a bounded feed (FX-56 Section 24, mirroring the economic-calendar
    rule that disappearance from a feed is never evidence of
    cancellation). An item that vanishes from a feed is left
    completely untouched at its last-known status; nothing in this
    codebase marks it `WITHDRAWN` on absence alone.
    """

    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"

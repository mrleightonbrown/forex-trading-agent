from enum import Enum


class IntelligenceSourceKind(Enum):
    """FX-62 Section 4.1: the categorical kind of a durable
    `IntelligenceSource` identity -- deliberately distinguishes an
    ORGANIZATION (e.g. the Bank of England itself) from the TECHNICAL_
    FEED FTA ingests it through (e.g. the `"BOE"` `NewsSourceIdentity.
    source_key` FX-57 already mints), and from a PUBLICATION or a
    PERSON. A durable `source_key` is never reassigned from one kind
    to another -- that would mean silently reassigning a stable
    identity to a different actor (FX-62 Section 4.1's own explicit
    prohibition)."""

    ORGANIZATION = "ORGANIZATION"
    PERSON = "PERSON"
    PUBLICATION = "PUBLICATION"
    TECHNICAL_FEED = "TECHNICAL_FEED"

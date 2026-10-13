from enum import Enum


class ForecastEvidenceKind(Enum):
    """FX-64 Section 6: the exact shape of a forecast's own supporting
    evidence -- either an existing FX-56/57 `NewsItemVintage` basis,
    or a standalone external document reference for a survey/report
    not represented as a NewsItem. No forecast may be recorded without
    exactly one of these, structurally enforced by `ForecastEvidence
    Reference.__post_init__`."""

    NEWS_ITEM_VINTAGE_BASIS = "NEWS_ITEM_VINTAGE_BASIS"
    """The claim originates in an existing `NewsItem` -- pins an
    EXACT `NewsItemVintage` via a composite reference, mirroring
    FX-59/62's own basis-pinning convention exactly. Never a
    fabricated `NewsItem` created merely to satisfy this reference."""

    EXTERNAL_DOCUMENT_REFERENCE = "EXTERNAL_DOCUMENT_REFERENCE"
    """An auditable reference to a source-issued document (e.g. a
    survey release) that is NOT (yet) represented as a `NewsItem` --
    identified by the source's own stable document identifier, never
    by an opaque match on displayed text alone."""

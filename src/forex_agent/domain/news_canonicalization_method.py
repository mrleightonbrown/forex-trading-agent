from enum import Enum


class NewsCanonicalizationMethod(Enum):
    """How a `NewsCanonicalRelationVintage` was decided (FX-58
    Section 6).

    The automatic FX-58 v1 matcher (`CanonicalizeNewsOnce`) may emit
    ONLY the first three members, and only paired with `NewsCanonical
    RelationKind.SAME_STORY` -- enforced by `NewsCanonicalRelation
    Vintage.__post_init__`, never merely a convention. `MANUAL_REVIEW`
    is reserved for a future, explicitly-audited human correction (no
    UI is built in FX-58) and is the ONLY method `NOT_SAME_STORY` may
    ever carry.
    """

    EXACT_CANONICAL_URL = "EXACT_CANONICAL_URL"
    EXACT_BODY_TEXT = "EXACT_BODY_TEXT"
    EXACT_HEADLINE_AND_SUMMARY = "EXACT_HEADLINE_AND_SUMMARY"
    MANUAL_REVIEW = "MANUAL_REVIEW"

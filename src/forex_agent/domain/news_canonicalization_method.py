from enum import Enum


class NewsCanonicalizationMethod(Enum):
    """How a `NewsCanonicalRelationVintage` was decided (FX-58
    Section 6; narrowed by FX-58H Section 5).

    The automatic `fx58_v2` matcher (`CanonicalizeNewsOnce`) may emit
    ONLY `EXACT_CANONICAL_URL`/`EXACT_BODY_TEXT`, and only paired with
    `NewsCanonicalRelationKind.SAME_STORY` -- enforced by `NewsCanon
    icalRelationVintage.__post_init__`, never merely a convention.
    `MANUAL_REVIEW` is reserved for a future, explicitly-audited human
    correction (no UI is built in FX-58/FX-58H) and is the ONLY method
    `NOT_SAME_STORY` may ever carry.

    **FX-58H Section 5 removed `EXACT_HEADLINE_AND_SUMMARY` from this
    enum entirely.** The mandatory real-data dry-run safety gate
    (`fx58_v1`, FX-58's own Section 42/43) found that exact headline+
    summary equality is NOT sufficient evidence of same-story identity
    when a source's own "summary" field is itself recurring
    institutional boilerplate (confirmed for Bank of Canada rate-
    decision outcome text and Federal Reserve committee-hearing
    titles) -- 6 of 7 real pairs this rule proposed were confirmed
    related-but-distinct publications, and ZERO relations using this
    method were ever persisted (see ADR 0007's own "Real-data
    finding" and its FX-58H addendum). The underlying exact-headline-
    and-summary SIGNAL still exists as a non-persisted review-only
    concept -- see `domain.news_canonicalization_review.
    NewsCanonicalizationReviewReason` -- but it can never again become
    a value of THIS enum, which is reserved for methods strong enough
    to independently prove same-story identity without human review.
    """

    EXACT_CANONICAL_URL = "EXACT_CANONICAL_URL"
    EXACT_BODY_TEXT = "EXACT_BODY_TEXT"
    MANUAL_REVIEW = "MANUAL_REVIEW"

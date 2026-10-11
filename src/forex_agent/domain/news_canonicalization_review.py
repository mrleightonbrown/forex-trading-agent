"""FX-58H: a non-persisted, review-only signal -- deliberately a
DIFFERENT type from `NewsCanonicalizationMethod` (Section 4/11), so
accidentally feeding one into `RecordNewsCanonicalRelation` is a type
error, not a silent logic bug.

`NewsCanonicalizationReviewReason` names a signal strong enough to
surface for human inspection, but NOT strong enough to independently
prove same-story identity -- `CanonicalizeNewsOnce` reports these as
diagnostics only and NEVER calls `RecordNewsCanonicalRelation` for a
pair classified this way. A human reviewer who inspects the evidence
and agrees it really is the same story records that decision as
`relation_kind=SAME_STORY, method=MANUAL_REVIEW` -- the review
reason itself is never persisted anywhere; it exists purely to drive
`CanonicalizeNewsOnce`'s own reporting.
"""

from enum import Enum


class NewsCanonicalizationReviewReason(Enum):
    """`EXACT_HEADLINE_AND_SUMMARY`: exact normalized headline AND
    exact normalized summary (>= 80 chars) both match, but this is
    NOT sufficient evidence of same-story identity on its own (FX-58H
    Section 4/15) -- real Bank of Canada and Federal Reserve data
    confirmed sources whose own "summary" field is itself recurring
    institutional boilerplate (an unchanged rate-decision outcome
    sentence; a standing committee-hearing title), reused verbatim
    across genuinely distinct publications."""

    EXACT_HEADLINE_AND_SUMMARY = "EXACT_HEADLINE_AND_SUMMARY"

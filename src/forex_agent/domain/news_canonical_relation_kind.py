from enum import Enum


class NewsCanonicalRelationKind(Enum):
    """What a `NewsCanonicalRelationVintage` asserts about a pair of
    `NewsItem`s (FX-58 Section 5).

    `SAME_STORY`: FTA knows, as of this relation vintage's own
    `availability`, that these two source items should be
    deduplicated into one canonical group.

    `NOT_SAME_STORY`: an explicit, reviewed correction stating that
    the pair must NOT be treated as the same story -- represented
    only through `NewsCanonicalizationMethod.MANUAL_REVIEW` (enforced
    by `NewsCanonicalRelationVintage.__post_init__`), since the
    automatic matcher never writes this kind (Section 5's own
    explicit invariant: absence of `SAME_STORY` is never treated as
    `NOT_SAME_STORY`).
    """

    SAME_STORY = "SAME_STORY"
    NOT_SAME_STORY = "NOT_SAME_STORY"

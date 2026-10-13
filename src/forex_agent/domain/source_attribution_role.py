from enum import Enum


class SourceAttributionRole(Enum):
    """FX-62 Section 4.3: the role an identified actor plays with
    respect to one evidence record -- these roles are DELIBERATELY
    kept distinct (Section 4.3's own explicit requirement): a source
    may publish a document containing a quotation without originating
    the quoted claim, and the existence of a quotation or named entity
    never by itself proves a claimant attribution (Section 4.3)."""

    #: The actor responsible for making the material available --
    #: never assumed to be every institution mentioned in the article
    #: (Section 5's own explicit prohibition).
    PUBLISHER = "PUBLISHER"

    #: The actor FTA has independently established as the originator
    #: of the claim/content itself -- normally UNRESOLVED unless
    #: explicit evidence exists (Section 5).
    ORIGINATING_CLAIMANT = "ORIGINATING_CLAIMANT"

    #: An actor quoted within the material -- never automatically
    #: treated as the claimant (Section 4.3's own explicit warning).
    QUOTED_ACTOR = "QUOTED_ACTOR"

from enum import Enum


class SourceAttributionStatus(Enum):
    """FX-62 Section 4.4: whether ONE attribution vintage's own role is
    currently established. Deliberately only two members -- a
    "correction" (Section 9) is represented structurally, as a NEW
    `CONFIRMED` (or `UNRESOLVED`) vintage with a higher `revision_
    sequence` superseding an earlier one, mirroring FX-58/FX-59's own
    append-only correction precedent (a `NOT_SAME_STORY` relation
    superseding `SAME_STORY`; a new semantic-annotation revision
    superseding an older one) -- never a third `CORRECTED` status
    value that would duplicate what the revision history already
    shows unambiguously."""

    #: Supported by explicit, recorded `SourceProvenanceEvidence` --
    #: `SourceAttributionVintage.attributed_source_key` is REQUIRED
    #: (non-`None`) whenever this status is used.
    CONFIRMED = "CONFIRMED"

    #: The role cannot currently be established -- `attributed_
    #: source_key` is REQUIRED to be `None` whenever this status is
    #: used (Section 4.4's own "do not force an uncertain attribution
    #: into a confirmed identity" requirement).
    UNRESOLVED = "UNRESOLVED"

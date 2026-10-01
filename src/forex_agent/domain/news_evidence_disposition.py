from enum import Enum


class NewsEvidenceDisposition(Enum):
    """Whether a `NewsItemVintage` may be returned by an evidence-
    eligible PIT query (FX-56 Section 25/65) -- independent of
    `NewsSourceStatus`: an `ACTIVE` article can be `QUARANTINED` (its
    own timestamps are anomalous), and a `WITHDRAWN` article can be
    `EVIDENCE_ELIGIBLE` (the withdrawal itself is valid factual
    evidence FTA actually observed). Never conflate the two.

    `QUARANTINED` does not auto-expire (FX-56 Section 26): nothing in
    this codebase ever promotes a quarantined revision to eligible
    merely because wall-clock time passed. A later, separately-
    observed CLEAN revision can become eligible on its own; the
    quarantined one stays quarantined forever. No adapter exists yet
    (FX-57's job) to actually decide WHEN a revision is anomalous --
    this enum, and `NewsItemVintage.quarantine_reason`, only provide
    the structural capability a future adapter will use.
    """

    EVIDENCE_ELIGIBLE = "EVIDENCE_ELIGIBLE"
    QUARANTINED = "QUARANTINED"

from enum import Enum


class ForecastPerformanceExclusionReason(Enum):
    """FX-66 Section 6: WHY a candidate evaluation was excluded from a
    performance population -- every exclusion is recorded, never
    silently dropped (Section 6's own "an excluded evaluation must
    remain visible in the audit trail" requirement). Mirrors `Forecast
    EvaluationAdmissibility`'s own closed-set-of-named-reasons
    convention."""

    NOT_YET_AVAILABLE = "NOT_YET_AVAILABLE"
    """The evaluation's own `availability` is later than the
    population's requested knowledge cutoff -- this is a PIT boundary,
    never a content defect.

    Currently UNREACHABLE by construction as of FX-66H.1 (F66-04):
    `BuildForecastPerformancePopulationAsOf` fetches ONLY the AS-OF-
    BOUNDED read (`list_latest_evaluations_for_protocol_as_of`), whose
    every returned row already satisfies `availability <= as_of` --
    there is no longer any unbounded read to discover a too-new key's
    existence in the first place. The earlier FX-66 design deliberately
    used a second, unbounded read specifically to surface this reason
    in the audit trail, but that is exactly what let future knowledge
    leak into a historical result: a key FTA did not know about at
    `as_of` would still show up here, as an EXCLUSION, merely because
    it was later discovered to exist -- violating "historical
    exclusions must not include evaluation keys that FTA did not know
    existed at the cutoff." A key with zero eligible revisions is now
    simply never fetched and never appears anywhere in the population
    at all, exclusions included. Kept here, like `INCOMPATIBLE_HORIZON`,
    for forward compatibility and because old persisted snapshots may
    still name it."""

    MISSING_OR_UNRESOLVED_OUTCOME = "MISSING_OR_UNRESOLVED_OUTCOME"
    """Currently UNREACHABLE by construction, documented here only
    because Section 6 names it explicitly: `EvaluateStructuredForecast`
    never persists an evaluation vintage unless the outcome was
    already resolved as `OUTCOME_AVAILABLE` (an inadmissible attempt
    is rejected before ever reaching the repository) -- there is
    structurally no way for a PERSISTED evaluation to have a missing
    outcome. Kept for forward compatibility should a future story
    introduce a "pending evaluation" concept."""

    INCOMPATIBLE_TARGET = "INCOMPATIBLE_TARGET"
    """The underlying forecast's own `target_key` does not match the
    cohort's pinned target -- a different variable/measurement
    convention entirely (Section 4's own explicit warning)."""

    INCOMPATIBLE_FORECAST_TYPE = "INCOMPATIBLE_FORECAST_TYPE"
    """The underlying forecast's own `forecast_type` does not match
    the cohort's pinned type."""

    INCOMPATIBLE_HORIZON = "INCOMPATIBLE_HORIZON"
    """Currently UNREACHABLE: `horizon_category` is a cohort-identity/
    documentation dimension only in `fx66_v1` -- FX-64's own
    `StructuredForecastVintage` carries no per-forecast structural
    horizon/lead-time field to compare it against, and adding one
    would be a schema change to an existing FX-64 table, outside this
    story's own scope restrictions. See ADR 0014's own discovery
    findings. Kept here so a future story that DOES add such a field
    has a ready-made exclusion reason, rather than inventing a new
    one and silently diverging from this one's own intended meaning."""

    INCOMPATIBLE_ORIGINATOR = "INCOMPATIBLE_ORIGINATOR"
    """The underlying forecast's own attribution (kind, publisher,
    and -- for `NAMED_INSTITUTION` -- forecaster) does not match the
    cohort's pinned originator (Section 5)."""

    INCOMPATIBLE_PROTOCOL = "INCOMPATIBLE_PROTOCOL"
    """The evaluation's own `(protocol_key, protocol_version_sequence)`
    does not match the cohort's pinned protocol version -- this
    transitively also rules out an incompatible metric, since a
    protocol's own metric is fixed by its `supported_forecast_type`."""

    OUTSIDE_ISSUE_WINDOW = "OUTSIDE_ISSUE_WINDOW"
    """The underlying forecast vintage's own TRUE issue instant
    (`original_publication_at`, falling back to `availability` only
    when the forecast carries no `original_publication_at` -- Section
    4's own "forecast issue date" vs. "FTA availability" distinction)
    falls outside the cohort's pinned `[issue_window_start, issue_
    window_end]` bound."""

    KNOWN_DUPLICATE_SYNDICATED = "KNOWN_DUPLICATE_SYNDICATED"
    """The evaluation's own `evaluation_key` appears in the cohort's
    own curated `known_duplicate_evaluation_keys` list -- a human-
    identified syndicated/duplicate forecast, fixed independently of
    any realized error (Section 6/7)."""

    SUPERSEDED_BY_EARLIER_QUALIFYING_ISSUE = "SUPERSEDED_BY_EARLIER_QUALIFYING_ISSUE"
    """A DIFFERENT forecast issue, for the SAME originator and outcome
    event, was selected instead under the cohort's own `duplicate_
    selection_policy` (Section 7) -- grouped by shared `outcome_key`
    (FX-65H.2's own durable target-event identity), since the
    originator is already fixed cohort-wide by construction."""

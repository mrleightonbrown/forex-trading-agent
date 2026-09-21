from enum import Enum


class PointInTimeSafety(Enum):
    """How much a data SOURCE can be trusted to reproduce what the
    market actually knew at a past instant (FX-41; relocated onto
    `ProviderSeriesMapping` only by FX-42H -- see below).

    This classification exists because "point-in-time correct" is not
    a property a value can prove about itself — it is a property of
    the SOURCE the series' vintages come from. A source that only ever
    exposes the current/latest value of each observation period (no
    vintage history) can populate this same domain model with
    plausible-looking data that is silently wrong for any historical
    as-of query before the most recent revision. This enum makes that
    distinction an explicit, first-class fact instead of an assumption
    baked into a query result.

    - POINT_IN_TIME_SAFE: the source preserves enough vintage history
      that an as-of query for a past instant reproduces what was truly
      knowable at that instant, revisions included.
    - LATEST_ONLY: the source only ever gives the current value of each
      observation period. Any vintage stored for it MUST be treated as
      unsafe for historical research, even though it satisfies the
      same repository interface.
    - UNKNOWN: safety has not been established either way. Deliberately
      NOT treated as an alias for POINT_IN_TIME_SAFE.

    Fail-closed rule: only POINT_IN_TIME_SAFE may be used for historical
    research. LATEST_ONLY and UNKNOWN must both be rejected -- an
    unverified source is treated as unsafe, not as safe-until-proven-
    otherwise.

    FX-41 originally put this classification on `MacroSeriesDefinition`
    itself (the canonical, provider-independent concept). FX-42H
    removed it from there: a canonical concept is provider-independent
    by construction and has no source of its own to classify: only a
    `ProviderSeriesMapping` (`domain.provider_series_mapping`) -- a
    specific provider/identifier pair -- actually has a source, and so
    is the only place this classification now lives. The fail-closed
    guard is `require_research_usable_mapping`, which additionally
    requires `ProviderSeriesMapping.verified` to be `True` -- a mapping
    is not research-usable merely because a human judges its source
    type point-in-time-safe in the abstract; it must also have been
    concretely confirmed against the live provider.
    """

    POINT_IN_TIME_SAFE = "POINT_IN_TIME_SAFE"
    LATEST_ONLY = "LATEST_ONLY"
    UNKNOWN = "UNKNOWN"

from enum import Enum


class PointInTimeSafety(Enum):
    """How much a `MacroSeriesDefinition` can be trusted to reproduce
    what the market actually knew at a past instant (FX-41).

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
      NOT treated as an alias for POINT_IN_TIME_SAFE -- see
      `require_point_in_time_safe` in `macro_series_definition.py`.

    Fail-closed rule: only POINT_IN_TIME_SAFE may be used for historical
    research. LATEST_ONLY and UNKNOWN must both be rejected -- an
    unverified source is treated as unsafe, not as safe-until-proven-
    otherwise.
    """

    POINT_IN_TIME_SAFE = "POINT_IN_TIME_SAFE"
    LATEST_ONLY = "LATEST_ONLY"
    UNKNOWN = "UNKNOWN"

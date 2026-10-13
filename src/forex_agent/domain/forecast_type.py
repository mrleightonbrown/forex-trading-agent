from enum import Enum


class ForecastType(Enum):
    """FX-64 Section 4: the two initially-supported structured
    forecast classes. Deliberately closed -- a general probabilistic/
    distributional/threshold/directional forecast type is explicitly
    OUT of scope for this story (Section 4's own "Deferred types") and
    is never silently coerced into one of these two."""

    NUMERIC_POINT = "NUMERIC_POINT"
    """A forecast of a numeric variable at a defined target period or
    instant (Section 4.1) -- e.g. "euro-area HICP inflation for
    calendar year 2025 is 1.9%." A directional statement with no exact
    value ("inflation will be lower next year") is NOT this type and
    must never be silently converted into one."""

    CATEGORICAL_EVENT = "CATEGORICAL_EVENT"
    """A forecast of one outcome from an explicitly defined, closed
    set of alternatives (Section 4.2) -- today, only a central-bank
    HIKE/HOLD/CUT decision at an identified policy meeting. The source
    statement must actually support that exact classification; HOLD is
    never inferred merely because no change was explicitly forecast."""

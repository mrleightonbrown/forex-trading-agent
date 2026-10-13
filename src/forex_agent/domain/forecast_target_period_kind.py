from enum import Enum


class ForecastTargetPeriodKind(Enum):
    """FX-64 Section 10: the exact shape of a forecast's own target
    period/event -- never assumed to be a fixed number of days out
    from the forecast's own publication. Each `ForecastTargetDefinition`
    (Section 9) declares which ONE of these its own admitted forecasts
    must use, via `period_frequency`; a candidate using a different
    kind than its own target definition expects is rejected, never
    silently reinterpreted."""

    CALENDAR_YEAR = "CALENDAR_YEAR"
    CALENDAR_QUARTER = "CALENDAR_QUARTER"
    CALENDAR_MONTH = "CALENDAR_MONTH"
    SPECIFIC_DATE = "SPECIFIC_DATE"
    POLICY_MEETING = "POLICY_MEETING"
    """An explicit, independently-grounded policy meeting identity
    (Section 10) -- e.g. a specific Governing Council decision date --
    never a vague "next meeting" or a meeting FTA itself invents an
    identifier for."""

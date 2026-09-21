from enum import Enum


class MacroFrequency(Enum):
    """How often a `MacroSeriesDefinition` produces a new observation
    period (FX-41).

    Purely descriptive metadata about the series' cadence — it does not
    drive scheduling or ingestion (no such thing exists yet in this
    codebase) and it must never be inferred from provider release
    calendars, which is exactly the kind of provider-specific detail
    the canonical series identity must stay independent of.
    """

    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"
    IRREGULAR = "IRREGULAR"

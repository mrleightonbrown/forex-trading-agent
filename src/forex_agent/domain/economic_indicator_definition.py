from dataclasses import dataclass

from forex_agent.domain._guards import require_currency_code
from forex_agent.domain.economic_event_category import EconomicEventCategory
from forex_agent.domain.macro_frequency import MacroFrequency


@dataclass(frozen=True, slots=True)
class EconomicIndicatorDefinition:
    """Canonical, provider-independent identity of a scheduled economic
    event/indicator (FX-51) -- e.g. "US CPI (YoY)", "US Nonfarm
    Payrolls", "ECB policy-rate decision", "BoE meeting minutes".

    Deliberately mirrors `domain.macro_series_definition.
    MacroSeriesDefinition` (FX-41) as closely as the two concepts'
    otherwise-different lifecycles allow: no provider-specific ID (no
    calendar vendor's own event code), and -- for the identical reason
    FX-41 gave `MacroSeriesDefinition` -- NOT persisted in its own
    database table. A canonical economic concept ("US Nonfarm
    Payrolls exists and is a numeric, monthly, USD-denominated
    release") is provider-independent by construction and has no
    per-instance state of its own; every PIT-sensitive fact belongs on
    an `EconomicEventOccurrence` and its vintages instead, referencing
    this definition only by `key` (a bare string), exactly how
    `MacroObservationVintage.series_key` references `MacroSeriesDefinition.
    key` without a database foreign key. FX-52 (provider mapping) maps
    a calendar vendor's own event identifiers onto `key` without this
    class ever depending on any provider.

    Fields:
        key: stable canonical identifier, e.g. "US_CPI_YOY",
            "US_NONFARM_PAYROLLS", "ECB_POLICY_RATE_DECISION". Chosen
            by this codebase, not borrowed from any provider.
        name: human-readable display name, e.g. "US CPI (YoY)".
        economy: the economy/region the event describes, e.g. "US",
            "EA" (euro area) -- same convention as `MacroSeriesDefinition.
            economy`.
        currency: the ISO 4217 currency this event is most associated
            with. Deliberately singular, mirroring `MacroSeriesDefinition.
            currency` -- a genuine need for a multi-currency event is a
            future extension, not something FX-51 builds speculatively
            (CLAUDE.md: no design for hypothetical future requirements).
        category: what kind of event this is (see
            `EconomicEventCategory`).
        is_numeric: whether an occurrence of this event ever carries a
            numeric consensus/actual value. `False` for events like a
            central-bank press conference or meeting minutes, which
            still matter to event risk (FX-51 Section 18) despite
            having no number attached -- such an occurrence simply
            never gets a consensus or actual-value vintage.
        unit: the unit numeric values are expressed in, e.g. "PERCENT",
            "THOUSANDS", "INDEX_2015_100". Required (non-empty) when
            `is_numeric` is `True`; must be `None` when `is_numeric` is
            `False` -- a qualitative event has no unit to preserve.
            Free-form, not enforced against a fixed vocabulary, same
            convention as `MacroSeriesDefinition.unit`.
        frequency: how often a new occurrence/reference-period is
            produced. Reuses `domain.macro_frequency.MacroFrequency`
            unchanged -- cadence is the same concept for a continuous
            series and a scheduled event, and duplicating that enum
            here would be exactly the kind of unnecessary parallel
            taxonomy CLAUDE.md and FX-51's own Section 26 forbid.
    """

    key: str
    name: str
    economy: str
    currency: str
    category: EconomicEventCategory
    is_numeric: bool
    unit: str | None
    frequency: MacroFrequency

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key.strip():
            raise ValueError(f"key must be a non-empty string, got {self.key!r}")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"name must be a non-empty string, got {self.name!r}")
        if not isinstance(self.economy, str) or not self.economy.strip():
            raise ValueError(f"economy must be a non-empty string, got {self.economy!r}")
        require_currency_code("currency", self.currency)
        if not isinstance(self.category, EconomicEventCategory):
            raise TypeError(
                f"category must be an EconomicEventCategory, got {type(self.category)!r}"
            )
        if not isinstance(self.is_numeric, bool):
            raise TypeError(f"is_numeric must be a bool, got {type(self.is_numeric)!r}")
        if self.unit is not None and not isinstance(self.unit, str):
            raise TypeError(f"unit must be a str or None, got {type(self.unit)!r}")
        if self.is_numeric:
            if self.unit is None or not self.unit.strip():
                raise ValueError("unit must be a non-empty string when is_numeric is True")
        elif self.unit is not None:
            raise ValueError("unit must be None when is_numeric is False")
        if not isinstance(self.frequency, MacroFrequency):
            raise TypeError(f"frequency must be a MacroFrequency, got {type(self.frequency)!r}")

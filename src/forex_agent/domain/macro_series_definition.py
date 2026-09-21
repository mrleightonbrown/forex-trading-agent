from dataclasses import dataclass

from forex_agent.domain._guards import require_currency_code
from forex_agent.domain.macro_category import MacroCategory
from forex_agent.domain.macro_frequency import MacroFrequency


@dataclass(frozen=True, slots=True)
class MacroSeriesDefinition:
    """Canonical, provider-independent identity of a macro/fundamental
    series (FX-41).

    Deliberately holds no provider-specific ID (no FRED series ID, no
    central-bank API code, no vendor ticker). Infrastructure adapters
    map a provider's own identifiers onto this canonical identity when
    they translate provider responses into `MacroObservationVintage`
    records -- the domain model itself must support an official
    central-bank source, a FRED/ALFRED-style source, or a commercial
    provider without changing shape.

    Not persisted in its own database table -- see `docs/DECISIONS.md`
    (FX-41): keeping it a pure in-memory value object avoids building
    a generic economic-data warehouse before there is a second
    consumer that needs one.

    No `point_in_time_safety` field here -- FX-41 originally gave this
    class one (defaulting to `UNKNOWN`), but FX-42H removed it: a
    canonical economic CONCEPT ("the USD policy rate") is
    provider-independent by construction and has no point-in-time
    trustworthiness of its own to classify -- trustworthiness is a
    property of whichever SOURCE a research or ingestion consumer
    actually reads from. That property now lives solely on
    `ProviderSeriesMapping.point_in_time_safety` (`domain.
    provider_series_mapping`), guarded there by
    `require_research_usable_mapping`. See `docs/DECISIONS.md`'s FX-42H
    entry.

    Fields:
        key: stable canonical identifier, e.g. "US_CPI_YOY". Chosen by
            this codebase, not borrowed from any provider.
        economy: the economy/region the series describes, e.g. "US",
            "EA" (euro area). Not a currency code -- an economy may be
            described in a series without a single-currency mapping.
        currency: the ISO 4217 currency the series is denominated in
            or most associated with, reusing the same 3-letter
            uppercase validation as `Instrument`.
        category: what kind of macro fact this is (see `MacroCategory`).
        unit: the unit the observation values are expressed in, e.g.
            "PERCENT", "INDEX_2015_100". Free-form label, not enforced
            against a fixed vocabulary -- new units must not require a
            code change elsewhere.
        frequency: how often a new observation period is produced (see
            `MacroFrequency`).
    """

    key: str
    economy: str
    currency: str
    category: MacroCategory
    unit: str
    frequency: MacroFrequency

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key.strip():
            raise ValueError(f"key must be a non-empty string, got {self.key!r}")
        if not isinstance(self.economy, str) or not self.economy.strip():
            raise ValueError(f"economy must be a non-empty string, got {self.economy!r}")
        require_currency_code("currency", self.currency)
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError(f"unit must be a non-empty string, got {self.unit!r}")
        if not isinstance(self.category, MacroCategory):
            raise TypeError(f"category must be a MacroCategory, got {type(self.category)!r}")
        if not isinstance(self.frequency, MacroFrequency):
            raise TypeError(f"frequency must be a MacroFrequency, got {type(self.frequency)!r}")

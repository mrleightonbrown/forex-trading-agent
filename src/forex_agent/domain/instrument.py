from dataclasses import dataclass

from forex_agent.domain._guards import require_currency_code


@dataclass(frozen=True, slots=True)
class Instrument:
    """A tradeable currency pair.

    Provider-agnostic by design — CLAUDE.md: "Provider-specific objects must
    not escape infrastructure adapters." An OANDA (or any other broker)
    adapter is responsible for translating to/from this type.
    """

    base_currency: str
    quote_currency: str
    pip_decimal_places: int = 4

    def __post_init__(self) -> None:
        require_currency_code("base_currency", self.base_currency)
        require_currency_code("quote_currency", self.quote_currency)
        if self.base_currency == self.quote_currency:
            raise ValueError("base_currency and quote_currency must differ")
        if self.pip_decimal_places <= 0:
            raise ValueError(f"pip_decimal_places must be positive, got {self.pip_decimal_places}")

    @property
    def symbol(self) -> str:
        """Canonical `BASE_QUOTE` form, e.g. `EUR_USD`."""
        return f"{self.base_currency}_{self.quote_currency}"

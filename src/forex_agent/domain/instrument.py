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


def parse_instrument(pair_code: str, *, pip_decimal_places: int = 4) -> Instrument:
    """Parses a human-readable `"BASE/QUOTE"` pair code (e.g.
    `"EUR/USD"`) into an `Instrument` -- FX-60 Section 4's own
    explicit instruction to reuse this type's existing contract
    rather than inventing a parallel symbol system. Every currency-
    code-format and same-currency validation rule is delegated
    entirely to `Instrument.__post_init__`; this function only
    recognizes the `"BASE/QUOTE"` separator shape itself, raising
    `ValueError` for anything else (wrong separator, wrong part
    count, a blank base or quote)."""
    parts = pair_code.split("/")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise ValueError(
            f'pair_code must be in "BASE/QUOTE" form (e.g. "EUR/USD"), got {pair_code!r}'
        )
    base, quote = parts
    return Instrument(
        base_currency=base.strip(),
        quote_currency=quote.strip(),
        pip_decimal_places=pip_decimal_places,
    )

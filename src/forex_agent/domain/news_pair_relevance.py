"""FX-60 Sections 5/22-27: whether, and how, one piece of CURRENT
FX-59 semantic evidence is relevant to a specific currency pair --
mirrors `domain.pair_currency_role`'s own structural, non-directional
classification exactly, generalized for the case where a single piece
of evidence can legitimately be relevant to BOTH pair currencies at
once (an economic event concerns exactly one currency by
construction; a news item's own `currency_relevance` does not share
that constraint).

**Pair relevance comes ONLY from `NewsSemanticClassification.
currency_relevance` (Section 22/23)** -- this module never re-derives
relevance from entities, jurisdictions, topics, or text; FX-59 alone
owns that decision. `classify_pair_relevance` is a pure function: no
I/O, no re-interpretation of FX-59's own output, just a structural
BASE/QUOTE/BOTH classification over whichever currency codes FX-59
already decided were relevant.

**No directional meaning whatsoever (Section 5)**: `BASE_ONLY` means
"this evidence is relevant to the pair's base currency," never
"bullish base" or "buy this pair"; `QUOTE_ONLY`/`BOTH` are equally
non-directional. See this module's own `NewsPairRelevanceSide`
docstring."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.domain.instrument import Instrument
from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason


class NewsPairRelevanceSide(Enum):
    """FX-60 Section 5/24: purely categorical relevance LOCATION,
    never a directional/bullish/bearish/sentiment signal of any kind.

    `BASE_ONLY`: FX-59's own `currency_relevance` named the pair's
    base currency, but not its quote currency.
    `QUOTE_ONLY`: the reverse.
    `BOTH`: FX-59's own `currency_relevance` named BOTH currencies --
    this does NOT mean the story is "stronger," "conflicting," or
    "neutral" (Section 5); it means different source-native
    representations (or one single item) provided explicit relevance
    evidence for both sides of the pair."""

    BASE_ONLY = "BASE_ONLY"
    QUOTE_ONLY = "QUOTE_ONLY"
    BOTH = "BOTH"


@dataclass(frozen=True, slots=True)
class NewsPairRelevance:
    """One piece of evidence's own pair relevance, with the ORIGINAL
    FX-59 reasons preserved verbatim (Section 25) -- never collapsed
    into a generic "relevant" flag that would throw the evidence away.

    `base_relevance_reasons`/`quote_relevance_reasons` are each a
    canonical sorted, deduplicated, NON-EMPTY tuple whenever that side
    is actually present (`BASE_ONLY`/`BOTH` imply `base_relevance_
    reasons` is non-empty; `QUOTE_ONLY`/`BOTH` imply `quote_relevance_
    reasons` is non-empty); the absent side's own tuple is always
    empty."""

    side: NewsPairRelevanceSide
    base_relevance_reasons: tuple[NewsCurrencyRelevanceReason, ...]
    quote_relevance_reasons: tuple[NewsCurrencyRelevanceReason, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.side, NewsPairRelevanceSide):
            raise TypeError(f"side must be a NewsPairRelevanceSide, got {type(self.side).__name__}")
        _validate_reasons("base_relevance_reasons", self.base_relevance_reasons)
        _validate_reasons("quote_relevance_reasons", self.quote_relevance_reasons)

        has_base = bool(self.base_relevance_reasons)
        has_quote = bool(self.quote_relevance_reasons)
        if self.side is NewsPairRelevanceSide.BASE_ONLY and not (has_base and not has_quote):
            raise ValueError("BASE_ONLY requires non-empty base reasons and empty quote reasons")
        if self.side is NewsPairRelevanceSide.QUOTE_ONLY and not (has_quote and not has_base):
            raise ValueError("QUOTE_ONLY requires non-empty quote reasons and empty base reasons")
        if self.side is NewsPairRelevanceSide.BOTH and not (has_base and has_quote):
            raise ValueError("BOTH requires non-empty reasons on both sides")


def _validate_reasons(name: str, reasons: tuple[NewsCurrencyRelevanceReason, ...]) -> None:
    if not isinstance(reasons, tuple):
        raise TypeError(f"{name} must be a tuple, got {type(reasons).__name__}")
    for reason in reasons:
        if not isinstance(reason, NewsCurrencyRelevanceReason):
            raise TypeError(
                f"each {name} entry must be a NewsCurrencyRelevanceReason, got "
                f"{type(reason).__name__}"
            )
    if len(set(reasons)) != len(reasons):
        raise ValueError(f"{name} must not contain duplicates, got {reasons!r}")
    canonical = tuple(sorted(reasons, key=lambda r: r.value))
    if reasons != canonical:
        raise ValueError(
            f"{name} must be in canonical sorted order, got {reasons!r}, expected {canonical!r}"
        )


def classify_pair_relevance(
    instrument: Instrument, currency_relevance: tuple[NewsCurrencyRelevance, ...]
) -> NewsPairRelevance | None:
    """Returns this pair's own `NewsPairRelevance` for `currency_
    relevance` (already-decided FX-59 output, Section 22), or `None`
    if neither `instrument.base_currency` nor `instrument.quote_
    currency` appears in it at all -- `None` means this evidence is
    simply not a pair-evidence entry for this pair (Section 24's own
    "neither: not a pair-evidence entry"). Pure: no re-derivation of
    relevance from entities/jurisdictions/topics/text (Section 23)."""
    base_entry = next(
        (r for r in currency_relevance if r.currency_code == instrument.base_currency), None
    )
    quote_entry = next(
        (r for r in currency_relevance if r.currency_code == instrument.quote_currency), None
    )
    if base_entry is None and quote_entry is None:
        return None

    base_reasons = base_entry.reasons if base_entry is not None else ()
    quote_reasons = quote_entry.reasons if quote_entry is not None else ()
    if base_entry is not None and quote_entry is not None:
        side = NewsPairRelevanceSide.BOTH
    elif base_entry is not None:
        side = NewsPairRelevanceSide.BASE_ONLY
    else:
        side = NewsPairRelevanceSide.QUOTE_ONLY

    return NewsPairRelevance(
        side=side, base_relevance_reasons=base_reasons, quote_relevance_reasons=quote_reasons
    )

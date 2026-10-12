"""FX-60 Sections 55-56/74: pin `classify_pair_relevance`'s own
BASE_ONLY/QUOTE_ONLY/BOTH/excluded behavior and reason preservation,
plus `NewsPairRelevance`'s own domain validation."""

import pytest

from forex_agent.domain.instrument import Instrument
from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
from forex_agent.domain.news_pair_relevance import (
    NewsPairRelevance,
    NewsPairRelevanceSide,
    classify_pair_relevance,
)

EURUSD = Instrument(base_currency="EUR", quote_currency="USD")


def _relevance(code: str, *reasons: NewsCurrencyRelevanceReason) -> NewsCurrencyRelevance:
    return NewsCurrencyRelevance(
        currency_code=code, reasons=tuple(sorted(reasons, key=lambda r: r.value))
    )


def test_base_only() -> None:
    result = classify_pair_relevance(
        EURUSD, (_relevance("EUR", NewsCurrencyRelevanceReason.SOURCE_JURISDICTION),)
    )

    assert result is not None
    assert result.side is NewsPairRelevanceSide.BASE_ONLY
    assert result.quote_relevance_reasons == ()


def test_quote_only() -> None:
    result = classify_pair_relevance(
        EURUSD, (_relevance("USD", NewsCurrencyRelevanceReason.SOURCE_JURISDICTION),)
    )

    assert result is not None
    assert result.side is NewsPairRelevanceSide.QUOTE_ONLY
    assert result.base_relevance_reasons == ()


def test_both() -> None:
    result = classify_pair_relevance(
        EURUSD,
        (
            _relevance("EUR", NewsCurrencyRelevanceReason.SOURCE_JURISDICTION),
            _relevance("USD", NewsCurrencyRelevanceReason.EXPLICIT_CURRENCY_MENTION),
        ),
    )

    assert result is not None
    assert result.side is NewsPairRelevanceSide.BOTH
    assert result.base_relevance_reasons != ()
    assert result.quote_relevance_reasons != ()


def test_cad_only_excluded_as_pair_irrelevant() -> None:
    result = classify_pair_relevance(
        EURUSD, (_relevance("CAD", NewsCurrencyRelevanceReason.SOURCE_JURISDICTION),)
    )

    assert result is None


def test_empty_currency_relevance_excluded() -> None:
    result = classify_pair_relevance(EURUSD, ())

    assert result is None


# --- Section 56: reason preservation -----------------------------------------


def test_reasons_preserved_verbatim_for_base() -> None:
    result = classify_pair_relevance(
        EURUSD, (_relevance("EUR", NewsCurrencyRelevanceReason.SOURCE_JURISDICTION),)
    )

    assert result is not None
    assert result.base_relevance_reasons == (NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)


def test_reasons_preserved_verbatim_for_quote() -> None:
    result = classify_pair_relevance(
        EURUSD, (_relevance("USD", NewsCurrencyRelevanceReason.EXPLICIT_CURRENCY_MENTION),)
    )

    assert result is not None
    assert result.quote_relevance_reasons == (
        NewsCurrencyRelevanceReason.EXPLICIT_CURRENCY_MENTION,
    )


def test_multiple_reasons_on_same_currency_preserved() -> None:
    result = classify_pair_relevance(
        EURUSD,
        (
            _relevance(
                "USD",
                NewsCurrencyRelevanceReason.EXPLICIT_CURRENCY_MENTION,
                NewsCurrencyRelevanceReason.EXPLICIT_INSTITUTION_MENTION,
            ),
        ),
    )

    assert result is not None
    assert result.quote_relevance_reasons == (
        NewsCurrencyRelevanceReason.EXPLICIT_CURRENCY_MENTION,
        NewsCurrencyRelevanceReason.EXPLICIT_INSTITUTION_MENTION,
    )


# --- Domain validation (Section 74) ------------------------------------------


def test_base_only_cannot_claim_quote_reasons() -> None:
    with pytest.raises(ValueError, match="BASE_ONLY"):
        NewsPairRelevance(
            side=NewsPairRelevanceSide.BASE_ONLY,
            base_relevance_reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
            quote_relevance_reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
        )


def test_quote_only_cannot_claim_base_reasons() -> None:
    with pytest.raises(ValueError, match="QUOTE_ONLY"):
        NewsPairRelevance(
            side=NewsPairRelevanceSide.QUOTE_ONLY,
            base_relevance_reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
            quote_relevance_reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
        )


def test_both_requires_relevance_evidence_for_both_sides() -> None:
    with pytest.raises(ValueError, match="BOTH"):
        NewsPairRelevance(
            side=NewsPairRelevanceSide.BOTH,
            base_relevance_reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
            quote_relevance_reasons=(),
        )


def test_duplicate_reasons_rejected() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        NewsPairRelevance(
            side=NewsPairRelevanceSide.BASE_ONLY,
            base_relevance_reasons=(
                NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,
                NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,
            ),
            quote_relevance_reasons=(),
        )


def test_noncanonical_reason_order_rejected() -> None:
    with pytest.raises(ValueError, match="canonical sorted order"):
        NewsPairRelevance(
            side=NewsPairRelevanceSide.BASE_ONLY,
            base_relevance_reasons=(
                NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,
                NewsCurrencyRelevanceReason.EXPLICIT_CURRENCY_MENTION,
            ),
            quote_relevance_reasons=(),
        )


def test_no_direction_field_exists() -> None:
    # Section 75: introspect the surface for a stray direction/
    # sentiment-style field.
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(NewsPairRelevance)}
    forbidden = {"direction", "sentiment", "stance", "bias", "bullish", "bearish", "score"}
    assert field_names.isdisjoint(forbidden)

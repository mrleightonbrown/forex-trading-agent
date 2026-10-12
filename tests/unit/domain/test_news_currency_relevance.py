import pytest

from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason


def test_valid_currency_relevance_constructs() -> None:
    relevance = NewsCurrencyRelevance(
        currency_code="USD", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
    )
    assert relevance.currency_code == "USD"


def test_invalid_currency_code_rejected() -> None:
    with pytest.raises(ValueError, match="currency_code"):
        NewsCurrencyRelevance(
            currency_code="usd", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
        )


def test_empty_reasons_rejected() -> None:
    with pytest.raises(ValueError, match="reasons"):
        NewsCurrencyRelevance(currency_code="USD", reasons=())


def test_duplicate_reasons_rejected() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        NewsCurrencyRelevance(
            currency_code="USD",
            reasons=(
                NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,
                NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,
            ),
        )


def test_multiple_distinct_reasons_consolidated_into_one_entry() -> None:
    relevance = NewsCurrencyRelevance(
        currency_code="USD",
        reasons=(
            NewsCurrencyRelevanceReason.EXPLICIT_CURRENCY_MENTION,
            NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,
        ),
    )
    assert len(relevance.reasons) == 2


def test_noncanonical_reason_order_rejected() -> None:
    with pytest.raises(ValueError, match="canonical sorted order"):
        NewsCurrencyRelevance(
            currency_code="USD",
            reasons=(
                NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,
                NewsCurrencyRelevanceReason.EXPLICIT_CURRENCY_MENTION,
            ),
        )

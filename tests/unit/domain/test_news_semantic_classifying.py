"""FX-59 Sections 68-72: pins the `fx59_v1` classifier's own source-
profile mappings, alias matching (with boundary negatives), currency
relevance rules, topic rules, and the explicit no-sentiment
regression -- all against `classify_news_semantics`, the pure
classifier (no DB, no I/O)."""

import dataclasses
from datetime import UTC, datetime

import pytest

from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_semantic_classifying import (
    NewsSemanticClassificationCandidate,
    classify_news_semantics,
)
from forex_agent.domain.news_semantic_source_profile import UnsupportedNewsSemanticSourceError
from forex_agent.domain.news_topic import NewsTopic
from forex_agent.domain.timestamps import UtcTimestamp


def _candidate(
    source_key: str,
    headline: str = "H",
    summary: str | None = None,
    body_text: str | None = None,
) -> NewsSemanticClassificationCandidate:
    return NewsSemanticClassificationCandidate(
        news_item_key="K1",
        source_key=source_key,
        basis_news_item_revision_sequence=0,
        basis_availability=UtcTimestamp(datetime(2026, 1, 1, 10, tzinfo=UTC)),
        headline=headline,
        summary=summary,
        body_text=body_text,
        source_content_type=None,
        source_channel=None,
    )


def _currency_codes(classification) -> set[str]:  # type: ignore[no-untyped-def]
    return {r.currency_code for r in classification.currency_relevance}


def _entity_keys(classification, entity_type: NewsEntityType) -> set[str]:  # type: ignore[no-untyped-def]
    return {e.entity_key for e in classification.entities if e.entity_type is entity_type}


# --- Section 68: source profiles -------------------------------------------


@pytest.mark.parametrize(
    "source_key,institution,jurisdiction,currency",
    [
        ("FED", "FEDERAL_RESERVE", "UNITED_STATES", "USD"),
        ("ECB", "EUROPEAN_CENTRAL_BANK", "EURO_AREA", "EUR"),
        ("BOE", "BANK_OF_ENGLAND", "UNITED_KINGDOM", "GBP"),
        ("GOVUK_HMT", "HM_TREASURY", "UNITED_KINGDOM", "GBP"),
        ("STATCAN", "STATISTICS_CANADA", "CANADA", "CAD"),
        ("BOC", "BANK_OF_CANADA", "CANADA", "CAD"),
    ],
)
def test_source_profile_entities_and_currency(
    source_key: str, institution: str, jurisdiction: str, currency: str
) -> None:
    classification = classify_news_semantics(_candidate(source_key, headline="Routine update."))
    institutions = {
        e for e in classification.entities if e.entity_type is NewsEntityType.INSTITUTION
    }
    jurisdictions = {
        e for e in classification.entities if e.entity_type is NewsEntityType.JURISDICTION
    }
    assert any(e.entity_key == institution for e in institutions)
    assert any(e.entity_key == jurisdiction for e in jurisdictions)
    assert classification.currency_relevance[0].currency_code == currency or any(
        r.currency_code == currency for r in classification.currency_relevance
    )
    primary = next(r for r in classification.currency_relevance if r.currency_code == currency)
    assert NewsCurrencyRelevanceReason.SOURCE_JURISDICTION in primary.reasons


def test_no_topic_created_merely_from_publisher_identity() -> None:
    # Section 44: Fed -> MONETARY_POLICY must NOT happen from source
    # identity alone, with deliberately neutral text.
    classification = classify_news_semantics(
        _candidate(
            "FED", headline="Building maintenance notice.", body_text="The building will be closed."
        )
    )
    assert classification.topics == ()


def test_unknown_source_fails_closed() -> None:
    with pytest.raises(UnsupportedNewsSemanticSourceError):
        classify_news_semantics(_candidate("UNKNOWN_SOURCE"))


# --- Section 69: alias matching + boundary negatives -----------------------


def test_federal_reserve_mention_matched() -> None:
    classification = classify_news_semantics(
        _candidate("ECB", headline="The Federal Reserve announced a decision.")
    )
    assert "FEDERAL_RESERVE" in _entity_keys(classification, NewsEntityType.INSTITUTION)


def test_fomc_mention_matched() -> None:
    classification = classify_news_semantics(_candidate("ECB", headline="FOMC minutes released."))
    assert "FEDERAL_OPEN_MARKET_COMMITTEE" in _entity_keys(
        classification, NewsEntityType.INSTITUTION
    )


def test_ecb_mention_matched() -> None:
    classification = classify_news_semantics(_candidate("FED", headline="The ECB raised rates."))
    assert "EUROPEAN_CENTRAL_BANK" in _entity_keys(classification, NewsEntityType.INSTITUTION)


def test_bank_of_england_mention_matched() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="Bank of England held its rate.")
    )
    assert "BANK_OF_ENGLAND" in _entity_keys(classification, NewsEntityType.INSTITUTION)


def test_hm_treasury_mention_matched() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="HM Treasury published a report.")
    )
    assert "HM_TREASURY" in _entity_keys(classification, NewsEntityType.INSTITUTION)


def test_statistics_canada_mention_matched() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="Statistics Canada released new data.")
    )
    assert "STATISTICS_CANADA" in _entity_keys(classification, NewsEntityType.INSTITUTION)


def test_bank_of_canada_mention_matched() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="Bank of Canada held rates.")
    )
    assert "BANK_OF_CANADA" in _entity_keys(classification, NewsEntityType.INSTITUTION)


def test_united_states_mention_matched() -> None:
    classification = classify_news_semantics(
        _candidate("ECB", headline="Growth continued in the United States.")
    )
    assert "UNITED_STATES" in _entity_keys(classification, NewsEntityType.JURISDICTION)


def test_us_abbreviation_mention_matched() -> None:
    classification = classify_news_semantics(
        _candidate("ECB", headline="Growth in the U.S. slowed.")
    )
    assert "UNITED_STATES" in _entity_keys(classification, NewsEntityType.JURISDICTION)


def test_euro_area_mention_matched() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="The euro area saw inflation ease.")
    )
    assert "EURO_AREA" in _entity_keys(classification, NewsEntityType.JURISDICTION)


def test_united_kingdom_mention_matched() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="The United Kingdom reported growth.")
    )
    assert "UNITED_KINGDOM" in _entity_keys(classification, NewsEntityType.JURISDICTION)


def test_canadian_mention_matched() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="Canadian exports rose last quarter.")
    )
    assert "CANADA" in _entity_keys(classification, NewsEntityType.JURISDICTION)


def test_pronoun_us_does_not_match_united_states() -> None:
    classification = classify_news_semantics(
        _candidate("ECB", headline="The committee told us the decision was final.")
    )
    assert "UNITED_STATES" not in _entity_keys(classification, NewsEntityType.JURISDICTION)


def test_decade_does_not_match_cad() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="Looking ahead over the coming decade.")
    )
    assert "CAD" not in _currency_codes(classification)


def test_substring_containing_ecb_characters_does_not_match() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="The specbook was updated.")  # contains "ecb" substring
    )
    assert "EUROPEAN_CENTRAL_BANK" not in _entity_keys(classification, NewsEntityType.INSTITUTION)


def test_bare_dollar_does_not_select_any_currency() -> None:
    classification = classify_news_semantics(
        _candidate("ECB", headline="The dollar strengthened broadly today.")
    )
    # Only the source's own primary currency (EUR) may be present --
    # bare "dollar" alone must never select USD or CAD.
    assert _currency_codes(classification) == {"EUR"}


# --- Section 70: currency-relevance rules -----------------------------------


def test_fed_article_with_no_foreign_references_is_usd_only() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="The committee met to discuss conditions.")
    )
    assert _currency_codes(classification) == {"USD"}


def test_fed_article_mentioning_bank_of_canada_adds_cad() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="Officials compared notes with the Bank of Canada.")
    )
    assert _currency_codes(classification) == {"USD", "CAD"}


def test_ecb_article_mentioning_sterling_adds_gbp() -> None:
    classification = classify_news_semantics(
        _candidate("ECB", headline="The report noted sterling's recent moves.")
    )
    assert _currency_codes(classification) == {"EUR", "GBP"}


def test_boc_article_mentioning_united_states_is_cad_only() -> None:
    # Section 31: a bare jurisdiction mention never adds currency
    # relevance on its own.
    classification = classify_news_semantics(
        _candidate("BOC", headline="Trade with the United States remained strong.")
    )
    assert _currency_codes(classification) == {"CAD"}


def test_boc_article_mentioning_us_dollar_adds_usd() -> None:
    classification = classify_news_semantics(
        _candidate("BOC", headline="The Canadian dollar weakened against the U.S. dollar.")
    )
    assert _currency_codes(classification) == {"CAD", "USD"}


def test_multiple_reasons_for_same_currency_consolidated() -> None:
    # The source's own currency (CAD/SOURCE_JURISDICTION) PLUS an
    # explicit currency mention of the same code (CAD/EXPLICIT_
    # CURRENCY_MENTION) must consolidate into ONE entry.
    classification = classify_news_semantics(
        _candidate("BOC", headline="The Canadian dollar held steady today.")
    )
    cad_entries = [r for r in classification.currency_relevance if r.currency_code == "CAD"]
    assert len(cad_entries) == 1
    assert NewsCurrencyRelevanceReason.SOURCE_JURISDICTION in cad_entries[0].reasons
    assert NewsCurrencyRelevanceReason.EXPLICIT_CURRENCY_MENTION in cad_entries[0].reasons


# --- Section 71: topic rules -------------------------------------------------


@pytest.mark.parametrize(
    "topic,text",
    [
        (NewsTopic.MONETARY_POLICY, "The committee set monetary policy today."),
        (NewsTopic.INFLATION_PRICES, "Inflation eased for the third month."),
        (NewsTopic.LABOUR_EMPLOYMENT, "The labour market remains tight."),
        (NewsTopic.GROWTH_ACTIVITY, "Gross domestic product rose 2 percent."),
        (NewsTopic.INTERNATIONAL_TRADE, "The trade balance narrowed."),
        (NewsTopic.FISCAL_POLICY, "The budget outlined new fiscal policy."),
        (NewsTopic.FINANCIAL_STABILITY, "The report assessed financial stability."),
        (NewsTopic.BANKING_REGULATION, "New capital requirements were proposed."),
        (NewsTopic.EXCHANGE_RATES, "The exchange rate moved sharply."),
    ],
)
def test_topic_positive_example(topic: NewsTopic, text: str) -> None:
    classification = classify_news_semantics(_candidate("FED", headline=text))
    assert topic in {t.topic for t in classification.topics}


def test_topic_negative_example_no_match() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="The building lobby was repainted blue.")
    )
    assert classification.topics == ()


def test_international_alone_does_not_trigger_trade_topic() -> None:
    # Section 39: the bare word "international" must not infer
    # INTERNATIONAL_TRADE.
    classification = classify_news_semantics(
        _candidate("FED", headline="An international delegation visited today.")
    )
    assert NewsTopic.INTERNATIONAL_TRADE not in {t.topic for t in classification.topics}


def test_hmt_story_without_fiscal_text_is_not_fiscal_policy() -> None:
    # Section 40: publisher identity (HMT) alone must never imply
    # FISCAL_POLICY -- text evidence is still required.
    classification = classify_news_semantics(
        _candidate("GOVUK_HMT", headline="A new overseas trade mission was announced.")
    )
    assert NewsTopic.FISCAL_POLICY not in {t.topic for t in classification.topics}


def test_exchange_rates_not_inferred_merely_from_currency_code_presence() -> None:
    # Section 43: a currency code appearing once must not, by itself,
    # classify EXCHANGE_RATES.
    classification = classify_news_semantics(
        _candidate("FED", headline="The USD was mentioned once.")
    )
    assert NewsTopic.EXCHANGE_RATES not in {t.topic for t in classification.topics}


def test_multi_topic_story() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="Monetary policy decision amid rising inflation.")
    )
    topics = {t.topic for t in classification.topics}
    assert NewsTopic.MONETARY_POLICY in topics
    assert NewsTopic.INFLATION_PRICES in topics
    assert len(topics) >= 2


def test_zero_topic_story() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="A routine staff announcement.")
    )
    assert classification.topics == ()


def test_same_terms_different_case_still_match() -> None:
    classification = classify_news_semantics(_candidate("FED", headline="INFLATION rose again."))
    assert NewsTopic.INFLATION_PRICES in {t.topic for t in classification.topics}


def test_html_entity_normalization_in_topic_matching() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="Monetary&nbsp;policy was reviewed.")
    )
    assert NewsTopic.MONETARY_POLICY in {t.topic for t in classification.topics}


def test_whitespace_variation_in_topic_matching() -> None:
    classification = classify_news_semantics(
        _candidate("FED", headline="Monetary    policy   decision made.")
    )
    assert NewsTopic.MONETARY_POLICY in {t.topic for t in classification.topics}


def test_token_boundary_false_positive_avoided() -> None:
    # "CPI" must not match inside an unrelated longer token.
    classification = classify_news_semantics(_candidate("FED", headline="The ACPIX fund rose."))
    assert NewsTopic.INFLATION_PRICES not in {t.topic for t in classification.topics}


# --- Section 72: no stance/sentiment regression -----------------------------


def test_hawkish_dovish_bullish_bearish_text_produces_no_sentiment_field() -> None:
    classification = classify_news_semantics(
        _candidate(
            "FED",
            headline="Hawkish tone surprises markets.",
            body_text="Commentators called the statement hawkish, even bullish for the dollar, "
            "while others saw a dovish, bearish undertone.",
        )
    )
    # The classification surface carries only entities/topics/
    # currency_relevance -- no sentiment/stance attribute exists at all.
    field_names = {f.name for f in dataclasses.fields(classification)}
    assert field_names == {"entities", "topics", "currency_relevance"}

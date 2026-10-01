import pytest

from forex_agent.domain.news_item_identity import mint_news_item_key


def test_mint_produces_a_source_prefixed_key() -> None:
    key = mint_news_item_key("FED")
    assert key.startswith("FED:")


def test_mint_is_unique_each_call() -> None:
    assert mint_news_item_key("FED") != mint_news_item_key("FED")


def test_source_key_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="source_key"):
        mint_news_item_key("")

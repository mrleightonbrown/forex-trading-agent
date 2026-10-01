import pytest

from forex_agent.domain.news_source_identity import NewsSourceIdentity


def test_valid_identity_constructs() -> None:
    identity = NewsSourceIdentity(source_key="FED", external_item_id="monetary20260916a")
    assert identity.source_key == "FED"
    assert identity.external_item_id == "monetary20260916a"


def test_source_key_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="source_key"):
        NewsSourceIdentity(source_key="", external_item_id="x")


def test_external_item_id_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="external_item_id"):
        NewsSourceIdentity(source_key="FED", external_item_id="")


def test_two_identities_with_same_values_are_equal() -> None:
    a = NewsSourceIdentity(source_key="FED", external_item_id="x")
    b = NewsSourceIdentity(source_key="FED", external_item_id="x")
    assert a == b
    assert hash(a) == hash(b)


def test_different_external_item_id_is_a_different_identity() -> None:
    a = NewsSourceIdentity(source_key="FED", external_item_id="x")
    b = NewsSourceIdentity(source_key="FED", external_item_id="y")
    assert a != b

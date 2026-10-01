from forex_agent.domain.news_source_registry import (
    admitted_prospective_text_source_keys,
    source_by_key,
)


def test_exactly_six_admitted_text_bearing_sources() -> None:
    # FX-55/FX-55H's own adopted-prospective-set confirmation.
    assert admitted_prospective_text_source_keys() == {
        "FED",
        "ECB",
        "BOE",
        "GOVUK_HMT",
        "STATCAN",
        "BOC",
    }


def test_source_by_key_returns_none_for_unadmitted_source() -> None:
    # BEA (DEFER), GDELT (ADOPT_AUXILIARY_METADATA, excluded), and any
    # commercial provider must have NO entry at all (ADR 0005/FX-55H).
    assert source_by_key("BEA") is None
    assert source_by_key("GDELT") is None
    assert source_by_key("REUTERS") is None


def test_every_admitted_source_is_flagged_admitted() -> None:
    for key in admitted_prospective_text_source_keys():
        definition = source_by_key(key)
        assert definition is not None
        assert definition.admitted_for_prospective_text is True

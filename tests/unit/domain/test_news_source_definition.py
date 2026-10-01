import pytest

from forex_agent.domain.news_source_definition import NewsSourceDefinition


def test_valid_definition_constructs() -> None:
    definition = NewsSourceDefinition(
        source_key="FED",
        display_name="Federal Reserve Board / FOMC",
        source_family="CENTRAL_BANK",
        admitted_for_prospective_text=True,
    )
    assert definition.admitted_for_prospective_text is True


@pytest.mark.parametrize("field", ["source_key", "display_name", "source_family"])
def test_text_fields_must_be_non_empty(field: str) -> None:
    kwargs: dict[str, object] = {
        "source_key": "FED",
        "display_name": "Federal Reserve Board / FOMC",
        "source_family": "CENTRAL_BANK",
        "admitted_for_prospective_text": True,
    }
    kwargs[field] = ""
    with pytest.raises(ValueError, match=field):
        NewsSourceDefinition(**kwargs)  # type: ignore[arg-type]


def test_admitted_flag_must_be_a_bool() -> None:
    with pytest.raises(TypeError, match="admitted_for_prospective_text"):
        NewsSourceDefinition(
            source_key="FED",
            display_name="Federal Reserve Board / FOMC",
            source_family="CENTRAL_BANK",
            admitted_for_prospective_text="yes",  # type: ignore[arg-type]
        )

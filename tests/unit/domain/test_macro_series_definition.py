import pytest

from forex_agent.domain.macro_category import MacroCategory
from forex_agent.domain.macro_frequency import MacroFrequency
from forex_agent.domain.macro_series_definition import MacroSeriesDefinition


def _series(**overrides: object) -> MacroSeriesDefinition:
    defaults: dict[str, object] = {
        "key": "US_CPI_YOY",
        "economy": "US",
        "currency": "USD",
        "category": MacroCategory.INFLATION,
        "unit": "PERCENT",
        "frequency": MacroFrequency.MONTHLY,
    }
    defaults.update(overrides)
    return MacroSeriesDefinition(**defaults)  # type: ignore[arg-type]


def test_valid_series_definition_holds_fields() -> None:
    series = _series()

    assert series.key == "US_CPI_YOY"
    assert series.economy == "US"
    assert series.currency == "USD"


def test_rejects_empty_key() -> None:
    with pytest.raises(ValueError, match="key"):
        _series(key="")


def test_rejects_empty_economy() -> None:
    with pytest.raises(ValueError, match="economy"):
        _series(economy="")


def test_rejects_empty_unit() -> None:
    with pytest.raises(ValueError, match="unit"):
        _series(unit="")


@pytest.mark.parametrize("code", ["usd", "US", "DOLLARS", "123"])
def test_rejects_invalid_currency_code(code: str) -> None:
    with pytest.raises(ValueError, match="currency code"):
        _series(currency=code)


def test_rejects_wrong_category_type() -> None:
    with pytest.raises(TypeError, match="category"):
        _series(category="INFLATION")


def test_rejects_wrong_frequency_type() -> None:
    with pytest.raises(TypeError, match="frequency"):
        _series(frequency="MONTHLY")


def test_series_definition_is_immutable() -> None:
    series = _series()

    with pytest.raises(AttributeError):
        series.key = "OTHER"  # type: ignore[misc]


def test_no_provider_specific_id_field_exists() -> None:
    # FX-41: canonical identity must not carry provider IDs (FRED series
    # ID, central-bank API code, vendor ticker, ...). Asserted structurally
    # rather than by convention, so adding one later trips this test.
    field_names = set(MacroSeriesDefinition.__dataclass_fields__)
    assert field_names == {
        "key",
        "economy",
        "currency",
        "category",
        "unit",
        "frequency",
    }


def test_no_point_in_time_safety_field_exists() -> None:
    # FX-42H: point-in-time safety is now tracked solely on
    # ProviderSeriesMapping, not on the canonical series itself -- see
    # domain.provider_series_mapping.require_research_usable_mapping.
    # Asserted structurally so a future field re-add trips this test.
    assert "point_in_time_safety" not in MacroSeriesDefinition.__dataclass_fields__


def test_two_definitions_with_identical_fields_are_equal() -> None:
    # Registry validation (FX-42H) relies on MacroSeriesDefinition equality
    # to detect "same key, different semantics" mismatches -- confirm plain
    # dataclass equality holds for two structurally identical instances.
    assert _series() == _series()


def test_definitions_differing_in_one_field_are_not_equal() -> None:
    assert _series() != _series(unit="INDEX_2015_100")

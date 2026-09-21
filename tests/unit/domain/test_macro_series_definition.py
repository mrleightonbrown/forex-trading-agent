import pytest

from forex_agent.domain.macro_category import MacroCategory
from forex_agent.domain.macro_frequency import MacroFrequency
from forex_agent.domain.macro_series_definition import (
    MacroSeriesDefinition,
    require_point_in_time_safe,
)
from forex_agent.domain.point_in_time_safety import PointInTimeSafety


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


def test_valid_series_definition_defaults_to_unknown_safety() -> None:
    series = _series()

    assert series.key == "US_CPI_YOY"
    assert series.point_in_time_safety is PointInTimeSafety.UNKNOWN


def test_series_definition_accepts_explicit_safety_classification() -> None:
    series = _series(point_in_time_safety=PointInTimeSafety.POINT_IN_TIME_SAFE)

    assert series.point_in_time_safety is PointInTimeSafety.POINT_IN_TIME_SAFE


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
        "point_in_time_safety",
    }


def test_require_point_in_time_safe_passes_for_safe_series() -> None:
    series = _series(point_in_time_safety=PointInTimeSafety.POINT_IN_TIME_SAFE)

    require_point_in_time_safe(series)  # must not raise


@pytest.mark.parametrize("safety", [PointInTimeSafety.LATEST_ONLY, PointInTimeSafety.UNKNOWN])
def test_require_point_in_time_safe_fails_closed(safety: PointInTimeSafety) -> None:
    series = _series(point_in_time_safety=safety)

    with pytest.raises(ValueError, match="not point-in-time safe"):
        require_point_in_time_safe(series)

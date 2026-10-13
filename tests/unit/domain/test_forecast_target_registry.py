"""FX-64 Section 9: tests for `ForecastTargetDefinition` and the
admitted `forecast_target_registry` -- validation, and the
admission-discipline invariants this registry must hold."""

import pytest

from forex_agent.domain.forecast_target_definition import ForecastTargetDefinition
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_target_registry import (
    FORECAST_TARGET_REGISTRY,
    target_by_key,
)
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.forecast_variable_family import ForecastVariableFamily


def _definition(**overrides: object) -> ForecastTargetDefinition:
    defaults: dict[str, object] = {
        "target_key": "TEST_TARGET",
        "variable_family": ForecastVariableFamily.INFLATION,
        "jurisdiction": "TESTLAND",
        "variable_name": "Test variable",
        "unit": "PERCENT",
        "measurement_convention": "ANNUAL_AVERAGE",
        "period_frequency": ForecastTargetPeriodKind.CALENDAR_YEAR,
        "supported_forecast_types": (ForecastType.NUMERIC_POINT,),
        "authoritative_definition_reference": "Test reference",
    }
    defaults.update(overrides)
    return ForecastTargetDefinition(**defaults)  # type: ignore[arg-type]


def test_categorical_only_target_requires_no_unit() -> None:
    definition = _definition(unit=None, supported_forecast_types=(ForecastType.CATEGORICAL_EVENT,))
    assert definition.unit is None


def test_numeric_supported_requires_unit() -> None:
    with pytest.raises(ValueError, match="unit"):
        _definition(unit=None, supported_forecast_types=(ForecastType.NUMERIC_POINT,))


def test_empty_supported_forecast_types_rejected() -> None:
    with pytest.raises(ValueError, match="supported_forecast_types"):
        _definition(supported_forecast_types=())


def test_constructs_with_valid_fields() -> None:
    definition = _definition()
    assert definition.target_key == "TEST_TARGET"


def test_empty_target_key_rejected() -> None:
    with pytest.raises(ValueError, match="target_key"):
        _definition(target_key="")


def test_empty_measurement_convention_rejected() -> None:
    with pytest.raises(ValueError, match="measurement_convention"):
        _definition(measurement_convention="")


def test_wrong_variable_family_type_rejected() -> None:
    with pytest.raises(TypeError, match="variable_family"):
        _definition(variable_family="INFLATION")


def test_wrong_period_frequency_type_rejected() -> None:
    with pytest.raises(TypeError, match="period_frequency"):
        _definition(period_frequency="CALENDAR_YEAR")


def test_registry_has_exactly_six_definitions() -> None:
    assert len(FORECAST_TARGET_REGISTRY) == 6


def test_registry_keys_are_unique() -> None:
    keys = [d.target_key for d in FORECAST_TARGET_REGISTRY]
    assert len(keys) == len(set(keys))


def test_registry_covers_all_four_initial_variable_families() -> None:
    families = {d.variable_family for d in FORECAST_TARGET_REGISTRY}
    assert families == {
        ForecastVariableFamily.INFLATION,
        ForecastVariableFamily.GDP_GROWTH,
        ForecastVariableFamily.POLICY_RATE,
        ForecastVariableFamily.UNEMPLOYMENT,
    }


def test_target_by_key_returns_admitted_definition() -> None:
    definition = target_by_key("EA_HICP_YOY_ANNUAL_AVERAGE")
    assert definition is not None
    assert definition.variable_family is ForecastVariableFamily.INFLATION


def test_target_by_key_returns_none_for_unadmitted_key() -> None:
    assert target_by_key("SOME_UNADMITTED_TARGET") is None


def test_every_registry_entry_has_a_distinct_measurement_convention_identity() -> None:
    """Section 9's own explicit example: two definitions must never be
    conflated even if they share a variable_family/jurisdiction --
    proven here since every entry's own (jurisdiction, measurement_
    convention) pair is unique across the whole registry."""
    pairs = [(d.jurisdiction, d.measurement_convention) for d in FORECAST_TARGET_REGISTRY]
    assert len(pairs) == len(set(pairs))

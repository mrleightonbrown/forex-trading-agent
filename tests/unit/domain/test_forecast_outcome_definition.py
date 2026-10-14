"""FX-65 Section 4: tests for `ForecastOutcomeDefinition` -- including
its own cross-validation against FX-64's `forecast_target_registry`
(Section 4's "do not match variables based only on display names")."""

from datetime import UTC, datetime

import pytest

from forex_agent.domain.forecast_outcome_definition import ForecastOutcomeDefinition
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.outcome_vintage_selection_policy import OutcomeVintageSelectionPolicy
from forex_agent.domain.timestamps import UtcTimestamp


def _ts() -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))


def _definition(**overrides: object) -> ForecastOutcomeDefinition:
    defaults: dict[str, object] = {
        "definition_key": "ECB-HICP-OUTCOME",
        "version_sequence": 0,
        "target_key": "EA_HICP_YOY_ANNUAL_AVERAGE",
        "outcome_type": ForecastType.NUMERIC_POINT,
        "provider_source_key": "EUROPEAN_CENTRAL_BANK",
        "required_source_series_identifier": "EUROSTAT_HICP_ANNUAL",
        "outcome_vintage_selection_policy": OutcomeVintageSelectionPolicy.FIRST_RELEASE,
        "availability": _ts(),
        "supporting_definition_reference": "Eurostat HICP methodology",
    }
    defaults.update(overrides)
    return ForecastOutcomeDefinition(**defaults)  # type: ignore[arg-type]


def test_valid_definition() -> None:
    definition = _definition()
    assert definition.version_sequence == 0


def test_unadmitted_target_key_rejected() -> None:
    with pytest.raises(ValueError, match="not in the admitted forecast target registry"):
        _definition(target_key="NOT_A_REAL_TARGET")


def test_outcome_type_not_supported_by_target_rejected() -> None:
    """EA_HICP_YOY_ANNUAL_AVERAGE only supports NUMERIC_POINT."""
    with pytest.raises(ValueError, match="not supported by"):
        _definition(
            target_key="CA_POLICY_RATE_DECISION_HIKE_HOLD_CUT",
            outcome_type=ForecastType.NUMERIC_POINT,
        )


def test_categorical_target_is_admitted() -> None:
    definition = _definition(
        target_key="CA_POLICY_RATE_DECISION_HIKE_HOLD_CUT",
        outcome_type=ForecastType.CATEGORICAL_EVENT,
        provider_source_key="BANK_OF_CANADA",
    )
    assert definition.outcome_type is ForecastType.CATEGORICAL_EVENT


def test_negative_version_sequence_rejected() -> None:
    with pytest.raises(ValueError, match="version_sequence"):
        _definition(version_sequence=-1)

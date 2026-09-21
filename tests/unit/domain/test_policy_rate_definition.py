from datetime import UTC, datetime

import pytest

from forex_agent.domain.macro_category import MacroCategory
from forex_agent.domain.macro_frequency import MacroFrequency
from forex_agent.domain.macro_series_definition import MacroSeriesDefinition
from forex_agent.domain.policy_rate_definition import PolicyRateDefinition
from forex_agent.domain.provider_series_mapping import ProviderSeriesMapping
from forex_agent.domain.rate_transformation import RateTransformation, RateTransformationKind
from forex_agent.domain.timestamps import UtcTimestamp

_POLICY_RATE_SERIES = MacroSeriesDefinition(
    key="XXX_POLICY_RATE",
    economy="XX",
    currency="XXX",
    category=MacroCategory.POLICY_RATE,
    unit="PERCENT",
    frequency=MacroFrequency.IRREGULAR,
)

_NON_POLICY_RATE_SERIES = MacroSeriesDefinition(
    key="XXX_CPI_YOY",
    economy="XX",
    currency="XXX",
    category=MacroCategory.INFLATION,
    unit="PERCENT",
    frequency=MacroFrequency.MONTHLY,
)

_IDENTITY = RateTransformation(
    kind=RateTransformationKind.IDENTITY, version="v1", description="raw value used as-is"
)

_MAPPING = ProviderSeriesMapping(provider="TEST_PROVIDER", provider_series_ids=("TEST_ID",))


def _ts(*args: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(*args, tzinfo=UTC))


def _definition(**overrides: object) -> PolicyRateDefinition:
    defaults: dict[str, object] = {
        "series": _POLICY_RATE_SERIES,
        "institution": "Test Central Bank",
        "instrument_name": "Test Policy Rate",
        "transformation": _IDENTITY,
        "valid_from": _ts(2000, 1, 1),
        "valid_to": None,
        "provider_mappings": (_MAPPING,),
    }
    defaults.update(overrides)
    return PolicyRateDefinition(**defaults)  # type: ignore[arg-type]


def test_valid_definition_holds_fields() -> None:
    definition = _definition()

    assert definition.institution == "Test Central Bank"
    assert definition.valid_to is None


def test_rejects_series_with_wrong_category() -> None:
    with pytest.raises(ValueError, match="POLICY_RATE"):
        _definition(series=_NON_POLICY_RATE_SERIES)


def test_rejects_empty_institution() -> None:
    with pytest.raises(ValueError, match="institution"):
        _definition(institution="")


def test_rejects_empty_instrument_name() -> None:
    with pytest.raises(ValueError, match="instrument_name"):
        _definition(instrument_name="")


def test_rejects_valid_to_before_valid_from() -> None:
    with pytest.raises(ValueError, match="valid_to"):
        _definition(valid_from=_ts(2020, 1, 1), valid_to=_ts(2010, 1, 1))


def test_rejects_valid_to_equal_to_valid_from() -> None:
    with pytest.raises(ValueError, match="valid_to"):
        _definition(valid_from=_ts(2020, 1, 1), valid_to=_ts(2020, 1, 1))


def test_rejects_empty_provider_mappings() -> None:
    with pytest.raises(ValueError, match="provider_mappings"):
        _definition(provider_mappings=())


def test_rejects_non_tuple_provider_mappings() -> None:
    with pytest.raises(ValueError, match="provider_mappings"):
        _definition(provider_mappings=[_MAPPING])


def test_definition_is_immutable() -> None:
    definition = _definition()

    with pytest.raises(AttributeError):
        definition.institution = "Other Bank"  # type: ignore[misc]


def test_covers_open_ended_window() -> None:
    definition = _definition(valid_from=_ts(2000, 1, 1), valid_to=None)

    assert definition.covers(_ts(1999, 12, 31)) is False
    assert definition.covers(_ts(2000, 1, 1)) is True
    assert definition.covers(_ts(2099, 1, 1)) is True


def test_covers_bounded_window_is_half_open() -> None:
    definition = _definition(valid_from=_ts(2000, 1, 1), valid_to=_ts(2010, 1, 1))

    assert definition.covers(_ts(1999, 12, 31)) is False
    assert definition.covers(_ts(2000, 1, 1)) is True
    assert definition.covers(_ts(2009, 12, 31)) is True
    assert definition.covers(_ts(2010, 1, 1)) is False


def test_summary_answers_all_six_required_audit_questions() -> None:
    definition = _definition()

    summary = definition.summary()

    assert set(summary) == {
        "economic_concept",
        "currency_economy",
        "unit",
        "transformation",
        "provider_mapping",
        "valid_period",
    }
    for value in summary.values():
        assert isinstance(value, str)
        assert value.strip() != ""


def test_summary_reflects_multiple_provider_mappings() -> None:
    other_mapping = ProviderSeriesMapping(provider="OTHER", provider_series_ids=("OTHER_ID",))
    definition = _definition(provider_mappings=(_MAPPING, other_mapping))

    summary = definition.summary()

    assert "TEST_PROVIDER" in summary["provider_mapping"]
    assert "OTHER" in summary["provider_mapping"]

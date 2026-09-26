import pytest

from forex_agent.domain.economic_event_category import EconomicEventCategory
from forex_agent.domain.economic_indicator_definition import EconomicIndicatorDefinition
from forex_agent.domain.macro_frequency import MacroFrequency


def _def(**overrides: object) -> EconomicIndicatorDefinition:
    defaults: dict[str, object] = {
        "key": "US_CPI_YOY",
        "name": "US CPI (YoY)",
        "economy": "US",
        "currency": "USD",
        "category": EconomicEventCategory.INFLATION,
        "is_numeric": True,
        "unit": "PERCENT",
        "frequency": MacroFrequency.MONTHLY,
    }
    defaults.update(overrides)
    return EconomicIndicatorDefinition(**defaults)  # type: ignore[arg-type]


def test_numeric_indicator_requires_unit() -> None:
    with pytest.raises(ValueError, match="unit"):
        _def(unit=None)


def test_numeric_indicator_rejects_blank_unit() -> None:
    with pytest.raises(ValueError, match="unit"):
        _def(unit="   ")


def test_non_numeric_indicator_rejects_unit() -> None:
    with pytest.raises(ValueError, match="unit"):
        _def(is_numeric=False, unit="PERCENT")


def test_non_numeric_indicator_allows_no_unit() -> None:
    indicator = _def(
        key="ECB_PRESS_CONFERENCE",
        name="ECB press conference",
        category=EconomicEventCategory.CENTRAL_BANK_COMMUNICATION,
        is_numeric=False,
        unit=None,
        frequency=MacroFrequency.IRREGULAR,
    )
    assert indicator.is_numeric is False
    assert indicator.unit is None


def test_rejects_invalid_currency() -> None:
    with pytest.raises(ValueError, match="currency"):
        _def(currency="usd")


def test_rejects_blank_key() -> None:
    with pytest.raises(ValueError, match="key"):
        _def(key="")


def test_rejects_wrong_category_type() -> None:
    with pytest.raises(TypeError, match="category"):
        _def(category="INFLATION")


def test_is_frozen() -> None:
    indicator = _def()
    with pytest.raises(AttributeError):
        indicator.key = "OTHER"  # type: ignore[misc]

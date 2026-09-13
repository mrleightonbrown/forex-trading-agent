from decimal import Decimal

import pytest

from forex_agent.domain.units import Units


def test_valid_units() -> None:
    units = Units(Decimal("1000"))

    assert units.value == Decimal("1000")


def test_rejects_float() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        Units(1000.0)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-1")])
def test_rejects_non_positive(value: Decimal) -> None:
    with pytest.raises(ValueError, match="positive"):
        Units(value)

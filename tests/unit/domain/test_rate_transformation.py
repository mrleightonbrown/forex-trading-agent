from decimal import Decimal

import pytest

from forex_agent.domain.rate_transformation import RateTransformation, RateTransformationKind


def _identity() -> RateTransformation:
    return RateTransformation(
        kind=RateTransformationKind.IDENTITY,
        version="v1",
        description="raw value used as-is",
    )


def _midpoint() -> RateTransformation:
    return RateTransformation(
        kind=RateTransformationKind.TARGET_RANGE_MIDPOINT,
        version="v1",
        description="mean of upper/lower bound",
    )


def test_identity_returns_the_single_raw_value_unchanged() -> None:
    result = _identity().apply(Decimal("2.375"))

    assert result == Decimal("2.375")


def test_identity_rejects_wrong_argument_count() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        _identity().apply(Decimal("1"), Decimal("2"))

    with pytest.raises(ValueError, match="exactly one"):
        _identity().apply()


def test_target_range_midpoint_computes_exact_decimal_average() -> None:
    result = _midpoint().apply(Decimal("0.50"), Decimal("0.25"))

    assert result == Decimal("0.375")


def test_target_range_midpoint_rejects_wrong_argument_count() -> None:
    with pytest.raises(ValueError, match="exactly two"):
        _midpoint().apply(Decimal("0.50"))


def test_target_range_midpoint_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="must not be less than"):
        _midpoint().apply(Decimal("0.25"), Decimal("0.50"))  # (upper, lower) swapped


def test_apply_rejects_float_arguments() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        _identity().apply(2.375)  # type: ignore[arg-type]


def test_rejects_empty_version() -> None:
    with pytest.raises(ValueError, match="version"):
        RateTransformation(kind=RateTransformationKind.IDENTITY, version="", description="x")


def test_rejects_empty_description() -> None:
    with pytest.raises(ValueError, match="description"):
        RateTransformation(kind=RateTransformationKind.IDENTITY, version="v1", description="")


def test_rejects_wrong_kind_type() -> None:
    with pytest.raises(TypeError, match="kind"):
        RateTransformation(kind="IDENTITY", version="v1", description="x")  # type: ignore[arg-type]


def test_transformation_is_immutable() -> None:
    transformation = _identity()

    with pytest.raises(AttributeError):
        transformation.version = "v2"  # type: ignore[misc]

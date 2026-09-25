from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.timestamps import UtcTimestamp


def _vintage(**overrides: object) -> MacroObservationVintage:
    defaults: dict[str, object] = {
        "series_key": "US_CPI_YOY",
        "observation_period": UtcTimestamp(datetime(2024, 2, 1, tzinfo=UTC)),
        "value": Decimal("2.1"),
        "released_at": UtcTimestamp(datetime(2024, 3, 12, 13, 30, tzinfo=UTC)),
        "revision_sequence": 0,
        "source": "FRED",
    }
    defaults.update(overrides)
    return MacroObservationVintage(**defaults)  # type: ignore[arg-type]


def test_valid_vintage_holds_exact_fields() -> None:
    vintage = _vintage()

    assert vintage.series_key == "US_CPI_YOY"
    assert vintage.value == Decimal("2.1")
    assert vintage.revision_sequence == 0
    assert vintage.effective_at is None


def test_vintage_observation_period_is_distinct_from_released_at() -> None:
    # FX-41: reference period and availability time must never collapse
    # into a single timestamp -- the February observation is released in
    # March, and both fields must independently reflect that.
    vintage = _vintage()

    assert vintage.observation_period.value.month == 2
    assert vintage.released_at.value.month == 3
    assert vintage.observation_period != vintage.released_at


def test_vintage_accepts_optional_effective_at() -> None:
    effective = UtcTimestamp(datetime(2024, 4, 1, tzinfo=UTC))
    vintage = _vintage(effective_at=effective)

    assert vintage.effective_at == effective


def test_decimal_fidelity_is_preserved_exactly() -> None:
    # FX-41: value must be Decimal-only and must not lose precision the
    # way a float round-trip would (e.g. 2.1 is not exactly representable
    # in binary floating point).
    precise = Decimal("2.123456789")
    vintage = _vintage(value=precise)

    assert vintage.value == precise
    assert str(vintage.value) == "2.123456789"


def test_rejects_float_value() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        _vintage(value=2.1)


def test_rejects_naive_observation_period() -> None:
    # UtcTimestamp itself enforces this -- constructing one from a naive
    # datetime raises before MacroObservationVintage is even reached.
    with pytest.raises(ValueError, match="naive"):
        UtcTimestamp(datetime(2024, 2, 1))  # noqa: DTZ001 -- deliberately naive, to test rejection


def test_normalizes_non_utc_timestamp_to_utc() -> None:
    from datetime import timedelta, timezone

    plus_two = timezone(timedelta(hours=2))
    released = UtcTimestamp(datetime(2024, 3, 12, 15, 30, tzinfo=plus_two))
    vintage = _vintage(released_at=released)

    assert vintage.released_at.value.tzinfo == UTC
    assert vintage.released_at.value.hour == 13


def test_rejects_raw_datetime_for_released_at() -> None:
    with pytest.raises(TypeError, match="released_at"):
        _vintage(released_at=datetime(2024, 3, 12, tzinfo=UTC))


def test_rejects_negative_revision_sequence() -> None:
    with pytest.raises(ValueError, match="revision_sequence"):
        _vintage(revision_sequence=-1)


def test_rejects_empty_source() -> None:
    with pytest.raises(ValueError, match="source"):
        _vintage(source="")


def test_rejects_empty_series_key() -> None:
    with pytest.raises(ValueError, match="series_key"):
        _vintage(series_key="")


def test_vintage_is_immutable() -> None:
    vintage = _vintage()

    with pytest.raises(AttributeError):
        vintage.value = Decimal("9.9")  # type: ignore[misc]


def test_released_at_is_verified_defaults_to_false() -> None:
    # FX-43H.1: fail closed -- a caller that does not explicitly claim
    # verified release timing must not have that go unnoticed by
    # defaulting to "verified". A newly constructed vintage is
    # provisional unless proven otherwise.
    vintage = _vintage()

    assert vintage.released_at_is_verified is False


def test_released_at_is_verified_can_be_explicitly_true() -> None:
    # A caller that genuinely possesses confirmed release timing must be
    # able to say so explicitly.
    vintage = _vintage(released_at_is_verified=True)

    assert vintage.released_at_is_verified is True


def test_rejects_non_bool_released_at_is_verified() -> None:
    with pytest.raises(TypeError, match="released_at_is_verified"):
        _vintage(released_at_is_verified="yes")


def test_released_at_is_conservative_bound_defaults_to_false() -> None:
    # FX-44: fails closed the same way released_at_is_verified does -- a
    # newly constructed vintage claims no conservative-bound status
    # either, unless explicitly given one.
    vintage = _vintage()

    assert vintage.released_at_is_conservative_bound is False


def test_released_at_is_conservative_bound_can_be_explicitly_true() -> None:
    vintage = _vintage(released_at_is_conservative_bound=True)

    assert vintage.released_at_is_conservative_bound is True
    assert vintage.released_at_is_verified is False  # unaffected, independent flag


def test_rejects_non_bool_released_at_is_conservative_bound() -> None:
    with pytest.raises(TypeError, match="released_at_is_conservative_bound"):
        _vintage(released_at_is_conservative_bound="yes")


def test_rejects_exact_and_conservative_simultaneously() -> None:
    # FX-44H: a timestamp cannot be simultaneously exactly confirmed AND a
    # deliberately inexact conservative bound -- structurally rejected,
    # not merely discouraged by convention.
    with pytest.raises(ValueError, match="must not both be True"):
        _vintage(released_at_is_verified=True, released_at_is_conservative_bound=True)

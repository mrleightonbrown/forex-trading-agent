import pytest

from forex_agent.domain.point_in_time_safety import PointInTimeSafety
from forex_agent.domain.provider_series_mapping import (
    ProviderSeriesMapping,
    require_point_in_time_safe_mapping,
)


def _mapping(**overrides: object) -> ProviderSeriesMapping:
    defaults: dict[str, object] = {
        "provider": "FRED",
        "provider_series_ids": ("DFEDTAR",),
    }
    defaults.update(overrides)
    return ProviderSeriesMapping(**defaults)  # type: ignore[arg-type]


def test_valid_mapping_defaults_to_unknown_and_unverified() -> None:
    mapping = _mapping()

    assert mapping.point_in_time_safety is PointInTimeSafety.UNKNOWN
    assert mapping.verified is False
    assert mapping.notes == ""


def test_mapping_accepts_multiple_provider_series_ids_in_order() -> None:
    mapping = _mapping(provider_series_ids=("DFEDTARU", "DFEDTARL"))

    assert mapping.provider_series_ids == ("DFEDTARU", "DFEDTARL")


def test_rejects_empty_provider() -> None:
    with pytest.raises(ValueError, match="provider"):
        _mapping(provider="")


def test_rejects_empty_provider_series_ids_tuple() -> None:
    with pytest.raises(ValueError, match="provider_series_ids"):
        _mapping(provider_series_ids=())


def test_rejects_non_tuple_provider_series_ids() -> None:
    with pytest.raises(ValueError, match="provider_series_ids"):
        _mapping(provider_series_ids=["DFEDTAR"])


def test_rejects_empty_string_within_provider_series_ids() -> None:
    with pytest.raises(ValueError, match="provider_series_ids"):
        _mapping(provider_series_ids=("DFEDTARU", ""))


def test_rejects_wrong_point_in_time_safety_type() -> None:
    with pytest.raises(TypeError, match="point_in_time_safety"):
        _mapping(point_in_time_safety="SAFE")


def test_rejects_non_bool_verified() -> None:
    with pytest.raises(TypeError, match="verified"):
        _mapping(verified="yes")


def test_mapping_is_immutable() -> None:
    mapping = _mapping()

    with pytest.raises(AttributeError):
        mapping.provider = "ECB_SDW"  # type: ignore[misc]


def test_require_point_in_time_safe_mapping_passes_for_safe_mapping() -> None:
    mapping = _mapping(point_in_time_safety=PointInTimeSafety.POINT_IN_TIME_SAFE)

    require_point_in_time_safe_mapping(mapping)  # must not raise


@pytest.mark.parametrize("safety", [PointInTimeSafety.LATEST_ONLY, PointInTimeSafety.UNKNOWN])
def test_require_point_in_time_safe_mapping_fails_closed(safety: PointInTimeSafety) -> None:
    mapping = _mapping(point_in_time_safety=safety)

    with pytest.raises(ValueError, match="not point-in-time safe"):
        require_point_in_time_safe_mapping(mapping)

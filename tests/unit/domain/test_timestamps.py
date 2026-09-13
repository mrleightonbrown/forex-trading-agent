from datetime import UTC, datetime, timedelta, timezone

import pytest

from forex_agent.domain.timestamps import UtcTimestamp

# CLAUDE.md: "All persisted timestamps use timezone-aware UTC values. Naive
# datetimes must be rejected." Required regression coverage per CLAUDE.md's
# testing rules ("timezone errors").


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="naive"):
        UtcTimestamp(datetime(2026, 1, 1, 12, 0, 0))  # noqa: DTZ001


def test_utc_datetime_is_kept_as_is() -> None:
    dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    assert UtcTimestamp(dt).value == dt


def test_non_utc_aware_datetime_is_normalized_to_utc() -> None:
    plus_two = timezone(timedelta(hours=2))
    dt = datetime(2026, 1, 1, 14, 0, 0, tzinfo=plus_two)

    ts = UtcTimestamp(dt)

    assert ts.value == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert ts.value.tzinfo == UTC


def test_now_returns_utc_aware_timestamp() -> None:
    ts = UtcTimestamp.now()

    assert ts.value.tzinfo == UTC

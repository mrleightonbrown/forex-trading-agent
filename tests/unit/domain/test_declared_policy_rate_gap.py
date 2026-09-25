from datetime import UTC, datetime

import pytest

from forex_agent.domain.declared_policy_rate_gap import DeclaredPolicyRateGap
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    microsecond: int = 0,
) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, minute, second, microsecond, tzinfo=UTC))


def _gap(**overrides: object) -> DeclaredPolicyRateGap:
    defaults: dict[str, object] = {
        "currency": "JPY",
        "start": _ts(2001, 3, 19),
        "end": _ts(2006, 3, 9),
        "reason": "Quantitative Easing Policy: BoJ targeted a quantity, not a rate.",
    }
    defaults.update(overrides)
    return DeclaredPolicyRateGap(**defaults)  # type: ignore[arg-type]


def test_valid_gap_holds_fields() -> None:
    gap = _gap()

    assert gap.currency == "JPY"
    assert gap.start == _ts(2001, 3, 19)
    assert gap.end == _ts(2006, 3, 9)


@pytest.mark.parametrize("code", ["jpy", "JP", "DOLLARS", "123"])
def test_rejects_invalid_currency_code(code: str) -> None:
    with pytest.raises(ValueError, match="currency code"):
        _gap(currency=code)


def test_rejects_end_before_start() -> None:
    with pytest.raises(ValueError, match="end"):
        _gap(start=_ts(2010, 1, 1), end=_ts(2000, 1, 1))


def test_rejects_end_equal_to_start() -> None:
    with pytest.raises(ValueError, match="end"):
        _gap(start=_ts(2010, 1, 1), end=_ts(2010, 1, 1))


def test_rejects_empty_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        _gap(reason="")


def test_rejects_wrong_start_type() -> None:
    with pytest.raises(TypeError, match="start"):
        _gap(start=datetime(2001, 3, 19, tzinfo=UTC))


def test_rejects_wrong_end_type() -> None:
    with pytest.raises(TypeError, match="end"):
        _gap(end=datetime(2006, 3, 9, tzinfo=UTC))


def test_gap_is_immutable() -> None:
    gap = _gap()

    with pytest.raises(AttributeError):
        gap.reason = "other"  # type: ignore[misc]


def test_covers_is_half_open() -> None:
    gap = _gap(start=_ts(2001, 3, 19), end=_ts(2006, 3, 9))

    assert gap.covers(_ts(2001, 3, 18)) is False
    assert gap.covers(_ts(2001, 3, 19)) is True
    assert gap.covers(_ts(2006, 3, 8)) is True
    assert gap.covers(_ts(2006, 3, 9)) is False

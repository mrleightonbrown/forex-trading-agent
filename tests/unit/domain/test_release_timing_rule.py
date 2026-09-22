from datetime import UTC, date, datetime, time

import pytest

from forex_agent.domain.release_timing_rule import ReleaseTimingConfidence, ReleaseTimingRule


def _rule(**overrides: object) -> ReleaseTimingRule:
    defaults: dict[str, object] = {
        "institution": "Bank of England",
        "local_time": time(12, 0, 0),
        "timezone": "Europe/London",
        "confidence": ReleaseTimingConfidence.EXACT,
        "applies_from": date(1997, 1, 1),
        "applies_to": None,
        "citation": "https://www.bankofengland.co.uk/monetary-policy/the-interest-rate-bank-rate",
    }
    defaults.update(overrides)
    return ReleaseTimingRule(**defaults)  # type: ignore[arg-type]


def test_exact_intraday_utc_conversion_winter() -> None:
    # FX-44 test requirement: exact intraday UTC conversion. Noon London
    # time in January (GMT, UTC+0) must convert to exactly 12:00 UTC.
    rule = _rule()
    resolved = rule.resolve(date(2020, 1, 9))

    assert resolved.value == datetime(2020, 1, 9, 12, 0, 0, tzinfo=UTC)


def test_dst_sensitive_local_announcement_time() -> None:
    # FX-44 test requirement: DST-sensitive local announcement time. The
    # SAME rule (noon Europe/London) applied to a summer date must
    # resolve to a DIFFERENT UTC hour than a winter date, because the
    # UK observes BST (UTC+1) in summer -- zoneinfo must apply the
    # correct historical offset for each date, not a fixed offset.
    rule = _rule()

    winter = rule.resolve(date(2020, 1, 9))  # GMT, UTC+0
    summer = rule.resolve(date(2020, 7, 9))  # BST, UTC+1

    assert winter.value == datetime(2020, 1, 9, 12, 0, 0, tzinfo=UTC)
    assert summer.value == datetime(2020, 7, 9, 11, 0, 0, tzinfo=UTC)
    assert winter.value.hour != summer.value.hour


def test_dst_sensitive_us_eastern_rule() -> None:
    # A second institution/timezone, to confirm this isn't UK-specific:
    # 2:00pm America/New_York is 18:00 UTC in winter (EST, UTC-5) and
    # 18:00 UTC in summer too would be wrong -- summer is EDT (UTC-4),
    # so 2pm ET in July must resolve to 18:00 UTC, and 2pm ET in
    # January must resolve to 19:00 UTC.
    rule = _rule(
        institution="Federal Reserve",
        local_time=time(14, 0, 0),
        timezone="America/New_York",
        citation="https://www.federalreserve.gov/newsevents/pressreleases/monetary20130313a.htm",
    )

    winter = rule.resolve(date(2016, 12, 14))  # EST, UTC-5
    summer = rule.resolve(date(2017, 6, 15))  # EDT, UTC-4

    assert winter.value == datetime(2016, 12, 14, 19, 0, 0, tzinfo=UTC)
    assert summer.value == datetime(2017, 6, 15, 18, 0, 0, tzinfo=UTC)


def test_covers_respects_half_open_window() -> None:
    rule = _rule(applies_from=date(2013, 3, 19), applies_to=date(2020, 1, 1))

    assert rule.covers(date(2013, 3, 19)) is True  # inclusive lower bound
    assert rule.covers(date(2019, 12, 31)) is True
    assert rule.covers(date(2020, 1, 1)) is False  # exclusive upper bound
    assert rule.covers(date(2013, 3, 18)) is False


def test_covers_with_no_upper_bound_is_open_ended() -> None:
    rule = _rule(applies_from=date(2013, 3, 19), applies_to=None)

    assert rule.covers(date(2013, 3, 19)) is True
    assert rule.covers(date(2099, 1, 1)) is True


def test_rejects_invalid_timezone_name() -> None:
    with pytest.raises(Exception, match="No time zone found"):
        _rule(timezone="Not/AZone")


def test_rejects_applies_to_before_applies_from() -> None:
    with pytest.raises(ValueError, match="applies_to"):
        _rule(applies_from=date(2020, 1, 1), applies_to=date(2019, 1, 1))


def test_rejects_empty_citation() -> None:
    with pytest.raises(ValueError, match="citation"):
        _rule(citation="")


def test_rejects_empty_institution() -> None:
    with pytest.raises(ValueError, match="institution"):
        _rule(institution="")

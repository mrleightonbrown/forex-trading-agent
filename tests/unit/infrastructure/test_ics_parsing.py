"""FX-52A: unit tests for the minimal ICS VEVENT parser. FX-52AH adds
malformed-document detection and invalid-event counting coverage."""

from datetime import date, time

import pytest

from forex_agent.infrastructure.economic_calendar_sources.ics_parsing import (
    MalformedIcsError,
    UnresolvedTimezoneError,
    parse_ics_events,
)

_UTC_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:abc-123
DTSTART:20261028T134500Z
SUMMARY:Interest Rate Announcement and Monetary Policy Report
END:VEVENT
END:VCALENDAR
"""

_TZID_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:def-456
DTSTART;TZID=US-Eastern:20250115T083000
SUMMARY:Consumer Price Index
END:VEVENT
END:VCALENDAR
"""

_DATE_ONLY_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:ghi-789
DTSTART;VALUE=DATE:20261012
SUMMARY:Thanksgiving Day
END:VEVENT
END:VCALENDAR
"""

_UNKNOWN_TZID_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:jkl-000
DTSTART;TZID=Some/Unmapped-Zone:20260101T090000
SUMMARY:Unresolvable Event
END:VEVENT
END:VCALENDAR
"""

_STATUS_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:mno-111
DTSTART:20260115T083000Z
SUMMARY:Consumer Price Index
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""

_FOLDED_SUMMARY_ICS = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:pqr-222\r\n"
    "DTSTART:20260201T090000Z\r\n"
    "SUMMARY:Employment \r\n"
    " Situation\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


def test_utc_z_suffix_event_parsed() -> None:
    result = parse_ics_events(_UTC_ICS, default_timezone="America/Toronto")
    assert len(result.events) == 1
    assert result.invalid_count == 0
    event = result.events[0]
    assert event.uid == "abc-123"
    assert event.summary == "Interest Rate Announcement and Monetary Policy Report"
    assert event.event_date == date(2026, 10, 28)
    assert event.event_time == time(13, 45, 0)
    assert event.event_timezone == "UTC"
    assert event.status is None


def test_known_tzid_resolved_to_iana_name() -> None:
    result = parse_ics_events(_TZID_ICS, default_timezone="America/Toronto")
    assert len(result.events) == 1
    event = result.events[0]
    assert event.event_date == date(2025, 1, 15)
    assert event.event_time == time(8, 30, 0)
    assert event.event_timezone == "America/New_York"


def test_date_only_event_has_no_time_and_uses_default_timezone() -> None:
    result = parse_ics_events(_DATE_ONLY_ICS, default_timezone="America/Toronto")
    assert len(result.events) == 1
    event = result.events[0]
    assert event.event_date == date(2026, 10, 12)
    assert event.event_time is None
    assert event.event_timezone == "America/Toronto"


def test_unknown_tzid_is_omitted_and_counted_invalid() -> None:
    result = parse_ics_events(_UNKNOWN_TZID_ICS, default_timezone="America/Toronto")
    assert result.events == ()
    assert result.invalid_count == 1


def test_unresolved_timezone_error_is_raised_by_the_helper_directly() -> None:
    from forex_agent.infrastructure.economic_calendar_sources.ics_parsing import (
        _parse_one_vevent,
        _split_vevent_blocks,
        _unfold_lines,
    )

    blocks = _split_vevent_blocks(_unfold_lines(_UNKNOWN_TZID_ICS))
    with pytest.raises(UnresolvedTimezoneError):
        _parse_one_vevent(blocks[0], default_timezone="America/Toronto")


def test_status_field_is_preserved() -> None:
    result = parse_ics_events(_STATUS_ICS, default_timezone="America/Toronto")
    assert len(result.events) == 1
    assert result.events[0].status == "CANCELLED"


def test_folded_summary_line_is_unfolded() -> None:
    result = parse_ics_events(_FOLDED_SUMMARY_ICS, default_timezone="America/Toronto")
    assert len(result.events) == 1
    assert result.events[0].summary == "Employment Situation"


def test_malformed_event_missing_uid_is_omitted_and_counted_invalid() -> None:
    malformed = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20260101T090000Z
SUMMARY:No UID Here
END:VEVENT
END:VCALENDAR
"""
    result = parse_ics_events(malformed, default_timezone="America/Toronto")
    assert result.events == ()
    assert result.invalid_count == 1


def test_empty_calendar_is_a_valid_empty_result() -> None:
    result = parse_ics_events(
        "BEGIN:VCALENDAR\nEND:VCALENDAR\n", default_timezone="America/Toronto"
    )
    assert result.events == ()
    assert result.invalid_count == 0


def test_two_events_both_parsed() -> None:
    combined = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:abc-123
DTSTART:20261028T134500Z
SUMMARY:Interest Rate Announcement and Monetary Policy Report
END:VEVENT
BEGIN:VEVENT
UID:def-456
DTSTART;TZID=US-Eastern:20250115T083000
SUMMARY:Consumer Price Index
END:VEVENT
END:VCALENDAR
"""
    result = parse_ics_events(combined, default_timezone="America/Toronto")
    assert len(result.events) == 2
    assert {e.uid for e in result.events} == {"abc-123", "def-456"}


# --- FX-52AH: malformed-document detection (distinct from valid-empty) -----


def test_html_error_page_raises_malformed_ics_error() -> None:
    html = "<!DOCTYPE HTML><html><head><title>Access Denied</title></head></html>"
    with pytest.raises(MalformedIcsError):
        parse_ics_events(html, default_timezone="America/Toronto")


def test_garbage_text_raises_malformed_ics_error() -> None:
    with pytest.raises(MalformedIcsError):
        parse_ics_events("this is not an ics document at all", default_timezone="America/Toronto")


def test_empty_string_raises_malformed_ics_error() -> None:
    with pytest.raises(MalformedIcsError):
        parse_ics_events("", default_timezone="America/Toronto")

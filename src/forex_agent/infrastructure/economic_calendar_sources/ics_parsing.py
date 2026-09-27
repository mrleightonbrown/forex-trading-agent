"""Minimal, dependency-free iCalendar (RFC 5545) VEVENT parser (FX-52A;
fail-closed/observability hardened by FX-52AH).

Deliberately NOT a general-purpose ICS library -- no `VALARM`, no
`RRULE`/recurrence expansion (FX-52A Section 31: "recurrence only if
the official source genuinely uses it"; neither BLS's nor Bank of
Canada's feed does), no `VTIMEZONE` block interpretation. Handles
exactly what this story's two ICS sources actually produce: `UID`,
`SUMMARY`, `STATUS` (if present), and `DTSTART` in its three real
shapes -- UTC (`Z` suffix), a named `TZID` parameter, or an all-day
date-only value (`VALUE=DATE`).

`TZID` resolution is a small, explicit, closed lookup
(`_KNOWN_TZID_ALIASES`) -- never a guess. An unrecognized `TZID`
raises `UnresolvedTimezoneError` internally, counted as one invalid
event rather than aborting the whole feed (FX-52A Section 21: "If
timezone cannot be established safely: do not fabricate it.").

FX-52AH: a response that is not a valid ICS document AT ALL (missing
`BEGIN:VCALENDAR` entirely -- an HTML error page, garbage text, an
unrelated document) now raises `MalformedIcsError` rather than
silently returning zero events indistinguishable from a genuinely
empty, well-formed calendar. A caller (adapter) must treat
`MalformedIcsError` as a source failure (`EconomicCalendarSource
UnavailableError`), never as "nothing is currently scheduled." An
individual malformed/incomplete VEVENT block WITHIN an otherwise-valid
calendar is still merely counted and skipped (`IcsParseResult.
invalid_count`), not escalated to a whole-feed failure -- FX-52A's own
"partial official coverage is preferable to invented certainty"
applied at event granularity, distinct from whole-DOCUMENT validity.
"""

from dataclasses import dataclass
from datetime import date, datetime, time

# BLS's own ICS feed uses this exact non-IANA TZID for every timed event
# (confirmed directly against the live feed). Extend only after directly
# confirming a new source's own real TZID string against its live feed --
# never guess a plausible-looking one.
_KNOWN_TZID_ALIASES: dict[str, str] = {
    "US-Eastern": "America/New_York",
}


class UnresolvedTimezoneError(ValueError):
    """Raised internally when an event's `TZID` is not in
    `_KNOWN_TZID_ALIASES` -- this project refuses to guess a timezone
    (FX-52A Section 21). Caught by `parse_ics_events` itself and
    counted as one invalid event; never escapes to a caller."""


class MalformedIcsError(ValueError):
    """Raised when `text` is not a recognizable ICS document at all
    (FX-52AH) -- e.g. an HTML error page or unrelated content returned
    with an HTTP 200. Distinct from a genuinely empty, well-formed
    calendar (`BEGIN:VCALENDAR`...`END:VCALENDAR` with zero `VEVENT`
    blocks), which is a valid, non-error result. A caller must treat
    this as a source failure, never as "nothing is scheduled.\""""


@dataclass(frozen=True, slots=True)
class IcsEvent:
    uid: str
    summary: str
    event_date: date
    event_time: time | None
    event_timezone: str
    status: str | None


@dataclass(frozen=True, slots=True)
class IcsParseResult:
    events: tuple[IcsEvent, ...]
    invalid_count: int


def parse_ics_events(text: str, default_timezone: str) -> IcsParseResult:
    """Every `VEVENT` in `text`, plus a count of malformed/incomplete
    VEVENT blocks skipped along the way. `default_timezone` is used
    only for a date-only (`VALUE=DATE`) `DTSTART`, which carries no
    timezone context of its own -- callers must pass the feed's own
    known civil-calendar timezone (e.g. the issuing institution's own
    jurisdiction), never a guess made per event.

    Raises `MalformedIcsError` if `text` does not contain a
    `BEGIN:VCALENDAR` line at all -- see the module docstring.
    """
    lines = _unfold_lines(text)
    if not any(line.strip() == "BEGIN:VCALENDAR" for line in lines):
        raise MalformedIcsError(
            "no BEGIN:VCALENDAR line found -- this does not look like an ICS document"
        )

    events: list[IcsEvent] = []
    invalid_count = 0
    for block in _split_vevent_blocks(lines):
        try:
            event = _parse_one_vevent(block, default_timezone)
        except UnresolvedTimezoneError:
            invalid_count += 1
            continue
        if event is None:
            invalid_count += 1
        else:
            events.append(event)
    return IcsParseResult(events=tuple(events), invalid_count=invalid_count)


def _unfold_lines(text: str) -> list[str]:
    # RFC 5545 line folding: a continuation line starts with a single
    # space or tab and must be joined onto the previous logical line.
    raw_lines = text.replace("\r\n", "\n").split("\n")
    unfolded: list[str] = []
    for line in raw_lines:
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _split_vevent_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if line.strip() == "BEGIN:VEVENT":
            current = []
        elif line.strip() == "END:VEVENT":
            if current is not None:
                blocks.append(current)
            current = None
        elif current is not None:
            current.append(line)
    return blocks


def _parse_property(line: str) -> tuple[str, dict[str, str], str] | None:
    if ":" not in line:
        return None
    head, _, value = line.partition(":")
    name, *param_parts = head.split(";")
    params: dict[str, str] = {}
    for part in param_parts:
        if "=" in part:
            key, _, val = part.partition("=")
            params[key.upper()] = val
    return name.upper(), params, value


def _parse_one_vevent(lines: list[str], default_timezone: str) -> IcsEvent | None:
    uid: str | None = None
    summary: str | None = None
    status: str | None = None
    dtstart_property: tuple[dict[str, str], str] | None = None

    for line in lines:
        parsed = _parse_property(line)
        if parsed is None:
            continue
        name, params, value = parsed
        if name == "UID":
            uid = value
        elif name == "SUMMARY":
            summary = value.replace("\\,", ",").replace("\\n", " ")
        elif name == "STATUS":
            status = value
        elif name == "DTSTART":
            dtstart_property = (params, value)

    if uid is None or summary is None or dtstart_property is None:
        return None  # malformed/incomplete event -- counted as invalid by the caller

    event_date, event_time, event_timezone = _resolve_dtstart(dtstart_property, default_timezone)
    return IcsEvent(
        uid=uid,
        summary=summary,
        event_date=event_date,
        event_time=event_time,
        event_timezone=event_timezone,
        status=status,
    )


def _resolve_dtstart(
    dtstart_property: tuple[dict[str, str], str], default_timezone: str
) -> tuple[date, time | None, str]:
    # Every branch below intentionally parses a naive datetime and then
    # immediately splits it into (date, time) components paired with a
    # separately-tracked timezone NAME -- exactly EconomicEventSchedule
    # Vintage's own three-field shape (scheduled_date/scheduled_time/
    # schedule_timezone), never a single timezone-aware datetime. Not
    # an oversight; ruff's naive-datetime rule does not apply here.
    params, value = dtstart_property
    if params.get("VALUE") == "DATE" or (len(value) == 8 and "T" not in value):
        parsed_date = datetime.strptime(value, "%Y%m%d").date()  # noqa: DTZ007
        return parsed_date, None, default_timezone

    if value.endswith("Z"):
        parsed = datetime.strptime(value, "%Y%m%dT%H%M%SZ")  # noqa: DTZ007
        return parsed.date(), parsed.time(), "UTC"

    tzid = params.get("TZID")
    if tzid is None:
        raise UnresolvedTimezoneError(f"DTSTART {value!r} has no TZID and is not UTC/date-only")
    iana_name = _KNOWN_TZID_ALIASES.get(tzid)
    if iana_name is None:
        raise UnresolvedTimezoneError(f"unrecognized TZID {tzid!r} -- refusing to guess")
    parsed = datetime.strptime(value, "%Y%m%dT%H%M%S")  # noqa: DTZ007
    return parsed.date(), parsed.time(), iana_name

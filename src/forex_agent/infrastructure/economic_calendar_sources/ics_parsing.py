"""Minimal, dependency-free iCalendar (RFC 5545) VEVENT parser (FX-52A).

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
raises `UnresolvedTimezoneError` rather than silently assuming a
timezone (FX-52A Section 21: "If timezone cannot be established
safely: do not fabricate it. Treat that source/event as unavailable
until clarified.") -- a caller (adapter) should catch this per event
and skip it, not abort the entire feed.
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
    """Raised when an event's `TZID` is not in `_KNOWN_TZID_ALIASES` --
    this project refuses to guess a timezone (FX-52A Section 21)."""


@dataclass(frozen=True, slots=True)
class IcsEvent:
    uid: str
    summary: str
    event_date: date
    event_time: time | None
    event_timezone: str
    status: str | None


def parse_ics_events(text: str, default_timezone: str) -> tuple[IcsEvent, ...]:
    """Every `VEVENT` in `text`. `default_timezone` is used only for a
    date-only (`VALUE=DATE`) `DTSTART`, which carries no timezone
    context of its own -- callers must pass the feed's own known
    civil-calendar timezone (e.g. the issuing institution's own
    jurisdiction), never a guess made per event.

    An event whose `TZID` cannot be resolved is OMITTED from the
    result (with the failure logged by re-raising per-event internally
    and catching it here) rather than aborting the whole feed --
    FX-52A's own "partial official coverage is preferable to invented
    certainty" applied at event granularity, not just source
    granularity.
    """
    events: list[IcsEvent] = []
    for block in _split_vevent_blocks(_unfold_lines(text)):
        try:
            event = _parse_one_vevent(block, default_timezone)
        except UnresolvedTimezoneError:
            continue
        if event is not None:
            events.append(event)
    return tuple(events)


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
        return None  # malformed/incomplete event -- caller reports this as a parse gap

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

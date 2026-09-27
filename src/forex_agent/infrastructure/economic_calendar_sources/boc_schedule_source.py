"""Bank of Canada official release-schedule adapter (FX-52A).

Source: `https://www.bankofcanada.ca/?feed=ical&content_type=upcoming-
events` -- the Bank's own public iCalendar feed (no API key),
confirmed live in this story's own source-verification pass. Confirmed
VEVENT shape: `UID` (a stable-looking, numeric, domain-qualified ID,
e.g. `247309@bank-banque-canada.ca`), `SUMMARY`, `DTSTART` always in
UTC (`Z` suffix) -- no `TZID` resolution needed for this source at
all, unlike BLS. No `STATUS` field was observed; same "absence is
never cancellation" treatment as `bls_schedule_source`.

This feed mixes rate announcements with speeches, holidays, and other
non-economic-event items -- only the exact title
"Interest Rate Announcement and Monetary Policy Report" is mapped;
everything else is UNMAPPED by construction (Section 12: explicit
mapping, never fuzzy).
"""

from datetime import UTC, datetime

import httpx

from forex_agent.application.ports.economic_calendar_source import (
    EconomicCalendarSourceUnavailableError,
    RawScheduleObservation,
    ScheduleFetchResult,
)
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.economic_calendar_sources.ics_parsing import (
    MalformedIcsError,
    parse_ics_events,
)

_BASE_URL = "https://www.bankofcanada.ca"
_FEED_PATH = "/"
_FEED_PARAMS = {"feed": "ical", "content_type": "upcoming-events"}
_TIMEOUT_SECONDS = 30.0
_SOURCE_NAME = "BOC_ICS"
_DEFAULT_TIMEZONE = "America/Toronto"

_SUMMARY_TO_INDICATORS: dict[str, tuple[str, ...]] = {
    "Interest Rate Announcement and Monetary Policy Report": ("CAD_POLICY_RATE_DECISION",),
    "Interest Rate Announcement": ("CAD_POLICY_RATE_DECISION",),
}


class BocScheduleSource:
    """Implements `EconomicCalendarScheduleSource` against the Bank of
    Canada's own public ICS feed."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=_BASE_URL, timeout=_TIMEOUT_SECONDS, follow_redirects=True
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_schedule(self) -> ScheduleFetchResult:
        try:
            response = await self._client.get(_FEED_PATH, params=_FEED_PARAMS)
        except httpx.RequestError as exc:
            raise EconomicCalendarSourceUnavailableError(
                f"failed to reach Bank of Canada calendar feed: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise EconomicCalendarSourceUnavailableError(
                f"Bank of Canada calendar feed request failed with status {response.status_code}"
            )

        try:
            parsed = parse_ics_events(response.text, default_timezone=_DEFAULT_TIMEZONE)
        except MalformedIcsError as exc:
            raise EconomicCalendarSourceUnavailableError(
                f"Bank of Canada calendar feed did not parse as ICS: {exc}"
            ) from exc

        observed_at = UtcTimestamp(datetime.now(UTC))
        observations: list[RawScheduleObservation] = []
        unmapped_count = 0
        for event in parsed.events:
            indicator_keys = _SUMMARY_TO_INDICATORS.get(event.summary)
            if indicator_keys is None:
                unmapped_count += 1  # a speech, holiday, or other non-covered item
                continue
            observations.append(
                RawScheduleObservation(
                    source=_SOURCE_NAME,
                    external_event_id=event.uid,
                    indicator_keys=indicator_keys,
                    scheduled_date=event.event_date,
                    scheduled_time=event.event_time,
                    schedule_timezone=event.event_timezone,
                    status=EconomicEventStatus.SCHEDULED,
                    observed_at=observed_at,
                    raw_title=event.summary,
                )
            )
        return ScheduleFetchResult(
            observations=tuple(observations),
            mapped_count=len(observations),
            unmapped_count=unmapped_count,
            invalid_count=parsed.invalid_count,
        )

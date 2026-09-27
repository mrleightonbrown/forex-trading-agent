"""BLS (Bureau of Labor Statistics) official release-schedule adapter
(FX-52A).

Source: `https://www.bls.gov/schedule/news_release/bls.ics` -- BLS's
own public iCalendar feed, no API key, confirmed live in this story's
own source-verification pass. Confirmed VEVENT shape: `UID` (a GUID),
`SUMMARY` (an exact, stable release title -- "Consumer Price Index",
"Employment Situation"), `DTSTART;TZID=US-Eastern:...` (a full local
date+time, in BLS's own non-IANA `US-Eastern` TZID, resolved via
`ics_parsing`'s explicit alias table). No `STATUS` field was observed
on any live event in this pass -- BLS's calendar cancellation/
postponement semantics remain UNKNOWN; this adapter always emits
`EconomicEventStatus.SCHEDULED` and relies on FX-52A's own "absence is
never cancellation" rule rather than claiming to detect either.

KNOWN LIMITATION, not yet independently verified: whether a real-world
BLS calendar item's `UID` stays IDENTICAL across separate feed
regenerations over time (i.e. whether it is safe to treat as a stable
external identifier for occurrence-identity purposes, not merely
stable within one HTTP response) was not confirmed in this story's own
research pass -- flagged explicitly for the real-source validation
step (FX-52A Section 43) rather than assumed.

REAL LIMITATION CONFIRMED BY FX-52A'S OWN REAL-SOURCE VALIDATION (Section
43), not merely theoretical: a plain server-side `httpx` request to this
feed currently receives an HTTP 403 "Access Denied" page from BLS's own
infrastructure, even with a realistic browser `User-Agent`/`Accept`/
`Accept-Language` header set -- this is NOT a documentation, licensing,
or parsing problem (a browser-capable fetch during this story's
research DID retrieve and confirm the feed's real content and shape,
which is exactly what this adapter's parsing logic is unit-tested
against). It appears to be network/infrastructure-level bot mitigation
independent of request headers. `tests/integration/test_bls_schedule_
source_live.py` is EXPECTED to fail for this reason until it is
resolved (e.g. a different egress path, or confirming with BLS whether
routine automated access needs registration) -- this is an honestly
surfaced operational gap, not a silently swallowed one, and this
adapter must not be relied on for real ingestion until it is fixed.

"Employment Situation" maps onto TWO canonical indicators sharing one
release_group_key (`US_NONFARM_PAYROLLS`, `US_UNEMPLOYMENT_RATE`) --
FX-52A Section 11's own worked example, demonstrated here directly.
"""

from datetime import UTC, datetime

import httpx

from forex_agent.application.ports.economic_calendar_source import (
    EconomicCalendarSourceUnavailableError,
    RawScheduleObservation,
)
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.economic_calendar_sources.ics_parsing import parse_ics_events

_BASE_URL = "https://www.bls.gov"
_FEED_PATH = "/schedule/news_release/bls.ics"
_TIMEOUT_SECONDS = 30.0
_SOURCE_NAME = "BLS_ICS"
_DEFAULT_TIMEZONE = "America/New_York"

_SUMMARY_TO_INDICATORS: dict[str, tuple[str, ...]] = {
    "Consumer Price Index": ("US_CPI_YOY",),
    "Employment Situation": ("US_NONFARM_PAYROLLS", "US_UNEMPLOYMENT_RATE"),
}


class BlsScheduleSource:
    """Implements `EconomicCalendarScheduleSource` against BLS's own
    public ICS feed."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=_BASE_URL, timeout=_TIMEOUT_SECONDS, follow_redirects=True
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_schedule(self) -> tuple[RawScheduleObservation, ...]:
        try:
            response = await self._client.get(_FEED_PATH)
        except httpx.RequestError as exc:
            raise EconomicCalendarSourceUnavailableError(
                f"failed to reach BLS calendar feed: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise EconomicCalendarSourceUnavailableError(
                f"BLS calendar feed request failed with status {response.status_code}"
            )

        observed_at = UtcTimestamp(datetime.now(UTC))
        events = parse_ics_events(response.text, default_timezone=_DEFAULT_TIMEZONE)
        observations: list[RawScheduleObservation] = []
        for event in events:
            indicator_keys = _SUMMARY_TO_INDICATORS.get(event.summary)
            if indicator_keys is None:
                continue  # UNMAPPED -- not a release title this registry covers
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
        return tuple(observations)

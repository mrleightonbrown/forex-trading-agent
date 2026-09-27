"""ONS (Office for National Statistics) official release-schedule
adapter (FX-52A).

Source: `https://www.ons.gov.uk/releasecalendar?rss&release-type=type-
upcoming&limit=...` -- ONS's own public RSS 2.0 feed, no API key,
confirmed live in this story's own source-verification pass. Confirmed
`<item>` shape: `<guid>` equal to `<link>` (a genuine, stable permalink
whose URL PATH encodes the release series -- e.g. `/economy/
grossdomesticproductgdp/bulletins/quarterlynationalaccounts/...`),
`<pubDate>` with an EXPLICIT `+0000` (UTC) offset -- resolving ADR
0003's own "timezone implicit" concern for this specific feed:
`pubDate` here is the scheduled release instant itself (confirmed by
inspecting real future-dated items), not merely the feed's own
publish time, unlike the general RSS caveat `rss_parsing` otherwise
applies.

Mapping is by URL PATH PREFIX, not by title text -- Section 12's own
preferred hierarchy ("exact source feed identifier" over title
matching) -- because the guid/link IS a stable per-release-series
identifier, unlike BLS/BoC's bare `SUMMARY` text. Only ONE path is
mapped in this pass (`GBP_GDP_QOQ`, ONS's quarterly GDP bulletin):
CPI/employment/retail-sales paths were NOT directly confirmed against
a real live item in this story's own research (see `docs/adr/0004-
official-economic-calendar-timing-sources.md`) and are deliberately
excluded rather than guessed -- a documented gap, not an oversight.

`reference_period` is extracted from the title's own explicit period
text (e.g. "GDP quarterly national accounts, UK: April to June 2026")
-- source-established, not derived by this adapter's own arithmetic
assumption (FX-52A Section 14). A title that does not match the known
pattern yields `reference_period=None`, never a guess.
"""

import re
from datetime import UTC, datetime

import httpx

from forex_agent.application.ports.economic_calendar_source import (
    EconomicCalendarSourceUnavailableError,
    RawScheduleObservation,
)
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.economic_calendar_sources.rss_parsing import parse_rss_items

_BASE_URL = "https://www.ons.gov.uk"
_FEED_PATH = "/releasecalendar"
_FEED_PARAMS = {
    "rss": "",
    "release-type": "type-upcoming",
    "limit": "20",
}
_TIMEOUT_SECONDS = 30.0
_SOURCE_NAME = "ONS_RSS"
_SCHEDULE_TIMEZONE = "Europe/London"

_PATH_PREFIX_TO_INDICATORS: dict[str, tuple[str, ...]] = {
    "/economy/grossdomesticproductgdp/bulletins/quarterlynationalaccounts/": ("GBP_GDP_QOQ",),
}

_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_PERIOD_PATTERN = re.compile(
    r"(?P<start_month>" + "|".join(_MONTH_NAMES) + r") to \w+ (?P<year>\d{4})$"
)


class OnsScheduleSource:
    """Implements `EconomicCalendarScheduleSource` against ONS's own
    public RSS feed."""

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
            response = await self._client.get(_FEED_PATH, params=_FEED_PARAMS)
        except httpx.RequestError as exc:
            raise EconomicCalendarSourceUnavailableError(
                f"failed to reach ONS release calendar feed: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise EconomicCalendarSourceUnavailableError(
                f"ONS release calendar feed request failed with status {response.status_code}"
            )

        observed_at = UtcTimestamp(datetime.now(UTC))
        items = parse_rss_items(response.text)
        observations: list[RawScheduleObservation] = []
        for item in items:
            indicator_keys = _indicator_keys_for_link(item.link)
            if indicator_keys is None:
                continue  # UNMAPPED -- not a release series this registry covers
            observations.append(
                RawScheduleObservation(
                    source=_SOURCE_NAME,
                    external_event_id=item.guid,
                    indicator_keys=indicator_keys,
                    scheduled_date=item.pub_date.date(),
                    scheduled_time=item.pub_date.time(),
                    schedule_timezone=_SCHEDULE_TIMEZONE,
                    status=EconomicEventStatus.SCHEDULED,
                    observed_at=observed_at,
                    raw_title=item.title,
                    reference_period=reference_period_from_title(item.title),
                )
            )
        return tuple(observations)


def _indicator_keys_for_link(link: str) -> tuple[str, ...] | None:
    for prefix, indicator_keys in _PATH_PREFIX_TO_INDICATORS.items():
        if prefix in link:
            return indicator_keys
    return None


def reference_period_from_title(title: str) -> UtcTimestamp | None:
    """Extracts a reference period from an ONS title's own explicit
    "<Month> to <Month> <Year>" text (e.g. "...: April to June
    2026") -- `None` if the title does not match this exact known
    pattern, never a guess (FX-52A Section 14)."""
    match = _PERIOD_PATTERN.search(title)
    if match is None:
        return None
    month_number = _MONTH_NAMES.index(match.group("start_month")) + 1
    year = int(match.group("year"))
    return UtcTimestamp(datetime(year, month_number, 1, tzinfo=UTC))

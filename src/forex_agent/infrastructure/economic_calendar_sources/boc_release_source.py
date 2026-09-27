"""Bank of Canada official release-occurrence adapter (FX-52A).

Source: `https://www.bankofcanada.ca/feed/?content_type=press-
releases` -- the Bank's own public press-release feed, confirmed live
in this story's own research pass to be RDF/RSS 1.0 (the CBWiki
"Central Bank RSS" schema: `<item rdf:about="...">`, `<dc:date>` with
an explicit UTC offset). This feed mixes rate announcements with
unrelated press releases (appointments, bank-note launches, ...) --
only a title matching `_RATE_ANNOUNCEMENT_TITLE_PATTERN` is treated as
release evidence for `CAD_POLICY_RATE_DECISION`; everything else is
UNMAPPED by construction.

`dc:date` is used directly as the release instant: for a genuine
PRESS-RELEASE feed specifically (unlike a forward-schedule feed), "when
this item was published" and "when the underlying event was released"
are the same real-world fact, not two different things FX-52A Section
32 warns about conflating -- that warning concerns a SCHEDULE feed's
`pubDate`, which is not what this adapter reads.
"""

import re
from datetime import UTC, datetime

import httpx

from forex_agent.application.ports.economic_calendar_source import (
    EconomicCalendarSourceUnavailableError,
    RawReleaseObservation,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.economic_calendar_sources.rss_parsing import parse_rss_items

_BASE_URL = "https://www.bankofcanada.ca"
_FEED_PATH = "/feed/"
_FEED_PARAMS = {"content_type": "press-releases"}
_TIMEOUT_SECONDS = 30.0
_SOURCE_NAME = "BOC_RSS"
_RELEASE_TIMEZONE = "UTC"

_RATE_ANNOUNCEMENT_TITLE_PATTERN = re.compile(
    r"^Bank of Canada (maintains|raises|increases|lowers|cuts|decreases) "
    r"(the|its) (target for the overnight rate|policy rate)",
    re.IGNORECASE,
)
_INDICATOR_KEYS: tuple[str, ...] = ("CAD_POLICY_RATE_DECISION",)


class BocReleaseSource:
    """Implements `EconomicCalendarReleaseSource` against the Bank of
    Canada's own public press-release feed."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=_BASE_URL, timeout=_TIMEOUT_SECONDS, follow_redirects=True
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_releases(self) -> tuple[RawReleaseObservation, ...]:
        try:
            response = await self._client.get(_FEED_PATH, params=_FEED_PARAMS)
        except httpx.RequestError as exc:
            raise EconomicCalendarSourceUnavailableError(
                f"failed to reach Bank of Canada press-release feed: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise EconomicCalendarSourceUnavailableError(
                f"Bank of Canada press-release feed request failed with status "
                f"{response.status_code}"
            )

        observed_at = UtcTimestamp(datetime.now(UTC))
        items = parse_rss_items(response.text)
        observations: list[RawReleaseObservation] = []
        for item in items:
            if not _RATE_ANNOUNCEMENT_TITLE_PATTERN.match(item.title):
                continue  # UNMAPPED -- not a rate-announcement press release
            observations.append(
                RawReleaseObservation(
                    source=_SOURCE_NAME,
                    external_event_id=item.guid,
                    indicator_keys=_INDICATOR_KEYS,
                    released_date=item.pub_date.date(),
                    released_time=item.pub_date.time(),
                    released_timezone=_RELEASE_TIMEZONE,
                    observed_at=observed_at,
                    raw_title=item.title,
                )
            )
        return tuple(observations)

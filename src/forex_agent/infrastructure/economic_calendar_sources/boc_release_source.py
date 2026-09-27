"""Bank of Canada official release-occurrence adapter (FX-52A; release-
time semantics corrected by FX-52AH).

Source: `https://www.bankofcanada.ca/feed/?content_type=press-
releases` -- the Bank's own public press-release feed, confirmed live
in this story's own research pass to be RDF/RSS 1.0 (the CBWiki
"Central Bank RSS" schema: `<item rdf:about="...">`, `<dc:date>` with
an explicit UTC offset, and -- on at least some items -- a nested
`<cb:news><cb:occurrenceDate>` date-only field). This feed mixes rate
announcements with unrelated press releases (appointments, bank-note
launches, ...) -- only a title matching `_RATE_ANNOUNCEMENT_TITLE_
PATTERN` is treated as release evidence for `CAD_POLICY_RATE_
DECISION`; everything else is UNMAPPED by construction.

FX-52AH CORRECTION: FX-52A's original version used `dc:date` directly
as an EXACT `released_time`, reasoning that "when this item was
published" and "when the underlying event was released" are the same
fact for a press-release feed. On reflection this overclaimed:
`dc:date` is documented by the CBWiki schema only as a generic
Dublin-Core "date of the resource" -- nothing in Bank of Canada's own
primary documentation establishes that it carries second-level
precision equal to the OFFICIAL announcement instant (as opposed to,
say, whenever the press office's publishing system happened to commit
the item). This adapter therefore no longer promotes `dc:date` to
`released_time` at all:

- `released_date` prefers `cb:occurrenceDate` (a field the CBWiki
  schema defines specifically for "the date this news item's subject
  actually occurred") when present, falling back to `dc:date`'s own
  calendar date when it is not -- a same-day publication is a safe
  enough date-level inference for a press release, even though its
  own exact TIME is not.
- `released_time` is always `None` -- genuinely unestablished, never
  fabricated (FX-52A's own "never fabricate a time" discipline,
  applied here for the first time to a RELEASE fact rather than a
  SCHEDULE one).
- `dc:date` itself is preserved as `source_published_at` -- provenance
  only, never interpreted as the announcement's own official timing.
"""

import re
from datetime import UTC, datetime

import httpx

from forex_agent.application.ports.economic_calendar_source import (
    EconomicCalendarSourceUnavailableError,
    RawReleaseObservation,
    ReleaseFetchResult,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.economic_calendar_sources.rss_parsing import (
    MalformedFeedError,
    parse_rss_items,
)

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

    async def fetch_releases(self) -> ReleaseFetchResult:
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

        try:
            parsed = parse_rss_items(response.text)
        except MalformedFeedError as exc:
            raise EconomicCalendarSourceUnavailableError(
                f"Bank of Canada press-release feed did not parse as RSS: {exc}"
            ) from exc

        observed_at = UtcTimestamp(datetime.now(UTC))
        observations: list[RawReleaseObservation] = []
        unmapped_count = 0
        for item in parsed.items:
            if not _RATE_ANNOUNCEMENT_TITLE_PATTERN.match(item.title):
                unmapped_count += 1  # not a rate-announcement press release
                continue
            observations.append(
                RawReleaseObservation(
                    source=_SOURCE_NAME,
                    external_event_id=item.guid,
                    indicator_keys=_INDICATOR_KEYS,
                    released_date=item.occurrence_date or item.pub_date.date(),
                    released_time=None,
                    released_timezone=_RELEASE_TIMEZONE,
                    observed_at=observed_at,
                    raw_title=item.title,
                    source_published_at=UtcTimestamp(item.pub_date),
                )
            )
        return ReleaseFetchResult(
            observations=tuple(observations),
            mapped_count=len(observations),
            unmapped_count=unmapped_count,
            invalid_count=parsed.invalid_count,
        )

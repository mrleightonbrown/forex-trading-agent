"""FX-57A: Federal Reserve RSS news source adapter.

Implements exactly the three Fed aggregate RSS feeds ADR 0005 adopted
-- monetary-policy press releases, speeches, and testimony -- as live-
verified on 2026-10-03 (see this story's own final report for the full
live-validation record). Deliberately excludes per-governor feeds,
yearly HTML archive scraping, and any article-page fetch (FX-57A
Section 5/16): this is RSS metadata ingestion, not HTML extraction.

`source_key` is always the already-registered `"FED"` (`domain.
news_source_registry.FEDERAL_RESERVE`) -- never a per-feed key; a
feed/channel is provenance BELOW that stable identity (FX-57A Section
6). `external_item_id` is always the RSS `<guid>`, confirmed live to
equal the item's own canonical `<link>` with no `isPermaLink`
attribute present on any sampled item.

**FX-57A originally reused `source_content_type` for Fed's own
channel identity** (each Fed feed maps 1:1 to one descriptive content
type), deferring a genuinely separate `source_channel` field until a
future source demonstrated the two axes diverge. **FX-57B's own ECB
adapter did exactly that** (ECB's single combined feed serves three
content types through ONE channel), so `source_channel` now exists as
a real, separate, `NOT NULL` field (migration `a95058f88727`) -- Fed
simply sets it to its own already-known channel value
(`feed.channel`: `press_monetary`/`speeches`/`testimony`), identical
to what it always reported via `source_content_type`. This is a pure
provenance refinement: Fed's own item identity, mapping, and content-
type values are completely unchanged; see `docs/DECISIONS.md` for
both decisions (FX-57A's original reuse, and FX-57B's follow-up
field) recorded in full.
"""

from dataclasses import dataclass

import httpx

from forex_agent.application.ports.news_source import (
    NewsSourceFetchOutcome,
    NewsSourceUnavailableError,
    NormalizedNewsObservation,
)
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.news_source_timestamp_provenance import NewsSourceTimestampProvenance
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.news_sources.http_fetch import ClockFn, default_clock, fetch_text
from forex_agent.infrastructure.news_sources.rss_item_parsing import (
    MalformedNewsFeedError,
    NewsRssItem,
    parse_news_rss_items,
)

SOURCE_KEY = "FED"
_BASE_URL = "https://www.federalreserve.gov"
_TIMEOUT_SECONDS = 30.0
_USER_AGENT = "forex-agent-research/1.0 (+https://github.com/mrleightonbrown/forex-trading-agent)"


@dataclass(frozen=True, slots=True)
class FedFeedDefinition:
    """One explicit, statically-configured Fed aggregate feed -- never
    discovered dynamically or crawled (FX-57A Section 7)."""

    channel: str
    path: str
    content_type: str
    language: str = "en"


FED_FEEDS: tuple[FedFeedDefinition, ...] = (
    FedFeedDefinition(
        channel="press_monetary",
        path="/feeds/press_monetary.xml",
        content_type="monetary_policy_release",
    ),
    FedFeedDefinition(
        channel="speeches",
        path="/feeds/speeches.xml",
        content_type="speech",
    ),
    FedFeedDefinition(
        channel="testimony",
        path="/feeds/testimony.xml",
        content_type="testimony",
    ),
)


class FedRssSource:
    """Fetches and normalizes one Fed feed at a time via `fetch_feed`
    -- callers build the zero-argument `NewsSourceChannelFetcher`
    closures `IngestNewsSourceOnce` expects (e.g. via
    `functools.partial(source.fetch_feed, feed)` for each configured
    feed)."""

    def __init__(
        self, client: httpx.AsyncClient | None = None, *, clock: ClockFn = default_clock
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=_TIMEOUT_SECONDS,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
        self._clock = clock

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_feed(self, feed: FedFeedDefinition) -> NewsSourceFetchOutcome:
        fetched = await fetch_text(self._client, feed.path, clock=self._clock)
        try:
            parsed = parse_news_rss_items(fetched.text)
        except MalformedNewsFeedError as exc:
            raise NewsSourceUnavailableError(
                f"Fed {feed.channel} feed at {feed.path} did not parse as RSS: {exc}"
            ) from exc

        observations = tuple(
            _to_observation(item, feed, fetched.retrieved_at) for item in parsed.items
        )
        return NewsSourceFetchOutcome(
            source_channel=feed.channel,
            retrieved_at=fetched.retrieved_at,
            observations=observations,
            items_invalid=parsed.invalid_count,
            invalid_reasons=parsed.invalid_reasons,
        )


def _to_observation(
    item: NewsRssItem, feed: FedFeedDefinition, retrieved_at: UtcTimestamp
) -> NormalizedNewsObservation:
    timestamp_provenance: tuple[NewsSourceTimestampProvenance, ...] = ()
    source_published_at: UtcTimestamp | None = None
    if item.raw_pub_date is not None:
        if item.pub_date is not None:
            source_published_at = UtcTimestamp(item.pub_date)
            note = "standard RSS/RFC-822 pubDate parsing"
        else:
            note = item.pub_date_issue or "pubDate present but unusable"
        timestamp_provenance = (
            NewsSourceTimestampProvenance(
                field_name="pubDate",
                raw_value=item.raw_pub_date,
                normalized_at=source_published_at,
                normalization_note=note,
            ),
        )

    return NormalizedNewsObservation(
        source_key=SOURCE_KEY,
        external_item_id=item.guid,
        observed_at=retrieved_at,
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline=item.title,
        source_channel=feed.channel,
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        summary=item.description,
        body_text=None,
        canonical_url=item.link,
        authors=(),
        language=feed.language,
        source_content_type=feed.content_type,
        source_published_at=source_published_at,
        source_updated_at=None,
        source_timestamp_provenance=timestamp_provenance,
        source_revision_metadata=(),
        quarantine_reason=None,
    )

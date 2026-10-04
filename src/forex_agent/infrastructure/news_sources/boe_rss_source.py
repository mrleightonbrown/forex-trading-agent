"""FX-57C: Bank of England news/speeches/publications RSS source
adapter.

Implements exactly the three adopted BoE RSS feeds (ADR 0005),
live-reconfirmed on 2026-10-03: `/rss/news` (includes MPC minutes and
Financial Policy Committee records), `/rss/speeches`, `/rss/
publications` -- 50 items each, matching the ADR's own finding
exactly. No per-governor/per-committee feeds, no yearly archive
scraping, no article-page fetch (Section 25/33/59): RSS metadata
ingestion only.

`source_key` is always the already-registered `"BOE"` (`domain.
news_source_registry.BANK_OF_ENGLAND`) -- never a per-feed key.
`external_item_id` is always the RSS `<guid>`, confirmed live to be a
genuinely OPAQUE CMS identifier (`{B641CC4F-0AD7-46E2-9965-
B44629C6E93E}`-shaped, `isPermaLink="false"` on every sampled item) --
NOT the canonical URL, unlike Fed and ECB. BoE's own design is the
strongest identity among the RSS sources adopted so far: a slug
rename of the linked article cannot break this GUID.

**Each feed maps 1:1 to one content type** (`news`/`speech`/
`publication`), exactly like Fed's own shape (FX-57A) -- unlike ECB's
single combined feed (FX-57B), so `BoeFeedDefinition` carries its own
`content_type`, and `source_channel`/`source_content_type` happen to
coincide per-feed even though they remain genuinely separate fields.

**Cross-channel GUID overlap, explicitly checked live (FX-57C Section
9) -- NONE found.** All 150 sampled GUIDs (50 per feed x 3 feeds)
were confirmed pairwise distinct across all three feeds, as well as
unique within each feed. This clears the architectural concern the
story's own Section 9 raised (a GUID legitimately belonging to more
than one BoE channel at once would have made `source_channel`
unsafe to model as ordinary vintaged provenance) -- the standard
FX-56/FX-57 model applies without modification. If a future poll
ever DOES observe the same GUID across two BoE channels, `Record
NewsObservation`'s existing modeled-fact-equality mechanism would
treat the channel difference as a genuine provenance change (a new
vintage, never a new item) -- this has simply never been observed
live for BoE.

**Mixed pubDate timezone format, confirmed exactly as ADR 0005
predicted -- requires NO new code.** The speeches feed mixes RFC-822
numeric offsets (`+0100`, British Summer Time) with the bare
military-zone form (`Z`, i.e. UTC+0/GMT) within the SAME document;
`news` and `publications` were observed `+0100`-only in this sample.
Both forms were independently verified to parse correctly through the
EXISTING shared `email.utils.parsedate_to_datetime` (already used by
`rss_item_parsing`, Fed, and ECB) -- `"...16:00:00 Z"` parses to a
real, tz-aware UTC instant, and `"...09:00:00 +0100"` parses to the
correct UTC-shifted instant. The `Z`-tagged items cluster exactly in
GMT-season months (Jan-Mar) and the `+0100`-tagged items cluster
exactly in BST-season months (Apr-Oct) in the live sample -- BoE's own
CMS appears to simply render the zulu letter form instead of the
literal `+0000` offset during GMT season, a cosmetic quirk, not a
data defect. No BoE-specific timestamp normalization code exists in
this adapter; both forms flow through the SAME unmodified shared
parser Fed/ECB already use.

**No future-dated items observed (FX-57C Section 20) -- documented as
a negative finding, no quarantine rule added.** All 150 sampled items
across all three feeds had `source_published_at` strictly in the
past relative to the live retrieval instant. No speculative
future-date tolerance or quarantine threshold was invented.

**No description beyond the feed's own `<description>` is used as
`summary`** -- confirmed live to be a genuine, substantive per-item
summary (not boilerplate) on every sampled item. `body_text` is
always `None` (no article-page fetch). `authors` is always `()` (zero
`<author>` elements observed on any sampled item across any feed --
a speaker's name appearing inside a speech title, e.g. "Sasha Mills:
speech at...", is NOT parsed out into a structured author field).
`language` is always `"en"` (the feed's own declared, static
channel-level value). `source_updated_at` is always `None` (no
verified BoE correction/update field exists).

**Rights boundary, live-reconfirmed (FX-57C Section 65), unchanged
from ADR 0005**: `bankofengland.co.uk/legal` was re-fetched directly
and still states, word for word, that site Resources may be used "for
personal use or internal use within an individual organisation for
non-commercial purposes" -- exactly FTA's current research/paper-
trading use, with redistribution and commercial use still requiring
separate permission. No rights reinterpretation or expansion was made
or is implied by this adapter; it ingests only the feed-supplied
metadata fields above, never the linked article/PDF.
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

SOURCE_KEY = "BOE"
_BASE_URL = "https://www.bankofengland.co.uk"
_TIMEOUT_SECONDS = 30.0
_USER_AGENT = "forex-agent-research/1.0 (+https://github.com/mrleightonbrown/forex-trading-agent)"


@dataclass(frozen=True, slots=True)
class BoeFeedDefinition:
    """One explicit, statically-configured BoE feed -- never
    discovered dynamically or crawled (FX-57C Section 5)."""

    channel: str
    path: str
    content_type: str
    language: str = "en"


BOE_FEEDS: tuple[BoeFeedDefinition, ...] = (
    BoeFeedDefinition(channel="boe_news", path="/rss/news", content_type="news"),
    BoeFeedDefinition(channel="boe_speeches", path="/rss/speeches", content_type="speech"),
    BoeFeedDefinition(
        channel="boe_publications", path="/rss/publications", content_type="publication"
    ),
)


class BoeRssSource:
    """Fetches and normalizes one BoE feed at a time via `fetch_feed`
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

    async def fetch_feed(self, feed: BoeFeedDefinition) -> NewsSourceFetchOutcome:
        fetched = await fetch_text(self._client, feed.path, clock=self._clock)
        try:
            parsed = parse_news_rss_items(fetched.text)
        except MalformedNewsFeedError as exc:
            raise NewsSourceUnavailableError(
                f"BoE {feed.channel} feed at {feed.path} did not parse as RSS: {exc}"
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
    item: NewsRssItem, feed: BoeFeedDefinition, retrieved_at: UtcTimestamp
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

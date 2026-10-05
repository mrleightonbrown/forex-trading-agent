"""FX-57E: Statistics Canada "The Daily" prospective subject-feed
adapter -- exactly four English macro-relevant subject feeds (ADR
0005's own minimum macro set), built on `statcan_atom_parsing.py`'s
dedicated Atom evidence parser.

**Four explicit, static channels (Section 6)**: discovered/hardcoded
here, never dynamically enumerated from StatCan's own feed-index page
at ingestion time -- exactly mirroring Fed/ECB/BoE's own static feed
lists. The "all subjects" feed (`/0-eng.atom`) is never used; it would
duplicate the four selected subject feeds and broaden scope beyond
this story's own intentionally bounded set.

**Cross-subject identity overlap (Section 7) -- live research result:
GENUINE, REPRODUCIBLE OVERLAP FOUND** -- unlike every prior FX-57
source. Comparing every pairwise Atom-id intersection among genuine
Daily-release article ids across all four adopted feeds, live, twice,
independently, found the SAME Daily release cross-listed under
multiple subject feeds simultaneously (e.g. `dq260903a`, "Canadian
international merchandise trade, July 2026," appears identically in
both `prices` and `international_trade`). This disproved FX-57B/
FX-57CH's own durable assumption that a vintage has one `source_
channel` "at a time," and is exactly why FX-57E paused pending an
architecture review: **ADR 0006 / FX-57E0** corrected the model so
this is now representable truthfully. `source_channel` stays
singular (the channel of THIS vintage's own observation); `NewsItem
Vintage.observed_source_channels` (FX-57E0) carries the cumulative set
of every channel FTA has observed an item through. `CrossChannel
IdentityCollisionError` is RETIRED -- `IngestNewsSourceOnce` now keeps
BOTH observations of a cross-listed release (their non-channel facts
agree, since `source_content_type` is held constant at `"daily_
release"` across all four feeds below, never varying by channel the
way Fed's own per-channel content type does), merging them into one
item's own cumulative channel set via `RecordNewsObservation`. This
adapter's own `live_source` test re-checks this exact finding every
run -- asserting that any overlap found is BENIGN (agreeing non-
channel facts), not that no overlap exists (see that test's own
docstring).

**Sequential fetching, one `retrieved_at` per feed response (Sections
16/24)**: `StatCanSource` exposes one `fetch_feed(feed)` coroutine per
configured `StatCanFeedDefinition`; a caller passes all four as
separate fetchers into ONE `IngestNewsSourceOnce` run, exactly like
every other FX-57 multi-channel adapter -- `IngestNewsSourceOnce`
itself already iterates its fetchers sequentially, so no additional
concurrency guard is needed here. Each `fetch_feed` call captures its
OWN `retrieved_at`, shared by every observation parsed from that one
response, never a single run-start/run-end timestamp across all four.

**Crawl-delay pacing (Sections 22/23)**: `robots.txt` at `www150.
statcan.gc.ca` sets `User-agent: * / Crawl-delay: 2` (live-
reconfirmed), with no `Disallow` covering `/n1/rss/dai-quo/`.
`StatCanSource` paces every request it makes -- including `http_
fetch.fetch_text`'s own internal retry attempts, via that function's
`before_attempt` hook (FX-57E's own narrow, provider-neutral
extension to the common transport) -- to at least `crawl_delay_
seconds` (default 2.0) apart, using an injectable monotonic clock and
async sleep, mirroring `GovUkHmtSource._pace`'s own shape exactly.

**Timestamp semantics (Section 17, Case B)**: these feeds expose only
`<updated>`, never `<published>`. Live research found every same-day
entry across all four feeds shares one identical `08:30:00-04:00`
value, which always matches the date embedded in that SAME entry's
own `id` -- strong, direct evidence this field represents The Daily's
own release instant, not a later edit timestamp. It is therefore
mapped to `source_published_at` (never simultaneously to `source_
updated_at`, which stays `None` -- there is no second, genuinely
distinct update-time field anywhere in this schema), while the raw
`<updated>` string is ALSO preserved, unconditionally, as its own
`NewsSourceTimestampProvenance` entry. `availability`/`observed_at`
remains this adapter's own `retrieved_at` throughout, per FX-55H's
invariant -- never this timestamp, however confidently it is mapped.

**Daily-release articles vs recurring product/catalogue references**:
see `statcan_atom_parsing.py`'s own module docstring for the live
finding that drove that parser's own id-shape validation -- this
adapter relies on that validation entirely; it does not re-implement
any of it.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

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
from forex_agent.infrastructure.news_sources.http_fetch import (
    ClockFn,
    SleepFn,
    default_clock,
    fetch_text,
)
from forex_agent.infrastructure.news_sources.statcan_atom_parsing import (
    MalformedStatCanAtomFeedError,
    StatCanAtomEntry,
    parse_statcan_daily_atom,
)

SOURCE_KEY = "STATCAN"
_BASE_URL = "https://www150.statcan.gc.ca"
_CONTENT_TYPE = "daily_release"
_TIMEOUT_SECONDS = 30.0
_USER_AGENT = "forex-agent-research/1.0 (+https://github.com/mrleightonbrown/forex-trading-agent)"
_CRAWL_DELAY_SECONDS = 2.0  # robots.txt at www150.statcan.gc.ca: User-agent: * / Crawl-delay: 2


@dataclass(frozen=True, slots=True)
class StatCanFeedDefinition:
    channel: str
    path: str
    language: str = "en"


STATCAN_FEEDS: tuple[StatCanFeedDefinition, ...] = (
    StatCanFeedDefinition(channel="statcan_prices", path="/n1/rss/dai-quo/18-eng.atom"),
    StatCanFeedDefinition(channel="statcan_labour", path="/n1/rss/dai-quo/14-eng.atom"),
    StatCanFeedDefinition(channel="statcan_economic_accounts", path="/n1/rss/dai-quo/36-eng.atom"),
    StatCanFeedDefinition(
        channel="statcan_international_trade", path="/n1/rss/dai-quo/12-eng.atom"
    ),
)

MonotonicFn = Callable[[], float]


def _default_monotonic() -> float:
    return time.monotonic()


async def _default_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


class StatCanSource:
    """Coordinates Statistics Canada "The Daily" subject-feed polling.
    `fetch_feed` hydrates exactly ONE configured feed and is itself a
    complete `NewsSourceChannelFetcher`. Callers build one such
    fetcher per `StatCanFeedDefinition` in `STATCAN_FEEDS` and pass
    them all to `IngestNewsSourceOnce` together (see the module
    docstring)."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        clock: ClockFn = default_clock,
        crawl_delay_seconds: float = _CRAWL_DELAY_SECONDS,
        sleep: SleepFn = _default_sleep,
        monotonic: MonotonicFn = _default_monotonic,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=_TIMEOUT_SECONDS,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
        self._clock = clock
        self._crawl_delay_seconds = crawl_delay_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _pace(self) -> None:
        """Blocks until at least `crawl_delay_seconds` have elapsed
        since this instance's own last request -- called before EVERY
        HTTP attempt `fetch_feed` makes, including `fetch_text`'s own
        internal retries (Section 23), so this adapter can never
        violate the documented `Crawl-delay: 2` even under transient
        5xx/429 retry. Uses an injectable monotonic clock and sleep so
        a deterministic test can prove the pacing math without
        actually waiting."""
        now = self._monotonic()
        if self._last_request_at is not None:
            remaining = self._crawl_delay_seconds - (now - self._last_request_at)
            if remaining > 0:
                await self._sleep(remaining)
                now = self._monotonic()
        self._last_request_at = now

    async def fetch_feed(self, feed: StatCanFeedDefinition) -> NewsSourceFetchOutcome:
        """Hydrates exactly ONE configured StatCan subject feed.
        Raises `NewsSourceUnavailableError` if the HTTP fetch itself
        fails (after crawl-delay-paced retries) or the response does
        not parse as Atom at all. A structurally-invalid individual
        entry (missing id/title/link, or an id that is not a dated
        Daily-release article -- see `statcan_atom_parsing.py`) is an
        ordinary item-level invalid, never escalated to this
        exception."""
        fetched = await fetch_text(
            self._client,
            feed.path,
            clock=self._clock,
            before_attempt=self._pace,
            sleep=self._sleep,
        )
        try:
            parsed = parse_statcan_daily_atom(fetched.text)
        except MalformedStatCanAtomFeedError as exc:
            raise NewsSourceUnavailableError(
                f"StatCan {feed.channel!r} feed did not parse as Atom: {exc}"
            ) from exc

        observations = tuple(
            _to_observation(entry, feed, fetched.retrieved_at) for entry in parsed.entries
        )
        return NewsSourceFetchOutcome(
            source_channel=feed.channel,
            retrieved_at=fetched.retrieved_at,
            observations=observations,
            items_invalid=parsed.invalid_count,
            invalid_reasons=parsed.invalid_reasons,
        )


def _parse_utc_timestamp(raw: str) -> UtcTimestamp | None:
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return UtcTimestamp(parsed)


def _to_observation(
    entry: StatCanAtomEntry, feed: StatCanFeedDefinition, retrieved_at: UtcTimestamp
) -> NormalizedNewsObservation:
    normalized_updated = _parse_utc_timestamp(entry.updated_raw)
    note = (
        "standard ISO-8601 Atom <updated> parsing; live research confirmed this field "
        "represents The Daily's own release instant for every sampled entry (identical "
        "across same-day releases, and matching the date embedded in each entry's own "
        "id) rather than a later edit time -- mapped to source_published_at only, never "
        "simultaneously to source_updated_at"
        if normalized_updated is not None
        else "did not parse as a timezone-aware ISO-8601 timestamp"
    )
    timestamp_provenance = (
        NewsSourceTimestampProvenance(
            field_name="updated",
            raw_value=entry.updated_raw,
            normalized_at=normalized_updated,
            normalization_note=note,
        ),
    )

    return NormalizedNewsObservation(
        source_key=SOURCE_KEY,
        external_item_id=entry.entry_id,
        observed_at=retrieved_at,
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline=entry.title,
        source_channel=feed.channel,
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        summary=entry.summary,
        body_text=None,
        canonical_url=entry.canonical_url,
        authors=(),
        language=feed.language,
        source_content_type=_CONTENT_TYPE,
        source_published_at=normalized_updated,
        source_updated_at=None,
        source_timestamp_provenance=timestamp_provenance,
        source_revision_metadata=(),
        quarantine_reason=None,
    )

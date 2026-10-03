"""FX-57B: European Central Bank combined press/speech/interview RSS
source adapter.

Implements exactly the ONE adopted ECB feed, `/rss/press.html` (ADR
0005), under the already-registered `source_key="ECB"` (`domain.
news_source_registry.ECB`). Reuses the common transport (`infra
structure.news_sources.http_fetch.fetch_text`) and the common RSS
parser (`infrastructure.news_sources.rss_item_parsing.parse_news_rss_
items`) unchanged -- live re-verification on 2026-10-03 confirmed the
feed is still a well-formed RSS 2.0 document with a `<channel>`, fully
compatible with the shared, RSS-only parser FX-57AH hardened.

**Proves `source_channel` != `source_content_type` (FX-57B Section
10)**: unlike Fed's three feeds (one content type each), this ONE
ECB feed serves THREE content types -- `press_release`/`speech`/
`interview` -- so every ECB observation shares the SAME `source_
channel` (`"ecb_press"`) while `source_content_type` varies per item.
This is the first adapter to exercise the genuinely separate `source_
channel` field added by migration `a95058f88727`.

**Content-type discrimination is a SOURCE-STRUCTURAL fact, not FX-59
classification (Section 16)**: ECB's own URL namespace encodes
content class directly in the link/guid filename, immediately after
the literal `"ecb."` prefix -- e.g. `ecb.pr261002...` (press release),
`ecb.sp261002_1...` (speech), `ecb.in260930...` (interview). Live
re-verification found a FOURTH code, `ecb.gc...` ("Governing Council"
decision notices, e.g. "Decisions taken by the Governing Council of
the ECB (in addition to decisions setting interest rates)") -- not
documented in ADR 0005's own stated `pr`/`sp`/`in` trio. Mapped here
to `press_release` after explicit reasoning (not a silent guess, per
Section 17): a Governing Council decision notice bears no individual
author's name, so it cannot fall inside the ECB's own Working/
Occasional-Paper written-authorisation carve-out, and it is served
through the SAME single adopted feed URL ADR 0005 already blanket-
adopted -- see `docs/DECISIONS.md`'s FX-57B entry and the ADR 0005
addendum for the full reasoning. **Any OTHER, unrecognized content
class fails closed as an invalid item** (`_CONTENT_CLASS_TO_TYPE` is a
whitelist, never a blocklist) -- this is also how Working Papers/
Occasional Papers (rights-excluded, Section 18) would be refused if
one ever appeared in this feed, without needing a separate exclusion
list: nothing is admitted unless its class is explicitly, positively
known-safe.

**Operational caveat, documented per Section 34/35, no scheduler
added**: live-reconfirmed at exactly 15 items (matching ADR 0005's own
"~15 items" finding) -- this feed is genuinely shallow. A future
operational poller (not built here) must poll frequently enough that
a burst of more than ~15 new items between polls cannot create a
silent evidence gap; this module does not and cannot detect such a
gap itself (it has no way to prove an item was missed), so it makes no
completeness claim beyond "the response returned N items."

**No description, no author, no per-item language (live-reconfirmed,
Section 21/23/24)**: every live-sampled ECB item carries only `title`/
`link`/`guid`/`pubDate` -- `summary`/`authors` naturally resolve to
`None`/`()` through the shared parser's own item shape; `language` is
the feed's own declared, static channel-level value (`"en"`), not a
per-item field. `body_text` is always `None` -- this adapter never
fetches the linked ECB article page (Section 22/52).
"""

import re
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

SOURCE_KEY = "ECB"
_BASE_URL = "https://www.ecb.europa.eu"
_TIMEOUT_SECONDS = 30.0
_USER_AGENT = "forex-agent-research/1.0 (+https://github.com/mrleightonbrown/forex-trading-agent)"

_CONTENT_CLASS_PATTERN = re.compile(r"ecb\.([a-z]+)\d")

_CONTENT_CLASS_TO_TYPE: dict[str, str] = {
    "pr": "press_release",
    "sp": "speech",
    "in": "interview",
    # "Governing Council" decision notices -- institutional
    # announcements, never author-named -- see this module's own
    # docstring and docs/DECISIONS.md's FX-57B entry for the full
    # reasoning behind admitting this undocumented-by-ADR-0005 code.
    "gc": "press_release",
}


@dataclass(frozen=True, slots=True)
class EcbFeedDefinition:
    """The ONE explicit, statically-configured ECB feed -- never
    discovered dynamically or crawled (FX-57B Section 9). Deliberately
    has no `content_type` field (unlike `FedFeedDefinition`): ECB's
    single channel serves several content types, determined per item
    from its own URL namespace, never from which feed it came from."""

    channel: str
    path: str
    language: str = "en"


ECB_FEEDS: tuple[EcbFeedDefinition, ...] = (
    EcbFeedDefinition(channel="ecb_press", path="/rss/press.html"),
)


class EcbRssSource:
    """Fetches and normalizes the one configured ECB feed via
    `fetch_feed` -- callers build the zero-argument `NewsSourceChannel
    Fetcher` closure `IngestNewsSourceOnce` expects (e.g. via
    `functools.partial(source.fetch_feed, ECB_FEEDS[0])`)."""

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

    async def fetch_feed(self, feed: EcbFeedDefinition) -> NewsSourceFetchOutcome:
        fetched = await fetch_text(self._client, feed.path, clock=self._clock)
        try:
            parsed = parse_news_rss_items(fetched.text)
        except MalformedNewsFeedError as exc:
            raise NewsSourceUnavailableError(
                f"ECB {feed.channel} feed at {feed.path} did not parse as RSS: {exc}"
            ) from exc

        observations: list[NormalizedNewsObservation] = []
        invalid_reasons: list[str] = list(parsed.invalid_reasons)
        invalid_count = parsed.invalid_count
        for item in parsed.items:
            content_type = _content_type_for(item.link or item.guid)
            if content_type is None:
                invalid_count += 1
                invalid_reasons.append(
                    f"guid={item.guid!r}: unrecognized ECB content class in URL -- "
                    "refusing to guess (FX-57B Section 17)"
                )
                continue
            observations.append(_to_observation(item, feed, content_type, fetched.retrieved_at))

        return NewsSourceFetchOutcome(
            source_channel=feed.channel,
            retrieved_at=fetched.retrieved_at,
            observations=tuple(observations),
            items_invalid=invalid_count,
            invalid_reasons=tuple(invalid_reasons),
        )


def _content_type_for(url: str | None) -> str | None:
    if url is None:
        return None
    match = _CONTENT_CLASS_PATTERN.search(url)
    if match is None:
        return None
    return _CONTENT_CLASS_TO_TYPE.get(match.group(1))


def _to_observation(
    item: NewsRssItem,
    feed: EcbFeedDefinition,
    content_type: str,
    retrieved_at: UtcTimestamp,
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
        source_content_type=content_type,
        source_published_at=source_published_at,
        source_updated_at=None,
        source_timestamp_provenance=timestamp_provenance,
        source_revision_metadata=(),
        quarantine_reason=None,
    )

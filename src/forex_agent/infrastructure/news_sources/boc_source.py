"""FX-57F: Bank of Canada prospective press-release ingestion.

Adopts ONLY the single press-releases feed ADR 0005 approved
(`content_type/press-releases/feed/`, live-reconfirmed for this story
to match that shorthand exactly -- no endpoint drift found). The
speeches feed remains explicitly excluded: no production requests,
and no fetcher for it exists anywhere in this module.

**One genuine channel (`CHANNEL`)**: unlike Fed/ECB's multi-feed or
StatCan's multi-subject shape, Bank of Canada is adopted here as a
single-channel source -- there is exactly one adopted feed, so (unlike
`FedFeedDefinition`/`StatCanFeedDefinition`) no per-feed definition
dataclass is needed; this mirrors `govuk_content_api.py`'s own
single-channel `CHANNEL` constant shape rather than Fed/StatCan's
multi-channel one.

**`source_content_type` is fixed, never inferred (Section 9)**: every
observation reports the constant `"press_release"`, regardless of
title wording ("increases its policy rate," "maintains," etc.) or the
feed's own unread `<cb:news>` block -- see `boc_rdf_parsing.py`'s own
module docstring for why that block is not read at all.

**Timestamp remediation wiring (Section 20/27/37)**: `dc:date` is
known-malformed (see `boc_timestamp_remediation.py` for the full,
live-reconfirmed defect record and remediation design). A missing
`dc:date` (parser-confirmed optional, never item-invalid) simply
yields no timestamp provenance and `source_published_at=None` -- it is
NOT treated as a remediation failure. Whenever `dc:date` IS present,
its raw string is preserved unconditionally in `NewsSourceTimestampProvenance`
regardless of whether remediation succeeds. `source_published_at` is
the ONLY field the remediated value may ever reach; `observed_at`
remains this adapter's own response `retrieved_at` throughout, with no
exception, exactly like every other FX-57 adapter.
"""

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
from forex_agent.infrastructure.news_sources.boc_rdf_parsing import (
    BocPressReleaseEntry,
    MalformedBocFeedError,
    parse_boc_press_releases_rdf,
)
from forex_agent.infrastructure.news_sources.boc_timestamp_remediation import (
    remediate_boc_dc_date,
)
from forex_agent.infrastructure.news_sources.http_fetch import ClockFn, default_clock, fetch_text

SOURCE_KEY = "BOC"
CHANNEL = "boc_press_releases"
_BASE_URL = "https://www.bankofcanada.ca"
_FEED_PATH = "/content_type/press-releases/feed/"
_CONTENT_TYPE = "press_release"
_LANGUAGE = "en"
_TIMEOUT_SECONDS = 30.0
_USER_AGENT = "forex-agent-research/1.0 (+https://github.com/mrleightonbrown/forex-trading-agent)"


class BocSource:
    """Fetches and normalizes the Bank of Canada press-releases feed
    via `fetch_press_releases`, a complete `NewsSourceChannelFetcher`.
    No `before_attempt` pacing hook is used -- live-reconfirmed
    robots.txt has no `Crawl-delay` affecting this feed, unlike
    StatCan's own adapter."""

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

    async def fetch_press_releases(self) -> NewsSourceFetchOutcome:
        """Raises `NewsSourceUnavailableError` if the HTTP fetch
        itself fails or the response is not a recognizable RSS 1.0/RDF
        document at all. A structurally-invalid individual item
        (missing identity/link/title) is an ordinary item-level
        invalid, counted via `items_invalid`, never escalated."""
        fetched = await fetch_text(self._client, _FEED_PATH, clock=self._clock)
        try:
            parsed = parse_boc_press_releases_rdf(fetched.text)
        except MalformedBocFeedError as exc:
            raise NewsSourceUnavailableError(
                f"Bank of Canada press-releases feed did not parse as RSS 1.0/RDF: {exc}"
            ) from exc

        observations = tuple(
            _to_observation(entry, fetched.retrieved_at) for entry in parsed.entries
        )
        return NewsSourceFetchOutcome(
            source_channel=CHANNEL,
            retrieved_at=fetched.retrieved_at,
            observations=observations,
            items_invalid=parsed.invalid_count,
            invalid_reasons=parsed.invalid_reasons,
        )


def _to_observation(
    entry: BocPressReleaseEntry, retrieved_at: UtcTimestamp
) -> NormalizedNewsObservation:
    timestamp_provenance: tuple[NewsSourceTimestampProvenance, ...] = ()
    source_published_at: UtcTimestamp | None = None
    if entry.dc_date_raw is not None:
        remediation = remediate_boc_dc_date(entry.dc_date_raw)
        source_published_at = remediation.normalized_at
        timestamp_provenance = (
            NewsSourceTimestampProvenance(
                field_name="dc:date",
                raw_value=entry.dc_date_raw,
                normalized_at=remediation.normalized_at,
                normalization_note=remediation.normalization_note,
            ),
        )

    return NormalizedNewsObservation(
        source_key=SOURCE_KEY,
        external_item_id=entry.entry_id,
        observed_at=retrieved_at,
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline=entry.title,
        source_channel=CHANNEL,
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        summary=entry.summary,
        body_text=None,
        canonical_url=entry.canonical_url,
        authors=(),
        language=_LANGUAGE,
        source_content_type=_CONTENT_TYPE,
        source_published_at=source_published_at,
        source_updated_at=None,
        source_timestamp_provenance=timestamp_provenance,
        source_revision_metadata=(),
        quarantine_reason=None,
    )

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

**FX-57FH: a successfully-remediated `source_published_at` AFTER this
response's own `retrieved_at` fails the WHOLE response closed, BEFORE
any observation from it is returned (Section 3).** A future-dated
press release is a new, unreviewed source condition -- not clamped to
`retrieved_at`, not silently dropped, not quarantined automatically,
and not handled by copying the already-excluded speeches feed's own
policy. `fetch_press_releases` raises `NewsSourceUnavailableError`
(the SAME exception already used for a malformed feed response, per
the spec's own "translate to it" option) with a diagnostic naming the
offending `external_item_id`, its raw `dc:date`, the remediated
`source_published_at`, and this response's own `retrieved_at` --
`IngestNewsSourceOnce` already treats this exception as a whole-
response failure (see `test_one_malformed_response_writes_zero_news_
evidence`'s own precedent), so nothing from that response is ever
persisted. The remediation ALGORITHM itself (Sections 10/25/29/30) is
unchanged -- this is a contract guard around its output, not a change
to how `dc:date` is interpreted.

**FX-57FH: `language` is now the parser's own validated `dc:language`
value (Section 7), never a hardcoded adapter-level constant** -- every
entry `BocSource` receives has already been confirmed `"en"` by
`boc_rdf_parsing.py` (a different value is an item-level invalid,
never reaching this adapter at all).
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
from forex_agent.infrastructure.news_sources.http_fetch import (
    AcquisitionAttemptRecorder,
    ClockFn,
    bind_acquisition_recorder,
    default_clock,
    fetch_text,
)

SOURCE_KEY = "BOC"
CHANNEL = "boc_press_releases"
_BASE_URL = "https://www.bankofcanada.ca"
_FEED_PATH = "/content_type/press-releases/feed/"
_CONTENT_TYPE = "press_release"
_TIMEOUT_SECONDS = 30.0
_USER_AGENT = "forex-agent-research/1.0 (+https://github.com/mrleightonbrown/forex-trading-agent)"


class BocSource:
    """Fetches and normalizes the Bank of Canada press-releases feed
    via `fetch_press_releases`, a complete `NewsSourceChannelFetcher`.
    No `before_attempt` pacing hook is used -- live-reconfirmed
    robots.txt has no `Crawl-delay` affecting this feed, unlike
    StatCan's own adapter."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        clock: ClockFn = default_clock,
        on_acquisition_attempt: AcquisitionAttemptRecorder | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=_TIMEOUT_SECONDS,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
        self._clock = clock
        self._on_acquisition_attempt = on_acquisition_attempt

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_press_releases(self) -> NewsSourceFetchOutcome:
        """Raises `NewsSourceUnavailableError` if the HTTP fetch
        itself fails, the response is not a recognizable RSS 1.0/RDF
        document at all, or a successfully-remediated `source_
        published_at` lands AFTER this response's own `retrieved_at`
        (FX-57FH Section 3 -- a future-dated press release is a new
        source condition requiring review, never silently clamped or
        dropped). A structurally-invalid individual item (missing
        identity/link/title/dc:language) is an ordinary item-level
        invalid, counted via `items_invalid`, never escalated."""
        on_attempt = bind_acquisition_recorder(self._on_acquisition_attempt, SOURCE_KEY, CHANNEL)
        fetched = await fetch_text(
            self._client, _FEED_PATH, clock=self._clock, on_attempt=on_attempt
        )
        try:
            parsed = parse_boc_press_releases_rdf(fetched.text)
        except MalformedBocFeedError as exc:
            raise NewsSourceUnavailableError(
                f"Bank of Canada press-releases feed did not parse as RSS 1.0/RDF: {exc}"
            ) from exc

        observations = tuple(
            _to_observation(entry, fetched.retrieved_at) for entry in parsed.entries
        )
        _reject_future_dated_observations(parsed.entries, observations, fetched.retrieved_at)

        return NewsSourceFetchOutcome(
            source_channel=CHANNEL,
            retrieved_at=fetched.retrieved_at,
            observations=observations,
            items_invalid=parsed.invalid_count,
            invalid_reasons=parsed.invalid_reasons,
        )


def _reject_future_dated_observations(
    entries: tuple[BocPressReleaseEntry, ...],
    observations: tuple[NormalizedNewsObservation, ...],
    retrieved_at: UtcTimestamp,
) -> None:
    """Fails the WHOLE response closed, before any observation from it
    is returned, if any successfully-remediated `source_published_at`
    is strictly after this response's own `retrieved_at` (FX-57FH
    Section 3). `entries` and `observations` are index-aligned (both
    built from the same `parsed.entries` iteration), so `zip(...,
    strict=True)` pairs each observation with the raw entry it came
    from for diagnostic purposes."""
    for entry, observation in zip(entries, observations, strict=True):
        if observation.source_published_at is None:
            continue
        if observation.source_published_at.value > retrieved_at.value:
            raise NewsSourceUnavailableError(
                f"Bank of Canada press release {observation.external_item_id!r} has a "
                f"remediated source_published_at "
                f"({observation.source_published_at.value.isoformat()}) AFTER this "
                f"response's own retrieved_at ({retrieved_at.value.isoformat()}) -- raw "
                f"dc:date={entry.dc_date_raw!r}. This is a new source condition (a "
                "future-dated press release) requiring review; refusing to persist any "
                "part of this response."
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
        language=entry.language,
        source_content_type=_CONTENT_TYPE,
        source_published_at=source_published_at,
        source_updated_at=None,
        source_timestamp_provenance=timestamp_provenance,
        source_revision_metadata=(),
        quarantine_reason=None,
    )

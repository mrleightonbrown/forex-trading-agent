"""FX-57D: a dedicated, minimal GOV.UK Content API JSON parser, plus
the HM Treasury adapter built on top of it.

**Deliberately NOT a reuse of `rss_item_parsing.py`** -- that module
is an XML/RSS parser; this source is JSON. Keeping transport, parser,
and orchestration separate (FX-57A's own founding discipline) means
this module owns JSON parsing/validation ONLY; `govuk_discovery.py`
owns Atom discovery ONLY; `GovUkHmtSource` below coordinates the two
through the common `http_fetch`/`IngestNewsSourceOnce` infrastructure
without duplicating either.

**Why two stages (ADR 0005 / FX-57D Section 5/8)**: the Content API
is a lookup-by-path endpoint, not an item-enumeration endpoint -- it
cannot, by itself, tell FTA which paths currently exist. The Atom
discovery feed (`govuk_discovery.py`) supplies CURRENT paths worth
hydrating; the Content API response for each path is the sole
authoritative evidence source (stable identity, title, description,
body, document type, locale, three distinct source-side timestamps,
correction history, retraction flag) -- never the Atom entry itself,
which exposes only `updated`, never `published`, and no identity or
provenance richness at all.

**One Content API response = one observation, one `retrieved_at`
(FX-57D Section 9/10)**: `GovUkHmtSource.fetch_content_item` is
ITSELF a complete `NewsSourceChannelFetcher`-shaped callable for ONE
discovered path -- there is no batching, and no single end-of-run
timestamp is ever fabricated for multiple Content API responses. A
GOV.UK poll therefore configures ONE fetcher PER discovered path, all
passed into the SAME `IngestNewsSourceOnce` run alongside one
another -- the common two-phase, collect-then-persist orchestration
(FX-57CH, extended for this exact shape in FX-57D Section 14/55)
already handles many fetchers sharing one channel correctly.

**Rate pacing (Section 19/79)**: the documented Content API limit is
10 requests/second/client. `GovUkHmtSource` paces every request it
makes (discovery included) to at most one per `pace_seconds` (default
well under the limit), tracked via an injectable monotonic clock and
an injectable async sleep -- so a deterministic unit test can prove
the pacing math without ever actually waiting wall-clock time. This
is deliberately NOT a general scheduler: it only bounds how fast ONE
`GovUkHmtSource` instance issues its own requests within a single
run; nothing here polls repeatedly or runs unattended.
"""

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from forex_agent.application.ports.news_source import (
    NewsSourceFetchOutcome,
    NewsSourceUnavailableError,
    NormalizedNewsObservation,
)
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_revision_fact import (
    NewsSourceRevisionFact,
    NewsSourceRevisionKind,
)
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.news_source_timestamp_provenance import NewsSourceTimestampProvenance
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.news_sources.govuk_discovery import (
    MalformedGovUkDiscoveryFeedError,
    parse_govuk_discovery_atom,
)
from forex_agent.infrastructure.news_sources.http_fetch import (
    ClockFn,
    SleepFn,
    default_clock,
    fetch_text,
)

MonotonicFn = Callable[[], float]


def _default_monotonic() -> float:
    return time.monotonic()


async def _default_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


SOURCE_KEY = "GOVUK_HMT"
CHANNEL = "hmt_news_and_communications"
_BASE_URL = "https://www.gov.uk"
_DISCOVERY_PATH = "/search/news-and-communications.atom?organisations[]=hm-treasury"
_HMT_ORGANISATION_BASE_PATH = "/government/organisations/hm-treasury"
_TIMEOUT_SECONDS = 30.0
_USER_AGENT = "forex-agent-research/1.0 (+https://github.com/mrleightonbrown/forex-trading-agent)"
_DEFAULT_PACE_SECONDS = 0.15  # well under the documented 10 requests/second/client limit


class MalformedContentApiResponseError(ValueError):
    """Raised when a Content API response is not usable at all:
    invalid JSON, a non-object top-level value, or missing one of
    the hard-required identity fields (`content_id`, `base_path`,
    `title`, `document_type`, `locale`) -- fails that ONE item's own
    hydration closed. Distinct from an item that parses fine but is
    not HM-Treasury-associated (an ordinary item-level invalid, not
    this exception)."""


@dataclass(frozen=True, slots=True)
class _ChangeHistoryEntry:
    note: str | None
    public_timestamp_raw: str | None


@dataclass(frozen=True, slots=True)
class ContentApiItem:
    """A validated, structurally-faithful view of one Content API
    response -- preserves every material provider fact FX-57D's own
    adopted scope requires, nothing more. All timestamp fields are
    preserved RAW here; normalization/plausibility happens in the
    adapter's own mapping step, never here."""

    content_id: str
    base_path: str
    title: str
    description: str | None
    document_type: str
    locale: str
    body: str | None
    first_published_at_raw: str | None
    public_updated_at_raw: str | None
    updated_at_raw: str | None
    publishing_scheduled_at_raw: str | None
    change_history: tuple[_ChangeHistoryEntry, ...]
    withdrawn: bool
    withdrawn_explanation: str | None
    withdrawn_at_raw: str | None
    organisation_base_paths: tuple[str, ...]


def parse_content_api_item(text: str) -> ContentApiItem:
    """Parses and structurally validates one Content API JSON
    response. Raises `MalformedContentApiResponseError` for invalid
    JSON, a non-object top-level value, or a missing/blank hard-
    required identity field."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedContentApiResponseError(f"response body is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MalformedContentApiResponseError(
            f"top-level JSON value must be an object, got {type(data).__name__}"
        )

    content_id = _required_str(data, "content_id")
    base_path = _validate_base_path(_required_str(data, "base_path"))
    title = _required_str(data, "title")
    document_type = _required_str(data, "document_type")
    locale = _required_str(data, "locale")

    description = _optional_str(data.get("description"))
    details_raw = data.get("details")
    details: dict[str, Any] = details_raw if isinstance(details_raw, dict) else {}
    body = _optional_str(details.get("body"))

    change_history = _parse_change_history(details.get("change_history"))
    withdrawn, withdrawn_explanation, withdrawn_at_raw = _parse_withdrawn_notice(
        data.get("withdrawn_notice")
    )

    links_raw = data.get("links")
    links: dict[str, Any] = links_raw if isinstance(links_raw, dict) else {}
    organisations_raw = links.get("organisations")
    organisations: list[Any] = organisations_raw if isinstance(organisations_raw, list) else []
    organisation_base_paths = tuple(
        org["base_path"]
        for org in organisations
        if isinstance(org, dict) and isinstance(org.get("base_path"), str)
    )

    return ContentApiItem(
        content_id=content_id,
        base_path=base_path,
        title=title,
        description=description,
        document_type=document_type,
        locale=locale,
        body=body,
        first_published_at_raw=_optional_str(data.get("first_published_at")),
        public_updated_at_raw=_optional_str(data.get("public_updated_at")),
        updated_at_raw=_optional_str(data.get("updated_at")),
        publishing_scheduled_at_raw=_optional_str(data.get("publishing_scheduled_at")),
        change_history=change_history,
        withdrawn=withdrawn,
        withdrawn_explanation=withdrawn_explanation,
        withdrawn_at_raw=withdrawn_at_raw,
        organisation_base_paths=organisation_base_paths,
    )


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MalformedContentApiResponseError(f"{key!r} must be a non-empty string, got {value!r}")
    return value.strip()


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _validate_base_path(value: str) -> str:
    """FX-57DH Section 4: a malformed provider `base_path` must never
    be allowed to produce a bogus `canonical_url` -- rejects an
    absolute URL (has its own scheme), a scheme-relative URL (`//
    ...`), and anything not starting with a single leading `/`."""
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        raise MalformedContentApiResponseError(
            f"base_path must be a bare GOV.UK-relative content path, not an "
            f"absolute or scheme-relative URL, got {value!r}"
        )
    if not value.startswith("/") or value.startswith("//"):
        raise MalformedContentApiResponseError(
            f"base_path must start with exactly one leading '/', got {value!r}"
        )
    return value


def _parse_change_history(value: object) -> tuple[_ChangeHistoryEntry, ...]:
    """FX-57DH Section 5: malformed `change_history` must fail the
    whole item closed, never silently collapse to "no history" --
    the original behavior (non-list -> `()`, non-dict entry ->
    skipped) turned schema drift into a false "nothing happened"
    signal. Absent/`None` (the key missing entirely) remains a valid
    empty history; anything PRESENT but not a list, or any PRESENT
    list entry that is not an object, now raises."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise MalformedContentApiResponseError(
            f"details.change_history must be a list when present, got {type(value).__name__}"
        )
    entries: list[_ChangeHistoryEntry] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise MalformedContentApiResponseError(
                f"details.change_history[{index}] must be an object, got {type(entry).__name__}"
            )
        entries.append(
            _ChangeHistoryEntry(
                note=_optional_str(entry.get("note")),
                public_timestamp_raw=_optional_str(entry.get("public_timestamp")),
            )
        )
    return tuple(entries)


def _parse_withdrawn_notice(value: object) -> tuple[bool, str | None, str | None]:
    """FX-57DH Section 6: `withdrawn_notice` changes `source_status`
    and must therefore be STRUCTURALLY positive evidence, not merely
    "any non-empty dict." A wrong type (not a dict at all) fails
    closed rather than silently defaulting to ACTIVE. The only
    accepted active shape is an empty dict (live-confirmed, never
    `null`); a non-empty dict must carry its own non-empty,
    genuinely-parseable `withdrawn_at` timestamp to be trusted as a
    real withdrawal claim -- a populated notice with no verifiable
    timestamp of its own fails closed rather than being accepted on
    faith."""
    if not isinstance(value, dict):
        raise MalformedContentApiResponseError(
            f"withdrawn_notice must be an object, got {type(value).__name__}"
        )
    if not value:
        return False, None, None
    withdrawn_at_raw = _optional_str(value.get("withdrawn_at"))
    if withdrawn_at_raw is None or _parse_utc_timestamp(withdrawn_at_raw) is None:
        raise MalformedContentApiResponseError(
            "withdrawn_notice is non-empty but its own withdrawn_at value "
            f"({value.get('withdrawn_at')!r}) is missing or does not parse as a "
            "genuine timezone-aware timestamp -- a positive withdrawal claim must "
            "carry its own verifiable timestamp to be trusted"
        )
    return True, _optional_str(value.get("explanation")), withdrawn_at_raw


class GovUkHmtSource:
    """Coordinates GOV.UK discovery and hydration. `discover_current_
    paths` fetches the Atom discovery feed ONCE; `fetch_content_item`
    hydrates exactly ONE path through the Content API and is itself a
    complete `NewsSourceChannelFetcher`. Callers build one such
    fetcher per discovered path and pass them all to `IngestNewsSource
    Once` together (see the module docstring)."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        clock: ClockFn = default_clock,
        pace_seconds: float = _DEFAULT_PACE_SECONDS,
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
        self._pace_seconds = pace_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _pace(self) -> None:
        """Blocks until at least `pace_seconds` have elapsed since
        this instance's own last request, so this single `GovUkHmt
        Source` can never issue requests faster than the configured
        pace (Section 19/79) -- shared across discovery and every
        content-item fetch, since both count against the same
        documented 10 requests/second/client limit. Uses an
        injectable monotonic clock and sleep so a deterministic test
        can prove the pacing math without actually waiting."""
        now = self._monotonic()
        if self._last_request_at is not None:
            remaining = self._pace_seconds - (now - self._last_request_at)
            if remaining > 0:
                await self._sleep(remaining)
                now = self._monotonic()
        self._last_request_at = now

    async def discover_current_paths(self) -> tuple[str, ...]:
        """Fetches the HM Treasury discovery Atom feed once and
        returns every currently-usable, deduped `gov.uk` content path
        -- raises `NewsSourceUnavailableError` if the discovery
        response itself is unavailable or malformed (a source-level
        failure, not a per-path one).

        **FX-57DH Section 1**: a discovery response containing even
        ONE invalid entry (missing id/title, off-domain/malformed
        link) now fails this call closed, rather than silently
        returning only the remaining valid paths. FTA cannot know
        WHICH content item it failed to discover from an invalid
        entry -- silently ingesting the other N-1 valid entries would
        let a genuine source-schema drift disappear a currently-
        published HMT item from ingestion with no operational
        signal at all."""
        await self._pace()
        fetched = await fetch_text(self._client, _DISCOVERY_PATH, clock=self._clock)
        try:
            parsed = parse_govuk_discovery_atom(fetched.text)
        except MalformedGovUkDiscoveryFeedError as exc:
            raise NewsSourceUnavailableError(
                f"GOV.UK HMT discovery feed did not parse as Atom: {exc}"
            ) from exc
        if parsed.invalid_count:
            raise NewsSourceUnavailableError(
                f"GOV.UK HMT discovery feed contained {parsed.invalid_count} invalid "
                "entry(ies) -- refusing to silently discover only the remaining "
                f"valid entries while an unknown item may be missing: "
                f"{parsed.invalid_reasons!r}"
            )
        return tuple(entry.path for entry in parsed.entries)

    async def fetch_content_item(self, path: str) -> NewsSourceFetchOutcome:
        """Hydrates exactly ONE discovered path through the Content
        API. Returns a `NewsSourceFetchOutcome` with ONE observation
        if the item is valid and HM-Treasury-associated; with ZERO
        observations and `items_invalid=1` if the response parses but
        is not usable evidence (missing identity, not HM Treasury);
        raises `NewsSourceUnavailableError` if the HTTP fetch itself
        fails (404/410/5xx/network/malformed JSON)."""
        await self._pace()
        fetched = await fetch_text(self._client, f"/api/content{path}", clock=self._clock)
        try:
            item = parse_content_api_item(fetched.text)
        except MalformedContentApiResponseError as exc:
            raise NewsSourceUnavailableError(
                f"GOV.UK Content API response for {path!r} did not parse: {exc}"
            ) from exc

        if _HMT_ORGANISATION_BASE_PATH not in item.organisation_base_paths:
            return NewsSourceFetchOutcome(
                source_channel=CHANNEL,
                retrieved_at=fetched.retrieved_at,
                observations=(),
                items_invalid=1,
                invalid_reasons=(
                    f"content_id={item.content_id!r} at path={path!r} is not HM-Treasury-"
                    f"associated (organisations={item.organisation_base_paths!r})",
                ),
            )

        # FX-57DH Section 3: this adapter's bare content_id identity
        # was only live-validated against English-locale HMT content
        # (FX-57D's own live research found locale == "en" on every
        # sampled item). A non-English item under the same identity
        # model might need identity to become content_id+locale --
        # that is an architecture decision this adapter must never
        # make silently, so a non-"en" item fails closed as an
        # ordinary item-level invalid, never ingested, never
        # auto-switched to a different identity scheme, never
        # translated.
        if item.locale != "en":
            return NewsSourceFetchOutcome(
                source_channel=CHANNEL,
                retrieved_at=fetched.retrieved_at,
                observations=(),
                items_invalid=1,
                invalid_reasons=(
                    f"content_id={item.content_id!r} at path={path!r} has "
                    f"locale={item.locale!r}, not 'en' -- this adapter's bare "
                    "content_id identity was only validated against English-locale "
                    "content; refusing to normalize without an explicit "
                    "architecture review of whether identity must become "
                    "content_id+locale",
                ),
            )

        observation = _to_observation(item, fetched.retrieved_at)
        return NewsSourceFetchOutcome(
            source_channel=CHANNEL,
            retrieved_at=fetched.retrieved_at,
            observations=(observation,),
            items_invalid=0,
        )


def _parse_utc_timestamp(raw: str | None) -> UtcTimestamp | None:
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return UtcTimestamp(parsed)


def _timestamp_provenance(field_name: str, raw: str | None) -> NewsSourceTimestampProvenance | None:
    if raw is None:
        return None
    normalized = _parse_utc_timestamp(raw)
    note = (
        "standard ISO-8601 timestamp parsing"
        if normalized is not None
        else "did not parse as a timezone-aware ISO-8601 timestamp"
    )
    return NewsSourceTimestampProvenance(
        field_name=field_name, raw_value=raw, normalized_at=normalized, normalization_note=note
    )


def _to_observation(item: ContentApiItem, retrieved_at: UtcTimestamp) -> NormalizedNewsObservation:
    timestamp_provenance: list[NewsSourceTimestampProvenance] = []
    source_published_at = _parse_utc_timestamp(item.first_published_at_raw)
    for field_name, raw in (
        ("first_published_at", item.first_published_at_raw),
        ("public_updated_at", item.public_updated_at_raw),
        ("updated_at", item.updated_at_raw),
        ("publishing_scheduled_at", item.publishing_scheduled_at_raw),
    ):
        provenance = _timestamp_provenance(field_name, raw)
        if provenance is not None:
            timestamp_provenance.append(provenance)

    source_updated_at = _parse_utc_timestamp(item.public_updated_at_raw)

    revision_metadata: list[NewsSourceRevisionFact] = [
        NewsSourceRevisionFact(
            kind=NewsSourceRevisionKind.UPDATE,
            source_timestamp=_parse_utc_timestamp(entry.public_timestamp_raw),
            raw_timestamp=entry.public_timestamp_raw,
            note=entry.note,
        )
        for entry in item.change_history
    ]
    if item.withdrawn:
        revision_metadata.append(
            NewsSourceRevisionFact(
                kind=NewsSourceRevisionKind.WITHDRAWAL,
                source_timestamp=_parse_utc_timestamp(item.withdrawn_at_raw),
                raw_timestamp=item.withdrawn_at_raw,
                note=item.withdrawn_explanation,
            )
        )

    return NormalizedNewsObservation(
        source_key=SOURCE_KEY,
        external_item_id=item.content_id,
        observed_at=retrieved_at,
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline=item.title,
        source_channel=CHANNEL,
        source_status=NewsSourceStatus.WITHDRAWN if item.withdrawn else NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        summary=item.description,
        body_text=item.body,
        canonical_url=f"{_BASE_URL}{item.base_path}",
        authors=(),
        language=item.locale,
        source_content_type=item.document_type,
        source_published_at=source_published_at,
        source_updated_at=source_updated_at,
        source_timestamp_provenance=tuple(timestamp_provenance),
        source_revision_metadata=tuple(revision_metadata),
        quarantine_reason=None,
    )

"""The normalized, provider-neutral intermediate shape a source
adapter produces (FX-56 Section 31; the contract itself -- `NewsSource
UnavailableError`/`NewsSourceFetchOutcome`/`NewsSourceChannelFetcher`
-- defined by FX-57A, the first story to actually need it).

Mirrors `application.ports.economic_calendar_source.
RawScheduleObservation`'s own role exactly: keeps source-specific
parsing (`infrastructure.news_sources`, e.g. `fed_rss_source.py`), and
application-level evidence modeling (`application.use_cases.
record_news_observation.RecordNewsObservation`) as separate
responsibilities. Nothing in this module imports `httpx`, `xml.etree`,
or any provider SDK -- `NormalizedNewsObservation` performs no network
I/O, and `NewsSourceChannelFetcher` is a plain callable contract an
adapter implements, not a concrete transport.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_revision_fact import NewsSourceRevisionFact
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.news_source_timestamp_provenance import NewsSourceTimestampProvenance
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class NormalizedNewsObservation:
    """One source item, as a future adapter observed it at
    `observed_at` -- the single input `RecordNewsObservation` accepts.

    Fields mirror `domain.news_item_vintage.NewsItemVintage`'s own
    content/provenance fields exactly (see that type's own docstring
    for what each one means); this type additionally carries the
    external identity (`source_key`/`external_item_id`) and FTA's own
    observation instant, which belong on the OBSERVATION, not on the
    stored vintage fact itself (the vintage's own `news_item_key` is
    resolved later, by `RecordNewsObservation` via `NewsRepository.
    register_source_item`).

    `evidence_disposition`/`quarantine_reason` are included here
    because FX-56 Section 25 requires the CAPABILITY to represent a
    quarantined observation to exist end-to-end; the actual anomaly
    DETECTION that decides a disposition (e.g. "is this source
    timestamp suspiciously in the future?") is a future adapter's own
    job (FX-57), never this DTO's or `RecordNewsObservation`'s.

    **FX-57B**: `source_channel` (a stable, provider-neutral technical
    identifier for which configured feed/endpoint produced this item,
    e.g. `"press_monetary"`/`"ecb_press"`) is a separate concept from
    `source_content_type` (what kind of content this is) -- see
    `domain.news_item_vintage.NewsItemVintage.source_channel`'s own
    docstring for why collapsing the two is wrong in general, even
    though FX-57A's own Fed adapter happened to find them 1:1.
    Required, non-empty, validated below.

    **FX-56H**: unlike `RawScheduleObservation` (which carries no
    validation of its own), this DTO DOES validate its own structural
    invariants in `__post_init__` -- non-empty `headline`/`source_
    channel` and quarantine-reason mutual exclusivity, mirroring
    `domain.news_item_vintage.NewsItemVintage`'s own checks exactly. This is
    deliberate defense in depth (FX-56H Section 3): a malformed
    observation must never reach `RecordNewsObservation`, let alone
    any repository call, at all -- rejecting it here means not even a
    candidate `NewsItem`/`NewsSourceMapping` row is ever considered,
    rather than relying solely on the later domain-object construction
    inside the use case to catch it first.
    """

    source_key: str
    external_item_id: str
    observed_at: UtcTimestamp
    observation_mode: NewsObservationMode
    headline: str
    source_channel: str
    source_status: NewsSourceStatus
    evidence_disposition: NewsEvidenceDisposition
    summary: str | None = None
    body_text: str | None = None
    canonical_url: str | None = None
    authors: tuple[str, ...] = ()
    language: str | None = None
    source_content_type: str | None = None
    source_published_at: UtcTimestamp | None = None
    source_updated_at: UtcTimestamp | None = None
    source_timestamp_provenance: tuple[NewsSourceTimestampProvenance, ...] = ()
    source_revision_metadata: tuple[NewsSourceRevisionFact, ...] = ()
    quarantine_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.headline, str) or not self.headline.strip():
            raise ValueError(f"headline must be a non-empty string, got {self.headline!r}")
        if not isinstance(self.source_channel, str) or not self.source_channel.strip():
            raise ValueError(
                f"source_channel must be a non-empty string, got {self.source_channel!r}"
            )
        is_quarantined = self.evidence_disposition is NewsEvidenceDisposition.QUARANTINED
        if is_quarantined and (
            not isinstance(self.quarantine_reason, str) or not self.quarantine_reason.strip()
        ):
            raise ValueError(
                "quarantine_reason must be a non-empty string when evidence_disposition is "
                "QUARANTINED -- a quarantined observation must always say why"
            )
        if not is_quarantined and self.quarantine_reason is not None:
            raise ValueError(
                "quarantine_reason must be None when evidence_disposition is EVIDENCE_ELIGIBLE"
            )


class NewsSourceUnavailableError(Exception):
    """Raised by a source adapter on a genuine network/transport
    failure, a non-2xx HTTP status, or a response that fails to parse
    as a recognizable document for this source's own format at all --
    mirrors `EconomicCalendarSourceUnavailableError`. A caller
    (`IngestNewsSourceOnce`, FX-57A) treats this as "this one
    channel's fetch failed," recorded in `NewsIngestionResult.errors`,
    never as "the channel genuinely has nothing new" -- that is a
    zero-observation `NewsSourceFetchOutcome`, a distinct, valid,
    non-error result."""


class NewsSourceFetchContractError(Exception):
    """Raised when a source adapter's own `NewsSourceFetchOutcome`
    violates the common fetch contract every adapter must uphold
    (FX-57AH Section 1) -- fails closed at CONSTRUCTION time, never
    silently corrected, so a violating adapter's own bug can never
    propagate into stored evidence. The adapter itself must be fixed;
    this exception exists precisely so that never happens quietly."""


@dataclass(frozen=True, slots=True)
class NewsSourceFetchOutcome:
    """One channel/response's own fetch-and-normalize result -- what
    any source adapter hands to `IngestNewsSourceOnce` (FX-57A). One
    `retrieved_at` per response, shared by every observation in
    `observations` (FX-57A Section 4) -- never a per-item clock call.

    **FX-57AH Section 1**: this is now an ENFORCED invariant, not just
    documentation -- `__post_init__` requires `observation.observed_at
    == retrieved_at` for every observation in `observations`, raising
    `NewsSourceFetchContractError` (never silently rewriting the
    mismatched timestamp) if any observation disagrees. A source's own
    `source_published_at` is irrelevant to this check -- only FTA's own
    retrieval instant is compared.

    `items_invalid`/`invalid_reasons` describe ITEM-level parse
    failures within an otherwise structurally-valid response (FX-57A
    Section 27) -- a malformed item is never silently included in
    `observations`, and never escalates to `NewsSourceUnavailableError`
    on its own."""

    source_channel: str | None
    retrieved_at: UtcTimestamp
    observations: tuple[NormalizedNewsObservation, ...]
    items_invalid: int
    invalid_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for observation in self.observations:
            if observation.observed_at != self.retrieved_at:
                raise NewsSourceFetchContractError(
                    f"observation external_item_id={observation.external_item_id!r} has "
                    f"observed_at={observation.observed_at.value.isoformat()!r}, which "
                    f"differs from this response's own retrieved_at="
                    f"{self.retrieved_at.value.isoformat()!r} -- every observation "
                    "produced from the SAME response must share the exact same FTA "
                    "retrieval instant; the adapter that built this outcome has a bug "
                    "and must be fixed, not worked around here"
                )


NewsSourceChannelFetcher = Callable[[], Awaitable[NewsSourceFetchOutcome]]
"""One configured channel's own zero-argument fetch -- e.g.
`functools.partial(fed_source.fetch_feed, FED_FEEDS[0])`. Raises
`NewsSourceUnavailableError` on failure; otherwise returns a
`NewsSourceFetchOutcome`, even when it fetched zero items (a valid,
empty result, never an error)."""

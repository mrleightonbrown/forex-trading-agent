"""The normalized, provider-neutral intermediate shape a FUTURE source
adapter (FX-57) will produce (FX-56 Section 31).

Mirrors `application.ports.economic_calendar_source.
RawScheduleObservation`'s own role exactly: keeps source-specific
parsing (a future `infrastructure.news_sources` package, FX-57's own
job), and application-level evidence modeling (`application.use_cases.
record_news_observation.RecordNewsObservation`, this story) as separate
responsibilities. No `NewsSource`/`Protocol` is defined here yet --
deliberately: FX-56 provides the model a future adapter will target,
it does not build or assume the shape of the adapter itself. `Normal
izedNewsObservation` performs no network I/O; nothing in this module
imports `httpx` or any provider SDK.
"""

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

    **FX-56H**: unlike `RawScheduleObservation` (which carries no
    validation of its own), this DTO DOES validate its own two
    structural invariants in `__post_init__` -- a non-empty `headline`
    and quarantine-reason mutual exclusivity, mirroring `domain.
    news_item_vintage.NewsItemVintage`'s own checks exactly. This is
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

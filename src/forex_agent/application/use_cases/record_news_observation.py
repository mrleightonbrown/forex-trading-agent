"""FX-56: record one normalized news observation into the point-in-
time news evidence model, idempotently.

Mirrors `application.use_cases.ingest_official_calendar_schedule.
IngestOfficialCalendarSchedule`'s own change-detection shape: this use
case asks the repository what the latest known vintage for an item
is, compares it field-by-field against the newly observed fact, and
only writes a new vintage when something genuinely differs -- a
repeated identical poll must never create a duplicate vintage (FX-56
Section 34). Unlike that use case, item-identity resolution here goes
through `NewsRepository.register_source_item`'s own ATOMIC
registration (see that port's own docstring) rather than a separate
mint-then-map sequence -- this use case never mints or persists an
item itself, and can never leave an orphan one.

This use case performs no network I/O and assumes no specific source
adapter (FX-57's own job): it only ever receives an already-normalized
`NormalizedNewsObservation`.
"""

import dataclasses
from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.news_repository import (
    NewsItemRegistrationOutcome,
    NewsRepository,
)
from forex_agent.application.ports.news_source import NormalizedNewsObservation
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_source_identity import NewsSourceIdentity


class RecordNewsObservationOutcome(Enum):
    """What `RecordNewsObservation` actually did for one observation
    (FX-56 Section 66)."""

    CREATED = "CREATED"
    REVISION_ADDED = "REVISION_ADDED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True, slots=True)
class RecordNewsObservationResult:
    news_item_key: str
    revision_sequence: int
    outcome: RecordNewsObservationOutcome


class RecordNewsObservation:
    """FX-56's provider-neutral evidence-recording use case -- see the
    module docstring."""

    def __init__(self, repository: NewsRepository) -> None:
        self._repository = repository

    async def __call__(self, observation: NormalizedNewsObservation) -> RecordNewsObservationResult:
        identity = NewsSourceIdentity(observation.source_key, observation.external_item_id)
        registration = await self._repository.register_source_item(
            identity, observation.observed_at, observation.observation_mode
        )
        news_item_key = registration.news_item_key

        existing_vintages = await self._repository.list_vintages(news_item_key)
        latest = _latest_by_revision(existing_vintages)

        candidate = _build_vintage(news_item_key, observation)

        if latest is not None and _same_modeled_facts(latest, candidate):
            return RecordNewsObservationResult(
                news_item_key=news_item_key,
                revision_sequence=latest.revision_sequence,
                outcome=RecordNewsObservationOutcome.UNCHANGED,
            )

        next_revision = 0 if latest is None else latest.revision_sequence + 1
        vintage = dataclasses.replace(candidate, revision_sequence=next_revision)
        await self._repository.add_vintage(vintage)

        outcome = (
            RecordNewsObservationOutcome.CREATED
            if registration.outcome is NewsItemRegistrationOutcome.CREATED and latest is None
            else RecordNewsObservationOutcome.REVISION_ADDED
        )
        return RecordNewsObservationResult(
            news_item_key=news_item_key,
            revision_sequence=next_revision,
            outcome=outcome,
        )


def _build_vintage(news_item_key: str, observation: NormalizedNewsObservation) -> NewsItemVintage:
    """Maps one observation onto a (provisional, `revision_sequence ==
    0`) vintage -- the caller overwrites `revision_sequence` via
    `dataclasses.replace` once the real next revision number is known;
    every OTHER field here is the vintage's own final value."""
    return NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=0,
        availability=observation.observed_at,
        observation_mode=observation.observation_mode,
        headline=observation.headline,
        source_status=observation.source_status,
        evidence_disposition=observation.evidence_disposition,
        summary=observation.summary,
        body_text=observation.body_text,
        canonical_url=observation.canonical_url,
        authors=observation.authors,
        language=observation.language,
        source_content_type=observation.source_content_type,
        source_published_at=observation.source_published_at,
        source_updated_at=observation.source_updated_at,
        source_timestamp_provenance=observation.source_timestamp_provenance,
        source_revision_metadata=observation.source_revision_metadata,
        quarantine_reason=observation.quarantine_reason,
    )


def _latest_by_revision(vintages: tuple[NewsItemVintage, ...]) -> NewsItemVintage | None:
    if not vintages:
        return None
    return max(vintages, key=lambda v: v.revision_sequence)


def _modeled_facts(vintage: NewsItemVintage) -> tuple[object, ...]:
    """Every field describing the observed content/state -- i.e.
    everything EXCEPT `news_item_key`/`revision_sequence`/
    `availability`, which are identity/bookkeeping, not an observed
    fact (FX-56 Section 15/34: "repeated observation of the same
    modeled facts should NOT mint another revision")."""
    return (
        vintage.observation_mode,
        vintage.headline,
        vintage.summary,
        vintage.body_text,
        vintage.canonical_url,
        vintage.authors,
        vintage.language,
        vintage.source_content_type,
        vintage.source_published_at,
        vintage.source_updated_at,
        vintage.source_timestamp_provenance,
        vintage.source_revision_metadata,
        vintage.source_status,
        vintage.evidence_disposition,
        vintage.quarantine_reason,
    )


def _same_modeled_facts(a: NewsItemVintage, b: NewsItemVintage) -> bool:
    return _modeled_facts(a) == _modeled_facts(b)

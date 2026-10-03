"""FX-56: record one normalized news observation into the point-in-
time news evidence model, idempotently. First-observation atomicity
and PIT ordering hardened by FX-56H.

Mirrors `application.use_cases.ingest_official_calendar_schedule.
IngestOfficialCalendarSchedule`'s own change-detection shape: this use
case asks the repository what the latest known vintage for an item
is, compares it field-by-field against the newly observed fact, and
only writes a new vintage when something genuinely differs -- a
repeated identical poll must never create a duplicate vintage (FX-56
Section 34). Unlike that use case, item-identity resolution here goes
through `NewsRepository.register_source_item_with_first_vintage`'s own
ATOMIC registration-plus-first-vintage (see that port's own
docstring) rather than two separately-committed steps -- this use
case never leaves a durably-registered item with no revision 0, and
never mints or persists an item itself.

**FX-56H's own PIT-ordering guard**: once an item already has a
latest vintage, a CHANGED observation claiming an `observed_at`
EARLIER than that latest vintage's own `availability` is refused
outright (`NewsObservationOutOfOrderError`) rather than silently
appended as a backdated revision -- PIT history must never be
rewritten. An IDENTICAL observation is always accepted as `UNCHANGED`
regardless of its own `observed_at` ordering, since no new vintage is
actually written in that case; only a genuinely NEW fact is subject
to the ordering check. Equal `availability` timestamps between
consecutive revisions are explicitly permitted (tie-broken by
`revision_sequence`), matching `NewsItemVintage`'s own PIT-query
ordering (`availability DESC, revision_sequence DESC`).

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
    NewsVintageWriteOutcome,
)
from forex_agent.application.ports.news_source import NormalizedNewsObservation
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.timestamps import UtcTimestamp


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


class NewsObservationOutOfOrderError(Exception):
    """Raised when a CHANGED observation claims an `observed_at`
    earlier than the latest known vintage's own `availability` for
    the same item (FX-56H Section 7) -- refusing to append a
    backdated revision. This can never fire for an observation whose
    modeled facts are IDENTICAL to the latest vintage (that case is
    always `UNCHANGED`, regardless of timing), only for a genuinely
    new fact that would otherwise be appended out of order."""

    def __init__(
        self,
        news_item_key: str,
        latest_availability: UtcTimestamp,
        observed_at: UtcTimestamp,
    ) -> None:
        self.news_item_key = news_item_key
        self.latest_availability = latest_availability
        self.observed_at = observed_at
        super().__init__(
            f"observation for news_item_key={news_item_key!r} claims observed_at="
            f"{observed_at.value.isoformat()}, earlier than the latest known revision's "
            f"own availability={latest_availability.value.isoformat()} -- refusing to "
            "append a backdated revision; point-in-time history must never be rewritten"
        )


class RecordNewsObservation:
    """FX-56's provider-neutral evidence-recording use case -- see the
    module docstring."""

    def __init__(self, repository: NewsRepository) -> None:
        self._repository = repository

    async def __call__(self, observation: NormalizedNewsObservation) -> RecordNewsObservationResult:
        identity = NewsSourceIdentity(observation.source_key, observation.external_item_id)

        registration = await self._repository.register_source_item_with_first_vintage(
            identity,
            observation.observed_at,
            observation.observation_mode,
            build_vintage=lambda key: _build_vintage(key, observation, revision_sequence=0),
        )
        if registration.outcome is NewsItemRegistrationOutcome.CREATED:
            # Item, mapping, and revision 0 were just committed together,
            # atomically (FX-56H) -- nothing further to compare or write.
            return RecordNewsObservationResult(
                news_item_key=registration.news_item_key,
                revision_sequence=0,
                outcome=RecordNewsObservationOutcome.CREATED,
            )

        news_item_key = registration.news_item_key
        existing_vintages = await self._repository.list_vintages(news_item_key)
        latest = _latest_by_revision(existing_vintages)
        # FX-56H's own atomic first-observation guarantee means an
        # existing item ALWAYS has at least a revision-0 vintage.
        assert latest is not None

        candidate = _build_vintage(news_item_key, observation, revision_sequence=0)
        if _same_modeled_facts(latest, candidate):
            return RecordNewsObservationResult(
                news_item_key=news_item_key,
                revision_sequence=latest.revision_sequence,
                outcome=RecordNewsObservationOutcome.UNCHANGED,
            )

        if observation.observed_at.value < latest.availability.value:
            raise NewsObservationOutOfOrderError(
                news_item_key, latest.availability, observation.observed_at
            )

        next_revision = latest.revision_sequence + 1
        vintage = dataclasses.replace(candidate, revision_sequence=next_revision)
        write_outcome = await self._repository.add_vintage(vintage)
        if write_outcome is NewsVintageWriteOutcome.ALREADY_PRESENT:
            # A concurrent writer already inserted this EXACT revision
            # (same identity, same content) -- this caller did not add
            # anything of its own; report truthfully, never REVISION_ADDED.
            return RecordNewsObservationResult(
                news_item_key=news_item_key,
                revision_sequence=next_revision,
                outcome=RecordNewsObservationOutcome.UNCHANGED,
            )
        return RecordNewsObservationResult(
            news_item_key=news_item_key,
            revision_sequence=next_revision,
            outcome=RecordNewsObservationOutcome.REVISION_ADDED,
        )


def _build_vintage(
    news_item_key: str, observation: NormalizedNewsObservation, *, revision_sequence: int
) -> NewsItemVintage:
    """Maps one observation onto a vintage at the given
    `revision_sequence` -- every field other than `revision_sequence`
    is this vintage's own final value, never a placeholder."""
    return NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=revision_sequence,
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

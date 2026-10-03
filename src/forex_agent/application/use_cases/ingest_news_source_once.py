"""FX-57A: the provider-neutral one-shot ingestion orchestration every
concrete news-source adapter (Fed now; ECB/BoE/... later) reuses
unchanged. Hardened by FX-57AH: source-key isolation is now an
enforced, fail-closed contract (Section 2), and the result's own
item counters (Section 4) now distinguish fetched/normalized/
processed explicitly rather than relying on one ambiguous count.

Deliberately the SMALLEST shared orchestration piece (FX-57A Section
8/9): given a tuple of already-configured channel fetchers (each one
a zero-argument `NewsSourceChannelFetcher`, e.g. `functools.partial
(fed_source.fetch_feed, FED_FEEDS[0])`), fetch each channel in turn,
deduplicate within each response, and persist every valid observation
via `RecordNewsObservation`, returning a factual, count-only
`NewsIngestionResult`. No source-specific HTTP/XML/schema knowledge
lives here -- that is each adapter's own job, behind the
`NewsSourceChannelFetcher` contract (`application.ports.news_source`).

No daemon, worker, or scheduler of any kind (FX-57A Section 6): this
class performs exactly one pass over the fetchers it is given, once
per call, and returns.

**Error handling (FX-57A Section 27)**: a single channel's own fetch
failure (`NewsSourceUnavailableError`) is recorded in `errors` and
that channel is skipped -- it must never abort the other configured
channels. A single response's own internal identity conflict
(`ConflictingDuplicateExternalIdError`) is likewise recorded and that
RESPONSE is skipped, never the whole operation. Anything else --
notably a `NewsObservationOutOfOrderError` or any repository/database
failure from `RecordNewsObservation` -- is an unexpected system
failure and propagates unchanged, aborting the call; it is never
swallowed into `errors`.
"""

from dataclasses import dataclass

from forex_agent.application.ports.news_source import (
    NewsSourceChannelFetcher,
    NewsSourceUnavailableError,
    NormalizedNewsObservation,
)
from forex_agent.application.use_cases.record_news_observation import (
    RecordNewsObservation,
    RecordNewsObservationOutcome,
)
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.timestamps import UtcTimestamp


class ConflictingDuplicateExternalIdError(Exception):
    """Raised when the SAME `(source_key, external_item_id)` appears
    more than once within a SINGLE response with DIFFERING modeled
    facts (FX-57A Section 39) -- fails closed for that one response
    rather than guessing, from item ordering, which occurrence FTA
    "really" saw. An identical repeat of the same identity within one
    response is NOT an error (handled idempotently, see `_dedupe_
    within_response`); only a genuine content conflict is."""

    def __init__(self, source_key: str, external_item_id: str) -> None:
        self.source_key = source_key
        self.external_item_id = external_item_id
        super().__init__(
            f"source_key={source_key!r} external_item_id={external_item_id!r} appears more "
            "than once in the same response with differing modeled facts -- refusing to "
            "guess which occurrence FTA actually saw"
        )


class SourceKeyMismatchError(Exception):
    """Raised when a fetcher handed to `IngestNewsSourceOnce(source_
    key=...)` produces an observation whose own `source_key` disagrees
    with the source key this ingestion run was identified as (FX-57AH
    Section 2) -- an explicit source-contract violation, never a plain
    assertion, and never silently corrected by rewriting the
    observation's own `source_key`. This is a wiring bug (a fetcher
    supplying the wrong source's data to the wrong run) and must be
    fixed at the call site, not worked around here: a run identified
    as `"FED"` must never persist `"ECB"`/`"BOE"`/... evidence. Raised
    BEFORE the mismatched observation reaches deduplication or
    `RecordNewsObservation`, and propagates uncaught out of
    `IngestNewsSourceOnce.__call__` -- it is never recorded in
    `NewsIngestionResult.errors` and swallowed, unlike a channel's own
    `NewsSourceUnavailableError`."""

    def __init__(self, expected_source_key: str, observation: NormalizedNewsObservation) -> None:
        self.expected_source_key = expected_source_key
        self.actual_source_key = observation.source_key
        self.external_item_id = observation.external_item_id
        super().__init__(
            f"ingestion run identified as source_key={expected_source_key!r} received an "
            f"observation with source_key={observation.source_key!r} "
            f"(external_item_id={observation.external_item_id!r}) -- a fetcher was wired "
            "incorrectly; refusing to persist evidence under the wrong source identity"
        )


@dataclass(frozen=True, slots=True)
class NewsIngestionResult:
    """A purely factual summary of one `IngestNewsSourceOnce` call
    (FX-57A Section 42) -- counts only, never sentiment/importance/
    pair-relevance/trading-direction, which belong to later stories.

    **FX-57AH Section 4**: the item counters are now explicit about
    which stage they describe, rather than one ambiguous `items_seen`:

    - `items_fetched`: every raw item element presented by a
      structurally valid response, INCLUDING invalid items and
      duplicates (i.e. `len(outcome.observations) + outcome.
      items_invalid`, summed over every successfully-fetched
      response).
    - `items_normalized`: valid normalized observations, BEFORE
      within-response deduplication (`len(outcome.observations)`,
      summed over every successfully-fetched response).
    - `items_processed`: observations remaining after identical-
      duplicate collapse, actually submitted to `RecordNewsObserva
      tion` (zero for a response that failed closed on a conflicting
      duplicate guid -- see `ConflictingDuplicateExternalIdError`).
      `items_processed == created + revisions_added + unchanged`
      always.
    """

    source_key: str
    source_channels: tuple[str, ...]
    retrieved_at: tuple[UtcTimestamp, ...]
    items_fetched: int
    items_normalized: int
    items_processed: int
    items_invalid: int
    created: int
    revisions_added: int
    unchanged: int
    quarantined: int
    errors: tuple[str, ...]


class IngestNewsSourceOnce:
    """See the module docstring."""

    def __init__(self, source_key: str, record_observation: RecordNewsObservation) -> None:
        self._source_key = source_key
        self._record_observation = record_observation

    async def __call__(self, fetchers: tuple[NewsSourceChannelFetcher, ...]) -> NewsIngestionResult:
        channels: list[str] = []
        retrieved_ats: list[UtcTimestamp] = []
        items_fetched = 0
        items_normalized = 0
        items_processed = 0
        items_invalid = 0
        created = 0
        revisions_added = 0
        unchanged = 0
        quarantined = 0
        errors: list[str] = []

        for fetcher in fetchers:
            try:
                outcome = await fetcher()
            except NewsSourceUnavailableError as exc:
                errors.append(str(exc))
                continue

            if outcome.source_channel is not None:
                channels.append(outcome.source_channel)
            retrieved_ats.append(outcome.retrieved_at)
            items_invalid += outcome.items_invalid
            items_fetched += len(outcome.observations) + outcome.items_invalid
            items_normalized += len(outcome.observations)
            errors.extend(outcome.invalid_reasons)

            for observation in outcome.observations:
                if observation.source_key != self._source_key:
                    raise SourceKeyMismatchError(self._source_key, observation)

            try:
                deduped = _dedupe_within_response(self._source_key, outcome.observations)
            except ConflictingDuplicateExternalIdError as exc:
                errors.append(str(exc))
                continue

            for observation in deduped:
                items_processed += 1
                record_result = await self._record_observation(observation)
                if record_result.outcome is RecordNewsObservationOutcome.CREATED:
                    created += 1
                elif record_result.outcome is RecordNewsObservationOutcome.REVISION_ADDED:
                    revisions_added += 1
                else:
                    unchanged += 1
                if observation.evidence_disposition is NewsEvidenceDisposition.QUARANTINED:
                    quarantined += 1

        return NewsIngestionResult(
            source_key=self._source_key,
            source_channels=tuple(channels),
            retrieved_at=tuple(retrieved_ats),
            items_fetched=items_fetched,
            items_normalized=items_normalized,
            items_processed=items_processed,
            items_invalid=items_invalid,
            created=created,
            revisions_added=revisions_added,
            unchanged=unchanged,
            quarantined=quarantined,
            errors=tuple(errors),
        )


def _dedupe_within_response(
    source_key: str, observations: tuple[NormalizedNewsObservation, ...]
) -> tuple[NormalizedNewsObservation, ...]:
    by_external_id: dict[str, NormalizedNewsObservation] = {}
    for observation in observations:
        existing = by_external_id.get(observation.external_item_id)
        if existing is None:
            by_external_id[observation.external_item_id] = observation
            continue
        if _same_observation_facts(existing, observation):
            continue
        raise ConflictingDuplicateExternalIdError(source_key, observation.external_item_id)
    return tuple(by_external_id.values())


def _observation_facts(observation: NormalizedNewsObservation) -> tuple[object, ...]:
    return (
        observation.headline,
        observation.source_channel,
        observation.summary,
        observation.body_text,
        observation.canonical_url,
        observation.authors,
        observation.language,
        observation.source_content_type,
        observation.source_published_at,
        observation.source_updated_at,
        observation.source_timestamp_provenance,
        observation.source_revision_metadata,
        observation.source_status,
        observation.evidence_disposition,
        observation.quarantine_reason,
    )


def _same_observation_facts(a: NormalizedNewsObservation, b: NormalizedNewsObservation) -> bool:
    return _observation_facts(a) == _observation_facts(b)

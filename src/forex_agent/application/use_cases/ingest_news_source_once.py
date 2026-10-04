"""FX-57A: the provider-neutral one-shot ingestion orchestration every
concrete news-source adapter (Fed/ECB now; BoE/... later) reuses
unchanged. Hardened by FX-57AH: source-key isolation is now an
enforced, fail-closed contract (Section 2), and the result's own
item counters (Section 4) now distinguish fetched/normalized/
processed explicitly rather than relying on one ambiguous count.

**FX-57BH**: `NewsSourceFetchOutcome.source_channel` is now required
(never `None`) and its own `__post_init__` additionally enforces that
every observation's `source_channel` matches the response's own --
see that type's own docstring. The common fetch contract now
guarantees THREE aligned response-level facts for every observation:
`observed_at == retrieved_at`, `source_key == <this run's own source
key>` (enforced here, in `__call__`), and `source_channel ==
<the response's own source_channel>` (enforced in `NewsSourceFetch
Outcome` itself). This module therefore no longer needs to guard
against an anonymous channel -- `outcome.source_channel` is appended
to `channels` unconditionally.

**FX-57CH: two-phase run, collect-then-persist.** `__call__` now
fetches, validates, and dedupes EVERY configured channel's response
FIRST (Phase 1), and only persists anything (Phase 2) once Phase 1
has confirmed no `(source_key, external_item_id)` was observed under
more than one DISTINCT `source_channel` anywhere in this SAME run
(`CrossChannelIdentityCollisionError`, raised before Phase 2 starts
-- see that exception's own docstring for why this must fail the
WHOLE run closed, never just the colliding channels). The original
single-pass design persisted each response's own observations
immediately after validating it, which meant an EARLIER channel's
evidence could already be durably written before a LATER channel's
response revealed a collision with it -- this refactor closes that
gap by construction: nothing is persisted until every channel in the
run has been fetched and checked.

**FX-57D Section 14/55: a narrow extension to the same two-phase
design.** GOV.UK's own adapter configures ONE fetcher PER DISCOVERED
PATH, all sharing a single `source_channel` -- a shape none of Fed/
ECB/BoE ever produce (they configure exactly one fetcher per
channel). This means the SAME identity could, in principle, be
produced by TWO DIFFERENT fetchers/responses that happen to share one
channel (e.g. two discovery paths that both hydrate to the same
`content_id`) -- a case the original per-response-only dedupe never
checked, since each of those two responses' own `observations` tuple
has length 1 and is trivially "deduped" on its own. Phase 1 now ALSO
accumulates every response's own deduped observations into one flat,
whole-run list; after the Phase 1b cross-channel check passes, that
flat list is deduped AGAIN at the whole-run level (`_dedupe_
observations`, the same function, reused) -- an identical duplicate
collapses silently; a genuinely conflicting one raises `Conflicting
DuplicateExternalIdError` and aborts the WHOLE run, exactly like a
cross-channel collision (not caught and skipped the way a single
response's own internal conflict is). This is a no-op for Fed/ECB/
BoE: none of them can ever have more than one response per channel
in a single run, so the whole-run pass can never find anything the
per-response pass didn't already resolve.

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
notably a `NewsObservationOutOfOrderError`, `SourceKeyMismatchError`,
`CrossChannelIdentityCollisionError`, or any repository/database
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
    more than once with DIFFERING modeled facts -- either within a
    SINGLE response (FX-57A Section 39, e.g. a duplicate `<item>` in
    one RSS document), or, more generally, ACROSS two different
    responses sharing the SAME `source_channel` within one run
    (FX-57D Section 14/55 -- e.g. GOV.UK's own one-fetcher-per-
    discovered-path shape, where two different discovery paths could
    legitimately hydrate to the same `content_id`). Both cases fail
    closed rather than guessing, from response or item ordering,
    which occurrence FTA "really" saw. An identical repeat of the
    same identity -- within one response, or across responses in the
    same channel -- is NOT an error (handled idempotently, see
    `_dedupe_observations`); only a genuine content conflict is. This
    is a no-op distinction for Fed/ECB/BoE, which never produce more
    than one response per configured channel in a single run."""

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


class CrossChannelIdentityCollisionError(Exception):
    """Raised when the SAME `(source_key, external_item_id)` is
    observed under more than one DISTINCT `source_channel` WITHIN THE
    SAME `IngestNewsSourceOnce` call (FX-57CH) -- fails the WHOLE run
    closed, before ANY observation from ANY channel in this run is
    persisted, never just the colliding channels' own observations.

    A single-valued `source_channel` per vintage can represent a
    genuinely SEQUENTIAL provenance change (the same item observed
    under channel A in one run, then under channel B in a LATER run)
    -- that remains an ordinary new vintage, unaffected by this check,
    since this guard is scoped to one `__call__` invocation's own
    collected responses, never across separate calls. But the SAME
    identity appearing under two DIFFERENT channels within ONE run
    means the source presented it as belonging to both SIMULTANEOUSLY
    -- there is no way to tell, from that single run alone, which
    channel FTA "should" treat as current, and modeling it as
    `revision 0 channel=A, revision 1 channel=B` would invent a false
    temporal transition that never actually happened. Rather than
    guess (first channel wins, last channel wins, concatenate the
    channel names, or silently drop one), this fails the entire run
    closed and returns nothing -- the adapter or the source itself
    needs review, not a fabricated history."""

    def __init__(self, source_key: str, external_item_id: str, channels: frozenset[str]) -> None:
        self.source_key = source_key
        self.external_item_id = external_item_id
        self.channels = channels
        super().__init__(
            f"source_key={source_key!r} external_item_id={external_item_id!r} was observed "
            f"under multiple distinct channels within the same ingestion run: "
            f"{sorted(channels)!r} -- a single source_channel per vintage cannot represent "
            "simultaneous multi-channel membership without inventing a false temporal "
            "transition; refusing to persist any observation from this run"
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
        items_invalid = 0
        errors: list[str] = []

        # Phase 1: fetch every channel, enforce source-key isolation,
        # and dedupe within each response -- collect everything
        # BEFORE persisting anything, so a cross-channel identity
        # collision can be detected and fail the WHOLE run closed
        # before any response's evidence is written (FX-57CH).
        ready_batches: list[tuple[NormalizedNewsObservation, ...]] = []
        identity_channels: dict[str, set[str]] = {}

        for fetcher in fetchers:
            try:
                outcome = await fetcher()
            except NewsSourceUnavailableError as exc:
                errors.append(str(exc))
                continue

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
                deduped = _dedupe_observations(self._source_key, outcome.observations)
            except ConflictingDuplicateExternalIdError as exc:
                errors.append(str(exc))
                continue

            for observation in deduped:
                identity_channels.setdefault(observation.external_item_id, set()).add(
                    observation.source_channel
                )
            ready_batches.append(deduped)

        # Phase 1b: cross-channel identity collision check, across
        # EVERY successfully-fetched, non-conflicting response in
        # this run -- before any persistence.
        for external_item_id, observed_channels in identity_channels.items():
            if len(observed_channels) > 1:
                raise CrossChannelIdentityCollisionError(
                    self._source_key, external_item_id, frozenset(observed_channels)
                )

        # Phase 1c (FX-57D): whole-run, cross-response, same-channel
        # duplicate identity check -- a no-op for Fed/ECB/BoE (see the
        # module docstring); raises uncaught, aborting the whole run,
        # exactly like a cross-channel collision -- a run-level
        # identity conflict is not one response's own problem to skip.
        all_observations = tuple(obs for batch in ready_batches for obs in batch)
        final_observations = _dedupe_observations(self._source_key, all_observations)

        # Phase 2: persist -- only reached once every response in
        # this run is confirmed free of any identity collision.
        items_processed = 0
        created = 0
        revisions_added = 0
        unchanged = 0
        quarantined = 0
        for observation in final_observations:
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


def _dedupe_observations(
    source_key: str, observations: tuple[NormalizedNewsObservation, ...]
) -> tuple[NormalizedNewsObservation, ...]:
    """Collapses an identical duplicate identity to one entry;
    raises `ConflictingDuplicateExternalIdError` for a genuinely
    conflicting one. Used twice: once per response (Phase 1, FX-57A),
    and once across the whole run's own flattened observations
    (Phase 1c, FX-57D) -- the same logic applies at both scopes."""
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

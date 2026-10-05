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

**FX-57CH: two-phase run, collect-then-persist.** `__call__` fetches,
validates, and dedupes EVERY configured channel's response FIRST
(Phase 1), and only persists anything (Phase 2) once Phase 1 has
confirmed the whole run is internally consistent -- see Phase 1c
below. The original single-pass design persisted each response's own
observations immediately after validating it, which meant an EARLIER
channel's evidence could already be durably written before a LATER
channel's response revealed a conflict with it -- this refactor closes
that gap by construction: nothing is persisted until every channel in
the run has been fetched and checked.

**FX-57D Section 14/55: a narrow extension to the same two-phase
design.** GOV.UK's own adapter configures ONE fetcher PER DISCOVERED
PATH, all sharing a single `source_channel` -- a shape none of Fed/
ECB/BoE ever produce (they configure exactly one fetcher per
channel). This means the SAME identity could, in principle, be
produced by TWO DIFFERENT fetchers/responses that happen to share one
channel (e.g. two discovery paths that both hydrate to the same
`content_id`) -- a case the original per-response-only dedupe never
checked, since each of those two responses' own `observations` tuple
has length 1 and is trivially "deduped" on its own. Phase 1 therefore
accumulates every response's own deduped observations into one flat,
whole-run list; Phase 1c (below) validates and orders that list.

**FX-57E0: cross-channel identity is no longer inherently a
collision.** Live Statistics Canada research proved false the
original FX-57CH assumption that the SAME `(source_key, external_
item_id)` observed under more than one DISTINCT `source_channel`
within one run is ALWAYS an error -- StatCan legitimately cross-lists
the SAME Daily release under multiple subject feeds simultaneously:
same identity, same content, several genuinely-true channels. The
original `CrossChannelIdentityCollisionError` has therefore been
RETIRED (removed, not kept as a parallel concept alongside the
mechanism below -- CLAUDE.md's own "don't keep unused/overlapping
concepts" discipline) in favour of one unified rule, Phase 1c:

Phase 1c groups this run's own flat, whole-run observation list by
external identity. Within each identity's own group: an exact
same-channel re-observation (identical NON-channel facts) collapses
silently -- this is the FX-57D Section 14/55 case, still a no-op for
Fed/ECB/BoE/GOV.UK today. A DISTINCT channel whose own non-channel
facts AGREE with every other channel already seen for this identity
is genuine ADDITIONAL channel provenance and is kept, never collapsed
-- both observations reach `RecordNewsObservation`, which merges them
into one item's own cumulative `observed_source_channels` (FX-57E0;
see that use case's own docstring). But if ANY two observations for
the SAME identity, in this SAME run, have DISAGREEING non-channel
facts -- regardless of whether they share a channel or not -- the
WHOLE run fails closed with `ConflictingDuplicateExternalIdError`,
before anything is persisted: FTA cannot safely tell, from one run
alone, whether that disagreement is a genuine source update between
requests, a feed inconsistency, or a parser bug. Surviving
observations are then persisted in `observed_at` ascending order
(ties broken by original fetch order) -- not channel name -- so FTA's
own cumulative channel knowledge accumulates in the actual order it
was learned.

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
RESPONSE is skipped, never the whole operation; the SAME exception
raised by Phase 1c, however, aborts the WHOLE run (it propagates
uncaught -- see that phase's own docstring for why a whole-run
conflict cannot safely be narrowed to "just skip the offending
identity"). Anything else -- notably a `NewsObservationOutOfOrderError`,
`SourceKeyMismatchError`, or any repository/database failure from
`RecordNewsObservation` -- is an unexpected system failure and
propagates unchanged, aborting the call; it is never swallowed into
`errors`.
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
    more than once with DIFFERING NON-CHANNEL modeled facts, anywhere
    within one run -- within a SINGLE response (FX-57A Section 39,
    e.g. a duplicate `<item>` in one RSS document), ACROSS two
    different responses sharing the SAME `source_channel` (FX-57D
    Section 14/55 -- e.g. GOV.UK's own one-fetcher-per-discovered-path
    shape, where two different discovery paths could legitimately
    hydrate to the same `content_id`), or ACROSS two different
    responses under genuinely DIFFERENT channels (FX-57E0 -- e.g.
    StatCan's own same-release-multiple-subject-feeds shape; this case
    used to be `CrossChannelIdentityCollisionError`, now RETIRED,
    since live evidence proved cross-channel identity is not
    inherently invalid -- only a genuine NON-CHANNEL content conflict
    is). `source_channel` itself is explicitly EXCLUDED from the
    comparison that decides this (FX-57E0 Section 9/11) -- two
    observations that agree on everything else but differ only in
    channel are legitimate ADDITIONAL provenance, never a conflict,
    and both survive to be merged by `RecordNewsObservation`'s own
    cumulative `observed_source_channels` logic. All conflicting cases
    fail closed rather than guessing, from response/item ordering,
    which occurrence FTA "really" saw. An identical repeat of the same
    identity -- within one response, across responses in the same
    channel, or across responses in different but content-agreeing
    channels -- is NOT an error (handled idempotently or kept as
    additional provenance, see `_dedupe_observations`/`_group_and_
    validate_whole_run`); only a genuine non-channel content conflict
    is. The within-one-response case is a no-op distinction for Fed/
    ECB/BoE/GOV.UK, which never produce more than one response per
    configured channel in a single run."""

    def __init__(self, source_key: str, external_item_id: str) -> None:
        self.source_key = source_key
        self.external_item_id = external_item_id
        super().__init__(
            f"source_key={source_key!r} external_item_id={external_item_id!r} appears more "
            "than once in this run with differing NON-CHANNEL modeled facts -- refusing to "
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

    **FX-57E0**: `channel_memberships_added` counts how many of this
    run's own `RecordNewsObservation` calls reported `channel_added=
    True` -- i.e. added a channel to an EXISTING item's cumulative
    `observed_source_channels` that FTA did not already know about.
    This is NOT a subset of `created` (a brand-new item's own first
    channel is never counted here, matching `RecordNewsObservation
    Result.channel_added`'s own docstring) and is reported separately
    from `revisions_added` so a revision caused purely by a newly-
    learned channel is distinguishable from an ordinary content
    change, without removing or redefining any existing counter.
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
    channel_memberships_added: int
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
        # and dedupe WITHIN each response -- collect everything
        # BEFORE persisting anything, so a whole-run conflict can be
        # detected and fail the WHOLE run closed before any response's
        # evidence is written (FX-57CH).
        ready_batches: list[tuple[NormalizedNewsObservation, ...]] = []

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
                deduped = _dedupe_within_response(self._source_key, outcome.observations)
            except ConflictingDuplicateExternalIdError as exc:
                errors.append(str(exc))
                continue

            ready_batches.append(deduped)

        # Phase 1c (FX-57D/FX-57E0): whole-run validation across EVERY
        # successfully-fetched, non-conflicting response's own
        # observations -- see `_group_and_validate_whole_run`'s own
        # docstring for the exact rule. Raises uncaught, aborting the
        # whole run: a run-level conflict is not one response's own
        # problem to skip. Surviving observations are then persisted
        # in `observed_at` order (ties broken by original fetch
        # order), so cumulative channel provenance (FX-57E0) is
        # learned in the order it actually happened.
        all_observations = tuple(obs for batch in ready_batches for obs in batch)
        ordered = _group_and_validate_whole_run(
            self._source_key, tuple(enumerate(all_observations))
        )
        final_observations = tuple(
            observation
            for _, observation in sorted(
                ordered, key=lambda pair: (pair[1].observed_at.value, pair[0])
            )
        )

        # Phase 2: persist -- only reached once the whole run is
        # confirmed internally consistent.
        items_processed = 0
        created = 0
        revisions_added = 0
        unchanged = 0
        quarantined = 0
        channel_memberships_added = 0
        for observation in final_observations:
            items_processed += 1
            record_result = await self._record_observation(observation)
            if record_result.outcome is RecordNewsObservationOutcome.CREATED:
                created += 1
            elif record_result.outcome is RecordNewsObservationOutcome.REVISION_ADDED:
                revisions_added += 1
            else:
                unchanged += 1
            if record_result.channel_added:
                channel_memberships_added += 1
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
            channel_memberships_added=channel_memberships_added,
            errors=tuple(errors),
        )


def _dedupe_within_response(
    source_key: str, observations: tuple[NormalizedNewsObservation, ...]
) -> tuple[NormalizedNewsObservation, ...]:
    """Collapses an identical duplicate identity WITHIN ONE response
    to one entry; raises `ConflictingDuplicateExternalIdError` for a
    genuinely conflicting one (FX-57A Section 39). Every observation
    in one response shares the same `source_channel` (enforced by
    `NewsSourceFetchOutcome.__post_init__`), so comparing the FULL
    fact set here (`_observation_facts`, channel included) is
    equivalent to comparing non-channel facts only -- channel is never
    the discriminating field at this scope."""
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


def _group_and_validate_whole_run(
    source_key: str,
    indexed_observations: tuple[tuple[int, NormalizedNewsObservation], ...],
) -> tuple[tuple[int, NormalizedNewsObservation], ...]:
    """FX-57E0: groups this run's own flat, whole-run observation list
    by external identity. Within each identity's own group: an exact
    same-channel re-observation (identical NON-channel facts)
    collapses silently -- the FX-57D Section 14/55 case, still a no-op
    for Fed/ECB/BoE/GOV.UK today, since none of them ever produce more
    than one response per channel in a single run. A DISTINCT channel
    whose own non-channel facts AGREE with every other channel already
    seen for this identity is genuine ADDITIONAL channel provenance
    and is KEPT, never collapsed away -- live Statistics Canada
    research proved the same identity can legitimately be observed
    through more than one channel within a single run (the same Daily
    release cross-listed under several subject feeds). Both survive to
    reach `RecordNewsObservation`, which merges them into one item's
    own cumulative `observed_source_channels`. But if ANY two
    observations for the SAME identity in this run have DISAGREEING
    non-channel facts -- regardless of whether they share a channel or
    not -- this raises `ConflictingDuplicateExternalIdError` for the
    WHOLE run: FTA cannot safely tell, from one run alone, whether
    that disagreement is a genuine source update between requests, a
    feed inconsistency, or a parser bug. The original `CrossChannel
    IdentityCollisionError` (same identity, different channel is
    ALWAYS an error) has been retired -- this is its direct
    replacement."""
    groups: dict[str, list[tuple[int, NormalizedNewsObservation]]] = {}
    for index, observation in indexed_observations:
        groups.setdefault(observation.external_item_id, []).append((index, observation))

    surviving: list[tuple[int, NormalizedNewsObservation]] = []
    for external_item_id, group in groups.items():
        by_channel: dict[str, tuple[int, NormalizedNewsObservation]] = {}
        for index, observation in group:
            existing = by_channel.get(observation.source_channel)
            if existing is None:
                by_channel[observation.source_channel] = (index, observation)
                continue
            _, existing_observation = existing
            if _same_non_channel_facts(existing_observation, observation):
                continue
            raise ConflictingDuplicateExternalIdError(source_key, external_item_id)

        channel_entries = list(by_channel.values())
        _, first_observation = channel_entries[0]
        for _, other_observation in channel_entries[1:]:
            if not _same_non_channel_facts(first_observation, other_observation):
                raise ConflictingDuplicateExternalIdError(source_key, external_item_id)
        surviving.extend(channel_entries)

    return tuple(surviving)


def _observation_facts(observation: NormalizedNewsObservation) -> tuple[object, ...]:
    return (
        observation.headline,
        observation.source_channel,
        *_non_channel_observation_facts(observation),
    )


def _non_channel_observation_facts(observation: NormalizedNewsObservation) -> tuple[object, ...]:
    """Every modeled fact EXCEPT `source_channel` (FX-57E0 Section 9/
    11) -- two observations agreeing on all of these but differing
    only in channel are legitimate additional provenance, never a
    conflict."""
    return (
        observation.headline,
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


def _same_non_channel_facts(a: NormalizedNewsObservation, b: NormalizedNewsObservation) -> bool:
    return _non_channel_observation_facts(a) == _non_channel_observation_facts(b)

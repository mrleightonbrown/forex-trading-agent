"""FX-56: record one normalized news observation into the point-in-
time news evidence model, idempotently. First-observation atomicity
hardened by FX-56H; PIT-ordering precedence corrected by FX-56H.1.

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

**FX-56H.1's own corrected PIT-ordering precedence.** Ordering is now
checked BEFORE modeled-fact equality, not after: an incoming
observation whose `observed_at` is earlier than the latest known
vintage's own `availability` is refused (`NewsObservationOutOfOrder
Error`) EVEN IF its modeled facts happen to be identical to that
latest vintage. FX-56H's own original ordering checked equality
first, which silently returned `UNCHANGED` for an identical-but-
earlier observation -- but an earlier `observed_at` asserts that FTA
possessed those exact facts earlier than the stored PIT history
currently says, and silently returning `UNCHANGED` would knowingly
preserve an availability history known to be wrong. The corrected
processing order is: (1) obtain the latest vintage; (2) if
`observed_at < latest.availability`, raise `NewsObservationOutOf
OrderError` -- unconditionally, regardless of content; (3) only once
ordering is confirmed non-violating, compare modeled facts and return
`UNCHANGED` if identical; (4) otherwise append a new revision. Equal
`availability` timestamps between consecutive revisions remain
explicitly permitted (the check is `<`, never `<=`), tie-broken by
`revision_sequence`, matching `NewsItemVintage`'s own PIT-query
ordering (`availability DESC, revision_sequence DESC`). This never
backdates or rewrites an existing row -- a violating observation is
rejected outright, never silently reconciled.

This use case performs no network I/O and assumes no specific source
adapter (FX-57's own job): it only ever receives an already-normalized
`NormalizedNewsObservation`.

**FX-57E0: cumulative multi-channel provenance.** Live Statistics
Canada research proved false a durable assumption FX-57B/FX-57CH both
made: that the same external identity is observed through at most ONE
channel "at a time," any channel change being a genuinely SEQUENTIAL
transition. StatCan legitimately cross-lists the SAME Daily release
under MULTIPLE subject feeds simultaneously -- same external id, same
headline, same content, several publisher channels. `NewsItemVintage.
source_channel` still names exactly which channel produced THIS
vintage's own observation (unchanged, singular, always one value); a
NEW field, `observed_source_channels`, now also carries the canonical,
CUMULATIVE set of every channel FTA has observed this item through by
this vintage's own `availability`. This use case computes that
cumulative set itself, on every call: `new_channels = canonicalize(
latest.observed_source_channels | {observation.source_channel})` --
channel membership only ever GROWS (an item disappearing from a feed
proves nothing about whether its publisher classification changed, so
nothing here ever removes a channel), and `observed_source_channels`
(not the bare `source_channel`) now participates in modeled-fact
equality: observing an identity through an ALREADY-known channel, with
otherwise-identical content, is still `UNCHANGED` (the cumulative set
does not grow); observing it through a genuinely NEW channel mints a
`REVISION_ADDED` even if every other field is byte-identical, because
FTA's own knowledge of this item's provenance just grew -- a fact
worth its own vintage, same discipline as any other content change.
This is never documented as "the publisher reclassified the item" --
it is FTA learning an additional, independently-true fact about an
item it already knew, nothing more.
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
    """Fields:
    news_item_key/revision_sequence/outcome: unchanged from
        before FX-57E0.
    channel_added: whether THIS call's own observation added a
        channel to the item's cumulative `observed_source_
        channels` that FTA did not already know about (FX-57E0
        Section 21) -- `False` for a brand new item's own
        first-ever observation (there is no prior "already known"
        set to add to), so `created`/`channel_added` remain
        mutually distinguishing signals, same discipline as
        `created`/`revisions_added`/`unchanged` are already
        mutually exclusive. Exists so a `REVISION_ADDED` outcome
        never hides WHY it happened -- an ordinary content change,
        a newly-learned channel, or both.
    """

    news_item_key: str
    revision_sequence: int
    outcome: RecordNewsObservationOutcome
    channel_added: bool


class NewsObservationOutOfOrderError(Exception):
    """Raised when an observation claims an `observed_at` earlier
    than the latest known vintage's own `availability` for the same
    item (FX-56H Section 7; precedence corrected by FX-56H.1) --
    refusing to append a backdated revision, or to silently accept an
    identical-but-earlier repeat as if it changed nothing about the
    system's own known availability history.

    **FX-56H.1 correction**: this error fires on the ORDERING
    violation alone -- it is NOT conditional on the observation's
    modeled facts differing from the latest vintage. An observation
    describing the IDENTICAL fact as the latest vintage but claiming
    an earlier `observed_at` still raises this: an earlier `observed_
    at` is itself an assertion that FTA possessed those facts earlier
    than the stored history says, and that assertion must be rejected
    regardless of whether the facts themselves also changed. Only an
    observation whose own `observed_at` is NOT earlier than the
    latest vintage's `availability` (strictly `>=`) ever reaches the
    modeled-facts comparison that can return `UNCHANGED`.
    """

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
            build_vintage=lambda key: _build_vintage(
                key,
                observation,
                revision_sequence=0,
                observed_source_channels=(observation.source_channel,),
            ),
        )
        if registration.outcome is NewsItemRegistrationOutcome.CREATED:
            # Item, mapping, and revision 0 were just committed together,
            # atomically (FX-56H) -- nothing further to compare or write.
            return RecordNewsObservationResult(
                news_item_key=registration.news_item_key,
                revision_sequence=0,
                outcome=RecordNewsObservationOutcome.CREATED,
                channel_added=False,
            )

        news_item_key = registration.news_item_key
        existing_vintages = await self._repository.list_vintages(news_item_key)
        latest = _latest_by_revision(existing_vintages)
        # FX-56H's own atomic first-observation guarantee means an
        # existing item ALWAYS has at least a revision-0 vintage.
        assert latest is not None

        # FX-56H.1: ordering is checked BEFORE modeled-fact equality,
        # unconditionally -- an identical-but-earlier observation must
        # still fail closed (see this module's own docstring and
        # `NewsObservationOutOfOrderError`'s own docstring for why).
        if observation.observed_at.value < latest.availability.value:
            raise NewsObservationOutOfOrderError(
                news_item_key, latest.availability, observation.observed_at
            )

        # FX-57E0: channel membership is monotonic -- FTA's own
        # cumulative knowledge of this item's channels only ever
        # grows, UNION'd with whatever this new observation's own
        # channel is, never subtracted for any reason.
        new_channels = _canonicalize_channels(
            (*latest.observed_source_channels, observation.source_channel)
        )
        channel_added = observation.source_channel not in latest.observed_source_channels

        candidate = _build_vintage(
            news_item_key,
            observation,
            revision_sequence=0,
            observed_source_channels=new_channels,
        )
        if _same_modeled_facts(latest, candidate):
            return RecordNewsObservationResult(
                news_item_key=news_item_key,
                revision_sequence=latest.revision_sequence,
                outcome=RecordNewsObservationOutcome.UNCHANGED,
                channel_added=False,
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
                channel_added=False,
            )
        return RecordNewsObservationResult(
            news_item_key=news_item_key,
            revision_sequence=next_revision,
            outcome=RecordNewsObservationOutcome.REVISION_ADDED,
            channel_added=channel_added,
        )


def _canonicalize_channels(channels: tuple[str, ...]) -> tuple[str, ...]:
    """The canonical, deterministic representation of a set of
    channels (FX-57E0 Section 5) -- sorted and deduped, never
    order-of-observation dependent."""
    return tuple(sorted(set(channels)))


def _build_vintage(
    news_item_key: str,
    observation: NormalizedNewsObservation,
    *,
    revision_sequence: int,
    observed_source_channels: tuple[str, ...],
) -> NewsItemVintage:
    """Maps one observation onto a vintage at the given
    `revision_sequence` -- every field other than `revision_sequence`/
    `observed_source_channels` is this vintage's own final value,
    never a placeholder. `observed_source_channels` is supplied by the
    caller (FX-57E0): it depends on the ALREADY-known cumulative set of
    the item this vintage belongs to, which this function has no
    access to on its own."""
    return NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=revision_sequence,
        availability=observation.observed_at,
        observation_mode=observation.observation_mode,
        headline=observation.headline,
        source_channel=observation.source_channel,
        observed_source_channels=observed_source_channels,
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
    modeled facts should NOT mint another revision").

    **FX-57E0**: the bare `vintage.source_channel` no longer
    participates here -- `vintage.observed_source_channels` (the
    cumulative set) does instead. Re-observing an identity through an
    ALREADY-known channel never changes this tuple on its own
    (`observed_source_channels` is unchanged); a genuinely NEW channel
    changes it (the cumulative set grew), correctly minting a revision
    even when every other field is byte-identical -- FTA's own
    knowledge just grew, which is itself a fact worth a vintage."""
    return (
        vintage.observation_mode,
        vintage.headline,
        vintage.observed_source_channels,
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

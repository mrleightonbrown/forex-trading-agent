"""Port for storing and point-in-time-querying news evidence (FX-56;
first-observation atomicity hardened by FX-56H; this port's own
public creation contract narrowed by FX-56H.1).

The defining invariant of every `*_as_of` method, mirroring `applica
tion.ports.economic_event_repository.EconomicEventRepository`'s own:
a query at `as_of` must never return a vintage whose `availability` is
after `as_of`. `availability` is ALWAYS FTA's own observation time
(see `domain.news_item_vintage.NewsItemVintage`'s own docstring) --
this port has no method anywhere that filters/selects on `source_
published_at`, `source_updated_at`, a canonical URL, or any provider
correction timestamp (FX-56 Section 44).

**FX-56H.1: this port's PUBLIC contract has exactly ONE item-creating
operation -- `register_source_item_with_first_vintage`.** FX-56's own
original design additionally exposed a bare `register_source_item`
(item+mapping only, no content) as a public Protocol method, intended
as a correction to FX-52A/FX-52AH's own two-step "mint an occurrence,
add it, THEN record its mapping" weakness (see `application.ports.
economic_event_source_mapping_repository`'s own module docstring for
that history). FX-56H then discovered that `register_source_item`
ALONE is not sufficient for safely recording a first observation,
because committing item+mapping and separately writing revision 0 in
a LATER transaction reopens a structurally identical atomicity gap one
level up (a failure between those two steps leaves a durably-
committed `NewsItem` with no revision 0 at all). FX-56H.1 completes
that correction: a bare, content-less item-creating operation is no
longer part of this port's own PUBLIC contract at all, because its
mere EXISTENCE as a legitimate public operation contradicted `Record
NewsObservation`'s own invariant that an existing item always has a
revision-0 vintage -- any production caller holding a `NewsRepository`
-typed reference can create an item ONLY together with its first
vintage, by construction, never separately. A concrete implementation
may still offer a lower-level, explicitly private/test-only helper for
its own repository-level test setup (see `SqlAlchemyNewsRepository`'s
own `_register_source_item_for_test_setup`) -- that helper is
deliberately NOT part of this Protocol, is never called by `Record
NewsObservation` or any other production code path, and exists only
to let a repository-level test exercise identity resolution in
isolation without legitimizing "an item exists with no revision 0" as
a real, supported production state.

`register_source_item_with_first_vintage` closes the full first-
observation gap by construction: a concrete implementation must
perform the candidate item's insert, its mapping's insert, AND its
first vintage's insert in ONE transaction, committing all three
TOGETHER only if the mapping insert actually wins the identity race --
a losing attempt, or ANY other failure before commit (including the
first vintage's own insert failing), rolls the WHOLE attempt back,
discarding even the candidate item. No caller of this port can ever
observe, or need to clean up, an orphan item, nor an item with no
revision 0.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from forex_agent.domain.news_item import NewsItem
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.timestamps import UtcTimestamp


class NewsItemRegistrationOutcome(Enum):
    """`CREATED`/`ALREADY_EXISTS` -- shared by `FirstObservationResult`
    (this port's own public creating operation) and by a concrete
    repository's private, test-only bare-identity helper, if it has
    one (FX-56H.1 -- see the module docstring for why a bare,
    content-less creating operation is no longer part of this port's
    own PUBLIC contract)."""

    CREATED = "CREATED"
    ALREADY_EXISTS = "ALREADY_EXISTS"


@dataclass(frozen=True, slots=True)
class NewsItemRegistrationResult:
    """The result shape for a bare identity-only registration --
    used by a concrete repository's own private, test-only helper
    (FX-56H.1), never by this port's own public Protocol, which has
    no bare, content-less creating operation (see the module
    docstring).

    `first_seen_at`/`first_observation_mode` always describe the
    CANONICAL item's own real first observation -- when `outcome` is
    `ALREADY_EXISTS`, these may differ from the `observed_at`/
    `observation_mode` the caller passed in (another registration won
    the race, or simply registered this identity earlier); a caller
    must use these fields, never its own input, as the item's true
    `first_seen_at`.
    """

    news_item_key: str
    outcome: NewsItemRegistrationOutcome
    first_seen_at: UtcTimestamp
    first_observation_mode: NewsObservationMode


@dataclass(frozen=True, slots=True)
class FirstObservationResult:
    """`register_source_item_with_first_vintage`'s own result (FX-56H)
    -- this port's own sole public creating operation (FX-56H.1).

    `outcome` reuses `NewsItemRegistrationOutcome` (`CREATED`/
    `ALREADY_EXISTS`). When `outcome` is `ALREADY_EXISTS`, the
    caller's own `build_vintage` callback was never invoked for
    persistence (the candidate item/vintage this attempt would have
    built are discarded entirely) -- a caller must fetch the existing
    item's own vintages itself (e.g. via `list_vintages`) to continue.
    """

    news_item_key: str
    outcome: NewsItemRegistrationOutcome


class NewsVintageWriteOutcome(Enum):
    """What `add_vintage` actually did (FX-56). Deliberately a
    separate, identically-shaped enum from `application.ports.
    economic_event_repository.VintageWriteOutcome` rather than a
    shared import -- the concept is generic, but the two ports are not
    coupled to each other (mirrors that port's own stated reasoning
    for not sharing its enum with `macro_observation_repository`'s
    identically-shaped one)."""

    INSERTED = "INSERTED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


class NewsVintageConflictError(Exception):
    """Raised by `add_vintage` when a vintage with the same natural
    identity -- `(news_item_key, revision_sequence)` -- already exists
    in storage but its payload differs from the incoming one (mirrors
    `EconomicEventVintageConflictError`). An exact duplicate of an
    already-stored vintage is NOT an error (idempotent, see
    `add_vintage`'s own contract); only a genuine content mismatch is.
    """

    def __init__(self, existing: NewsItemVintage, incoming: NewsItemVintage) -> None:
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            "vintage identity "
            f"(news_item_key={incoming.news_item_key!r}, "
            f"revision_sequence={incoming.revision_sequence}) already exists with a "
            f"different payload: existing={existing!r}, incoming={incoming!r}"
        )


class NewsRepository(Protocol):
    """Port for storing and point-in-time-querying news evidence --
    see the module docstring."""

    async def register_source_item_with_first_vintage(
        self,
        identity: NewsSourceIdentity,
        observed_at: UtcTimestamp,
        observation_mode: NewsObservationMode,
        build_vintage: Callable[[str], NewsItemVintage],
    ) -> FirstObservationResult:
        """Atomically resolve `identity` to its internal `NewsItem`
        identity AND, if -- and only if -- a brand NEW item is being
        created, persist its first vintage (`revision_sequence == 0`)
        together with it, in one transaction (FX-56H; see the module
        docstring).

        `build_vintage(candidate_news_item_key)` is called to
        construct the candidate revision-0 `NewsItemVintage` BEFORE
        any database write is attempted, for exactly ONE never-before-
        seen candidate key -- so a `build_vintage` that raises (e.g. a
        blank headline failing `NewsItemVintage.__post_init__`) leaves
        zero rows of any kind persisted. The returned vintage's own
        `revision_sequence` MUST be `0`, its `availability` MUST equal
        `observed_at`, and its `observation_mode` MUST equal
        `observation_mode` -- a concrete implementation validates this
        defensively and raises `ValueError` if violated, since it is a
        caller-construction bug, not a data condition.

        If `identity` already resolves to an existing item (whether
        because it was registered earlier, or because a CONCURRENT
        attempt for the SAME identity wins the race during this very
        call), `build_vintage` is simply never invoked for persistence
        purposes and `FirstObservationResult.outcome` is
        `ALREADY_EXISTS` -- the caller is responsible for comparing
        its own observation against the existing item's own vintage
        history itself (this method only ever handles the FIRST
        observation of a genuinely new item).

        If anything fails after the item/mapping insert attempt but
        before the whole transaction commits -- including the mapping
        losing its own race, or the vintage insert itself failing for
        any reason -- the ENTIRE transaction rolls back, so no
        candidate item, mapping, or vintage row survives. A losing
        race resolves to the winner's identity (`ALREADY_EXISTS`); any
        other failure propagates to the caller unchanged."""
        ...

    async def get_item(self, news_item_key: str) -> NewsItem | None:
        """The item at this internal key, or `None` if it does not
        exist."""
        ...

    async def get_item_by_source_identity(self, identity: NewsSourceIdentity) -> NewsItem | None:
        """The item `identity` currently resolves to, or `None` if no
        mapping for it has been registered yet. A read-only lookup;
        never creates anything (see `register_source_item_with_first_
        vintage` for this port's own sole creating path)."""
        ...

    async def add_vintage(self, vintage: NewsItemVintage) -> NewsVintageWriteOutcome:
        """Persist a new vintage. Never mutates or replaces an
        existing one -- a content change, withdrawal, or quarantine-
        status change is a new vintage with a higher `revision_
        sequence`, for the SAME `news_item_key`. Idempotent for an
        exact retry; raises `NewsVintageConflictError` for a same-
        identity, different-payload write. The owning item must exist
        before any vintage of it can be added (enforced by a database
        foreign key in the SQL implementation, not merely by
        convention)."""
        ...

    async def list_vintages(self, news_item_key: str) -> tuple[NewsItemVintage, ...]:
        """Every stored vintage of this item, in no particular
        guaranteed order -- an administrative/audit read, not a
        point-in-time query."""
        ...

    async def latest_vintage_as_of(
        self, news_item_key: str, as_of: UtcTimestamp
    ) -> NewsItemVintage | None:
        """The latest vintage of this item with `availability <=
        as_of`, regardless of `evidence_disposition` or `observation_
        mode` -- `None` if none qualifies. Never filters/selects on
        any source-supplied timestamp (see the module docstring)."""
        ...

    async def latest_evidence_eligible_vintage_as_of(
        self,
        news_item_key: str,
        as_of: UtcTimestamp,
        *,
        include_backfill: bool = False,
    ) -> NewsItemVintage | None:
        """The latest vintage of this item with `availability <=
        as_of` AND `evidence_disposition == EVIDENCE_ELIGIBLE` --
        `None` if none qualifies, even if `latest_vintage_as_of` would
        return something (e.g. the only qualifying vintage is
        QUARANTINED). `include_backfill=False` (the default) also
        excludes any vintage whose `observation_mode == BACKFILL`,
        so a future historical import can never masquerade as
        prospectively-observed evidence unless a caller explicitly
        opts in (FX-56 Section 28)."""
        ...

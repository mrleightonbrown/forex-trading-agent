"""Port for storing and point-in-time-querying FX-58's own derived
canonical-relation evidence -- a SEPARATE port from `NewsRepository`
(FX-58 Section 29), rather than bloating source-ingestion concerns
into that one. Every `*_as_of` method shares `NewsRepository`'s own
defining invariant: a query must never return/consider a relation
vintage whose `availability` is after the requested instant.

This port reuses `NewsRepository.latest_evidence_eligible_vintage_
as_of` for candidate construction (Section 27) rather than inventing
a second interpretation of "latest eligible" -- a concrete
implementation is expected to hold (or be given) a `NewsRepository`
instance for exactly that purpose.
"""

from dataclasses import dataclass
from typing import Protocol

from forex_agent.domain.news_canonical_relation_vintage import NewsCanonicalRelationVintage
from forex_agent.domain.news_canonicalization_matching import CanonicalizationCandidate
from forex_agent.domain.news_item import NewsItem
from forex_agent.domain.timestamps import UtcTimestamp


class NewsCanonicalRelationConflictError(Exception):
    """Raised by `add_relation_vintage` when a relation with the same
    natural identity -- `(left_news_item_key, right_news_item_key,
    revision_sequence)` -- already exists in storage but its payload
    differs from the incoming one (mirrors `NewsVintageConflictError`,
    FX-58 Section 51). An exact duplicate of an already-stored
    relation is NOT an error (idempotent); only a genuine content
    mismatch is."""

    def __init__(
        self, existing: NewsCanonicalRelationVintage, incoming: NewsCanonicalRelationVintage
    ) -> None:
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            "canonical relation identity "
            f"(left={incoming.left_news_item_key!r}, right={incoming.right_news_item_key!r}, "
            f"revision_sequence={incoming.revision_sequence}) already exists with a different "
            f"payload: existing={existing!r}, incoming={incoming!r}"
        )


@dataclass(frozen=True, slots=True)
class RelationVintageWriteResult:
    """`add_relation_vintage`'s own result -- `inserted=True` for a
    genuinely new row, `False` for an idempotent retry of an exact
    duplicate (mirrors `NewsVintageWriteOutcome`, kept as a dedicated
    type here since this port's own identity triple differs)."""

    inserted: bool


class NewsCanonicalizationRepository(Protocol):
    """Port for FX-58's own derived canonical-relation evidence --
    see the module docstring."""

    async def list_candidates_as_of(
        self, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> tuple[CanonicalizationCandidate, ...]:
        """One `CanonicalizationCandidate` per `NewsItem` that has a
        qualifying latest EVIDENCE-ELIGIBLE vintage as of `as_of`
        (Section 27) -- reusing `NewsRepository.latest_evidence_
        eligible_vintage_as_of` directly, mirroring its ACTUAL real
        semantics exactly, never a second, invented interpretation.
        Concretely: if the item's OVERALL latest vintage as of `as_of`
        is quarantined but an EARLIER vintage of the same item was
        evidence-eligible, that earlier vintage is what gets compared
        (this is the already-shipped FX-56 behavior, not a new rule
        FX-58 introduces) -- the item is excluded entirely ONLY when
        NO vintage at all, as of `as_of`, is evidence-eligible.
        `include_backfill=False` (the default) also excludes any
        `BACKFILL`-mode vintage, same as that method's own default."""
        ...

    async def list_items_seen_as_of(self, as_of: UtcTimestamp) -> tuple[NewsItem, ...]:
        """Every `NewsItem` with `first_seen_at <= as_of` (Section 29's
        own "list NewsItems seen as_of for group derivation") --
        deliberately NOT filtered by current evidence eligibility
        (Section 28: a story later marked withdrawn can still be the
        same underlying publication as another source representation,
        so group derivation considers every known item, not only
        currently evidence-eligible ones)."""
        ...

    async def latest_relation_for_pair(
        self, left_news_item_key: str, right_news_item_key: str
    ) -> NewsCanonicalRelationVintage | None:
        """The single latest-availability (tie-broken by highest
        `revision_sequence`) relation vintage ever recorded for this
        pair, regardless of any `as_of` bound -- `None` if no relation
        has ever been recorded for it. Used by `RecordNewsCanonical
        Relation` to decide CREATED/REVISION_ADDED/UNCHANGED/BLOCKED_
        BY_REVIEW_OVERRIDE and to enforce PIT ordering (Section 32)."""
        ...

    async def latest_relation_as_of(
        self, left_news_item_key: str, right_news_item_key: str, as_of: UtcTimestamp
    ) -> NewsCanonicalRelationVintage | None:
        """The latest relation vintage for this pair with `availability
        <= as_of` -- `None` if none qualifies, even if `latest_
        relation_for_pair` would return something newer."""
        ...

    async def list_relation_vintages_for_pair(
        self, left_news_item_key: str, right_news_item_key: str
    ) -> tuple[NewsCanonicalRelationVintage, ...]:
        """Every stored relation vintage for this pair, in no
        particular guaranteed order -- an administrative/audit read,
        mirrors `NewsRepository.list_vintages`."""
        ...

    async def list_latest_relation_states_as_of(
        self, as_of: UtcTimestamp
    ) -> tuple[NewsCanonicalRelationVintage, ...]:
        """For EVERY pair that has at least one relation vintage with
        `availability <= as_of`, its own latest such vintage -- one
        entry per pair, used by `GetCanonicalNewsGroupsAsOf` to build
        the `SAME_STORY`/`NOT_SAME_STORY` edge set for group
        derivation (Section 12/29)."""
        ...

    async def add_relation_vintage(
        self, vintage: NewsCanonicalRelationVintage
    ) -> RelationVintageWriteResult:
        """Persist a new relation vintage. Never mutates or replaces
        an existing one (Section 50: no application code path issues
        an `UPDATE` against this table) -- idempotent for an exact
        retry (`inserted=False`); raises `NewsCanonicalRelationConflict
        Error` for a same-identity, different-payload write (Section
        51). Both `left_news_item_key`/`right_news_item_key` must
        already exist as `NewsItem`s, and the two basis vintages
        (`left_item_revision_sequence`/`right_item_revision_sequence`)
        must already exist as `NewsItemVintage`s -- enforced by real
        foreign keys in the SQL implementation, not merely by
        convention (Section 48)."""
        ...

"""Port for storing and point-in-time-querying FX-59's own derived
semantic-annotation evidence -- a SEPARATE port from `NewsRepository`
and `NewsCanonicalizationRepository` (FX-59 Section 49), rather than
bloating either with an unrelated concern. Every `*_as_of` method
shares those ports' own defining invariant: a query must never
return/consider an annotation vintage whose `availability` is after
the requested instant.

This port reuses `NewsRepository.latest_evidence_eligible_vintage_
as_of` for candidate construction (Section 13), mirroring FX-58's own
`NewsCanonicalizationRepository` precedent exactly -- a concrete
implementation is expected to hold (or be given) a `NewsRepository`
instance for exactly that purpose."""

from dataclasses import dataclass
from typing import Protocol

from forex_agent.domain.news_semantic_annotation_vintage import NewsSemanticAnnotationVintage
from forex_agent.domain.news_semantic_classifying import NewsSemanticClassificationCandidate
from forex_agent.domain.timestamps import UtcTimestamp


class NewsSemanticAnnotationConflictError(Exception):
    """Raised by `add_annotation_vintage` when an annotation with the
    same natural identity -- `(news_item_key, revision_sequence)` --
    already exists in storage but its payload differs from the
    incoming one (mirrors `NewsCanonicalRelationConflictError`). An
    exact duplicate of an already-stored annotation is NOT an error
    (idempotent); only a genuine content mismatch is."""

    def __init__(
        self, existing: NewsSemanticAnnotationVintage, incoming: NewsSemanticAnnotationVintage
    ) -> None:
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            "semantic annotation identity "
            f"(news_item_key={incoming.news_item_key!r}, "
            f"revision_sequence={incoming.revision_sequence}) already exists with a different "
            f"payload: existing={existing!r}, incoming={incoming!r}"
        )


@dataclass(frozen=True, slots=True)
class SemanticAnnotationWriteResult:
    """`add_annotation_vintage`'s own result -- `inserted=True` for a
    genuinely new row, `False` for an idempotent retry of an exact
    duplicate (mirrors `RelationVintageWriteResult`)."""

    inserted: bool


class NewsSemanticRepository(Protocol):
    """Port for FX-59's own derived semantic-annotation evidence --
    see the module docstring."""

    async def list_candidates_as_of(
        self, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> tuple[NewsSemanticClassificationCandidate, ...]:
        """One `NewsSemanticClassificationCandidate` per `NewsItem`
        that has a qualifying latest EVIDENCE-ELIGIBLE vintage as of
        `as_of` (FX-59 Section 13) -- reusing `NewsRepository.latest_
        evidence_eligible_vintage_as_of` directly, mirroring its ACTUAL
        real semantics exactly (same fallback-to-an-earlier-eligible-
        vintage behavior FX-58 already established, never a second
        interpretation). `include_backfill=False` (the default, FX-59
        Section 14) also excludes any `BACKFILL`-mode vintage."""
        ...

    async def latest_annotation_for_item(
        self, news_item_key: str
    ) -> NewsSemanticAnnotationVintage | None:
        """The single latest-availability (tie-broken by highest
        `revision_sequence`) annotation vintage ever recorded for this
        item, regardless of any `as_of` bound -- `None` if none has
        ever been recorded. Used by `RecordNewsSemanticAnnotation` to
        decide CREATED/REVISION_ADDED/UNCHANGED and to enforce PIT
        ordering and determinism (Section 51/55)."""
        ...

    async def latest_annotation_as_of(
        self, news_item_key: str, as_of: UtcTimestamp
    ) -> NewsSemanticAnnotationVintage | None:
        """The latest annotation vintage for this item with
        `availability <= as_of` -- `None` if none qualifies, even if
        `latest_annotation_for_item` would return something newer.
        Used by `GetNewsSemanticStateAsOf` (Section 11/66)."""
        ...

    async def list_annotation_vintages_for_item(
        self, news_item_key: str
    ) -> tuple[NewsSemanticAnnotationVintage, ...]:
        """Every stored annotation vintage for this item, in no
        particular guaranteed order -- an administrative/audit read,
        mirrors `NewsRepository.list_vintages`."""
        ...

    async def list_latest_annotation_states_as_of(
        self, as_of: UtcTimestamp
    ) -> tuple[NewsSemanticAnnotationVintage, ...]:
        """For EVERY item that has at least one annotation vintage with
        `availability <= as_of`, its own latest such vintage -- one
        entry per item, suitable for a batch `GetNewsSemanticStateAsOf`
        variant (Section 66)."""
        ...

    async def add_annotation_vintage(
        self, vintage: NewsSemanticAnnotationVintage
    ) -> SemanticAnnotationWriteResult:
        """Persist a new annotation vintage. Never mutates or replaces
        an existing one (Section 60: no application code path issues
        an `UPDATE` against this table) -- idempotent for an exact
        retry (`inserted=False`); raises `NewsSemanticAnnotationConflict
        Error` for a same-identity, different-payload write. `news_
        item_key` must already exist as a `NewsItem`, and `(news_item_
        key, basis_news_item_revision_sequence)` must already exist as
        a `NewsItemVintage` -- enforced by real foreign keys in the SQL
        implementation, not merely by convention (Section 57)."""
        ...

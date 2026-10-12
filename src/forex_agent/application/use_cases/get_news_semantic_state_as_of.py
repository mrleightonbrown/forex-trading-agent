"""FX-59 Section 11/66: a PIT-safe query distinguishing CURRENT/
STALE/UNCLASSIFIED semantic state for one `NewsItem` -- the critical
invariant this story's own Section 11 calls out: a stale annotation
(classified against an EARLIER `NewsItemVintage` than the one
currently evidence-eligible) must NEVER be returned as though it were
current semantics for the item's latest content.

Operates on `news_item_key` ONLY, never a canonical-group key (Section
67) -- FX-60 is responsible for deriving canonical groups and
aggregating member semantics; this use case stays entirely at the
single-item level, per the FX-58/FX-59 architectural boundary this
story's own Section 2/3 establishes."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.news_repository import NewsRepository
from forex_agent.application.ports.news_semantic_repository import NewsSemanticRepository
from forex_agent.domain.news_semantic_annotation_vintage import NewsSemanticAnnotationVintage
from forex_agent.domain.timestamps import UtcTimestamp


class NewsSemanticState(Enum):
    """FX-59 Section 11: the three distinguishable PIT semantic
    states for one `NewsItem` as of a requested instant."""

    CURRENT = "CURRENT"
    """The latest annotation's own basis revision equals the item's
    current evidence-eligible `NewsItemVintage.revision_sequence` as
    of the same instant."""

    STALE = "STALE"
    """An annotation exists, but its basis does not equal the
    current evidence-eligible `NewsItemVintage` as of that instant --
    e.g. the source produced a new revision after the last
    classification run, and `ClassifyNewsOnce` has not yet re-run."""

    UNCLASSIFIED = "UNCLASSIFIED"
    """No semantic annotation is available as of that instant."""


@dataclass(frozen=True, slots=True)
class NewsSemanticStateResult:
    news_item_key: str
    state: NewsSemanticState
    annotation: NewsSemanticAnnotationVintage | None
    """The latest annotation vintage with `availability <= as_of`, if
    any -- present for both `CURRENT` and `STALE` (a caller can still
    inspect what the stale annotation itself said), `None` only for
    `UNCLASSIFIED`."""


class GetNewsSemanticStateAsOf:
    """FX-59's own single-item PIT semantic-state query -- see the
    module docstring."""

    def __init__(
        self, semantic_repository: NewsSemanticRepository, news_repository: NewsRepository
    ) -> None:
        self._semantic_repository = semantic_repository
        self._news_repository = news_repository

    async def __call__(
        self, news_item_key: str, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> NewsSemanticStateResult:
        annotation = await self._semantic_repository.latest_annotation_as_of(news_item_key, as_of)
        if annotation is None:
            return NewsSemanticStateResult(news_item_key, NewsSemanticState.UNCLASSIFIED, None)

        current_vintage = await self._news_repository.latest_evidence_eligible_vintage_as_of(
            news_item_key, as_of, include_backfill=include_backfill
        )
        if (
            current_vintage is not None
            and current_vintage.revision_sequence == annotation.basis_news_item_revision_sequence
        ):
            return NewsSemanticStateResult(news_item_key, NewsSemanticState.CURRENT, annotation)
        return NewsSemanticStateResult(news_item_key, NewsSemanticState.STALE, annotation)


class GetNewsSemanticStatesAsOf:
    """FX-59 Section 66's own batch variant, suitable for FX-60 -- a
    thin wrapper reusing `GetNewsSemanticStateAsOf`'s own single-item
    logic rather than duplicating it."""

    def __init__(
        self, semantic_repository: NewsSemanticRepository, news_repository: NewsRepository
    ) -> None:
        self._single = GetNewsSemanticStateAsOf(semantic_repository, news_repository)

    async def __call__(
        self,
        news_item_keys: tuple[str, ...],
        as_of: UtcTimestamp,
        *,
        include_backfill: bool = False,
    ) -> tuple[NewsSemanticStateResult, ...]:
        return tuple(
            [
                await self._single(news_item_key, as_of, include_backfill=include_backfill)
                for news_item_key in news_item_keys
            ]
        )

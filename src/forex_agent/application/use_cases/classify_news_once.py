"""FX-59: the automatic semantic classifier (`fx59_v1`) -- one
explicit, manually-invoked pass, no scheduler/daemon (Section 78),
performing ZERO network I/O (Section 86): it operates exclusively on
already-ingested, already-persisted evidence.

`run_at` is captured EXACTLY ONCE, via the injected `clock`, and used
as `availability` for every annotation this one run produces (Section
9) -- never called separately per item.

**Section 63's own two-phase discipline**: EVERY candidate is
classified in memory FIRST (a pure, side-effect-free call to
`classify_news_semantics`); only once every candidate has classified
successfully does recording begin, in deterministic (sorted
`news_item_key`) order. A single unsupported source, or any other
classifier failure, therefore leaves ZERO annotations half-written --
it is raised before this call ever touches the repository's own write
path."""

from collections.abc import Callable
from dataclasses import dataclass

from forex_agent.application.ports.news_semantic_repository import NewsSemanticRepository
from forex_agent.application.use_cases.record_news_semantic_annotation import (
    NewsSemanticAnnotationOutcome,
    RecordNewsSemanticAnnotation,
)
from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification
from forex_agent.domain.news_semantic_classifying import (
    NewsSemanticClassificationCandidate,
    classify_news_semantics,
)
from forex_agent.domain.news_semantic_source_profile import get_source_semantic_profile
from forex_agent.domain.news_topic import NewsTopic
from forex_agent.domain.timestamps import UtcTimestamp

ClockFn = Callable[[], UtcTimestamp]

ALGORITHM_VERSION = "fx59_v1"


def default_clock() -> UtcTimestamp:
    return UtcTimestamp.now()


@dataclass(frozen=True, slots=True)
class SemanticDiagnostic:
    """Compact, per-item diagnostics (FX-59 Section 65) -- enough for
    a human reviewer to inspect WITHOUT dumping full article bodies."""

    news_item_key: str
    headline: str
    source_key: str
    topics: tuple[NewsTopic, ...]
    currency_relevance: tuple[NewsCurrencyRelevance, ...]
    non_source_entities: tuple[NewsEntityAnnotation, ...]
    """Entities beyond the item's own source-profile institution/
    jurisdiction (FX-59 Section 79/80's own "explicit foreign-
    institution evidence") -- a TEXT_ALIAS-only entity, or an entity
    of a type/key the source profile itself does not already supply."""


@dataclass(frozen=True, slots=True)
class ClassifyNewsRunResult:
    """Factual counters for one `ClassifyNewsOnce` run (FX-59 Section
    65) -- no scores, no confidence percentages (Section 46)."""

    run_at: UtcTimestamp
    items_considered: int
    annotations_created: int
    revisions_added: int
    unchanged: int
    topics_none: int
    multi_topic_items: int
    multi_currency_items: int
    classifications_by_topic: tuple[tuple[NewsTopic, int], ...]
    relevance_by_currency: tuple[tuple[str, int], ...]
    diagnostics: tuple[SemanticDiagnostic, ...]
    multi_currency_classifications: tuple[SemanticDiagnostic, ...]
    foreign_institution_classifications: tuple[SemanticDiagnostic, ...]


class ClassifyNewsOnce:
    """FX-59's own automatic classifier -- see the module docstring."""

    def __init__(
        self,
        repository: NewsSemanticRepository,
        record: RecordNewsSemanticAnnotation,
        *,
        clock: ClockFn = default_clock,
        algorithm_version: str = ALGORITHM_VERSION,
    ) -> None:
        self._repository = repository
        self._record = record
        self._clock = clock
        self._algorithm_version = algorithm_version

    async def __call__(self, *, dry_run: bool = False) -> ClassifyNewsRunResult:
        """`dry_run=True` (Section 64) previews exactly what a real
        run would decide and persists nothing -- the EXACT SAME
        classification/decision logic, never a separate, divergent
        preview implementation."""
        run_at = self._clock()
        candidates = await self._repository.list_candidates_as_of(run_at)
        sorted_candidates = tuple(sorted(candidates, key=lambda c: c.news_item_key))

        # Section 63 step 4/5: classify EVERY candidate in memory
        # FIRST -- an unsupported source or any other classifier
        # failure propagates here, before a single annotation is
        # recorded.
        planned: list[tuple[NewsSemanticClassificationCandidate, NewsSemanticClassification]] = [
            (candidate, classify_news_semantics(candidate)) for candidate in sorted_candidates
        ]

        annotations_created = 0
        revisions_added = 0
        unchanged = 0
        topics_none = 0
        multi_topic_items = 0
        multi_currency_items = 0
        topic_counts: dict[NewsTopic, int] = {}
        currency_counts: dict[str, int] = {}
        diagnostics: list[SemanticDiagnostic] = []
        multi_currency_diagnostics: list[SemanticDiagnostic] = []
        foreign_institution_diagnostics: list[SemanticDiagnostic] = []

        for candidate, classification in planned:
            result = await self._record(
                candidate.news_item_key,
                candidate.basis_news_item_revision_sequence,
                availability=run_at,
                classification=classification,
                algorithm_version=self._algorithm_version,
                dry_run=dry_run,
            )
            if result.outcome is NewsSemanticAnnotationOutcome.CREATED:
                annotations_created += 1
            elif result.outcome is NewsSemanticAnnotationOutcome.REVISION_ADDED:
                revisions_added += 1
            else:
                unchanged += 1

            if not classification.topics:
                topics_none += 1
            if len(classification.topics) > 1:
                multi_topic_items += 1
            for topic_annotation in classification.topics:
                topic_counts[topic_annotation.topic] = (
                    topic_counts.get(topic_annotation.topic, 0) + 1
                )
            for relevance in classification.currency_relevance:
                currency_counts[relevance.currency_code] = (
                    currency_counts.get(relevance.currency_code, 0) + 1
                )

            profile = get_source_semantic_profile(candidate.source_key)
            non_source_entities = tuple(
                entity
                for entity in classification.entities
                if not (
                    entity.entity_type is NewsEntityType.INSTITUTION
                    and entity.entity_key == profile.institution_entity_key
                )
                and not (
                    entity.entity_type is NewsEntityType.JURISDICTION
                    and entity.entity_key == profile.jurisdiction_entity_key
                )
            )
            diagnostic = SemanticDiagnostic(
                news_item_key=candidate.news_item_key,
                headline=candidate.headline,
                source_key=candidate.source_key,
                topics=tuple(t.topic for t in classification.topics),
                currency_relevance=classification.currency_relevance,
                non_source_entities=non_source_entities,
            )
            diagnostics.append(diagnostic)

            if len(classification.currency_relevance) > 1:
                multi_currency_items += 1
                multi_currency_diagnostics.append(diagnostic)
            if any(
                entity.entity_type is NewsEntityType.INSTITUTION for entity in non_source_entities
            ):
                foreign_institution_diagnostics.append(diagnostic)

        return ClassifyNewsRunResult(
            run_at=run_at,
            items_considered=len(sorted_candidates),
            annotations_created=annotations_created,
            revisions_added=revisions_added,
            unchanged=unchanged,
            topics_none=topics_none,
            multi_topic_items=multi_topic_items,
            multi_currency_items=multi_currency_items,
            classifications_by_topic=tuple(
                sorted(
                    ((topic, count) for topic, count in topic_counts.items()),
                    key=lambda x: x[0].value,
                )
            ),
            relevance_by_currency=tuple(sorted(currency_counts.items())),
            diagnostics=tuple(diagnostics),
            multi_currency_classifications=tuple(multi_currency_diagnostics),
            foreign_institution_classifications=tuple(foreign_institution_diagnostics),
        )

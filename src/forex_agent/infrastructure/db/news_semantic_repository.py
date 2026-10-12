"""SQLAlchemy implementation of `NewsSemanticRepository` (FX-59).

`list_candidates_as_of` reuses `NewsRepository.latest_evidence_
eligible_vintage_as_of` DIRECTLY for the per-item PIT-eligibility
decision (Section 13) -- never a second interpretation of "latest
eligible" written independently here, mirroring `SqlAlchemyNewsCanon
icalizationRepository`'s own precedent exactly. `source_key` is read
from `news_source_mappings`, which this project's own FX-56 schema
already guarantees is exactly one row per `news_item_key` (`uq_news_
source_mappings_news_item_key`).

Every other read/write in this module follows the exact same
idempotent `INSERT ... ON CONFLICT DO NOTHING ... RETURNING id`
discipline `SqlAlchemyNewsRepository`/`SqlAlchemyNewsCanonicalization
Repository` already established -- no method here ever issues an
`UPDATE` against an annotation row (FX-59 Section 60)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.application.ports.news_repository import NewsRepository
from forex_agent.application.ports.news_semantic_repository import (
    NewsSemanticAnnotationConflictError,
    SemanticAnnotationWriteResult,
)
from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_semantic_annotation_vintage import NewsSemanticAnnotationVintage
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification
from forex_agent.domain.news_semantic_classifying import NewsSemanticClassificationCandidate
from forex_agent.domain.news_topic import NewsTopic
from forex_agent.domain.news_topic_annotation import NewsTopicAnnotation
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_semantic_annotation_vintage import (
    NewsSemanticAnnotationVintageRow,
)
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow

_ANNOTATION_KEY = ("news_item_key", "revision_sequence")


class MalformedNewsSemanticAnnotationRowError(Exception):
    """Raised when a persisted `NewsSemanticAnnotationVintageRow`'s
    JSONB columns do not match the shape `domain.news_semantic_
    classification` expects -- a malformed stored structure fails
    loudly here, never silently (mirrors `MalformedNewsVintageRowError`)."""


class SqlAlchemyNewsSemanticRepository:
    """Implements `NewsSemanticRepository`."""

    def __init__(self, session: AsyncSession, news_repository: NewsRepository) -> None:
        self._session = session
        self._news_repository = news_repository

    # --- Candidates ---------------------------------------------------------

    async def list_candidates_as_of(
        self, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> tuple[NewsSemanticClassificationCandidate, ...]:
        stmt = select(NewsItemRow, NewsSourceMappingRow.source_key).join(
            NewsSourceMappingRow, NewsSourceMappingRow.news_item_key == NewsItemRow.news_item_key
        )
        rows = (await self._session.execute(stmt)).all()
        await self._session.commit()

        candidates: list[NewsSemanticClassificationCandidate] = []
        for item_row, source_key in rows:
            vintage = await self._news_repository.latest_evidence_eligible_vintage_as_of(
                item_row.news_item_key, as_of, include_backfill=include_backfill
            )
            if vintage is None:
                continue
            candidates.append(
                NewsSemanticClassificationCandidate(
                    news_item_key=item_row.news_item_key,
                    source_key=source_key,
                    basis_news_item_revision_sequence=vintage.revision_sequence,
                    basis_availability=vintage.availability,
                    headline=vintage.headline,
                    summary=vintage.summary,
                    body_text=vintage.body_text,
                    source_content_type=vintage.source_content_type,
                    source_channel=vintage.source_channel,
                )
            )
        return tuple(candidates)

    # --- Annotations --------------------------------------------------------

    async def latest_annotation_for_item(
        self, news_item_key: str
    ) -> NewsSemanticAnnotationVintage | None:
        stmt = (
            select(NewsSemanticAnnotationVintageRow)
            .where(NewsSemanticAnnotationVintageRow.news_item_key == news_item_key)
            .order_by(
                NewsSemanticAnnotationVintageRow.availability.desc(),
                NewsSemanticAnnotationVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else _annotation_row_to_domain(row)

    async def latest_annotation_as_of(
        self, news_item_key: str, as_of: UtcTimestamp
    ) -> NewsSemanticAnnotationVintage | None:
        stmt = (
            select(NewsSemanticAnnotationVintageRow)
            .where(
                NewsSemanticAnnotationVintageRow.news_item_key == news_item_key,
                NewsSemanticAnnotationVintageRow.availability <= as_of.value,
            )
            .order_by(
                NewsSemanticAnnotationVintageRow.availability.desc(),
                NewsSemanticAnnotationVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else _annotation_row_to_domain(row)

    async def latest_annotations_as_of(
        self, news_item_keys: tuple[str, ...], as_of: UtcTimestamp
    ) -> dict[str, NewsSemanticAnnotationVintage]:
        """FX-60H Section H3: a BATCH equivalent of `latest_
        annotation_as_of` for multiple items in ONE round trip --
        the EXACT SAME `WHERE` conditions as the single-item method
        (membership instead of equality), with the identical "latest
        by (availability, revision_sequence)" reduction performed in
        Python rather than via a second SQL round trip per key. A key
        with no qualifying annotation is simply absent from the
        returned mapping, matching the single-item method's own
        `None` return exactly."""
        if not news_item_keys:
            return {}
        stmt = select(NewsSemanticAnnotationVintageRow).where(
            NewsSemanticAnnotationVintageRow.news_item_key.in_(news_item_keys),
            NewsSemanticAnnotationVintageRow.availability <= as_of.value,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()

        latest_by_key: dict[str, NewsSemanticAnnotationVintageRow] = {}
        for row in rows:
            current = latest_by_key.get(row.news_item_key)
            candidate_sort_key = (row.availability, row.revision_sequence)
            if current is None or candidate_sort_key > (
                current.availability,
                current.revision_sequence,
            ):
                latest_by_key[row.news_item_key] = row
        return {key: _annotation_row_to_domain(row) for key, row in latest_by_key.items()}

    async def list_annotation_vintages_for_item(
        self, news_item_key: str
    ) -> tuple[NewsSemanticAnnotationVintage, ...]:
        stmt = select(NewsSemanticAnnotationVintageRow).where(
            NewsSemanticAnnotationVintageRow.news_item_key == news_item_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_annotation_row_to_domain(row) for row in rows)

    async def list_latest_annotation_states_as_of(
        self, as_of: UtcTimestamp
    ) -> tuple[NewsSemanticAnnotationVintage, ...]:
        stmt = select(NewsSemanticAnnotationVintageRow).where(
            NewsSemanticAnnotationVintageRow.availability <= as_of.value
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()

        latest_by_item: dict[str, NewsSemanticAnnotationVintageRow] = {}
        for row in rows:
            current = latest_by_item.get(row.news_item_key)
            candidate_sort_key = (row.availability, row.revision_sequence)
            if current is None or candidate_sort_key > (
                current.availability,
                current.revision_sequence,
            ):
                latest_by_item[row.news_item_key] = row
        return tuple(_annotation_row_to_domain(row) for row in latest_by_item.values())

    async def add_annotation_vintage(
        self, vintage: NewsSemanticAnnotationVintage
    ) -> SemanticAnnotationWriteResult:
        stmt = (
            pg_insert(NewsSemanticAnnotationVintageRow)
            .values(_annotation_row_values(vintage))
            .on_conflict_do_nothing(index_elements=_ANNOTATION_KEY)
            .returning(NewsSemanticAnnotationVintageRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted_id is not None:
            await self._session.commit()
            return SemanticAnnotationWriteResult(inserted=True)

        existing_row = await self._select_one_annotation(
            vintage.news_item_key, vintage.revision_sequence
        )
        await self._session.commit()
        assert existing_row is not None  # the failed insert proves the identity already exists
        existing = _annotation_row_to_domain(existing_row)
        if existing == vintage:
            return SemanticAnnotationWriteResult(inserted=False)
        raise NewsSemanticAnnotationConflictError(existing, vintage)

    async def _select_one_annotation(
        self, news_item_key: str, revision_sequence: int
    ) -> NewsSemanticAnnotationVintageRow | None:
        stmt = select(NewsSemanticAnnotationVintageRow).where(
            NewsSemanticAnnotationVintageRow.news_item_key == news_item_key,
            NewsSemanticAnnotationVintageRow.revision_sequence == revision_sequence,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()


# --- Domain <-> row mapping -----------------------------------------------


def _annotation_row_values(vintage: NewsSemanticAnnotationVintage) -> dict[str, Any]:
    return {
        "news_item_key": vintage.news_item_key,
        "revision_sequence": vintage.revision_sequence,
        "availability": vintage.availability.value,
        "basis_news_item_revision_sequence": vintage.basis_news_item_revision_sequence,
        "algorithm_version": vintage.algorithm_version,
        "entities": _entities_to_json(vintage.classification.entities),
        "topics": _topics_to_json(vintage.classification.topics),
        "currency_relevance": _currency_relevance_to_json(
            vintage.classification.currency_relevance
        ),
    }


def _annotation_row_to_domain(
    row: NewsSemanticAnnotationVintageRow,
) -> NewsSemanticAnnotationVintage:
    classification = NewsSemanticClassification(
        entities=_entities_from_json(row.entities),
        topics=_topics_from_json(row.topics),
        currency_relevance=_currency_relevance_from_json(row.currency_relevance),
    )
    return NewsSemanticAnnotationVintage(
        news_item_key=row.news_item_key,
        revision_sequence=row.revision_sequence,
        availability=UtcTimestamp(row.availability),
        basis_news_item_revision_sequence=row.basis_news_item_revision_sequence,
        algorithm_version=row.algorithm_version,
        classification=classification,
    )


def _entities_to_json(entities: tuple[NewsEntityAnnotation, ...]) -> list[dict[str, Any]]:
    return [
        {
            "entity_type": entity.entity_type.value,
            "entity_key": entity.entity_key,
            "evidence": [kind.value for kind in entity.evidence],
        }
        for entity in entities
    ]


def _entities_from_json(data: object) -> tuple[NewsEntityAnnotation, ...]:
    if not isinstance(data, list):
        raise MalformedNewsSemanticAnnotationRowError(
            f"entities must be a list, got {type(data).__name__}"
        )
    result: list[NewsEntityAnnotation] = []
    for entry in data:
        if not isinstance(entry, dict):
            raise MalformedNewsSemanticAnnotationRowError(
                f"each entities entry must be an object, got {entry!r}"
            )
        try:
            result.append(
                NewsEntityAnnotation(
                    entity_type=NewsEntityType(entry["entity_type"]),
                    entity_key=entry["entity_key"],
                    evidence=tuple(NewsEntityEvidenceKind(kind) for kind in entry["evidence"]),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise MalformedNewsSemanticAnnotationRowError(
                f"malformed entities entry: {entry!r}"
            ) from exc
    return tuple(result)


def _topics_to_json(topics: tuple[NewsTopicAnnotation, ...]) -> list[dict[str, Any]]:
    return [
        {"topic": topic.topic.value, "matched_terms": list(topic.matched_terms)} for topic in topics
    ]


def _topics_from_json(data: object) -> tuple[NewsTopicAnnotation, ...]:
    if not isinstance(data, list):
        raise MalformedNewsSemanticAnnotationRowError(
            f"topics must be a list, got {type(data).__name__}"
        )
    result: list[NewsTopicAnnotation] = []
    for entry in data:
        if not isinstance(entry, dict):
            raise MalformedNewsSemanticAnnotationRowError(
                f"each topics entry must be an object, got {entry!r}"
            )
        try:
            result.append(
                NewsTopicAnnotation(
                    topic=NewsTopic(entry["topic"]),
                    matched_terms=tuple(entry["matched_terms"]),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise MalformedNewsSemanticAnnotationRowError(
                f"malformed topics entry: {entry!r}"
            ) from exc
    return tuple(result)


def _currency_relevance_to_json(
    currency_relevance: tuple[NewsCurrencyRelevance, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "currency_code": relevance.currency_code,
            "reasons": [reason.value for reason in relevance.reasons],
        }
        for relevance in currency_relevance
    ]


def _currency_relevance_from_json(data: object) -> tuple[NewsCurrencyRelevance, ...]:
    if not isinstance(data, list):
        raise MalformedNewsSemanticAnnotationRowError(
            f"currency_relevance must be a list, got {type(data).__name__}"
        )
    result: list[NewsCurrencyRelevance] = []
    for entry in data:
        if not isinstance(entry, dict):
            raise MalformedNewsSemanticAnnotationRowError(
                f"each currency_relevance entry must be an object, got {entry!r}"
            )
        try:
            result.append(
                NewsCurrencyRelevance(
                    currency_code=entry["currency_code"],
                    reasons=tuple(
                        NewsCurrencyRelevanceReason(reason) for reason in entry["reasons"]
                    ),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise MalformedNewsSemanticAnnotationRowError(
                f"malformed currency_relevance entry: {entry!r}"
            ) from exc
    return tuple(result)

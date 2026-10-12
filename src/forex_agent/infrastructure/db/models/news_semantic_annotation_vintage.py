from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class NewsSemanticAnnotationVintageRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable, append-only FX-59 semantic classification
    (`domain.news_semantic_annotation_vintage.NewsSemanticAnnotation
    Vintage`). This table has no application code path that UPDATEs
    an existing row (FX-59 Section 60) -- a correction is INSERTED as
    a new row with a higher `revision_sequence` for the same item.

    `(news_item_key, revision_sequence)` is unique -- the natural
    identity of one annotation. `news_item_key` carries a genuine
    `FOREIGN KEY` into `news_items`; `basis_news_item_revision_sequence`
    carries a genuine COMPOSITE `FOREIGN KEY` into `news_item_vintages
    (news_item_key, revision_sequence)`, so the exact source vintage
    classified to reach each annotation is always recoverable without
    this table ever copying its content.

    `entities`/`topics`/`currency_relevance` are `JSONB` arrays (FX-59
    Section 56) -- this project's second use of semi-structured
    persistence after FX-56's own `authors`/`source_timestamp_
    provenance`/`source_revision_metadata` precedent; validated on
    load/write by `SqlAlchemyNewsSemanticRepository`'s own
    serialization helpers, which reconstruct validating domain objects
    rather than trusting the stored shape. `ck_..._entities_array`/
    `ck_..._topics_array`/`ck_..._currency_relevance_array` mirror
    `jsonb_typeof(...) = 'array'` in storage; `ck_..._entities_
    nonempty`/`ck_..._currency_relevance_nonempty` (Section 57's own
    storage preference) mirror the domain layer's own non-empty
    requirement for those two fields -- `topics` may legitimately be
    an empty array.

    Only the index this story's own Section 58 actually calls for is
    added -- `(news_item_key, availability, revision_sequence)` for
    PIT item lookup. No speculative JSONB GIN index: FX-60 can
    establish a real query requirement first."""

    __tablename__ = "news_semantic_annotation_vintages"
    __table_args__ = (
        UniqueConstraint(
            "news_item_key",
            "revision_sequence",
            name="uq_nsav_identity",
        ),
        ForeignKeyConstraint(
            ["news_item_key"],
            ["news_items.news_item_key"],
            name="fk_nsav_news_item",
        ),
        ForeignKeyConstraint(
            ["news_item_key", "basis_news_item_revision_sequence"],
            ["news_item_vintages.news_item_key", "news_item_vintages.revision_sequence"],
            name="fk_nsav_basis_vintage",
        ),
        Index(
            "ix_nsav_item_availability",
            "news_item_key",
            "availability",
            "revision_sequence",
        ),
        CheckConstraint(
            "revision_sequence >= 0",
            name="ck_nsav_revision_sequence",
        ),
        CheckConstraint(
            "basis_news_item_revision_sequence >= 0",
            name="ck_nsav_basis_news_item_revision_sequence",
        ),
        CheckConstraint(
            "algorithm_version <> ''",
            name="ck_nsav_algorithm_version",
        ),
        CheckConstraint(
            "jsonb_typeof(entities) = 'array'",
            name="ck_nsav_entities_array",
        ),
        CheckConstraint(
            "jsonb_typeof(topics) = 'array'",
            name="ck_nsav_topics_array",
        ),
        CheckConstraint(
            "jsonb_typeof(currency_relevance) = 'array'",
            name="ck_nsav_currency_relevance_array",
        ),
        CheckConstraint(
            "jsonb_array_length(entities) > 0",
            name="ck_nsav_entities_nonempty",
        ),
        CheckConstraint(
            "jsonb_array_length(currency_relevance) > 0",
            name="ck_nsav_currency_relevance_nonempty",
        ),
    )

    news_item_key: Mapped[str] = mapped_column(String, nullable=False)
    revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    availability: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    basis_news_item_revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)
    entities: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    topics: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    currency_relevance: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class NewsCanonicalRelationVintageRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable, append-only FX-58 canonicalization decision
    (`domain.news_canonical_relation_vintage.NewsCanonicalRelation
    Vintage`). This table has no application code path that UPDATEs
    an existing row (FX-58 Section 50) -- a correction is INSERTED as
    a new row with a higher `revision_sequence` for the same pair.

    `(left_news_item_key, right_news_item_key, revision_sequence)` is
    unique -- the natural identity of one relation decision. Both
    `left_news_item_key`/`right_news_item_key` carry genuine `FOREIGN
    KEY`s into `news_items`; `left_item_revision_sequence`/`right_
    item_revision_sequence` carry genuine COMPOSITE `FOREIGN KEY`s
    into `news_item_vintages(news_item_key, revision_sequence)`, so
    the exact source vintages compared to reach each decision are
    always recoverable without this table ever copying their content.

    `ck_..._left_lt_right` mirrors the domain layer's own canonical-
    pair-ordering/self-relation check in storage (FX-58 Section 4).
    `ck_..._relation_kind`/`ck_..._method` mirror the two enums'
    members the same way every other FX-56/FX-58 table's own `ck_...`
    constraints do. `ck_..._automatic_method_is_same_story`/`ck_..._
    not_same_story_is_manual_review` mirror the domain layer's own
    two method/relation_kind cross-field invariants (`NewsCanonical
    RelationVintage.__post_init__`).
    """

    __tablename__ = "news_canonical_relation_vintages"
    __table_args__ = (
        UniqueConstraint(
            "left_news_item_key",
            "right_news_item_key",
            "revision_sequence",
            name="uq_ncrv_identity",
        ),
        ForeignKeyConstraint(
            ["left_news_item_key"],
            ["news_items.news_item_key"],
            name="fk_ncrv_left_item",
        ),
        ForeignKeyConstraint(
            ["right_news_item_key"],
            ["news_items.news_item_key"],
            name="fk_ncrv_right_item",
        ),
        ForeignKeyConstraint(
            ["left_news_item_key", "left_item_revision_sequence"],
            ["news_item_vintages.news_item_key", "news_item_vintages.revision_sequence"],
            name="fk_ncrv_left_vintage",
        ),
        ForeignKeyConstraint(
            ["right_news_item_key", "right_item_revision_sequence"],
            ["news_item_vintages.news_item_key", "news_item_vintages.revision_sequence"],
            name="fk_ncrv_right_vintage",
        ),
        Index(
            "ix_ncrv_pair_availability",
            "left_news_item_key",
            "right_news_item_key",
            "availability",
        ),
        CheckConstraint(
            "left_news_item_key < right_news_item_key",
            name="ck_ncrv_left_lt_right",
        ),
        CheckConstraint(
            "revision_sequence >= 0",
            name="ck_ncrv_revision_sequence",
        ),
        CheckConstraint(
            "left_item_revision_sequence >= 0",
            name="ck_ncrv_left_item_revision_sequence",
        ),
        CheckConstraint(
            "right_item_revision_sequence >= 0",
            name="ck_ncrv_right_item_revision_sequence",
        ),
        CheckConstraint(
            "relation_kind IN ('SAME_STORY', 'NOT_SAME_STORY')",
            name="ck_ncrv_relation_kind",
        ),
        CheckConstraint(
            "method IN ('EXACT_CANONICAL_URL', 'EXACT_BODY_TEXT', 'EXACT_HEADLINE_AND_SUMMARY', "
            "'MANUAL_REVIEW')",
            name="ck_ncrv_method",
        ),
        CheckConstraint(
            "method NOT IN ('EXACT_CANONICAL_URL', 'EXACT_BODY_TEXT', "
            "'EXACT_HEADLINE_AND_SUMMARY') OR relation_kind = 'SAME_STORY'",
            name="ck_ncrv_automatic_method_is_same_story",
        ),
        CheckConstraint(
            "relation_kind <> 'NOT_SAME_STORY' OR method = 'MANUAL_REVIEW'",
            name="ck_ncrv_not_same_story_is_manual_review",
        ),
        CheckConstraint(
            "algorithm_version <> ''",
            name="ck_ncrv_algorithm_version",
        ),
    )

    left_news_item_key: Mapped[str] = mapped_column(String, nullable=False)
    right_news_item_key: Mapped[str] = mapped_column(String, nullable=False)
    revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    availability: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    relation_kind: Mapped[str] = mapped_column(String, nullable=False)
    method: Mapped[str] = mapped_column(String, nullable=False)
    left_item_revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    right_item_revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)

"""add news semantic annotation vintages

FX-59: one new table, `news_semantic_annotation_vintages` -- the
derived, append-only PIT evidence layer recording FTA's `fx59_v1`
macro semantic classification (entities/topics/currency relevance)
for one source-native `NewsItem`. No existing `news_*` table is
touched, mutated, or gains a new column -- classification never
merges NewsItems, repoints their source mappings, or alters anything
FX-56/57/58 already persisted.

Every row pins the exact `NewsItemVintage` FTA actually classified
(`basis_news_item_revision_sequence`, via a genuine composite foreign
key into `news_item_vintages(news_item_key, revision_sequence)`)
rather than copying its content, so a classification can always be
audited against the exact evidence that produced it.

Downgrade is GUARDED from the start (the same precedent `274aabcc57dd`
itself already established for FX-58's own canonical-relation table,
which itself followed `504030474987`'s original FX-56 precedent):
once this table holds a row, dropping it would silently discard real
classification-decision history (exactly WHEN and under which
algorithm_version FTA classified an item) that cannot be reliably
reconstructed after the fact. `downgrade()` refuses with a clear
`RuntimeError` naming the row count if the table is non-empty;
proceeds normally when it is genuinely empty.

Revision ID: 4b2621787a37
Revises: 3fe8c43841ee
Create Date: 2026-10-12 17:23:29.082642

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4b2621787a37"
down_revision: str | None = "3fe8c43841ee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "news_semantic_annotation_vintages"


def _raise_if_downgrade_would_lose_data() -> None:
    """Refuses to drop the FX-59 semantic-annotation table while it
    holds any row -- mirrors `274aabcc57dd`'s own guard exactly,
    checked BEFORE any destructive DDL runs."""
    bind = op.get_bind()
    row_count: int = bind.execute(sa.text(f"SELECT COUNT(*) FROM {_TABLE}")).scalar_one()
    if row_count > 0:
        raise RuntimeError(
            f"Cannot downgrade migration {revision}: {_TABLE} has {row_count} row(s). "
            "Dropping this table would silently discard real classification-decision "
            "history -- exactly WHEN FTA classified an item, and under which algorithm_"
            "version -- which cannot be reliably reconstructed after the fact. Downgrading "
            "past this migration once real data exists is a permanent limitation, not a "
            "bug -- restore from a backup instead."
        )


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("news_item_key", sa.String(), nullable=False),
        sa.Column("revision_sequence", sa.Integer(), nullable=False),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=False),
        sa.Column("basis_news_item_revision_sequence", sa.Integer(), nullable=False),
        sa.Column("algorithm_version", sa.String(), nullable=False),
        sa.Column("entities", postgresql.JSONB(), nullable=False),
        sa.Column("topics", postgresql.JSONB(), nullable=False),
        sa.Column("currency_relevance", postgresql.JSONB(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "news_item_key",
            "revision_sequence",
            name="uq_nsav_identity",
        ),
        sa.ForeignKeyConstraint(
            ["news_item_key"],
            ["news_items.news_item_key"],
            name="fk_nsav_news_item",
        ),
        sa.ForeignKeyConstraint(
            ["news_item_key", "basis_news_item_revision_sequence"],
            ["news_item_vintages.news_item_key", "news_item_vintages.revision_sequence"],
            name="fk_nsav_basis_vintage",
        ),
        sa.CheckConstraint(
            "revision_sequence >= 0",
            name="ck_nsav_revision_sequence",
        ),
        sa.CheckConstraint(
            "basis_news_item_revision_sequence >= 0",
            name="ck_nsav_basis_news_item_revision_sequence",
        ),
        sa.CheckConstraint(
            "algorithm_version <> ''",
            name="ck_nsav_algorithm_version",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(entities) = 'array'",
            name="ck_nsav_entities_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(topics) = 'array'",
            name="ck_nsav_topics_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(currency_relevance) = 'array'",
            name="ck_nsav_currency_relevance_array",
        ),
        sa.CheckConstraint(
            "jsonb_array_length(entities) > 0",
            name="ck_nsav_entities_nonempty",
        ),
        sa.CheckConstraint(
            "jsonb_array_length(currency_relevance) > 0",
            name="ck_nsav_currency_relevance_nonempty",
        ),
    )
    op.create_index(
        "ix_nsav_item_availability",
        _TABLE,
        ["news_item_key", "availability", "revision_sequence"],
        unique=False,
    )


def downgrade() -> None:
    _raise_if_downgrade_would_lose_data()

    op.drop_index("ix_nsav_item_availability", table_name=_TABLE)
    op.drop_table(_TABLE)

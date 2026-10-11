"""add news canonical relation vintages

FX-58: one new table, `news_canonical_relation_vintages` -- the
derived, append-only PIT evidence layer recording whether FTA
believes a PAIR of source-native `NewsItem`s represents the SAME
underlying news story. No existing `news_*` table is touched, mutated,
or gains a new column -- canonicalization never merges NewsItems,
repoints their source mappings, or adds a mutable "canonical item"
pointer anywhere (FX-58 Section 3/4).

Every row pins the exact two `NewsItemVintage`s FTA actually compared
(`left_item_revision_sequence`/`right_item_revision_sequence`, via
genuine composite foreign keys into `news_item_vintages(news_item_
key, revision_sequence)`) rather than copying their content, so a
decision can always be audited against the exact evidence that
produced it.

Downgrade is GUARDED from the start (the same precedent `504030474987`
itself already established for the three original FX-56 news
tables): once this table holds a row, dropping it would silently
discard real canonicalization-decision history (exactly WHEN FTA
decided two items were, or were not, the same story) that cannot be
reliably reconstructed from the source NewsItems alone. `downgrade()`
refuses with a clear `RuntimeError` naming the row count if the table
is non-empty; proceeds normally when it is genuinely empty.

Revision ID: 274aabcc57dd
Revises: 73b1423a5949
Create Date: 2026-10-11 00:59:45.965302

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "274aabcc57dd"
down_revision: str | None = "73b1423a5949"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "news_canonical_relation_vintages"


def _raise_if_downgrade_would_lose_data() -> None:
    """Refuses to drop the FX-58 canonical-relation table while it
    holds any row -- mirrors `504030474987`'s own guard exactly,
    checked BEFORE any destructive DDL runs."""
    bind = op.get_bind()
    row_count: int = bind.execute(sa.text(f"SELECT COUNT(*) FROM {_TABLE}")).scalar_one()
    if row_count > 0:
        raise RuntimeError(
            f"Cannot downgrade migration {revision}: {_TABLE} has {row_count} row(s). "
            "Dropping this table would silently discard real canonicalization-decision "
            "history -- exactly WHEN FTA decided a pair of NewsItems was, or was not, the "
            "same underlying story -- which cannot be reliably reconstructed from the "
            "source NewsItems alone after the fact. Downgrading past this migration once "
            "real data exists is a permanent limitation, not a bug -- restore from a "
            "backup instead."
        )


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("left_news_item_key", sa.String(), nullable=False),
        sa.Column("right_news_item_key", sa.String(), nullable=False),
        sa.Column("revision_sequence", sa.Integer(), nullable=False),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=False),
        sa.Column("relation_kind", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("left_item_revision_sequence", sa.Integer(), nullable=False),
        sa.Column("right_item_revision_sequence", sa.Integer(), nullable=False),
        sa.Column("algorithm_version", sa.String(), nullable=False),
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
            "left_news_item_key",
            "right_news_item_key",
            "revision_sequence",
            name="uq_ncrv_identity",
        ),
        sa.ForeignKeyConstraint(
            ["left_news_item_key"],
            ["news_items.news_item_key"],
            name="fk_ncrv_left_item",
        ),
        sa.ForeignKeyConstraint(
            ["right_news_item_key"],
            ["news_items.news_item_key"],
            name="fk_ncrv_right_item",
        ),
        sa.ForeignKeyConstraint(
            ["left_news_item_key", "left_item_revision_sequence"],
            ["news_item_vintages.news_item_key", "news_item_vintages.revision_sequence"],
            name="fk_ncrv_left_vintage",
        ),
        sa.ForeignKeyConstraint(
            ["right_news_item_key", "right_item_revision_sequence"],
            ["news_item_vintages.news_item_key", "news_item_vintages.revision_sequence"],
            name="fk_ncrv_right_vintage",
        ),
        sa.CheckConstraint(
            "left_news_item_key < right_news_item_key",
            name="ck_ncrv_left_lt_right",
        ),
        sa.CheckConstraint(
            "revision_sequence >= 0",
            name="ck_ncrv_revision_sequence",
        ),
        sa.CheckConstraint(
            "left_item_revision_sequence >= 0",
            name="ck_ncrv_left_item_revision_sequence",
        ),
        sa.CheckConstraint(
            "right_item_revision_sequence >= 0",
            name="ck_ncrv_right_item_revision_sequence",
        ),
        sa.CheckConstraint(
            "relation_kind IN ('SAME_STORY', 'NOT_SAME_STORY')",
            name="ck_ncrv_relation_kind",
        ),
        sa.CheckConstraint(
            "method IN ('EXACT_CANONICAL_URL', 'EXACT_BODY_TEXT', 'EXACT_HEADLINE_AND_SUMMARY', "
            "'MANUAL_REVIEW')",
            name="ck_ncrv_method",
        ),
        sa.CheckConstraint(
            "method NOT IN ('EXACT_CANONICAL_URL', 'EXACT_BODY_TEXT', "
            "'EXACT_HEADLINE_AND_SUMMARY') OR relation_kind = 'SAME_STORY'",
            name="ck_ncrv_automatic_method_is_same_story",
        ),
        sa.CheckConstraint(
            "relation_kind <> 'NOT_SAME_STORY' OR method = 'MANUAL_REVIEW'",
            name="ck_ncrv_not_same_story_is_manual_review",
        ),
        sa.CheckConstraint(
            "algorithm_version <> ''",
            name="ck_ncrv_algorithm_version",
        ),
    )
    op.create_index(
        "ix_ncrv_pair_availability",
        _TABLE,
        ["left_news_item_key", "right_news_item_key", "availability"],
        unique=False,
    )


def downgrade() -> None:
    _raise_if_downgrade_would_lose_data()

    op.drop_index("ix_ncrv_pair_availability", table_name=_TABLE)
    op.drop_table(_TABLE)

"""add news evidence tables

FX-56: the point-in-time news evidence model's own three tables --
`news_items` (FTA's own internal item identity), `news_source_
mappings` (the persisted `(source_key, external_item_id) ->
news_item_key` association, registered atomically by
`SqlAlchemyNewsRepository.register_source_item` -- see that
repository's own module docstring for why this table's FK is
satisfiable from its very first row, unlike `economic_event_source_
mappings`' own FK, which needed a later migration), and `news_item_
vintages` (every immutable, point-in-time-safe news fact, append-only).

Downgrade is GUARDED from the start (learning directly from FX-51H.1/
FX-52AH.1's own correction, rather than shipping unguarded and fixing
it later): once any of these three tables holds a row, dropping them
would silently discard real point-in-time evidence (which external
identities already resolved to which internal items, and every
observed revision history) that cannot be reconstructed after the
fact. `downgrade()` refuses with a clear `RuntimeError` naming the
row counts if any of the three tables is non-empty; proceeds normally
when all three are genuinely empty.

Revision ID: 504030474987
Revises: ecdb152af0a8
Create Date: 2026-10-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "504030474987"
down_revision: str | None = "ecdb152af0a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("news_item_vintages", "news_source_mappings", "news_items")


def _raise_if_downgrade_would_lose_data() -> None:
    """Refuses to drop any of the three FX-56 news tables while any of
    them holds a row -- mirrors `df99b7796566`'s own (FX-52AH.1-added)
    guard exactly, checked BEFORE any destructive DDL runs."""
    bind = op.get_bind()
    row_counts: dict[str, int] = {
        table: bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        for table in _TABLES
    }
    non_empty = {table: count for table, count in row_counts.items() if count > 0}
    if non_empty:
        details = ", ".join(f"{table}={count} row(s)" for table, count in non_empty.items())
        raise RuntimeError(
            f"Cannot downgrade migration 504030474987: {details}. Dropping these tables "
            "would silently discard real point-in-time news evidence -- every resolved "
            "(source_key, external_item_id) -> news_item_key identity mapping and every "
            "observed vintage history -- none of which can be reconstructed after the "
            "fact (FTA's own first-seen/availability timestamps are not recoverable from "
            "any source re-poll). Downgrading past this migration once real data exists "
            "is a permanent limitation, not a bug -- restore from a backup instead."
        )


def upgrade() -> None:
    op.create_table(
        "news_items",
        sa.Column("news_item_key", sa.String(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_observation_mode", sa.String(), nullable=False),
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
        sa.UniqueConstraint("news_item_key", name="uq_news_items_news_item_key"),
    )

    op.create_table(
        "news_source_mappings",
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("external_item_id", sa.String(), nullable=False),
        sa.Column("news_item_key", sa.String(), nullable=False),
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
            "source_key", "external_item_id", name="uq_news_source_mappings_identity"
        ),
        sa.UniqueConstraint("news_item_key", name="uq_news_source_mappings_news_item_key"),
        sa.ForeignKeyConstraint(
            ["news_item_key"],
            ["news_items.news_item_key"],
            name="fk_news_source_mappings_news_item",
        ),
    )

    op.create_table(
        "news_item_vintages",
        sa.Column("news_item_key", sa.String(), nullable=False),
        sa.Column("revision_sequence", sa.Integer(), nullable=False),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_mode", sa.String(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("canonical_url", sa.String(), nullable=True),
        sa.Column(
            "authors",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("source_content_type", sa.String(), nullable=True),
        sa.Column("source_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source_timestamp_provenance",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "source_revision_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("source_status", sa.String(), nullable=False),
        sa.Column("evidence_disposition", sa.String(), nullable=False),
        sa.Column("quarantine_reason", sa.String(), nullable=True),
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
            "news_item_key", "revision_sequence", name="uq_news_item_vintages_identity"
        ),
        sa.ForeignKeyConstraint(
            ["news_item_key"],
            ["news_items.news_item_key"],
            name="fk_news_item_vintages_news_item",
        ),
        sa.CheckConstraint(
            "(evidence_disposition = 'QUARANTINED') = (quarantine_reason IS NOT NULL)",
            name="ck_news_item_vintages_quarantine_reason",
        ),
    )
    op.create_index(
        "ix_news_item_vintages_item_availability",
        "news_item_vintages",
        ["news_item_key", "availability"],
        unique=False,
    )


def downgrade() -> None:
    _raise_if_downgrade_would_lose_data()

    op.drop_index("ix_news_item_vintages_item_availability", table_name="news_item_vintages")
    op.drop_table("news_item_vintages")
    op.drop_table("news_source_mappings")
    op.drop_table("news_items")

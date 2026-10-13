"""add intelligence source registry

FX-62: three new tables establishing FTA's own durable source
identity and attribution registry -- `intelligence_sources` (durable,
minimal identity -- `source_key`/`source_kind`/`registered_at`,
written exactly once per source), `source_identity_vintages` (append-
only evolving identity knowledge: display name, aliases, website,
evidence), and `source_attribution_vintages` (append-only, per-
`(news_item_key, role)` attribution linking a NewsItem to an
identified actor -- PUBLISHER/ORIGINATING_CLAIMANT/QUOTED_ACTOR).

No existing `news_*` table is touched, mutated, or gains a new
column -- this registry is additive evidence, read-only with respect
to FX-56/57/58/59's own tables (`source_attribution_vintages` carries
composite foreign keys INTO `news_items`/`news_item_vintages`, never
the reverse).

Downgrade is GUARDED from the start (the same precedent `4b2621787a37`
itself already established for FX-59's own semantic-annotation table,
following `274aabcc57dd`'s original FX-58 precedent before it): once
any of these three tables holds a row, dropping it would silently
discard real identity/attribution-decision history that cannot be
reliably reconstructed after the fact. `downgrade()` refuses with a
clear `RuntimeError` naming each non-empty table's own row count;
proceeds normally only when all three are genuinely empty.

Revision ID: e23aac921014
Revises: 4b2621787a37
Create Date: 2026-10-13 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e23aac921014"
down_revision: str | None = "4b2621787a37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCES_TABLE = "intelligence_sources"
_IDENTITY_VINTAGES_TABLE = "source_identity_vintages"
_ATTRIBUTION_VINTAGES_TABLE = "source_attribution_vintages"


def _raise_if_downgrade_would_lose_data() -> None:
    """Refuses to drop any FX-62 table while it holds a row -- mirrors
    `4b2621787a37`'s own guard exactly, checked BEFORE any destructive
    DDL runs."""
    bind = op.get_bind()
    non_empty: list[tuple[str, int]] = []
    # Attribution/identity vintages are checked before the parent
    # `intelligence_sources` table, mirroring the FK-dependency order
    # the downgrade itself must follow.
    for table in (_ATTRIBUTION_VINTAGES_TABLE, _IDENTITY_VINTAGES_TABLE, _SOURCES_TABLE):
        row_count: int = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        if row_count > 0:
            non_empty.append((table, row_count))
    if non_empty:
        details = ", ".join(f"{table}={count}" for table, count in non_empty)
        raise RuntimeError(
            f"Cannot downgrade migration {revision}: non-empty table(s) found ({details}). "
            "Dropping these tables would silently discard real source-identity and "
            "attribution-decision history -- exactly WHEN and WHY FTA recorded an identity or "
            "attribution -- which cannot be reliably reconstructed after the fact. Downgrading "
            "past this migration once real data exists is a permanent limitation, not a bug -- "
            "restore from a backup instead."
        )


def upgrade() -> None:
    op.create_table(
        _SOURCES_TABLE,
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.UniqueConstraint("source_key", name="uq_intelligence_sources_source_key"),
        sa.CheckConstraint(
            "source_kind IN ('ORGANIZATION', 'PERSON', 'PUBLICATION', 'TECHNICAL_FEED')",
            name="ck_intelligence_sources_source_kind",
        ),
    )

    op.create_table(
        _IDENTITY_VINTAGES_TABLE,
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("revision_sequence", sa.Integer(), nullable=False),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("aliases", postgresql.JSONB(), nullable=False),
        sa.Column("authoritative_identifier", sa.String(), nullable=True),
        sa.Column("canonical_website", sa.String(), nullable=True),
        sa.Column("evidence_kind", sa.String(), nullable=False),
        sa.Column("evidence_description", sa.String(), nullable=False),
        sa.Column("correction_reason", sa.String(), nullable=True),
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
        sa.UniqueConstraint("source_key", "revision_sequence", name="uq_siv_identity"),
        sa.ForeignKeyConstraint(
            ["source_key"],
            ["intelligence_sources.source_key"],
            name="fk_siv_source",
        ),
        sa.CheckConstraint("revision_sequence >= 0", name="ck_siv_revision_sequence"),
        sa.CheckConstraint("algorithm_version <> ''", name="ck_siv_algorithm_version"),
        sa.CheckConstraint("display_name <> ''", name="ck_siv_display_name"),
        sa.CheckConstraint("jsonb_typeof(aliases) = 'array'", name="ck_siv_aliases_array"),
        sa.CheckConstraint(
            "evidence_kind IN "
            "('ADAPTER_CONFIGURATION', 'SOURCE_NATIVE_METADATA', "
            "'AUTHORITATIVE_REFERENCE', 'MANUAL_REVIEW')",
            name="ck_siv_evidence_kind",
        ),
        sa.CheckConstraint("evidence_description <> ''", name="ck_siv_evidence_description"),
    )
    op.create_index(
        "ix_siv_source_availability",
        _IDENTITY_VINTAGES_TABLE,
        ["source_key", "availability", "revision_sequence"],
        unique=False,
    )

    op.create_table(
        _ATTRIBUTION_VINTAGES_TABLE,
        sa.Column("news_item_key", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("revision_sequence", sa.Integer(), nullable=False),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attributed_source_key", sa.String(), nullable=True),
        sa.Column("evidence_basis_revision_sequence", sa.Integer(), nullable=False),
        sa.Column("evidence_kind", sa.String(), nullable=False),
        sa.Column("evidence_description", sa.String(), nullable=False),
        sa.Column("corrects_revision_sequence", sa.Integer(), nullable=True),
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
        sa.UniqueConstraint("news_item_key", "role", "revision_sequence", name="uq_sav_identity"),
        sa.ForeignKeyConstraint(
            ["news_item_key"],
            ["news_items.news_item_key"],
            name="fk_sav_news_item",
        ),
        sa.ForeignKeyConstraint(
            ["news_item_key", "evidence_basis_revision_sequence"],
            ["news_item_vintages.news_item_key", "news_item_vintages.revision_sequence"],
            name="fk_sav_basis_vintage",
        ),
        sa.ForeignKeyConstraint(
            ["attributed_source_key"],
            ["intelligence_sources.source_key"],
            name="fk_sav_attributed_source",
        ),
        sa.CheckConstraint("revision_sequence >= 0", name="ck_sav_revision_sequence"),
        sa.CheckConstraint(
            "evidence_basis_revision_sequence >= 0",
            name="ck_sav_evidence_basis_revision_sequence",
        ),
        sa.CheckConstraint("algorithm_version <> ''", name="ck_sav_algorithm_version"),
        sa.CheckConstraint(
            "role IN ('PUBLISHER', 'ORIGINATING_CLAIMANT', 'QUOTED_ACTOR')",
            name="ck_sav_role",
        ),
        sa.CheckConstraint("status IN ('CONFIRMED', 'UNRESOLVED')", name="ck_sav_status"),
        sa.CheckConstraint(
            "(status = 'CONFIRMED' AND attributed_source_key IS NOT NULL) OR "
            "(status = 'UNRESOLVED' AND attributed_source_key IS NULL)",
            name="ck_sav_status_source_key_consistency",
        ),
        sa.CheckConstraint(
            "evidence_kind IN "
            "('ADAPTER_CONFIGURATION', 'SOURCE_NATIVE_METADATA', "
            "'AUTHORITATIVE_REFERENCE', 'MANUAL_REVIEW')",
            name="ck_sav_evidence_kind",
        ),
        sa.CheckConstraint("evidence_description <> ''", name="ck_sav_evidence_description"),
        sa.CheckConstraint(
            "corrects_revision_sequence IS NULL OR corrects_revision_sequence < revision_sequence",
            name="ck_sav_corrects_revision_sequence",
        ),
    )
    op.create_index(
        "ix_sav_item_role_availability",
        _ATTRIBUTION_VINTAGES_TABLE,
        ["news_item_key", "role", "availability", "revision_sequence"],
        unique=False,
    )


def downgrade() -> None:
    _raise_if_downgrade_would_lose_data()

    op.drop_index("ix_sav_item_role_availability", table_name=_ATTRIBUTION_VINTAGES_TABLE)
    op.drop_table(_ATTRIBUTION_VINTAGES_TABLE)
    op.drop_index("ix_siv_source_availability", table_name=_IDENTITY_VINTAGES_TABLE)
    op.drop_table(_IDENTITY_VINTAGES_TABLE)
    op.drop_table(_SOURCES_TABLE)

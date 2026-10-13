"""add structured forecast registry

FX-64: two new tables establishing FTA's own immutable, point-in-time-
safe structured forecast registry -- `forecast_claims` (durable,
minimal identity, mirroring FX-62's own `intelligence_sources` shape)
and `structured_forecast_vintages` (append-only, every FX-64 value
object -- target period, attribution, evidence -- flattened directly
onto this one table, mirroring FX-62's own vintage flattening
convention).

No existing table is touched, mutated, or gains a new column.
`structured_forecast_vintages` carries FOUR foreign keys onto already-
approved tables, all read-only with respect to them: `claim_key` onto
`forecast_claims`, `publisher_source_key`/`forecaster_source_key`
(nullable) onto `intelligence_sources` (FX-62 reuse, never a new
identity mapping), and the COMPOSITE `(news_item_key, basis_revision_
sequence)` onto `news_item_vintages` (FX-56/59/62's own basis-pinning
convention, automatically satisfied/skipped by Postgres whenever
either column is NULL -- the external-document-evidence case).

Downgrade is GUARDED from the start, mirroring `e23aac921014`/
`d8995cb04276`'s own precedent exactly: once either table holds a
row, dropping it would silently discard real forecast-provenance
history that cannot be reliably reconstructed after the fact.

Revision ID: afb65123d185
Revises: d8995cb04276
Create Date: 2026-10-13 18:03:57.105962

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "afb65123d185"
down_revision: str | None = "d8995cb04276"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLAIMS_TABLE = "forecast_claims"
_VINTAGES_TABLE = "structured_forecast_vintages"


def _raise_if_downgrade_would_lose_data() -> None:
    bind = op.get_bind()
    non_empty: list[tuple[str, int]] = []
    for table in (_VINTAGES_TABLE, _CLAIMS_TABLE):
        row_count: int = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        if row_count > 0:
            non_empty.append((table, row_count))
    if non_empty:
        details = ", ".join(f"{table}={count}" for table, count in non_empty)
        raise RuntimeError(
            f"Cannot downgrade migration {revision}: non-empty table(s) found ({details}). "
            "Dropping these tables would silently discard real forecast-provenance history -- "
            "exactly WHAT was forecast, by WHOM, and WHEN FTA knew it -- which cannot be "
            "reliably reconstructed after the fact. Downgrading past this migration once real "
            "data exists is a permanent limitation, not a bug -- restore from a backup instead."
        )


def upgrade() -> None:
    op.create_table(
        _CLAIMS_TABLE,
        sa.Column("claim_key", sa.String(), nullable=False),
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
        sa.UniqueConstraint("claim_key", name="uq_forecast_claims_claim_key"),
        sa.CheckConstraint("claim_key <> ''", name="ck_forecast_claims_claim_key"),
    )

    op.create_table(
        _VINTAGES_TABLE,
        sa.Column("claim_key", sa.String(), nullable=False),
        sa.Column("revision_sequence", sa.Integer(), nullable=False),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(), nullable=False),
        sa.Column("forecast_type", sa.String(), nullable=False),
        sa.Column("target_key", sa.String(), nullable=False),
        sa.Column("target_period_kind", sa.String(), nullable=False),
        sa.Column("calendar_year", sa.Integer(), nullable=True),
        sa.Column("calendar_quarter", sa.Integer(), nullable=True),
        sa.Column("calendar_month", sa.Integer(), nullable=True),
        sa.Column("specific_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("policy_meeting_identifier", sa.String(), nullable=True),
        sa.Column("numeric_value", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("categorical_outcome", sa.String(), nullable=True),
        sa.Column("attribution_kind", sa.String(), nullable=False),
        sa.Column("publisher_source_key", sa.String(), nullable=False),
        sa.Column("forecaster_source_key", sa.String(), nullable=True),
        sa.Column("anonymous_respondent_id", sa.String(), nullable=True),
        sa.Column("provenance_mode", sa.String(), nullable=False),
        sa.Column("evidence_kind", sa.String(), nullable=False),
        sa.Column("evidence_description", sa.String(), nullable=False),
        sa.Column("news_item_key", sa.String(), nullable=True),
        sa.Column("basis_revision_sequence", sa.Integer(), nullable=True),
        sa.Column("document_identifier", sa.String(), nullable=True),
        sa.Column("document_locator", sa.String(), nullable=True),
        sa.Column("official_reference_url", sa.String(), nullable=True),
        sa.Column("content_fingerprint", sa.String(), nullable=True),
        sa.Column("publisher_declared_publication_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("original_publication_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("claim_key", "revision_sequence", name="uq_sfv_identity"),
        sa.ForeignKeyConstraint(
            ["claim_key"],
            ["forecast_claims.claim_key"],
            name="fk_sfv_claim",
        ),
        sa.ForeignKeyConstraint(
            ["publisher_source_key"],
            ["intelligence_sources.source_key"],
            name="fk_sfv_publisher_source",
        ),
        sa.ForeignKeyConstraint(
            ["forecaster_source_key"],
            ["intelligence_sources.source_key"],
            name="fk_sfv_forecaster_source",
        ),
        sa.ForeignKeyConstraint(
            ["news_item_key", "basis_revision_sequence"],
            ["news_item_vintages.news_item_key", "news_item_vintages.revision_sequence"],
            name="fk_sfv_basis_vintage",
        ),
        sa.CheckConstraint("revision_sequence >= 0", name="ck_sfv_revision_sequence"),
        sa.CheckConstraint("algorithm_version <> ''", name="ck_sfv_algorithm_version"),
        sa.CheckConstraint("target_key <> ''", name="ck_sfv_target_key"),
        sa.CheckConstraint(
            "forecast_type IN ('NUMERIC_POINT', 'CATEGORICAL_EVENT')",
            name="ck_sfv_forecast_type",
        ),
        sa.CheckConstraint(
            "(forecast_type = 'NUMERIC_POINT' AND numeric_value IS NOT NULL AND unit IS NOT "
            "NULL AND categorical_outcome IS NULL) OR "
            "(forecast_type = 'CATEGORICAL_EVENT' AND categorical_outcome IS NOT NULL AND "
            "numeric_value IS NULL AND unit IS NULL)",
            name="ck_sfv_payload_shape",
        ),
        sa.CheckConstraint(
            "target_period_kind IN "
            "('CALENDAR_YEAR', 'CALENDAR_QUARTER', 'CALENDAR_MONTH', 'SPECIFIC_DATE', "
            "'POLICY_MEETING')",
            name="ck_sfv_target_period_kind",
        ),
        sa.CheckConstraint(
            "attribution_kind IN "
            "('NAMED_INSTITUTION', 'AGGREGATE_SURVEY_CONSENSUS', 'ANONYMOUS_RESPONDENT')",
            name="ck_sfv_attribution_kind",
        ),
        sa.CheckConstraint(
            "(attribution_kind = 'NAMED_INSTITUTION' AND forecaster_source_key IS NOT NULL "
            "AND anonymous_respondent_id IS NULL) OR "
            "(attribution_kind = 'AGGREGATE_SURVEY_CONSENSUS' AND forecaster_source_key IS "
            "NULL AND anonymous_respondent_id IS NULL) OR "
            "(attribution_kind = 'ANONYMOUS_RESPONDENT' AND forecaster_source_key IS NULL)",
            name="ck_sfv_attribution_shape",
        ),
        sa.CheckConstraint("publisher_source_key <> ''", name="ck_sfv_publisher_source_key"),
        sa.CheckConstraint(
            "evidence_kind IN ('NEWS_ITEM_VINTAGE_BASIS', 'EXTERNAL_DOCUMENT_REFERENCE')",
            name="ck_sfv_evidence_kind",
        ),
        sa.CheckConstraint("evidence_description <> ''", name="ck_sfv_evidence_description"),
        sa.CheckConstraint(
            "(evidence_kind = 'NEWS_ITEM_VINTAGE_BASIS' AND news_item_key IS NOT NULL AND "
            "basis_revision_sequence IS NOT NULL AND document_identifier IS NULL) OR "
            "(evidence_kind = 'EXTERNAL_DOCUMENT_REFERENCE' AND document_identifier IS NOT "
            "NULL AND news_item_key IS NULL AND basis_revision_sequence IS NULL)",
            name="ck_sfv_evidence_shape",
        ),
    )
    op.create_index(
        "ix_sfv_claim_availability",
        _VINTAGES_TABLE,
        ["claim_key", "availability", "revision_sequence"],
        unique=False,
    )
    op.create_index(
        "ix_sfv_target_availability",
        _VINTAGES_TABLE,
        ["target_key", "availability"],
        unique=False,
    )


def downgrade() -> None:
    _raise_if_downgrade_would_lose_data()

    op.drop_index("ix_sfv_target_availability", table_name=_VINTAGES_TABLE)
    op.drop_index("ix_sfv_claim_availability", table_name=_VINTAGES_TABLE)
    op.drop_table(_VINTAGES_TABLE)
    op.drop_table(_CLAIMS_TABLE)

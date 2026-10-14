"""add forecast outcome and evaluation tables

FX-65: four new tables giving FTA a point-in-time-safe forecast
OUTCOME-ADJUDICATION registry, layered on top of FX-64's own
structured forecast capture/provenance registry without touching it:

- `forecast_outcome_definitions` -- append-only outcome-definition
  versions (HOW an outcome is measured), single-table-per-concept
  (mirroring `macro_observation_vintages`'s own simpler precedent,
  rather than FX-62/64's claim+vintage split -- this concept needs no
  `registered_at` distinct from version 0's own `availability`).
- `forecast_outcome_vintages` -- append-only outcome observations
  (WHAT was actually observed), mirroring `structured_forecast_
  vintages`'s own flattening convention.
- `forecast_evaluation_protocols` -- append-only evaluation-protocol
  versions (the frozen evaluation question, decided BEFORE outcomes
  are selected).
- `structured_forecast_evaluation_vintages` -- append-only evaluation
  results, with genuine composite foreign keys pinning the EXACT
  forecast claim vintage, protocol version, outcome definition
  version, and outcome vintage each evaluation used.

No existing table is touched, mutated, or gains a new column.
`structured_forecast_vintages` (FX-64) gains a REFERENCING foreign key
(from the new evaluation table) but is itself read-only with respect
to this migration.

Downgrade is GUARDED from the start, mirroring every prior FX-56+
migration's own precedent exactly.

Revision ID: 0829067d81ae
Revises: afb65123d185
Create Date: 2026-10-13 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0829067d81ae"
down_revision: str | None = "afb65123d185"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OUTCOME_DEFINITIONS_TABLE = "forecast_outcome_definitions"
_OUTCOME_VINTAGES_TABLE = "forecast_outcome_vintages"
_EVALUATION_PROTOCOLS_TABLE = "forecast_evaluation_protocols"
_EVALUATION_VINTAGES_TABLE = "structured_forecast_evaluation_vintages"

_ALL_TABLES = (
    _EVALUATION_VINTAGES_TABLE,
    _EVALUATION_PROTOCOLS_TABLE,
    _OUTCOME_VINTAGES_TABLE,
    _OUTCOME_DEFINITIONS_TABLE,
)


def _raise_if_downgrade_would_lose_data() -> None:
    bind = op.get_bind()
    non_empty: list[tuple[str, int]] = []
    for table in _ALL_TABLES:
        row_count: int = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        if row_count > 0:
            non_empty.append((table, row_count))
    if non_empty:
        details = ", ".join(f"{table}={count}" for table, count in non_empty)
        raise RuntimeError(
            f"Cannot downgrade migration {revision}: non-empty table(s) found ({details}). "
            "Dropping these tables would silently discard real outcome/evaluation history -- "
            "exactly WHAT was observed and HOW each forecast was evaluated -- which cannot be "
            "reliably reconstructed after the fact. Downgrading past this migration once real "
            "data exists is a permanent limitation, not a bug -- restore from a backup instead."
        )


def upgrade() -> None:
    op.create_table(
        _OUTCOME_DEFINITIONS_TABLE,
        sa.Column("definition_key", sa.String(), nullable=False),
        sa.Column("version_sequence", sa.Integer(), nullable=False),
        sa.Column("target_key", sa.String(), nullable=False),
        sa.Column("outcome_type", sa.String(), nullable=False),
        sa.Column("provider_source_key", sa.String(), nullable=False),
        sa.Column("required_source_series_identifier", sa.String(), nullable=False),
        sa.Column("outcome_vintage_selection_policy", sa.String(), nullable=False),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supporting_definition_reference", sa.String(), nullable=False),
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
        sa.UniqueConstraint(
            "definition_key", "version_sequence", name="uq_outcome_definition_identity"
        ),
        sa.ForeignKeyConstraint(
            ["provider_source_key"],
            ["intelligence_sources.source_key"],
            name="fk_outcome_definition_provider_source",
        ),
        sa.CheckConstraint("version_sequence >= 0", name="ck_outcome_definition_version_sequence"),
        sa.CheckConstraint("definition_key <> ''", name="ck_outcome_definition_key"),
        sa.CheckConstraint("target_key <> ''", name="ck_outcome_definition_target_key"),
        sa.CheckConstraint(
            "outcome_type IN ('NUMERIC_POINT', 'CATEGORICAL_EVENT')",
            name="ck_outcome_definition_outcome_type",
        ),
        sa.CheckConstraint(
            "outcome_vintage_selection_policy IN "
            "('FIRST_RELEASE', 'LATEST_AVAILABLE_AS_OF', 'FIXED_RELEASE_VINTAGE')",
            name="ck_outcome_definition_selection_policy",
        ),
        sa.CheckConstraint(
            "required_source_series_identifier <> ''",
            name="ck_outcome_definition_series_identifier",
        ),
        sa.CheckConstraint(
            "supporting_definition_reference <> ''",
            name="ck_outcome_definition_supporting_reference",
        ),
    )

    op.create_table(
        _OUTCOME_VINTAGES_TABLE,
        sa.Column("outcome_key", sa.String(), nullable=False),
        sa.Column("revision_sequence", sa.Integer(), nullable=False),
        sa.Column("definition_key", sa.String(), nullable=False),
        sa.Column("definition_version_sequence", sa.Integer(), nullable=False),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_period_kind", sa.String(), nullable=False),
        sa.Column("calendar_year", sa.Integer(), nullable=True),
        sa.Column("calendar_quarter", sa.Integer(), nullable=True),
        sa.Column("calendar_month", sa.Integer(), nullable=True),
        sa.Column("specific_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("policy_meeting_identifier", sa.String(), nullable=True),
        sa.Column("outcome_type", sa.String(), nullable=False),
        sa.Column("numeric_value", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("categorical_outcome", sa.String(), nullable=True),
        sa.Column("evidence_kind", sa.String(), nullable=False),
        sa.Column("evidence_description", sa.String(), nullable=False),
        sa.Column("news_item_key", sa.String(), nullable=True),
        sa.Column("basis_revision_sequence", sa.Integer(), nullable=True),
        sa.Column("document_identifier", sa.String(), nullable=True),
        sa.Column("document_locator", sa.String(), nullable=True),
        sa.Column("official_reference_url", sa.String(), nullable=True),
        sa.Column("content_fingerprint", sa.String(), nullable=True),
        sa.Column("publisher_declared_publication_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(), nullable=False),
        sa.Column("review_method", sa.String(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("corroboration_reference", sa.String(), nullable=True),
        sa.Column("provenance_mode", sa.String(), nullable=False),
        sa.Column("provider_release_identifier", sa.String(), nullable=True),
        sa.Column("provider_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_integrity_reference", sa.String(), nullable=True),
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
        sa.UniqueConstraint("outcome_key", "revision_sequence", name="uq_outcome_vintage_identity"),
        sa.ForeignKeyConstraint(
            ["definition_key", "definition_version_sequence"],
            [
                "forecast_outcome_definitions.definition_key",
                "forecast_outcome_definitions.version_sequence",
            ],
            name="fk_outcome_vintage_definition",
        ),
        sa.ForeignKeyConstraint(
            ["news_item_key", "basis_revision_sequence"],
            ["news_item_vintages.news_item_key", "news_item_vintages.revision_sequence"],
            name="fk_outcome_vintage_basis",
        ),
        sa.CheckConstraint("revision_sequence >= 0", name="ck_outcome_vintage_revision_sequence"),
        sa.CheckConstraint("outcome_key <> ''", name="ck_outcome_vintage_key"),
        sa.CheckConstraint(
            "outcome_type IN ('NUMERIC_POINT', 'CATEGORICAL_EVENT')",
            name="ck_outcome_vintage_type",
        ),
        sa.CheckConstraint(
            "(outcome_type = 'NUMERIC_POINT' AND numeric_value IS NOT NULL AND unit IS NOT "
            "NULL AND categorical_outcome IS NULL) OR "
            "(outcome_type = 'CATEGORICAL_EVENT' AND categorical_outcome IS NOT NULL AND "
            "numeric_value IS NULL AND unit IS NULL)",
            name="ck_outcome_vintage_payload_shape",
        ),
        sa.CheckConstraint(
            "target_period_kind IN "
            "('CALENDAR_YEAR', 'CALENDAR_QUARTER', 'CALENDAR_MONTH', 'SPECIFIC_DATE', "
            "'POLICY_MEETING')",
            name="ck_outcome_vintage_period_kind",
        ),
        sa.CheckConstraint(
            "evidence_kind IN ('NEWS_ITEM_VINTAGE_BASIS', 'EXTERNAL_DOCUMENT_REFERENCE')",
            name="ck_outcome_vintage_evidence_kind",
        ),
        sa.CheckConstraint(
            "evidence_description <> ''", name="ck_outcome_vintage_evidence_description"
        ),
        sa.CheckConstraint(
            "(evidence_kind = 'NEWS_ITEM_VINTAGE_BASIS' AND news_item_key IS NOT NULL AND "
            "basis_revision_sequence IS NOT NULL AND document_identifier IS NULL) OR "
            "(evidence_kind = 'EXTERNAL_DOCUMENT_REFERENCE' AND document_identifier IS NOT "
            "NULL AND news_item_key IS NULL AND basis_revision_sequence IS NULL)",
            name="ck_outcome_vintage_evidence_shape",
        ),
        sa.CheckConstraint(
            "provenance_mode IN ('PRODUCTION_OBSERVED', 'RETROSPECTIVE_RESEARCH')",
            name="ck_outcome_vintage_provenance_mode",
        ),
        sa.CheckConstraint("reviewed_by <> ''", name="ck_outcome_vintage_reviewed_by"),
        sa.CheckConstraint("review_method <> ''", name="ck_outcome_vintage_review_method"),
    )

    op.create_table(
        _EVALUATION_PROTOCOLS_TABLE,
        sa.Column("protocol_key", sa.String(), nullable=False),
        sa.Column("version_sequence", sa.Integer(), nullable=False),
        sa.Column("supported_forecast_type", sa.String(), nullable=False),
        sa.Column("target_key", sa.String(), nullable=False),
        sa.Column("outcome_definition_key", sa.String(), nullable=False),
        sa.Column("outcome_definition_version_sequence", sa.Integer(), nullable=False),
        sa.Column("outcome_vintage_selection_policy", sa.String(), nullable=False),
        sa.Column("fixed_outcome_revision_sequence", sa.Integer(), nullable=True),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
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
        sa.UniqueConstraint(
            "protocol_key", "version_sequence", name="uq_evaluation_protocol_identity"
        ),
        sa.ForeignKeyConstraint(
            ["outcome_definition_key", "outcome_definition_version_sequence"],
            [
                "forecast_outcome_definitions.definition_key",
                "forecast_outcome_definitions.version_sequence",
            ],
            name="fk_evaluation_protocol_outcome_definition",
        ),
        sa.CheckConstraint("version_sequence >= 0", name="ck_evaluation_protocol_version_sequence"),
        sa.CheckConstraint("protocol_key <> ''", name="ck_evaluation_protocol_key"),
        sa.CheckConstraint(
            "supported_forecast_type IN ('NUMERIC_POINT', 'CATEGORICAL_EVENT')",
            name="ck_evaluation_protocol_forecast_type",
        ),
        sa.CheckConstraint("target_key <> ''", name="ck_evaluation_protocol_target_key"),
        sa.CheckConstraint(
            "outcome_definition_key <> ''", name="ck_evaluation_protocol_outcome_definition_key"
        ),
        sa.CheckConstraint(
            "outcome_definition_version_sequence >= 0",
            name="ck_evaluation_protocol_outcome_definition_version",
        ),
        sa.CheckConstraint(
            "outcome_vintage_selection_policy IN "
            "('FIRST_RELEASE', 'LATEST_AVAILABLE_AS_OF', 'FIXED_RELEASE_VINTAGE')",
            name="ck_evaluation_protocol_selection_policy",
        ),
        sa.CheckConstraint(
            "metric IN ('NUMERIC_ERROR', 'CATEGORICAL_MATCH')", name="ck_evaluation_protocol_metric"
        ),
        sa.CheckConstraint(
            "(outcome_vintage_selection_policy = 'FIXED_RELEASE_VINTAGE' AND "
            "fixed_outcome_revision_sequence IS NOT NULL) OR "
            "(outcome_vintage_selection_policy <> 'FIXED_RELEASE_VINTAGE' AND "
            "fixed_outcome_revision_sequence IS NULL)",
            name="ck_evaluation_protocol_fixed_revision_shape",
        ),
        sa.CheckConstraint("rationale <> ''", name="ck_evaluation_protocol_rationale"),
    )

    op.create_table(
        _EVALUATION_VINTAGES_TABLE,
        sa.Column("evaluation_key", sa.String(), nullable=False),
        sa.Column("revision_sequence", sa.Integer(), nullable=False),
        sa.Column("forecast_claim_key", sa.String(), nullable=False),
        sa.Column("forecast_revision_sequence", sa.Integer(), nullable=False),
        sa.Column("protocol_key", sa.String(), nullable=False),
        sa.Column("protocol_version_sequence", sa.Integer(), nullable=False),
        sa.Column("outcome_definition_key", sa.String(), nullable=False),
        sa.Column("outcome_definition_version_sequence", sa.Integer(), nullable=False),
        sa.Column("outcome_key", sa.String(), nullable=False),
        sa.Column("outcome_revision_sequence", sa.Integer(), nullable=False),
        sa.Column("evaluation_mode", sa.String(), nullable=False),
        sa.Column("algorithm_version", sa.String(), nullable=False),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("signed_error", sa.Numeric(), nullable=True),
        sa.Column("absolute_error", sa.Numeric(), nullable=True),
        sa.Column("result_unit", sa.String(), nullable=True),
        sa.Column("categorical_result", sa.String(), nullable=True),
        sa.Column("forecast_reviewed_by", sa.String(), nullable=False),
        sa.Column("forecast_review_method", sa.String(), nullable=False),
        sa.Column("forecast_reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecast_corroboration_reference", sa.String(), nullable=True),
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
        sa.UniqueConstraint("evaluation_key", "revision_sequence", name="uq_evaluation_identity"),
        sa.ForeignKeyConstraint(
            ["forecast_claim_key", "forecast_revision_sequence"],
            [
                "structured_forecast_vintages.claim_key",
                "structured_forecast_vintages.revision_sequence",
            ],
            name="fk_evaluation_forecast_vintage",
        ),
        sa.ForeignKeyConstraint(
            ["protocol_key", "protocol_version_sequence"],
            [
                "forecast_evaluation_protocols.protocol_key",
                "forecast_evaluation_protocols.version_sequence",
            ],
            name="fk_evaluation_protocol_version",
        ),
        sa.ForeignKeyConstraint(
            ["outcome_definition_key", "outcome_definition_version_sequence"],
            [
                "forecast_outcome_definitions.definition_key",
                "forecast_outcome_definitions.version_sequence",
            ],
            name="fk_evaluation_outcome_definition",
        ),
        sa.ForeignKeyConstraint(
            ["outcome_key", "outcome_revision_sequence"],
            [
                "forecast_outcome_vintages.outcome_key",
                "forecast_outcome_vintages.revision_sequence",
            ],
            name="fk_evaluation_outcome_vintage",
        ),
        sa.CheckConstraint("revision_sequence >= 0", name="ck_evaluation_revision_sequence"),
        sa.CheckConstraint("evaluation_key <> ''", name="ck_evaluation_key"),
        sa.CheckConstraint(
            "evaluation_mode IN ('PRODUCTION_OBSERVED', 'RETROSPECTIVE_RESEARCH')",
            name="ck_evaluation_mode",
        ),
        sa.CheckConstraint("algorithm_version <> ''", name="ck_evaluation_algorithm_version"),
        sa.CheckConstraint(
            "metric IN ('NUMERIC_ERROR', 'CATEGORICAL_MATCH')", name="ck_evaluation_metric"
        ),
        sa.CheckConstraint(
            "(metric = 'NUMERIC_ERROR' AND signed_error IS NOT NULL AND absolute_error IS NOT "
            "NULL AND result_unit IS NOT NULL AND categorical_result IS NULL) OR "
            "(metric = 'CATEGORICAL_MATCH' AND categorical_result IS NOT NULL AND "
            "signed_error IS NULL AND absolute_error IS NULL AND result_unit IS NULL)",
            name="ck_evaluation_result_shape",
        ),
        sa.CheckConstraint(
            "categorical_result IS NULL OR categorical_result IN ('MATCH', 'MISMATCH')",
            name="ck_evaluation_categorical_result",
        ),
        sa.CheckConstraint("forecast_reviewed_by <> ''", name="ck_evaluation_reviewed_by"),
        sa.CheckConstraint("forecast_review_method <> ''", name="ck_evaluation_review_method"),
    )
    op.create_index(
        "ix_evaluation_key_availability",
        _EVALUATION_VINTAGES_TABLE,
        ["evaluation_key", "availability", "revision_sequence"],
        unique=False,
    )


def downgrade() -> None:
    _raise_if_downgrade_would_lose_data()

    op.drop_index("ix_evaluation_key_availability", table_name=_EVALUATION_VINTAGES_TABLE)
    op.drop_table(_EVALUATION_VINTAGES_TABLE)
    op.drop_table(_EVALUATION_PROTOCOLS_TABLE)
    op.drop_table(_OUTCOME_VINTAGES_TABLE)
    op.drop_table(_OUTCOME_DEFINITIONS_TABLE)

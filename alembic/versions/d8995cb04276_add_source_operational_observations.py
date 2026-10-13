"""add source operational observations

FX-63: one new table, `source_operational_observations`, recording
FTA's own forward-looking acquisition-attempt observations (Section
4) -- deliberately independent of every other table: no foreign key
onto `intelligence_sources` (acquisition instrumentation must keep
working regardless of FX-62's own bootstrap state, Section 5), and no
revision/correction concept at all (unlike every FX-56/58/59/62
vintage table) -- a retried attempt is simply another row, identified
by the stable natural key `(source_key, run_id, attempt_number)`.

No existing table is touched, mutated, or gains a new column.

Downgrade is GUARDED from the start, mirroring `e23aac921014`'s own
precedent exactly: once this table holds a row, dropping it would
silently discard real acquisition-attempt history that cannot be
reliably reconstructed after the fact.

Revision ID: d8995cb04276
Revises: e23aac921014
Create Date: 2026-10-13 15:08:45.937952

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8995cb04276"
down_revision: str | None = "e23aac921014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "source_operational_observations"


def _raise_if_downgrade_would_lose_data() -> None:
    bind = op.get_bind()
    row_count: int = bind.execute(sa.text(f"SELECT COUNT(*) FROM {_TABLE}")).scalar_one()
    if row_count > 0:
        raise RuntimeError(
            f"Cannot downgrade migration {revision}: {_TABLE} has {row_count} row(s). "
            "Dropping this table would silently discard real FTA acquisition-attempt "
            "history -- exactly WHEN and WHAT FTA observed when retrieving a feed -- which "
            "cannot be reliably reconstructed after the fact. Downgrading past this "
            "migration once real data exists is a permanent limitation, not a bug -- "
            "restore from a backup instead."
        )


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("source_channel", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("policy_version", sa.String(), nullable=False),
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
        sa.UniqueConstraint("source_key", "run_id", "attempt_number", name="uq_soo_natural_key"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_soo_attempt_number"),
        sa.CheckConstraint("source_key <> ''", name="ck_soo_source_key"),
        sa.CheckConstraint("source_channel <> ''", name="ck_soo_source_channel"),
        sa.CheckConstraint("run_id <> ''", name="ck_soo_run_id"),
        sa.CheckConstraint("kind IN ('ACQUISITION_ATTEMPT')", name="ck_soo_kind"),
        sa.CheckConstraint(
            "outcome IN ('SUCCESS', 'HTTP_FAILURE', 'TIMEOUT', 'NETWORK_FAILURE')",
            name="ck_soo_outcome",
        ),
        sa.CheckConstraint(
            "http_status IS NULL OR (http_status >= 100 AND http_status <= 599)",
            name="ck_soo_http_status",
        ),
        sa.CheckConstraint("policy_version <> ''", name="ck_soo_policy_version"),
    )
    op.create_index(
        "ix_soo_source_availability",
        _TABLE,
        ["source_key", "availability"],
        unique=False,
    )


def downgrade() -> None:
    _raise_if_downgrade_would_lose_data()

    op.drop_index("ix_soo_source_availability", table_name=_TABLE)
    op.drop_table(_TABLE)

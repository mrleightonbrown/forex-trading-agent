"""harden economic event identity and add release vintage

FX-51H: replaces `(indicator_key, reference_period)` as
`economic_event_occurrences`' own identity with a single stable
`occurrence_key` column (unique, not null) -- an occurrence's identity
must not depend on a reference period that may not exist at all for a
qualitative/irregular event (an FOMC press conference, meeting
minutes). `reference_period` becomes nullable for exactly that reason.
Every vintage table (`economic_event_schedule_vintages`/
`_consensus_vintages`/`_actual_value_vintages`) is re-keyed from
`(indicator_key, reference_period, revision_sequence)` onto
`(occurrence_key, revision_sequence)`, with `indicator_key`/
`reference_period` dropped from each (no longer needed there --
looked up via the occurrence itself when required). A new table,
`economic_event_release_vintages`, is added: the provider-neutral
"this occurrence actually happened" fact, independent of whether a
numeric value exists for it (see `domain.economic_event_release_
vintage.EconomicEventReleaseVintage`).

This migration adds every new/re-keyed column as NOT NULL directly,
without an intermediate nullable-then-backfill step, because all four
affected tables were verified EMPTY (`SELECT COUNT(*)` = 0 on each)
immediately before this migration was written -- FX-51 never populated
real or test data beyond a smoke test whose rows were deleted in the
same session. This is not a general-purpose backfill-safe migration
pattern; it is only correct because of that verified precondition.

Object-creation order matters here beyond what autogenerate produced:
a `FOREIGN KEY` requires the referenced columns' unique constraint to
already exist, so `economic_event_occurrences.occurrence_key` and its
own unique constraint are created and established FIRST, before any
vintage table's FK is repointed at it or the new release-vintage table
(which also FKs onto it) is created. Downgrade reverses this ordering
symmetrically -- the release-vintage table (and any FK depending on
`occurrence_key`) is dropped before that column/constraint itself is
removed from `economic_event_occurrences`.

Revision ID: 76a4b23b2129
Revises: bb7551fcef3a
Create Date: 2026-09-26 01:58:10.810329

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "76a4b23b2129"
down_revision: str | None = "bb7551fcef3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VINTAGE_TABLES = (
    "economic_event_schedule_vintages",
    "economic_event_consensus_vintages",
    "economic_event_actual_value_vintages",
)


def upgrade() -> None:
    # --- 1a. Drop every vintage table's OLD FK first -- each one depends on
    #         occurrences' OLD unique constraint, so that constraint cannot
    #         be dropped while any of them still exist.
    for table in _VINTAGE_TABLES:
        op.drop_constraint(f"fk_{table}_occurrence", table, type_="foreignkey")

    # --- 1b. Occurrences: establish occurrence_key as identity ---------------
    op.add_column(
        "economic_event_occurrences", sa.Column("occurrence_key", sa.String(), nullable=False)
    )
    op.drop_constraint(
        "uq_economic_event_occurrences_indicator_reference_period",
        "economic_event_occurrences",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_economic_event_occurrences_occurrence_key",
        "economic_event_occurrences",
        ["occurrence_key"],
    )
    op.alter_column(
        "economic_event_occurrences",
        "reference_period",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=True,
    )

    # --- 2. Re-key every existing vintage table onto occurrence_key ---------
    for table in _VINTAGE_TABLES:
        op.add_column(table, sa.Column("occurrence_key", sa.String(), nullable=False))
        op.drop_constraint(f"uq_{table}_identity", table, type_="unique")
        op.create_unique_constraint(
            f"uq_{table}_identity", table, ["occurrence_key", "revision_sequence"]
        )
        op.create_foreign_key(
            f"fk_{table}_occurrence",
            table,
            "economic_event_occurrences",
            ["occurrence_key"],
            ["occurrence_key"],
        )
        op.drop_index(f"ix_{table}_occurrence_availability", table_name=table)
        op.create_index(
            f"ix_{table}_occurrence_availability", table, ["occurrence_key", "availability"]
        )
        op.drop_column(table, "indicator_key")
        op.drop_column(table, "reference_period")

    # --- 3. New release-vintage table (FX-51H) -------------------------------
    op.create_table(
        "economic_event_release_vintages",
        sa.Column("occurrence_key", sa.String(), nullable=False),
        sa.Column("revision_sequence", sa.Integer(), nullable=False),
        sa.Column("released_date", sa.Date(), nullable=False),
        sa.Column("released_time", sa.Time(), nullable=True),
        sa.Column("released_timezone", sa.String(), nullable=False),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=True),
        sa.Column("availability_confidence", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
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
        sa.CheckConstraint(
            "(availability IS NULL) = (availability_confidence = 'UNKNOWN')",
            name="ck_economic_event_release_vintages_avail_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["occurrence_key"],
            ["economic_event_occurrences.occurrence_key"],
            name="fk_economic_event_release_vintages_occurrence",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "occurrence_key",
            "revision_sequence",
            name="uq_economic_event_release_vintages_identity",
        ),
    )
    op.create_index(
        "ix_economic_event_release_vintages_occurrence_availability",
        "economic_event_release_vintages",
        ["occurrence_key", "availability"],
    )


def downgrade() -> None:
    # --- 3. Drop the release-vintage table first (FKs onto occurrence_key) --
    op.drop_index(
        "ix_economic_event_release_vintages_occurrence_availability",
        table_name="economic_event_release_vintages",
    )
    op.drop_table("economic_event_release_vintages")

    # --- 2. Revert every vintage table's re-keying, leaving occurrence_key --
    #        columns in place until occurrences' own old unique constraint is
    #        restored below (their old FK cannot be recreated before that).
    for table in _VINTAGE_TABLES:
        op.add_column(
            table,
            sa.Column("indicator_key", sa.String(), nullable=False),
        )
        op.add_column(
            table,
            sa.Column("reference_period", postgresql.TIMESTAMP(timezone=True), nullable=False),
        )
        op.drop_constraint(f"fk_{table}_occurrence", table, type_="foreignkey")
        op.drop_constraint(f"uq_{table}_identity", table, type_="unique")
        op.drop_index(f"ix_{table}_occurrence_availability", table_name=table)
        op.drop_column(table, "occurrence_key")

    # --- 1. Restore occurrences' original identity ---------------------------
    op.alter_column(
        "economic_event_occurrences",
        "reference_period",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
    )
    op.drop_constraint(
        "uq_economic_event_occurrences_occurrence_key",
        "economic_event_occurrences",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_economic_event_occurrences_indicator_reference_period",
        "economic_event_occurrences",
        ["indicator_key", "reference_period"],
    )
    op.drop_column("economic_event_occurrences", "occurrence_key")

    # --- 2b. Now that the old occurrence unique constraint exists again, ----
    #         restore each vintage table's own old identity/FK/index.
    for table in _VINTAGE_TABLES:
        op.create_unique_constraint(
            f"uq_{table}_identity",
            table,
            ["indicator_key", "reference_period", "revision_sequence"],
        )
        op.create_index(
            f"ix_{table}_occurrence_availability",
            table,
            ["indicator_key", "reference_period", "availability"],
        )
        op.create_foreign_key(
            f"fk_{table}_occurrence",
            table,
            "economic_event_occurrences",
            ["indicator_key", "reference_period"],
            ["indicator_key", "reference_period"],
        )

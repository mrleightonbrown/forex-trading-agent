"""correct specific date canonical key microseconds

FX-65H.3 (H3): `80877afdbe75`'s own SQL equivalent of `domain.
forecast_outcome_identity.canonical_target_period_key` discarded the
fractional-second component of a `SPECIFIC_DATE` target period
entirely (`to_char(..., 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')` has no
microsecond token), while the Python function's own `datetime.
isoformat()` included microseconds whenever nonzero -- a genuine
Python/SQL parity break for any `SPECIFIC_DATE` outcome carrying
subsecond precision, not merely a cosmetic one. Both sides are now
fixed (this migration's own corrected SQL below; the Python function
in the SAME commit) to UNCONDITIONALLY include a fixed-width, zero-
padded 6-digit microsecond component, verified byte-identical against
several synthetic instants (0, nonzero, and near-boundary
microseconds) -- not merely the one real Bank of Canada row, which
uses `POLICY_MEETING`, not `SPECIFIC_DATE`, and is therefore
UNAFFECTED by this correction either way (confirmed below: zero
`SPECIFIC_DATE` rows exist in the real table at the time this
migration was written).

**Why a corrective migration, not just a code fix**: `80877afdbe75`
already backfilled `forecast_outcome_identity_bindings.target_period_
key` using the OLD, lossy SQL for any pre-existing `SPECIFIC_DATE`
row. Had one existed, its own stored key would now permanently
disagree with what the corrected Python function computes for the
SAME underlying `specific_date`, silently breaking H1/H2 enforcement
for that one row going forward. This migration re-derives `target_
period_key` for every `SPECIFIC_DATE`-kind binding row from its own
outcome's stored `forecast_outcome_vintages.specific_date` (full
microsecond precision is preserved there; it was only ever lost in
the DERIVED key) using the corrected formula -- a normalization
pass, not a renaming of any `outcome_key` or a touch of any OTHER
period kind's own key format, which are untouched and unaffected.

No row needed correcting when this migration was written (verified:
`SELECT COUNT(*) FROM forecast_outcome_identity_bindings WHERE
target_period_key LIKE 'SPECIFIC_DATE:%'` returned 0), so this is a
no-op against the real database today -- included for reproducibility
and to correct the record for any `SPECIFIC_DATE` outcome registered
in the future via a database that was bootstrapped before this fix.
The existing `POLICY_MEETING` identity (`BOC-RATE-DECISION-2024-12-
11`) is untouched.

Revision ID: 3b03a0c4f0ba
Revises: 80877afdbe75
Create Date: 2026-10-14 01:47:39.730742

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3b03a0c4f0ba"
down_revision: str | None = "80877afdbe75"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BINDINGS_TABLE = "forecast_outcome_identity_bindings"
_VINTAGES_TABLE = "forecast_outcome_vintages"


def _corrected_specific_date_key_sql(column_expr: str) -> str:
    """The CORRECTED SQL equivalent of `domain.forecast_outcome_
    identity.canonical_target_period_key`'s own `SPECIFIC_DATE`
    branch -- unconditionally appends a fixed-width, zero-padded
    6-digit microsecond component, matching the Python side's own
    `f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{dt.microsecond:06d}+00:00"`
    byte-for-byte (verified against several synthetic instants before
    writing this migration, not merely real data)."""
    return f"""
        'SPECIFIC_DATE:' || to_char({column_expr} AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')
            || '.' || lpad(
                (EXTRACT(MICROSECONDS FROM {column_expr} AT TIME ZONE 'UTC')::bigint % 1000000)
                    ::text,
                6, '0'
            ) || '+00:00'
    """


def _old_lossy_specific_date_key_sql(column_expr: str) -> str:
    """`80877afdbe75`'s own ORIGINAL (lossy) `SPECIFIC_DATE` formula
    -- kept here ONLY so `downgrade()` can reconstruct it exactly."""
    return f"""
        'SPECIFIC_DATE:' || to_char(
            {column_expr} AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'
        )
    """


def _raise_if_correction_would_create_a_conflict() -> None:
    bind = op.get_bind()
    corrected = _corrected_specific_date_key_sql("v.specific_date")
    conflicts = bind.execute(
        sa.text(f"""
            SELECT b.definition_key, ({corrected}) AS new_key, b.outcome_type, b.unit,
                   array_agg(DISTINCT b.outcome_key) AS outcome_keys
            FROM {_BINDINGS_TABLE} b
            JOIN (
                SELECT DISTINCT ON (outcome_key) outcome_key, specific_date
                FROM {_VINTAGES_TABLE}
                WHERE target_period_kind = 'SPECIFIC_DATE'
                ORDER BY outcome_key, revision_sequence
            ) v ON v.outcome_key = b.outcome_key
            WHERE b.target_period_key LIKE 'SPECIFIC_DATE:%'
            GROUP BY b.definition_key, ({corrected}), b.outcome_type, b.unit
            HAVING COUNT(DISTINCT b.outcome_key) > 1
        """)
    ).fetchall()
    if conflicts:
        raise RuntimeError(
            f"Cannot migrate {revision}: correcting SPECIFIC_DATE target_period_key would "
            f"create {len(conflicts)} NEW identity conflict(s) -- {conflicts!r}. This migration "
            "refuses to silently resolve a conflict it would itself introduce; investigate "
            "manually before retrying."
        )


def upgrade() -> None:
    _raise_if_correction_would_create_a_conflict()

    bind = op.get_bind()
    corrected = _corrected_specific_date_key_sql("v.specific_date")
    bind.execute(
        sa.text(f"""
            UPDATE {_BINDINGS_TABLE} b
            SET target_period_key = ({corrected})
            FROM (
                SELECT DISTINCT ON (outcome_key) outcome_key, specific_date
                FROM {_VINTAGES_TABLE}
                WHERE target_period_kind = 'SPECIFIC_DATE'
                ORDER BY outcome_key, revision_sequence
            ) v
            WHERE b.outcome_key = v.outcome_key
              AND b.target_period_key LIKE 'SPECIFIC_DATE:%'
        """)
    )


def downgrade() -> None:
    bind = op.get_bind()
    old_lossy = _old_lossy_specific_date_key_sql("v.specific_date")
    bind.execute(
        sa.text(f"""
            UPDATE {_BINDINGS_TABLE} b
            SET target_period_key = ({old_lossy})
            FROM (
                SELECT DISTINCT ON (outcome_key) outcome_key, specific_date
                FROM {_VINTAGES_TABLE}
                WHERE target_period_kind = 'SPECIFIC_DATE'
                ORDER BY outcome_key, revision_sequence
            ) v
            WHERE b.outcome_key = v.outcome_key
              AND b.target_period_key LIKE 'SPECIFIC_DATE:%'
        """)
    )

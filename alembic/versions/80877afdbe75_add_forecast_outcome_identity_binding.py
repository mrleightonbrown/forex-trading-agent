"""add forecast outcome identity binding table

FX-65H.2: one new table, `forecast_outcome_identity_bindings`,
completing FX-65H.1's own outcome-identity-binding contract with
database-enforced, concurrency-safe exclusivity in BOTH directions:

- `uq_outcome_identity_binding_identity`: one measurement identity
  `(definition_key, target_period_key, outcome_type, unit)` belongs to
  AT MOST ONE `outcome_key` (H1) -- replaces FX-65H.1's own read-then-
  decide application-level check, which could not guarantee
  exclusivity under concurrent transactions.
- `uq_outcome_identity_binding_key`: one `outcome_key` refers to
  EXACTLY ONE identity throughout its history (H2) -- FX-65H.1 never
  checked this at all.

**H3 (pre-migration integrity check)**: before creating the table,
`upgrade()` inspects every EXISTING `forecast_outcome_vintages` row
for exactly the two conflict shapes this table's own constraints
exist to prevent -- two different `outcome_key`s already sharing one
identity, or one `outcome_key` already spanning more than one
identity. If either is found, the migration RAISES and stops rather
than silently choosing a winner or rewriting historical evidence
(verified, before writing this migration, against the real database:
neither conflict shape exists -- exactly one real row, `outcome_key
='BOC-RATE-DECISION-2024-12-11'`).

The backfill then populates one binding row per DISTINCT `outcome_key`
already present, using the EXACT SAME canonical-period-key string
format `domain.forecast_outcome_identity.canonical_target_period_key`
computes at runtime -- duplicated inline here deliberately (Alembic's
own "a migration stays self-contained, never imports evolving
application code" convention), not approximated. No existing
`outcome_key` is renamed; `forecast_outcome_vintages` itself is
neither touched nor mutated.

No existing table is touched, mutated, or gains a new column.

Downgrade is GUARDED from the start, mirroring every prior FX-56+
migration's own precedent: once the new table holds a row, dropping
it would silently discard the durable identity-exclusivity record (a
different kind of loss than deleting outcome evidence itself, which
this migration never does either way).

Revision ID: 80877afdbe75
Revises: 0829067d81ae
Create Date: 2026-10-14 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "80877afdbe75"
down_revision: str | None = "0829067d81ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VINTAGES_TABLE = "forecast_outcome_vintages"
_BINDINGS_TABLE = "forecast_outcome_identity_bindings"
_NO_UNIT_SENTINEL = "__NO_UNIT__"


def _canonical_target_period_key_sql() -> str:
    """The EXACT SQL equivalent of `domain.forecast_outcome_identity.
    canonical_target_period_key` -- see that function's own docstring
    for why the two must never diverge. No real row uses `SPECIFIC_
    DATE` today, so this CASE branch's own timestamp formatting is
    deliberately not byte-exact for that one shape (documented there)."""
    return """
        CASE target_period_kind
            WHEN 'CALENDAR_YEAR' THEN 'CALENDAR_YEAR:' || calendar_year::text
            WHEN 'CALENDAR_QUARTER' THEN
                'CALENDAR_QUARTER:' || calendar_year::text || ':' || calendar_quarter::text
            WHEN 'CALENDAR_MONTH' THEN
                'CALENDAR_MONTH:' || calendar_year::text || ':'
                    || lpad(calendar_month::text, 2, '0')
            WHEN 'SPECIFIC_DATE' THEN
                'SPECIFIC_DATE:' || to_char(
                    specific_date AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'
                )
            WHEN 'POLICY_MEETING' THEN 'POLICY_MEETING:' || policy_meeting_identifier
        END
    """


def _raise_if_downgrade_would_lose_data() -> None:
    bind = op.get_bind()
    row_count: int = bind.execute(sa.text(f"SELECT COUNT(*) FROM {_BINDINGS_TABLE}")).scalar_one()
    if row_count > 0:
        raise RuntimeError(
            f"Cannot downgrade migration {revision}: {_BINDINGS_TABLE} holds {row_count} row(s). "
            "Dropping it would silently discard the durable outcome-identity-exclusivity record "
            "-- which outcome_key is the sole legitimate holder of which measurement identity -- "
            "which cannot be reliably reconstructed after the fact (a later write under a since-"
            "freed identity could then bind a DIFFERENT outcome_key to it, silently reassigning "
            "history). Downgrading past this migration once real data exists is a permanent "
            "limitation, not a bug -- restore from a backup instead."
        )


def _raise_if_existing_data_conflicts() -> None:
    bind = op.get_bind()
    period_key_sql = _canonical_target_period_key_sql()

    duplicate_identity_rows = bind.execute(
        sa.text(f"""
            SELECT definition_key, ({period_key_sql}) AS target_period_key, outcome_type, unit,
                   array_agg(DISTINCT outcome_key) AS outcome_keys
            FROM {_VINTAGES_TABLE}
            GROUP BY definition_key, ({period_key_sql}), outcome_type, unit
            HAVING COUNT(DISTINCT outcome_key) > 1
        """)
    ).fetchall()
    if duplicate_identity_rows:
        raise RuntimeError(
            f"Cannot migrate {revision}: found {len(duplicate_identity_rows)} measurement "
            f"identity/identities already claimed by more than one outcome_key in "
            f"{_VINTAGES_TABLE} -- {duplicate_identity_rows!r}. This migration refuses to "
            "silently select a winner; resolve the conflicting outcome_keys manually before "
            "retrying."
        )

    multi_identity_keys = bind.execute(
        sa.text(f"""
            SELECT outcome_key,
                   COUNT(DISTINCT (definition_key, ({period_key_sql}), outcome_type, unit)) AS n
            FROM {_VINTAGES_TABLE}
            GROUP BY outcome_key
            HAVING COUNT(DISTINCT (definition_key, ({period_key_sql}), outcome_type, unit)) > 1
        """)
    ).fetchall()
    if multi_identity_keys:
        raise RuntimeError(
            f"Cannot migrate {revision}: found {len(multi_identity_keys)} outcome_key(s) already "
            f"spanning more than one measurement identity in {_VINTAGES_TABLE} -- "
            f"{multi_identity_keys!r}. This migration refuses to silently rewrite historical "
            "evidence; resolve the conflicting revisions manually before retrying."
        )


def upgrade() -> None:
    _raise_if_existing_data_conflicts()

    op.create_table(
        _BINDINGS_TABLE,
        sa.Column("definition_key", sa.String(), nullable=False),
        sa.Column("target_period_key", sa.String(), nullable=False),
        sa.Column("outcome_type", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("outcome_key", sa.String(), nullable=False),
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
            "definition_key",
            "target_period_key",
            "outcome_type",
            "unit",
            name="uq_outcome_identity_binding_identity",
        ),
        sa.UniqueConstraint("outcome_key", name="uq_outcome_identity_binding_key"),
        sa.CheckConstraint(
            "definition_key <> ''", name="ck_outcome_identity_binding_definition_key"
        ),
        sa.CheckConstraint(
            "target_period_key <> ''", name="ck_outcome_identity_binding_target_period_key"
        ),
        sa.CheckConstraint(
            "outcome_type IN ('NUMERIC_POINT', 'CATEGORICAL_EVENT')",
            name="ck_outcome_identity_binding_outcome_type",
        ),
        sa.CheckConstraint("unit <> ''", name="ck_outcome_identity_binding_unit"),
        sa.CheckConstraint("outcome_key <> ''", name="ck_outcome_identity_binding_outcome_key"),
    )

    bind = op.get_bind()
    period_key_sql = _canonical_target_period_key_sql()
    bind.execute(
        sa.text(f"""
            INSERT INTO {_BINDINGS_TABLE}
                (definition_key, target_period_key, outcome_type, unit, outcome_key)
            SELECT DISTINCT
                definition_key,
                ({period_key_sql}) AS target_period_key,
                outcome_type,
                COALESCE(unit, :no_unit_sentinel) AS unit,
                outcome_key
            FROM {_VINTAGES_TABLE}
        """),
        {"no_unit_sentinel": _NO_UNIT_SENTINEL},
    )


def downgrade() -> None:
    _raise_if_downgrade_would_lose_data()
    op.drop_table(_BINDINGS_TABLE)

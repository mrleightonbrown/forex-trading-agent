"""FX-66H (H1): persist diag_pending_revision_count on snapshots

FX-66H's own H1 correction makes `BuildForecastPerformancePopulationAsOf`
report, as a SEPARATE administrative diagnostic, how many of a
snapshot's accepted members had a newer evaluation revision available
(but excluded from population by design) at build time -- the
`ForecastPerformanceSampleDiagnostics.pending_revision_count` domain
field. Every OTHER field of that same diagnostics object already has
its own persisted `diag_*` column on `forecast_performance_snapshots`
(`diag_raw_candidate_count`, `diag_accepted_count`, ...) rather than
being recomputed at read time, so leaving this one new field
unpersisted would silently lose the H1 audit trail on every real-
Postgres round trip -- defeating the "separate administrative
diagnostic" requirement's own purpose once a snapshot is actually
persisted and later read back. This migration is the narrow, additive
exception to this story's own "no migration unless required" default:
it adds exactly one nullable-then-backfilled-then-NOT-NULL integer
column, consistent with how every sibling diagnostic column already
works.

No existing row was ever evaluated against this field (it did not
exist at write time for any row created before this migration), so
the only honest backfill value is `0` -- not a guess, but the domain
field's own already-documented default semantics (no pending-revision
diagnostic was ever computed for data written before FX-66H existed).

Guarded `downgrade()`, mirroring `a95058f88727`'s own exact pattern:
refuses while `forecast_performance_snapshots` holds any row, since
dropping the column would discard a real (if zero-valued) audit fact
that is not, in general, re-derivable afterwards.

Revision ID: 0072c7c74f86
Revises: 0db892e6639a
Create Date: 2026-10-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0072c7c74f86"
down_revision: str | None = "0db892e6639a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "forecast_performance_snapshots"
_COLUMN = "diag_pending_revision_count"


def _raise_if_downgrade_would_lose_data() -> None:
    bind = op.get_bind()
    count: int = bind.execute(sa.text(f"SELECT COUNT(*) FROM {_TABLE}")).scalar_one()
    if count > 0:
        raise RuntimeError(
            f"Cannot downgrade migration {revision}: {_TABLE} holds {count} row(s). "
            f"Dropping {_COLUMN} would silently discard a real H1 audit fact that is not, "
            "in general, re-derivable afterwards -- restore from a backup instead."
        )


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.Integer(), nullable=True))

    bind = op.get_bind()
    bind.execute(sa.text(f"UPDATE {_TABLE} SET {_COLUMN} = 0 WHERE {_COLUMN} IS NULL"))

    op.alter_column(_TABLE, _COLUMN, nullable=False, server_default="0")


def downgrade() -> None:
    _raise_if_downgrade_would_lose_data()
    op.drop_column(_TABLE, _COLUMN)

"""fail closed default for released_at_is_verified

FX-43H.1: `released_at_is_verified` (added by FX-43H's 5707ecb39242
with `server_default='true'`) now fails closed instead -- the column
default becomes `false`, and every row that already exists in this
table when this migration runs is conservatively RECLASSIFIED to
`false` too, regardless of its current value. This is deliberate and
unconditional, not "clear and reload": a database applying this
migration must never depend on an operator remembering to manually
wipe and repopulate the table to obtain a correct classification --
the migration itself must leave every pre-existing row correctly
fail-closed.

No row in this codebase has ever been written via a genuinely verified
path (only FX-43's policy-rate backfill has written rows, and it
already explicitly set `released_at_is_verified=False` from FX-43H
onward) -- this migration's unconditional downgrade of any row still
sitting at the OLD `true` default therefore changes no real,
knowingly-verified data. It exists as a structural safety net, not a
correction of a known-wrong specific row.

See `domain.macro_observation_vintage`,
`infrastructure.db.models.macro_observation_vintage`, and
`docs/DECISIONS.md`'s FX-43H.1 entry.

Revision ID: 80c0ae20257b
Revises: 5707ecb39242
Create Date: 2026-09-22 00:30:59.810133

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "80c0ae20257b"
down_revision: str | None = "5707ecb39242"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "macro_observation_vintages"
_COLUMN = "released_at_is_verified"


def upgrade() -> None:
    # Conservative reclassification FIRST: every row that already exists
    # is provisional until proven otherwise, unconditionally -- this does
    # not merely leave already-false rows alone, it actively overwrites
    # any row still carrying the old `true` default (or, in principle,
    # any row a caller marked true without this codebase's knowledge).
    op.execute(sa.text(f"UPDATE {_TABLE} SET {_COLUMN} = false"))

    # Then the schema default itself, so every FUTURE row defaults to
    # provisional too, without relying on every caller passing the field
    # explicitly.
    op.alter_column(_TABLE, _COLUMN, server_default="false")


def downgrade() -> None:
    # Schema-only revert -- reverting the DATA reclassification above
    # would mean guessing which rows were "really" true before, which is
    # exactly the kind of invented certainty this story exists to avoid.
    op.alter_column(_TABLE, _COLUMN, server_default="true")

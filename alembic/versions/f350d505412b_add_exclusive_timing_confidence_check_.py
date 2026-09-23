"""add exclusive timing confidence check constraint

FX-44H: enforces at the persistence layer, not just in the domain
constructor, that a macro_observation_vintages row can never have
BOTH released_at_is_verified AND released_at_is_conservative_bound
True at once -- a timestamp cannot be simultaneously an exactly
confirmed announcement moment AND a deliberately inexact conservative
bound. Applying this constraint IS this migration's verification that
no existing row already violates it: Postgres refuses to add a CHECK
constraint over data that doesn't already satisfy it, so a failed
migration run here would itself be the fail-closed signal -- no
separate manual reclassification step is needed, unlike FX-43H.1's
boolean-default migration (this invariant was never something the old
code could violate: every path that ever set either flag set exactly
one). See domain.macro_observation_vintage's __post_init__ for the
mirrored, construction-time check.

Revision ID: f350d505412b
Revises: aee1fa641be6
Create Date: 2026-09-22 22:47:33.641415

"""

from collections.abc import Sequence

from alembic import op

revision: str = "f350d505412b"
down_revision: str | None = "aee1fa641be6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "macro_observation_vintages"
_CONSTRAINT = "ck_macro_observation_vintages_exclusive_timing_confidence"


def upgrade() -> None:
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        "NOT (released_at_is_verified AND released_at_is_conservative_bound)",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")

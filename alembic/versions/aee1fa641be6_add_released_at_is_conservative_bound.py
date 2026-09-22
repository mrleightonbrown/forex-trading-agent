"""add released_at_is_conservative_bound to macro observation vintages

FX-44: the narrower alternative to `released_at_is_verified` -- marks
`released_at` as a deliberately conservative, research-safe bound
(guaranteed no earlier than the true release) rather than an exactly
confirmed timestamp. Defaults `False` (provisional -- same fail-closed
posture as `released_at_is_verified`, per FX-43H.1) for every existing
and every future row: nothing about adding this column reclassifies
any row as safe for research on its own. See
domain.macro_observation_vintage and domain.research_readiness.

Revision ID: aee1fa641be6
Revises: 80c0ae20257b
Create Date: 2026-09-22 01:32:28.510138

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "aee1fa641be6"
down_revision: str | None = "80c0ae20257b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "macro_observation_vintages",
        sa.Column(
            "released_at_is_conservative_bound",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("macro_observation_vintages", "released_at_is_conservative_bound")

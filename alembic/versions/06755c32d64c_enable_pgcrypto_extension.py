"""enable pgcrypto extension

FX-1: needed for gen_random_uuid(), used by UUIDPrimaryKeyMixin
(forex_agent.infrastructure.db.mixins) as the primary key strategy for every
future table.

Revision ID: 06755c32d64c
Revises:
Create Date: 2026-09-12 23:24:03.129204

"""

from collections.abc import Sequence

from alembic import op

revision: str = "06755c32d64c"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")

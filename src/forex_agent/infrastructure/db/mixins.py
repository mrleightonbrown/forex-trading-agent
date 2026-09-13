"""Reusable ORM mixins establishing the DB-wide conventions for FX-1.

Every table defined under `infrastructure` should inherit these unless it has
a specific, documented reason not to (e.g. a pure association table).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    """Server-generated UUID primary key.

    Requires the `pgcrypto` extension (enabled by the
    `enable_pgcrypto_extension` migration) for `gen_random_uuid()`.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """Timezone-aware `created_at`/`updated_at`, per CLAUDE.md: "All persisted
    timestamps use timezone-aware UTC values. Naive datetimes must be
    rejected."

    Columns are `TIMESTAMPTZ`, populated server-side by Postgres — never by
    application-supplied naive datetimes. asyncpg decodes `TIMESTAMPTZ` back
    into UTC-aware `datetime` objects regardless of session timezone, so
    values read back through the async engine are always tz-aware.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

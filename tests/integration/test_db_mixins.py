"""Regression tests for the DB-wide conventions established in FX-1:
server-generated UUID primary keys and timezone-aware timestamps.

Requires a live Postgres with `pgcrypto` enabled — run
`docker compose up -d db && uv run alembic upgrade head` first (CI does this
automatically; see .github/workflows/ci.yml).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC

import pytest
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from forex_agent.infrastructure.db.session import get_engine


class _Widget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Throwaway table, local to this test module, to exercise the mixins
    without depending on any real domain model (none exist yet)."""

    __tablename__ = "_test_fx1_widgets"

    name: Mapped[str] = mapped_column(String, nullable=False)


_widget_table = Base.metadata.tables[_Widget.__tablename__]


@pytest.fixture
async def widget_table() -> AsyncIterator[AsyncEngine]:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[_widget_table])
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all, tables=[_widget_table])


async def _insert_widget(engine: AsyncEngine, name: str) -> _Widget:
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        widget = _Widget(name=name)
        session.add(widget)
        await session.commit()
        await session.refresh(widget)
        return widget


@pytest.mark.asyncio
async def test_primary_key_is_server_generated_uuid(widget_table: AsyncEngine) -> None:
    widget = await _insert_widget(widget_table, "alpha")

    assert isinstance(widget.id, uuid.UUID)


@pytest.mark.asyncio
async def test_timestamps_are_utc_and_tz_aware(widget_table: AsyncEngine) -> None:
    widget = await _insert_widget(widget_table, "beta")

    assert widget.created_at.tzinfo is not None
    assert widget.created_at.utcoffset() == UTC.utcoffset(None)
    assert widget.updated_at.tzinfo is not None


@pytest.mark.asyncio
async def test_two_inserts_get_distinct_ids(widget_table: AsyncEngine) -> None:
    first = await _insert_widget(widget_table, "gamma")
    second = await _insert_widget(widget_table, "delta")

    assert first.id != second.id

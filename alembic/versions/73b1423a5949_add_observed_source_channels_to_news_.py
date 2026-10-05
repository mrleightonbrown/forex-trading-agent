"""add observed_source_channels to news_item_vintages

FX-57E0: live Statistics Canada research proved false a durable
architecture assumption FX-57B/FX-57CH both made -- that the same
external identity is observed through at most ONE source channel "at
a time," any channel change being a genuinely SEQUENTIAL transition.
StatCan legitimately cross-lists the SAME Daily release under
MULTIPLE subject feeds simultaneously: same external id, same
headline, same content, several genuinely-true publisher channels.
The existing `source_channel` column can still represent WHICH
channel produced one particular vintage's own observation, but cannot
represent the CUMULATIVE set of channels FTA has observed an item
through by a given vintage's own availability -- this migration adds
exactly that cumulative field.

Three-step upgrade, never guessing a value: (1) add the column
nullable; (2) backfill EVERY existing vintage CUMULATIVELY -- for each
`news_item_key`, walking its own vintages in `revision_sequence`
order, `observed_source_channels` for revision N is the canonicalized
(sorted, deduped) UNION of every `source_channel` value seen on
revisions `0..N` of that SAME item, never merely `[that row's own
source_channel]` (which would be wrong for any item whose historical
revisions already recorded more than one distinct channel -- FX-57B/
FX-57CH allowed a genuine SEQUENTIAL channel change across separate
runs before this story, even though no row in this project's own dev
data currently has one, so this migration does not assume the
single-channel case is the only one that could exist); (3) raise
loudly, refusing to proceed, if any row is left with a NULL
`observed_source_channels` after the backfill -- only once zero NULLs
are confirmed does it alter the column to `NOT NULL`.

Guarded, data-loss-aware `downgrade()`: unlike `a95058f88727`'s own
blanket "refuse while non-empty" guard, dropping this column is safe
EXACTLY when every single vintage row's own `observed_source_channels`
has length 1 (i.e. equals `[source_channel]`) -- that case is fully
reconstructable from the old singular field alone, so a future
re-upgrade could backfill it right back. The guard refuses, naming
every offending `news_item_key`/`revision_sequence`, the moment ANY
row's own cumulative set has more than one channel -- that
information is NOT reconstructable from `source_channel` alone and
would be silently and permanently lost.

Revision ID: 73b1423a5949
Revises: a95058f88727
Create Date: 2026-10-05 00:37:58.349425

"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "73b1423a5949"
down_revision: str | None = "a95058f88727"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _compute_cumulative_channels(rows: Sequence[Any]) -> list[tuple[Any, list[str]]]:
    """Pure helper, unit-testable without a real database: given rows
    (each exposing `.id`/`.news_item_key`/`.revision_sequence`/`.
    source_channel`) ALREADY ordered by `(news_item_key, revision_
    sequence)`, returns `(row_id, canonical_channels)` pairs -- the
    cumulative, sorted, deduped UNION of every `source_channel` seen
    on that item's own revisions `0..N` so far."""
    seen_by_item: dict[Any, set[str]] = {}
    result: list[tuple[Any, list[str]]] = []
    for row in rows:
        channels = seen_by_item.setdefault(row.news_item_key, set())
        channels.add(row.source_channel)
        result.append((row.id, sorted(channels)))
    return result


def upgrade() -> None:
    op.add_column(
        "news_item_vintages",
        sa.Column("observed_source_channels", postgresql.JSONB(), nullable=True),
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, news_item_key, revision_sequence, source_channel "
            "FROM news_item_vintages ORDER BY news_item_key, revision_sequence"
        )
    ).all()

    for row_id, channels in _compute_cumulative_channels(rows):
        bind.execute(
            sa.text(
                "UPDATE news_item_vintages SET observed_source_channels = "
                "CAST(:channels AS JSONB) WHERE id = :id"
            ),
            {"channels": json.dumps(channels), "id": row_id},
        )

    null_count: int = bind.execute(
        sa.text("SELECT COUNT(*) FROM news_item_vintages WHERE observed_source_channels IS NULL")
    ).scalar_one()
    if null_count > 0:
        raise RuntimeError(
            f"Cannot backfill observed_source_channels: {null_count} row(s) were left NULL "
            "after the cumulative backfill pass -- refusing to proceed with an incomplete "
            "backfill; investigate before re-running this migration."
        )

    op.alter_column("news_item_vintages", "observed_source_channels", nullable=False)


def _raise_if_downgrade_would_lose_data() -> None:
    bind = op.get_bind()
    offending = bind.execute(
        sa.text(
            "SELECT news_item_key, revision_sequence FROM news_item_vintages "
            "WHERE jsonb_array_length(observed_source_channels) > 1 "
            "ORDER BY news_item_key, revision_sequence"
        )
    ).all()
    if offending:
        names = ", ".join(f"{row.news_item_key}#{row.revision_sequence}" for row in offending)
        raise RuntimeError(
            f"Cannot downgrade migration {revision}: {len(offending)} vintage row(s) carry "
            f"more than one observed source channel, not reconstructable from source_channel "
            f"alone: {names}. Dropping observed_source_channels would silently and permanently "
            "discard real multi-channel provenance -- downgrading past this migration once "
            "genuine multi-channel evidence has been stored is a permanent limitation, not a "
            "bug -- restore from a backup instead."
        )


def downgrade() -> None:
    _raise_if_downgrade_would_lose_data()
    op.drop_column("news_item_vintages", "observed_source_channels")

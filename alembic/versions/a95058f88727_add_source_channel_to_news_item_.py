"""add source_channel to news_item_vintages

FX-57B: ECB's own single combined feed (`/rss/press.html`) serves
THREE content types (press release/speech/interview) through ONE
channel -- proving `source_channel` (which configured feed/endpoint
produced an item) and `source_content_type` (what kind of content it
is) are genuinely separate concepts, not just two names for the same
thing. FX-57A deliberately reused `source_content_type` for Fed's own
channel identity because Fed's three feeds happen to map 1:1 to three
content types; ECB disproves that 1:1 coincidence in general, so this
migration adds the genuinely separate field FX-57A's own decision
memo (`docs/DECISIONS.md`) already anticipated needing once a source
demonstrated the divergence.

Three-step upgrade, never guessing a value: (1) add the column
nullable; (2) backfill every EXISTING row deterministically from its
own `source_content_type`, using FX-57A's own exact, known mapping
(`monetary_policy_release -> press_monetary`, `speech -> speeches`,
`testimony -> testimony` -- the only three content types any
currently-persisted row can have, since Fed is the only adapter that
has ever written to this table); (3) raise loudly, refusing to
proceed, if any row is left with a NULL `source_channel` after the
backfill (an unexpected content type would mean guessing, which this
migration refuses to do) -- only once zero NULLs are confirmed does it
alter the column to `NOT NULL`.

Guarded, data-loss-aware `downgrade()`: dropping this column would
silently discard real channel provenance that is not, in general,
re-derivable from `source_content_type` alone (ECB's three content
types all share the SAME channel; a future source could just as
easily have two channels sharing one content type) -- so `downgrade()`
refuses with a clear `RuntimeError` if `news_item_vintages` holds ANY
row at all, mirroring migration `504030474987`'s own blanket "refuse
while non-empty" guard exactly, rather than attempting a narrower
heuristic that might wrongly allow a real loss through.

Revision ID: a95058f88727
Revises: b2bbebf8ee3b
Create Date: 2026-10-03 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "a95058f88727"
down_revision: str | None = "b2bbebf8ee3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTENT_TYPE_TO_CHANNEL = {
    "monetary_policy_release": "press_monetary",
    "speech": "speeches",
    "testimony": "testimony",
}


def _raise_if_downgrade_would_lose_data() -> None:
    bind = op.get_bind()
    count: int = bind.execute(sa.text("SELECT COUNT(*) FROM news_item_vintages")).scalar_one()
    if count > 0:
        raise RuntimeError(
            f"Cannot downgrade migration {revision}: news_item_vintages holds {count} row(s). "
            "Dropping source_channel would silently discard real channel provenance that is "
            "not, in general, re-derivable from source_content_type alone -- a future source "
            "could have two channels sharing one content type, even though no currently "
            "persisted row does. Downgrading past this migration once real data exists is a "
            "permanent limitation, not a bug -- restore from a backup instead."
        )


def upgrade() -> None:
    op.add_column(
        "news_item_vintages",
        sa.Column("source_channel", sa.String(), nullable=True),
    )

    bind = op.get_bind()
    for content_type, channel in _CONTENT_TYPE_TO_CHANNEL.items():
        bind.execute(
            sa.text(
                "UPDATE news_item_vintages SET source_channel = :channel "
                "WHERE source_content_type = :content_type AND source_channel IS NULL"
            ),
            {"channel": channel, "content_type": content_type},
        )

    unmapped_count: int = bind.execute(
        sa.text("SELECT COUNT(*) FROM news_item_vintages WHERE source_channel IS NULL")
    ).scalar_one()
    if unmapped_count > 0:
        unmapped_types: list[Any] = list(
            bind.execute(
                sa.text(
                    "SELECT DISTINCT source_content_type FROM news_item_vintages "
                    "WHERE source_channel IS NULL"
                )
            ).scalars()
        )
        raise RuntimeError(
            f"Cannot backfill source_channel: {unmapped_count} row(s) have an unexpected "
            f"source_content_type not in the known Fed mapping: {unmapped_types!r}. Refusing "
            "to guess a channel value -- extend _CONTENT_TYPE_TO_CHANNEL only once the correct "
            "mapping for this content type is actually known, then re-run this migration."
        )

    op.alter_column("news_item_vintages", "source_channel", nullable=False)


def downgrade() -> None:
    _raise_if_downgrade_would_lose_data()
    op.drop_column("news_item_vintages", "source_channel")

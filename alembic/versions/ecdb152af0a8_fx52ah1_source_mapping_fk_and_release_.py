"""fx52ah1 source mapping fk and release provenance

FX-52AH.1: two independent, additive schema changes closing gaps left
by FX-52AH's own hardening pass.

1. `economic_event_source_mappings.occurrence_key` gains a genuine
   `FOREIGN KEY` onto `economic_event_occurrences.occurrence_key`.
   FX-52AH's own original design deliberately omitted this ("a mapping
   may be recorded in the same transaction as the occurrence it points
   to"), but both ingestion use cases already call `add_occurrence`
   and let it commit BEFORE calling `record_mapping` (this repository
   layer commits after every single statement, never spanning a wider
   unit of work) -- so the referenced occurrence row is always already
   durably committed by the time a mapping row referencing it is
   inserted, and this FK is safely satisfiable with no deferred-
   constraint machinery. Without it, nothing in the schema prevented a
   mapping row from pointing at an occurrence_key no occurrence
   actually has.

2. `economic_event_release_vintages` gains a nullable
   `source_published_at` column. FX-52AH introduced this field on
   `RawReleaseObservation` (provenance: when the SOURCE ITSELF says a
   piece of release evidence was published, e.g. an RSS `dc:date` --
   deliberately never promoted to `released_time`) but never actually
   persisted it anywhere: `IngestOfficialCalendarRelease` computed it
   and then silently discarded it on every real poll. This column is
   where it is now durably stored, independent of `availability` (when
   THIS system could first know the release fact) and independent of
   `TimestampMixin`'s own `created_at`/`updated_at` (when this ROW was
   written) -- three genuinely different instants, never conflated.

Both changes are purely additive (a new nullable column; a new FK
constraint that every existing row already satisfies, since
`economic_event_source_mappings` only ever holds rows written by
`record_mapping`, which is only ever called after the referenced
occurrence exists) -- `downgrade()` is ordinary, unguarded reversal;
neither change can lose data on its own. This does NOT touch
`df99b7796566`'s own `downgrade()`, whose non-empty-table guard is a
separate FX-52AH.1 requirement addressed directly in that migration's
own file (mirroring FX-51H.1's precedent of hardening a downgrade
guard in place rather than via a follow-on migration).

Revision ID: ecdb152af0a8
Revises: df99b7796566
Create Date: 2026-09-26 22:09:19.270678

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ecdb152af0a8"
down_revision: str | None = "df99b7796566"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "economic_event_release_vintages",
        sa.Column("source_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_economic_event_source_mappings_occurrence",
        "economic_event_source_mappings",
        "economic_event_occurrences",
        ["occurrence_key"],
        ["occurrence_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_economic_event_source_mappings_occurrence",
        "economic_event_source_mappings",
        type_="foreignkey",
    )
    op.drop_column("economic_event_release_vintages", "source_published_at")

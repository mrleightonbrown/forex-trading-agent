"""fx56h news evidence enum constraints

FX-56H: a focused hardening pass on FX-56 (migration `504030474987`),
performed before FX-57 is authorized to begin -- does NOT rewrite that
already-deployed migration, which `docs/DECISIONS.md`'s own FX-55H/
FX-52AH.1 precedent establishes should not happen once a migration has
shipped; this follow-up adds purely ADDITIVE `CHECK` constraints
instead.

Four new constraints, each mirroring a domain-layer `__post_init__`
check that this project's own established convention (`ck_economic_
event_schedule_vintages_avail_confidence`, `ck_news_item_vintages_
quarantine_reason`) already applies elsewhere, so the invariant holds
even for a row written by a future path that bypasses the domain
constructor:

- `news_items.first_observation_mode` must be `PROSPECTIVE` or
  `BACKFILL` (`domain.news_observation_mode.NewsObservationMode`).
- `news_item_vintages.revision_sequence` must be non-negative
  (`domain._guards.require_revision_sequence`'s own rule).
- `news_item_vintages.observation_mode` must be `PROSPECTIVE` or
  `BACKFILL`.
- `news_item_vintages.source_status` must be `ACTIVE` or `WITHDRAWN`
  (`domain.news_source_status.NewsSourceStatus`).
- `news_item_vintages.evidence_disposition` must be
  `EVIDENCE_ELIGIBLE` or `QUARANTINED` (`domain.news_evidence_
  disposition.NewsEvidenceDisposition`).

This does NOT attempt a cross-table CHECK enforcing "revision 0's own
`availability` equals its owning `NewsItem.first_seen_at`" -- Postgres
`CHECK` constraints cannot reference another table, and FX-56H
Section 8 explicitly directs that this particular invariant stay a
TRANSACTIONAL guarantee (`SqlAlchemyNewsRepository.register_source_
item_with_first_vintage`), proven by integration test, rather than
attempted at the schema level.

Purely additive and safe to reverse unguarded: every row written by
this codebase already satisfies all five constraints (application
code only ever persists the validated domain enum's own `.value`), so
`downgrade()` cannot lose data merely by relaxing them -- unlike
`504030474987`'s own guarded `downgrade()`, which this migration does
not touch.

Revision ID: b2bbebf8ee3b
Revises: 504030474987
Create Date: 2026-10-03 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2bbebf8ee3b"
down_revision: str | None = "504030474987"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_news_items_first_observation_mode",
        "news_items",
        "first_observation_mode IN ('PROSPECTIVE', 'BACKFILL')",
    )
    op.create_check_constraint(
        "ck_news_item_vintages_revision_sequence",
        "news_item_vintages",
        "revision_sequence >= 0",
    )
    op.create_check_constraint(
        "ck_news_item_vintages_observation_mode",
        "news_item_vintages",
        "observation_mode IN ('PROSPECTIVE', 'BACKFILL')",
    )
    op.create_check_constraint(
        "ck_news_item_vintages_source_status",
        "news_item_vintages",
        "source_status IN ('ACTIVE', 'WITHDRAWN')",
    )
    op.create_check_constraint(
        "ck_news_item_vintages_evidence_disposition",
        "news_item_vintages",
        "evidence_disposition IN ('EVIDENCE_ELIGIBLE', 'QUARANTINED')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_news_item_vintages_evidence_disposition", "news_item_vintages", type_="check"
    )
    op.drop_constraint("ck_news_item_vintages_source_status", "news_item_vintages", type_="check")
    op.drop_constraint(
        "ck_news_item_vintages_observation_mode", "news_item_vintages", type_="check"
    )
    op.drop_constraint(
        "ck_news_item_vintages_revision_sequence", "news_item_vintages", type_="check"
    )
    op.drop_constraint("ck_news_items_first_observation_mode", "news_items", type_="check")

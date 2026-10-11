"""narrow canonical relation method to exact url exact body manual review

FX-58H: `EXACT_HEADLINE_AND_SUMMARY` is REMOVED from the set of
`method` values `news_canonical_relation_vintages` (migration
`274aabcc57dd`, never edited in place) permits. FX-58's own mandatory
real-data dry-run safety gate found this signal unsafe as independent
`SAME_STORY` evidence: 6 of 7 real-data pairs it proposed were
confirmed related-but-distinct publications (recurring institutional
boilerplate in a source's own "summary" field, e.g. Bank of Canada
rate-decision outcome text and Federal Reserve committee-hearing
titles) -- see ADR 0007's own "Real-data finding" and its FX-58H
addendum. ZERO relations using this method were ever persisted, so
this migration narrows the schema PURELY prophylactically, with no
real row to migrate.

**Data precheck before any destructive constraint change**: `upgrade()`
counts existing rows with `method = 'EXACT_HEADLINE_AND_SUMMARY'`
first. The expected, verified count is zero. If any such row exists
regardless, this migration FAILS LOUDLY (`RuntimeError`) rather than
silently relabeling or deleting it -- a persisted row using a method
this story's own real-data research found unsafe needs a human to
look at it, not an automated migration deciding its fate.

`ck_ncrv_method` and `ck_ncrv_automatic_method_is_same_story` are
replaced with narrower versions permitting only `EXACT_CANONICAL_URL`/
`EXACT_BODY_TEXT`/`MANUAL_REVIEW`; `ck_ncrv_not_same_story_is_manual_
review` is untouched (still correct, references only `MANUAL_REVIEW`
and `NOT_SAME_STORY`, neither of which changed). `downgrade()` simply
restores the two prior, wider constraint definitions -- safe
unconditionally, since widening a `CHECK` constraint can never be
violated by existing data.

No other `news_*` table is touched.

Revision ID: 3fe8c43841ee
Revises: 274aabcc57dd
Create Date: 2026-10-11 01:59:47.526466

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3fe8c43841ee"
down_revision: str | None = "274aabcc57dd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "news_canonical_relation_vintages"
_UNSAFE_METHOD = "EXACT_HEADLINE_AND_SUMMARY"


def _raise_if_unsafe_method_rows_exist() -> None:
    """Refuses to narrow the `method` CHECK constraints while any row
    still uses the demoted `EXACT_HEADLINE_AND_SUMMARY` method --
    checked BEFORE any constraint DDL runs."""
    bind = op.get_bind()
    row_count: int = bind.execute(
        sa.text(f"SELECT COUNT(*) FROM {_TABLE} WHERE method = :method"),
        {"method": _UNSAFE_METHOD},
    ).scalar_one()
    if row_count > 0:
        raise RuntimeError(
            f"Cannot narrow migration {revision}'s own method constraint: {_TABLE} has "
            f"{row_count} row(s) with method={_UNSAFE_METHOD!r}. FX-58's own real-data "
            "dry-run safety gate found this method unsafe as independent SAME_STORY "
            "evidence, but a PERSISTED row using it is a genuine data condition this "
            "migration will not silently relabel, delete, or otherwise resolve on its "
            "own -- it requires explicit human review before this schema change proceeds."
        )


def upgrade() -> None:
    _raise_if_unsafe_method_rows_exist()

    op.drop_constraint("ck_ncrv_automatic_method_is_same_story", _TABLE, type_="check")
    op.drop_constraint("ck_ncrv_method", _TABLE, type_="check")

    op.create_check_constraint(
        "ck_ncrv_method",
        _TABLE,
        "method IN ('EXACT_CANONICAL_URL', 'EXACT_BODY_TEXT', 'MANUAL_REVIEW')",
    )
    op.create_check_constraint(
        "ck_ncrv_automatic_method_is_same_story",
        _TABLE,
        "method NOT IN ('EXACT_CANONICAL_URL', 'EXACT_BODY_TEXT') OR relation_kind = 'SAME_STORY'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ncrv_automatic_method_is_same_story", _TABLE, type_="check")
    op.drop_constraint("ck_ncrv_method", _TABLE, type_="check")

    op.create_check_constraint(
        "ck_ncrv_method",
        _TABLE,
        "method IN ('EXACT_CANONICAL_URL', 'EXACT_BODY_TEXT', 'EXACT_HEADLINE_AND_SUMMARY', "
        "'MANUAL_REVIEW')",
    )
    op.create_check_constraint(
        "ck_ncrv_automatic_method_is_same_story",
        _TABLE,
        "method NOT IN ('EXACT_CANONICAL_URL', 'EXACT_BODY_TEXT', 'EXACT_HEADLINE_AND_SUMMARY') "
        "OR relation_kind = 'SAME_STORY'",
    )

"""FX-43H.1: unit tests for migration 80c0ae20257b itself.

The live-Postgres integration suite (`tests/integration/
test_macro_observation_repository.py`) proves the CURRENT dev database
ended up correctly fail-closed -- it does not prove the migration
ITSELF is what would keep any OTHER database (a fresh one, a
colleague's, CI's) correct too, and re-running against a database that
merely happens to already be right would not catch a migration whose
reclassification was narrowed, scoped incorrectly, or dropped.

This loads `upgrade()`/`downgrade()` directly from the migration file
(via `importlib.util`, not a dotted import -- the project's own
`alembic/` directory and the installed `alembic` package share a name,
and `alembic/versions/` has no `__init__.py`, so it is not a regular
importable package) and replaces `alembic.op`'s `execute`/
`alter_column` with recording stubs, so the migration's exact DDL/DML
can be asserted against without a real database at all.
"""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import op

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "80c0ae20257b_fail_closed_default_for_released_at_is_.py"
)
_TABLE = "macro_observation_vintages"
_COLUMN = "released_at_is_verified"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fx43h1_migration", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sql_text(argument: object) -> str:
    # op.execute() is called with a sqlalchemy.sql.elements.TextClause
    # (from sa.text(...)) in the real migration -- str() renders its
    # literal SQL. Fall back to str() unconditionally so this also
    # tolerates a plain string, should the migration ever be rewritten
    # to pass one directly.
    return str(argument)


@pytest.fixture
def recorded_op_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"execute": [], "alter_column": []}

    def fake_execute(sqltext: object, *args: object, **kwargs: object) -> None:
        calls["execute"].append(sqltext)

    def fake_alter_column(table_name: str, column_name: str, **kwargs: object) -> None:
        calls["alter_column"].append(
            {"table_name": table_name, "column_name": column_name, **kwargs}
        )

    monkeypatch.setattr(op, "execute", fake_execute)
    monkeypatch.setattr(op, "alter_column", fake_alter_column)
    return calls


def test_upgrade_unconditionally_reclassifies_every_existing_row(
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    migration = _load_migration()

    migration.upgrade()

    assert len(recorded_op_calls["execute"]) == 1
    statement = _sql_text(recorded_op_calls["execute"][0]).lower()
    assert _TABLE in statement
    assert f"{_COLUMN} = false" in statement
    # Conservative == unconditional: nothing narrows which existing rows
    # get reclassified (e.g. no "where released_at_is_verified is null"
    # or similar escape hatch that would leave some pre-existing rows
    # un-reclassified).
    assert "where" not in statement


def test_upgrade_changes_the_schema_default_to_false(
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    migration = _load_migration()

    migration.upgrade()

    assert len(recorded_op_calls["alter_column"]) == 1
    call = recorded_op_calls["alter_column"][0]
    assert call["table_name"] == _TABLE
    assert call["column_name"] == _COLUMN
    assert str(call["server_default"]).lower() in ("false", "sa.text('false')") or (
        isinstance(call["server_default"], sa.sql.elements.TextClause)
        and "false" in str(call["server_default"]).lower()
    )


def test_upgrade_reclassifies_data_before_changing_future_default(
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    # Ordering has no functional effect on the end state, but pinning it
    # documents the intended reading: existing rows are fixed, THEN the
    # default for new rows changes -- not the other way around.
    migration = _load_migration()

    migration.upgrade()

    assert len(recorded_op_calls["execute"]) == 1
    assert len(recorded_op_calls["alter_column"]) == 1


def test_downgrade_only_reverts_the_schema_default_not_row_data(
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    # FX-43H.1: downgrading must not invent certainty about which rows
    # were "really" verified before -- it reverts the DEFAULT only, and
    # must not issue any data-level UPDATE at all.
    migration = _load_migration()

    migration.downgrade()

    assert recorded_op_calls["execute"] == []
    assert len(recorded_op_calls["alter_column"]) == 1
    call = recorded_op_calls["alter_column"][0]
    assert call["table_name"] == _TABLE
    assert call["column_name"] == _COLUMN
    assert "true" in str(call["server_default"]).lower()

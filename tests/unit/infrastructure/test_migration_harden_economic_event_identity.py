"""FX-51H.1: unit tests for migration 76a4b23b2129's own downgrade
guard.

Mirrors tests/unit/infrastructure/test_migration_released_at_is_verified_
fail_closed.py's own pattern: loads `upgrade()`/`downgrade()` directly
from the migration file (via `importlib.util`, not a dotted import --
`alembic/versions/` has no `__init__.py`) and replaces `alembic.op`'s
methods with recording/fake stubs, so the migration's own logic can be
asserted against without a real database at all. This does NOT
duplicate the live-Postgres up/down/up round-trip already verified
manually against the real dev database -- it proves the guard ITSELF
(the condition it checks, the exact table it blames, and that it runs
BEFORE any destructive DDL) rather than merely that today's dev
database happens to be in a state the guard allows.
"""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from alembic import op

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "76a4b23b2129_harden_economic_event_identity_and_add_.py"
)

_ALL_TABLES = (
    "economic_event_occurrences",
    "economic_event_schedule_vintages",
    "economic_event_consensus_vintages",
    "economic_event_actual_value_vintages",
    "economic_event_release_vintages",
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fx51h1_migration", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _FakeBind:
    """Returns `counts[table]` (default 0) for a `SELECT COUNT(*) FROM
    <table>` query, matched by substring on the fixed table name --
    safe here because the migration only ever queries the small, fixed
    set of table names in `_ALL_TABLES`, never anything derived from
    external input."""

    def __init__(self, counts: dict[str, int]) -> None:
        self._counts = counts
        self.executed: list[str] = []

    def execute(self, clause: object, *args: object, **kwargs: object) -> _FakeResult:
        sql = str(clause)
        self.executed.append(sql)
        for table, count in self._counts.items():
            if table in sql:
                return _FakeResult(count)
        return _FakeResult(0)


@pytest.fixture
def recorded_op_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {
        "drop_constraint": [],
        "drop_index": [],
        "drop_table": [],
        "drop_column": [],
        "add_column": [],
        "alter_column": [],
        "create_unique_constraint": [],
        "create_index": [],
        "create_foreign_key": [],
    }
    for name in calls:

        def _recorder(*args: object, _name: str = name, **kwargs: object) -> None:
            calls[_name].append({"args": args, "kwargs": kwargs})

        monkeypatch.setattr(op, name, _recorder)
    return calls


def _patch_bind(monkeypatch: pytest.MonkeyPatch, counts: dict[str, int]) -> _FakeBind:
    fake_bind = _FakeBind(counts)
    monkeypatch.setattr(op, "get_bind", lambda: fake_bind)
    return fake_bind


@pytest.mark.parametrize("table_with_data", _ALL_TABLES)
def test_downgrade_refuses_when_any_touched_table_has_data(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
    table_with_data: str,
) -> None:
    _patch_bind(monkeypatch, {table_with_data: 1})
    migration = _load_migration()

    with pytest.raises(RuntimeError, match=table_with_data):
        migration.downgrade()

    # The guard must run BEFORE any destructive DDL -- nothing dropped,
    # added, or recreated.
    assert all(len(v) == 0 for v in recorded_op_calls.values())


def test_downgrade_error_message_explains_the_permanent_limitation(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    _patch_bind(monkeypatch, {"economic_event_release_vintages": 3})
    migration = _load_migration()

    with pytest.raises(RuntimeError) as excinfo:
        migration.downgrade()

    message = str(excinfo.value)
    assert "3 row(s)" in message
    assert "economic_event_release_vintages" in message
    assert "permanent limitation" in message
    assert "restore from a backup" in message.lower()


def test_downgrade_proceeds_when_every_touched_table_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    _patch_bind(monkeypatch, dict.fromkeys(_ALL_TABLES, 0))
    migration = _load_migration()

    migration.downgrade()  # must not raise

    # Reached real DDL -- the release-vintage table drop is the first
    # destructive step in downgrade()'s own documented ordering.
    assert len(recorded_op_calls["drop_table"]) == 1
    assert recorded_op_calls["drop_table"][0]["args"][0] == "economic_event_release_vintages"


def test_downgrade_checks_every_table_this_migration_touches(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    fake_bind = _patch_bind(monkeypatch, dict.fromkeys(_ALL_TABLES, 0))
    migration = _load_migration()

    migration.downgrade()

    checked_tables = {
        table for table in _ALL_TABLES if any(table in sql for sql in fake_bind.executed)
    }
    assert checked_tables == set(_ALL_TABLES)

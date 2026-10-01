"""FX-56: unit tests for migration 504030474987's own downgrade guard.

Mirrors `test_migration_source_mapping_downgrade_guard.py`'s own
pattern exactly: loads `downgrade()` directly from the migration file
(via `importlib.util`, not a dotted import -- `alembic/versions/` has
no `__init__.py`) and replaces `alembic.op`'s methods with recording
stubs, so the guard's own logic can be asserted against without a
real database. This does NOT duplicate the live-Postgres up/down/up
round-trip (and the real-insert guard-firing check) already run
manually against the real dev database for this story -- it proves
the guard ITSELF (the condition it checks, which tables it blames, and
that it runs BEFORE any destructive DDL) rather than merely that
today's dev database happens to be in a state the guard allows.
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
    / "504030474987_add_news_evidence_tables.py"
)

_TABLES = ("news_item_vintages", "news_source_mappings", "news_items")


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fx56_news_tables_migration", _MIGRATION_PATH)
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
    def __init__(self, row_counts: dict[str, int]) -> None:
        self._row_counts = row_counts
        self.executed: list[str] = []

    def execute(self, clause: object, *args: object, **kwargs: object) -> _FakeResult:
        sql = str(clause)
        self.executed.append(sql)
        for table, count in self._row_counts.items():
            if table in sql:
                return _FakeResult(count)
        raise AssertionError(f"unexpected query: {sql!r}")


@pytest.fixture
def recorded_op_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"drop_index": [], "drop_table": []}
    for name in calls:

        def _recorder(*args: object, _name: str = name, **kwargs: object) -> None:
            calls[_name].append({"args": args, "kwargs": kwargs})

        monkeypatch.setattr(op, name, _recorder)
    return calls


def _patch_bind(monkeypatch: pytest.MonkeyPatch, row_counts: dict[str, int]) -> _FakeBind:
    fake_bind = _FakeBind(row_counts)
    monkeypatch.setattr(op, "get_bind", lambda: fake_bind)
    return fake_bind


def test_downgrade_refuses_when_any_news_table_has_data(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    _patch_bind(
        monkeypatch,
        {"news_items": 0, "news_source_mappings": 0, "news_item_vintages": 3},
    )
    migration = _load_migration()

    with pytest.raises(RuntimeError, match="news_item_vintages"):
        migration.downgrade()

    # The guard must run BEFORE any destructive DDL -- nothing dropped.
    assert all(len(v) == 0 for v in recorded_op_calls.values())


def test_downgrade_refuses_and_names_every_non_empty_table(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    _patch_bind(
        monkeypatch,
        {"news_items": 5, "news_source_mappings": 5, "news_item_vintages": 7},
    )
    migration = _load_migration()

    with pytest.raises(RuntimeError) as excinfo:
        migration.downgrade()

    message = str(excinfo.value)
    for table in _TABLES:
        assert table in message
    assert "permanent limitation" in message
    assert "restore from a backup" in message.lower()


def test_downgrade_proceeds_when_all_three_tables_are_empty(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    _patch_bind(
        monkeypatch,
        {"news_items": 0, "news_source_mappings": 0, "news_item_vintages": 0},
    )
    migration = _load_migration()

    migration.downgrade()  # must not raise

    assert recorded_op_calls["drop_table"] == [
        {"args": ("news_item_vintages",), "kwargs": {}},
        {"args": ("news_source_mappings",), "kwargs": {}},
        {"args": ("news_items",), "kwargs": {}},
    ]


def test_downgrade_checks_all_three_tables_specifically(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    fake_bind = _patch_bind(
        monkeypatch,
        {"news_items": 0, "news_source_mappings": 0, "news_item_vintages": 0},
    )
    migration = _load_migration()

    migration.downgrade()

    for table in _TABLES:
        assert any(table in sql for sql in fake_bind.executed)

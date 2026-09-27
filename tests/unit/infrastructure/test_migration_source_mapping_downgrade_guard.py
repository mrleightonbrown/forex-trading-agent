"""FX-52AH.1: unit tests for migration df99b7796566's own downgrade
guard (added by this story -- FX-52AH's original version of this
migration shipped with no guard at all, on the mistaken assumption
that downgrading a wholly-new, independent table can never lose
meaningful data; see the migration's own module docstring for the
correction).

Mirrors `test_migration_harden_economic_event_identity.py`'s own
pattern exactly: loads `downgrade()` directly from the migration file
(via `importlib.util`, not a dotted import -- `alembic/versions/` has
no `__init__.py`) and replaces `alembic.op`'s methods with recording
stubs, so the guard's own logic can be asserted against without a real
database. This does NOT duplicate the live-Postgres up/down/up
round-trip (and the real-insert guard-firing check) already run
manually against the real dev database for this story -- it proves the
guard ITSELF (the condition it checks, the exact table it blames, and
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
    / "df99b7796566_add_economic_event_source_mapping_table.py"
)

_TABLE = "economic_event_source_mappings"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fx52ah_mapping_migration", _MIGRATION_PATH)
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
    def __init__(self, row_count: int) -> None:
        self._row_count = row_count
        self.executed: list[str] = []

    def execute(self, clause: object, *args: object, **kwargs: object) -> _FakeResult:
        self.executed.append(str(clause))
        return _FakeResult(self._row_count)


@pytest.fixture
def recorded_op_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"drop_index": [], "drop_table": []}
    for name in calls:

        def _recorder(*args: object, _name: str = name, **kwargs: object) -> None:
            calls[_name].append({"args": args, "kwargs": kwargs})

        monkeypatch.setattr(op, name, _recorder)
    return calls


def _patch_bind(monkeypatch: pytest.MonkeyPatch, row_count: int) -> _FakeBind:
    fake_bind = _FakeBind(row_count)
    monkeypatch.setattr(op, "get_bind", lambda: fake_bind)
    return fake_bind


def test_downgrade_refuses_when_mapping_table_has_data(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    _patch_bind(monkeypatch, 3)
    migration = _load_migration()

    with pytest.raises(RuntimeError, match=_TABLE):
        migration.downgrade()

    # The guard must run BEFORE any destructive DDL -- nothing dropped.
    assert all(len(v) == 0 for v in recorded_op_calls.values())


def test_downgrade_error_message_explains_the_permanent_limitation(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    _patch_bind(monkeypatch, 7)
    migration = _load_migration()

    with pytest.raises(RuntimeError) as excinfo:
        migration.downgrade()

    message = str(excinfo.value)
    assert "7 row(s)" in message
    assert _TABLE in message
    assert "permanent limitation" in message
    assert "restore from a backup" in message.lower()


def test_downgrade_proceeds_when_mapping_table_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    _patch_bind(monkeypatch, 0)
    migration = _load_migration()

    migration.downgrade()  # must not raise

    assert len(recorded_op_calls["drop_table"]) == 1
    assert recorded_op_calls["drop_table"][0]["args"][0] == _TABLE


def test_downgrade_checks_the_mapping_table_specifically(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    fake_bind = _patch_bind(monkeypatch, 0)
    migration = _load_migration()

    migration.downgrade()

    assert any(_TABLE in sql for sql in fake_bind.executed)

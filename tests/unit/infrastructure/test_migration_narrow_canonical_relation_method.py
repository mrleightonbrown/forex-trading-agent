"""FX-58H: unit tests for migration 3fe8c43841ee's own precheck and
constraint-replacement logic.

Mirrors `test_migration_news_evidence_tables_downgrade_guard.py`'s own
pattern exactly: loads `upgrade()`/`downgrade()` directly from the
migration file (via `importlib.util`, not a dotted import --
`alembic/versions/` has no `__init__.py`) and replaces `alembic.op`'s
methods with recording stubs, so the precheck/constraint-swap logic
can be asserted against without a real database. Complements the
live-Postgres round-trip verified manually against the real dev
database for this story (see `docs/DECISIONS.md`'s FX-58H entry) and
`tests/integration/test_migration_narrow_canonical_relation_method.py`
for the genuine CHECK-constraint-rejection proof that only a real
Postgres can provide.
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
    / "3fe8c43841ee_narrow_canonical_relation_method_to_.py"
)

_TABLE = "news_canonical_relation_vintages"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fx58h_narrow_method_migration", _MIGRATION_PATH)
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
        self.executed: list[tuple[str, dict[str, object]]] = []

    def execute(self, clause: object, params: dict[str, object] | None = None) -> _FakeResult:
        self.executed.append((str(clause), params or {}))
        return _FakeResult(self._row_count)


@pytest.fixture
def recorded_op_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"drop_constraint": [], "create_check_constraint": []}
    for name in calls:

        def _recorder(*args: object, _name: str = name, **kwargs: object) -> None:
            calls[_name].append({"args": args, "kwargs": kwargs})

        monkeypatch.setattr(op, name, _recorder)
    return calls


def _patch_bind(monkeypatch: pytest.MonkeyPatch, row_count: int) -> _FakeBind:
    fake_bind = _FakeBind(row_count)
    monkeypatch.setattr(op, "get_bind", lambda: fake_bind)
    return fake_bind


def test_upgrade_succeeds_when_zero_unsafe_method_rows_exist(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    _patch_bind(monkeypatch, 0)
    migration = _load_migration()

    migration.upgrade()  # must not raise

    assert recorded_op_calls["drop_constraint"] == [
        {
            "args": ("ck_ncrv_automatic_method_is_same_story", _TABLE),
            "kwargs": {"type_": "check"},
        },
        {"args": ("ck_ncrv_method", _TABLE), "kwargs": {"type_": "check"}},
    ]
    assert len(recorded_op_calls["create_check_constraint"]) == 2


def test_upgrade_refuses_before_any_constraint_ddl_when_unsafe_rows_exist(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    _patch_bind(monkeypatch, 1)
    migration = _load_migration()

    with pytest.raises(RuntimeError, match="EXACT_HEADLINE_AND_SUMMARY"):
        migration.upgrade()

    # The precheck must run BEFORE any destructive constraint DDL.
    assert recorded_op_calls["drop_constraint"] == []
    assert recorded_op_calls["create_check_constraint"] == []


def test_upgrade_precheck_queries_the_exact_unsafe_method(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    fake_bind = _patch_bind(monkeypatch, 0)
    migration = _load_migration()

    migration.upgrade()

    assert len(fake_bind.executed) == 1
    sql, params = fake_bind.executed[0]
    assert _TABLE in sql
    assert params == {"method": "EXACT_HEADLINE_AND_SUMMARY"}


def test_downgrade_restores_the_wider_method_constraint(
    monkeypatch: pytest.MonkeyPatch,
    recorded_op_calls: dict[str, list[Any]],
) -> None:
    _patch_bind(monkeypatch, 0)  # downgrade never checks row counts
    migration = _load_migration()

    migration.downgrade()  # must not raise, regardless of data

    assert recorded_op_calls["drop_constraint"] == [
        {
            "args": ("ck_ncrv_automatic_method_is_same_story", _TABLE),
            "kwargs": {"type_": "check"},
        },
        {"args": ("ck_ncrv_method", _TABLE), "kwargs": {"type_": "check"}},
    ]
    create_calls = recorded_op_calls["create_check_constraint"]
    assert len(create_calls) == 2
    method_call_sql = create_calls[0]["args"][2]
    assert "EXACT_HEADLINE_AND_SUMMARY" in method_call_sql

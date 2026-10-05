"""FX-57E0: unit tests for migration 73b1423a5949's own cumulative
backfill helper and downgrade guard.

Mirrors `test_migration_news_evidence_tables_downgrade_guard.py`'s own
pattern exactly: loads the migration directly (via `importlib.util`,
not a dotted import -- `alembic/versions/` has no `__init__.py`) and
replaces `alembic.op`'s methods with recording/faking stubs, so the
guard's own logic can be asserted against without a real database.
This does NOT duplicate the live-Postgres upgrade/downgrade/re-upgrade
round-trip already run manually against the real 230-row dev database
for this story -- it proves the CUMULATIVE BACKFILL RULE itself (never
merely `[that row's own source_channel]`) and the downgrade guard's
own per-row, not blanket, condition.
"""

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from alembic import op

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "73b1423a5949_add_observed_source_channels_to_news_.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "fx57e0_observed_channels_migration", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- _compute_cumulative_channels: pure function, no DB needed -------------


@dataclass(frozen=True, slots=True)
class _Row:
    id: str
    news_item_key: str
    revision_sequence: int
    source_channel: str


def test_single_channel_item_gets_singleton_cumulative_set() -> None:
    migration = _load_migration()
    rows = [_Row("v0", "FED:abc", 0, "press_monetary")]
    result = migration._compute_cumulative_channels(rows)
    assert result == [("v0", ["press_monetary"])]


def test_cumulative_set_grows_across_revisions_never_just_the_latest_row() -> None:
    # FX-57E0 Section 16: must NOT simply set every historical row to
    # [that row's own source_channel] -- revision 1's own cumulative
    # set must include revision 0's channel too.
    migration = _load_migration()
    rows = [
        _Row("v0", "STATCAN:x", 0, "statcan_prices"),
        _Row("v1", "STATCAN:x", 1, "statcan_economic_accounts"),
    ]
    result = migration._compute_cumulative_channels(rows)
    assert result == [
        ("v0", ["statcan_prices"]),
        ("v1", ["statcan_economic_accounts", "statcan_prices"]),
    ]


def test_cumulative_set_is_canonicalized_sorted_and_deduped() -> None:
    migration = _load_migration()
    rows = [
        _Row("v0", "STATCAN:y", 0, "statcan_prices"),
        _Row("v1", "STATCAN:y", 1, "statcan_prices"),  # same channel again
        _Row("v2", "STATCAN:y", 2, "statcan_labour"),
    ]
    result = migration._compute_cumulative_channels(rows)
    assert result == [
        ("v0", ["statcan_prices"]),
        ("v1", ["statcan_prices"]),
        ("v2", ["statcan_labour", "statcan_prices"]),
    ]


def test_cumulative_set_is_scoped_per_item_never_leaks_across_items() -> None:
    migration = _load_migration()
    rows = [
        _Row("v0", "FED:a", 0, "press_monetary"),
        _Row("v1", "ECB:b", 0, "ecb_press"),
    ]
    result = migration._compute_cumulative_channels(rows)
    assert result == [
        ("v0", ["press_monetary"]),
        ("v1", ["ecb_press"]),
    ]


# --- downgrade guard: real DB interaction mocked via FakeBind ---------------


class _FakeOffendingResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


@dataclass(frozen=True, slots=True)
class _OffendingRow:
    news_item_key: str
    revision_sequence: int


class _FakeBind:
    def __init__(self, offending_rows: list[Any]) -> None:
        self._offending_rows = offending_rows
        self.executed: list[str] = []

    def execute(self, clause: object, *args: object, **kwargs: object) -> _FakeOffendingResult:
        self.executed.append(str(clause))
        return _FakeOffendingResult(self._offending_rows)


@pytest.fixture
def recorded_drop_column(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []

    def _recorder(*args: object, **kwargs: object) -> None:
        calls.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(op, "drop_column", _recorder)
    return calls


def test_downgrade_proceeds_when_every_row_is_single_channel(
    monkeypatch: pytest.MonkeyPatch, recorded_drop_column: list[Any]
) -> None:
    fake_bind = _FakeBind(offending_rows=[])
    monkeypatch.setattr(op, "get_bind", lambda: fake_bind)
    migration = _load_migration()

    migration.downgrade()  # must not raise

    assert recorded_drop_column == [
        {"args": ("news_item_vintages", "observed_source_channels"), "kwargs": {}}
    ]
    assert any("jsonb_array_length" in sql for sql in fake_bind.executed)


def test_downgrade_refuses_when_any_row_carries_more_than_one_channel(
    monkeypatch: pytest.MonkeyPatch, recorded_drop_column: list[Any]
) -> None:
    fake_bind = _FakeBind(
        offending_rows=[_OffendingRow("STATCAN:x", 1), _OffendingRow("STATCAN:y", 0)]
    )
    monkeypatch.setattr(op, "get_bind", lambda: fake_bind)
    migration = _load_migration()

    with pytest.raises(RuntimeError) as excinfo:
        migration.downgrade()

    message = str(excinfo.value)
    assert "STATCAN:x#1" in message
    assert "STATCAN:y#0" in message
    assert "permanent limitation" in message
    assert "restore from a backup" in message.lower()
    # The guard must run BEFORE any destructive DDL -- nothing dropped.
    assert recorded_drop_column == []

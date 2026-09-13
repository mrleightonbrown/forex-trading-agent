# Decisions

Lightweight running log of technical decisions. Once a decision is significant
and stable enough to need a fuller record (context/options/consequences),
promote it to `docs/adr/NNNN-title.md`.

## 2026-09-12 — Toolchain and dependency stack

**Decision:**

- Python 3.12, managed via `uv` (provisioned with `uv python install 3.12`,
  not the system/Homebrew Python).
- Package/dependency manager: `uv` (`pyproject.toml` + `uv.lock`). Installed
  via the official standalone installer (`astral.sh/uv/install.sh`), not
  Homebrew — see note below.
- Web framework: FastAPI (per CLAUDE.md).
- Database: PostgreSQL, accessed via SQLAlchemy 2 async engine, driver
  `asyncpg`. Migrations via Alembic.
- HTTP client for the OANDA Practice API adapter: `httpx` (async).
- Config loading: `pydantic-settings`, one typed `Settings` object that
  validates `TRADING_MODE=PAPER`, `BROKER_ENVIRONMENT=PRACTICE`,
  `LIVE_TRADING_COMPILED=false` at startup and fails closed otherwise.
- Lint + format: Ruff (single tool, replaces Black/Flake8/isort).
- Type checking: mypy.
- Testing: pytest, pytest-asyncio, pytest-cov, httpx `AsyncClient` for API
  tests.
- Local enforcement: pre-commit hooks (ruff lint, ruff format, mypy, basic
  hygiene, `detect-private-key`).
- CI: GitHub Actions — lint, type-check, pytest (with a Postgres service
  container) on push/PR.

**Why:** matches CLAUDE.md's fixed technologies (FastAPI, PostgreSQL,
SQLAlchemy 2, Alembic, Docker, pytest, OANDA Practice API) and fills the gaps
it deliberately leaves open. `uv` and Ruff chosen for speed and low
config-file overhead; async stack chosen throughout so the FastAPI app,
SQLAlchemy engine, and OANDA client share one concurrency model.

**Note on `uv` installation:** this machine is Intel x86_64 macOS, which
Homebrew stopped shipping prebuilt bottles for as of August 2025. `brew
install uv` falls back to building from source, which requires Xcode Command
Line Tools. Installed via `uv`'s own standalone installer script instead,
which ships a prebuilt binary — no compiler needed. Installed to
`~/.local/bin`, added to `PATH` via `~/.zprofile`.

## 2026-09-12 — FX-1: PostgreSQL primary key and timestamp conventions

**Decision:** every future table's primary key is a server-generated UUID
(`gen_random_uuid()`, requiring the `pgcrypto` extension), via a shared
`UUIDPrimaryKeyMixin`. Every table also gets `created_at`/`updated_at` as
`TIMESTAMPTZ`, populated server-side by Postgres, via a shared
`TimestampMixin`. Both live in
`forex_agent.infrastructure.db.mixins`.

**Why:** UUIDs avoid leaking row-count/ordering information (relevant for a
financial system) and need no coordination across services or replayed
backtests. Server-side, tz-aware timestamps directly enforce CLAUDE.md's
"All persisted timestamps use timezone-aware UTC values. Naive datetimes
must be rejected." — the column type is `TIMESTAMPTZ` and the value is never
supplied by application code, so a naive datetime can't reach the column in
the first place.

**Also recorded:** `asyncio_default_fixture_loop_scope` /
`asyncio_default_test_loop_scope` are both set to `"session"` in
`pyproject.toml`. Without this, pytest-asyncio's default per-test-function
event loop breaks `get_engine()`'s cached singleton engine (correct in
production, where one event loop lives for the process's whole lifetime) —
its asyncpg connections stay bound to whichever loop created them, so the
next test's loop can't use them. A session-scoped test loop matches
production's actual loop lifetime.

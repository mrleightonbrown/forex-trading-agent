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

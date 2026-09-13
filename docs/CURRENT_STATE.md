# Current State

_Last updated: 2026-09-13 (FX-2)_

## What exists

- Repository scaffolding: `apps/application/domain/infrastructure` package
  layout under `src/forex_agent/`, `tests/{unit,integration,contract,replay,golden_data}`,
  `docs/{adr,strategy-specifications,runbooks}`.
- Toolchain: Python 3.12 via `uv`, `pyproject.toml` with Ruff + mypy + pytest
  configured. See [DECISIONS.md](DECISIONS.md).
- `Settings` (pydantic-settings) that fails closed if trading mode / broker
  environment / live-trading-compiled would ever permit live trading.
- Minimal FastAPI app (`forex_agent.apps.api.main:app`) with a `/health`
  endpoint that reports trading mode and broker environment.
- Async SQLAlchemy engine/session factory and declarative `Base`, no models
  yet.
- Alembic wired to the same `Settings.database_url`. First migration
  (`06755c32d64c`) enables the `pgcrypto` extension; verified up/down/up
  end-to-end against live Postgres.
- `UUIDPrimaryKeyMixin` and `TimestampMixin`
  (`forex_agent.infrastructure.db.mixins`) — the PK and timestamp
  conventions every future table inherits. Covered by an integration test
  (`tests/integration/test_db_mixins.py`) against a throwaway table, proving
  server-generated UUIDs and tz-aware `TIMESTAMPTZ` round-trip correctly.
- `docker-compose.yml` for local PostgreSQL.
- Pre-commit hooks (ruff, mypy, hygiene, secret detection) and a GitHub
  Actions CI workflow (lint, type-check, pytest against a Postgres service
  container).
- Domain primitives (`forex_agent.domain`): `Instrument`, `Price` (bid/ask,
  with `entry_price`/`exit_price` per `TradeSide`), `Units`, `Money`,
  `UtcTimestamp` — all `Decimal`-based, all immutable, zero dependency on
  FastAPI/SQLAlchemy/OANDA/HTTP clients/environment variables. That boundary
  is enforced by an automated contract test
  (`tests/contract/test_domain_boundary.py`), not just review discipline.

## What does not exist yet

- Any actual domain *tables* — only the extension migration and the
  test-only throwaway table exist in the schema so far.
- Broker adapter abstraction / port definitions.
- OANDA Practice API connectivity.
- Historical data ingestion, candle aggregation, data quality checks.
- Strategy framework, backtester, regime detection.
- Any database models or migrations.

## Next

See [NEXT_STEPS.md](NEXT_STEPS.md).

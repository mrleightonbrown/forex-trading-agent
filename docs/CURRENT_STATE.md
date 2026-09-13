# Current State

_Last updated: 2026-09-13 (FX-4)_

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
- `BrokerPort` (`forex_agent.application.ports.broker_port`): a `Protocol`
  for broker connectivity — `get_price`/`get_account_balance` only, no
  order placement (out of scope until Risk Engine/Paper Trading Execution
  is assigned). A typed exception hierarchy
  (`application/ports/exceptions.py`) and an in-memory
  `FakeBrokerPort` (`tests/fakes/broker_port.py`) exist so anything
  depending on this port is testable before FX-4's real OANDA adapter
  lands. Same import-boundary enforcement as domain, via
  `tests/contract/test_application_boundary.py`.
- `OandaBrokerAdapter` (`forex_agent.infrastructure.broker_oanda`): the real
  `BrokerPort` implementation against OANDA's v20 REST practice API, via
  `httpx`. Refuses to operate against anything but the practice host.
  Verified against both a mocked HTTP transport (19 unit tests) and the
  real OANDA practice API (2 live integration tests, auto-skipped when
  OANDA credentials aren't configured — e.g. in CI).
- A local `.env` with real OANDA practice credentials (gitignored, never
  committed) — connectivity confirmed working.

## What does not exist yet

- Any actual domain *tables* — only the extension migration and the
  test-only throwaway table exist in the schema so far.
- Order placement of any kind — `BrokerPort` is read-only by design; see
  `docs/DECISIONS.md` (FX-3).
- Historical candle fetching — `OandaBrokerAdapter` only does live
  price/balance quotes so far.
- OANDA Practice API connectivity.
- Historical data ingestion, candle aggregation, data quality checks.
- Strategy framework, backtester, regime detection.
- Any database models or migrations.

## Next

See [NEXT_STEPS.md](NEXT_STEPS.md).

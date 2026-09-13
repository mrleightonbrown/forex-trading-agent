# Current State

_Last updated: 2026-09-13 (FX-11)_

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
- `Granularity`, `Ohlc`, `Candle` domain value objects (FX-5) — bid *and*
  ask OHLC per candle (spread, per CLAUDE.md), `is_finalized` flag.
- `candles` table (migration `91c1293c5760`) with a unique constraint on
  `(instrument, granularity, start_time)`, plus `CandleRepository`
  (application port) and `SqlAlchemyCandleRepository` — an idempotent
  `upsert_many` via Postgres `ON CONFLICT DO UPDATE`. Verified: repeated
  upsert of the same candle produces one row, not two; a candle finalizing
  (same key, new values) updates in place.

- `MarketDataPort` (`get_candles`), separate from `BrokerPort`, implemented
  by `OandaMarketDataAdapter` against OANDA's `/v3/instruments/.../candles`
  endpoint (no account ID needed for this one). Bounded to what a single
  request can return (OANDA's own 5000-candle cap) — raises
  `CandleRangeTooLargeError` rather than silently truncating; pagination
  for larger backfills isn't built yet.
- `IngestCandles` (`application/use_cases/`) — the first real use case,
  wiring `MarketDataPort.get_candles` to `CandleRepository.upsert_many`.
  Verified against the live OANDA practice API and, separately, that its
  output actually lands in the `candles` table.

- `aggregate_candles` (`forex_agent.domain.candle_aggregation`): pure
  function grouping same-instrument/same-source-granularity candles into
  higher-timeframe buckets (e.g. M1→M5/H1/D).
- `CandleRepository.get_range` (+ `SqlAlchemyCandleRepository`
  implementation) and `AggregateCandles` use case: reads source candles
  back out of `candles`, aggregates, upserts the result — the persistence
  half of FX-7 that the pure function alone didn't cover.

- `Candle` now rejects crossed-market data (ask below bid at open or
  close) — a real gap closed: nothing previously stopped bad provider
  data with `ask < bid` from being persisted.
- `find_gaps` (`forex_agent.domain.candle_gaps`) + `DetectDataGaps` use
  case: reports missing expected candle timestamps in a stored range. No
  market-calendar awareness (weekends/holidays) — callers pass ranges
  already known to be within a trading session.

- `TradeHypothesis`, `Strategy` Protocol, `run_strategy`
  (`forex_agent.domain.strategy`) — the strategy framework. No I/O; lives
  in `domain/` alongside `aggregate_candles`/`find_gaps`. `run_strategy`
  structurally enforces "strategies must only evaluate finalized candles"
  before delegating to a strategy, rather than trusting each
  implementation to check it.

- `run_backtest` (`forex_agent.domain.backtest`): walks candles to a
  `Strategy` one bar at a time (`candles[0:i+1]`, never further) and
  collects the `TradeHypothesis` values produced — the actual look-ahead
  prevention CLAUDE.md requires. Validates one instrument, one
  granularity, strictly ascending timestamps, and that every returned
  hypothesis is timestamped at the current bar. `O(n²)` reslicing,
  known and accepted for now.

- `SimulatedTrade` + `simulate_trades` (`forex_agent.domain.
  trade_simulation`): turns FX-10's hypotheses into simulated round-trip
  trades. Exit rule: close-and-reverse on an opposite-direction
  hypothesis, same-direction repeat is a no-op, still-open position
  force-closed at the end. `pnl` is a raw price delta per unit of
  base-currency notional — no position sizing yet.

## What does not exist yet

- Any concrete strategy implementation — FX-9 built the framework only.
- Position sizing / account-currency P&L — `simulate_trades`' `pnl` is
  per-unit only; multiplying by real position size is Risk Engine
  territory, not decided yet.

- Order placement of any kind — `BrokerPort` is read-only by design; see
  `docs/DECISIONS.md` (FX-3).
- Pagination for candle backfills larger than 5000 candles at a given
  granularity — `IngestCandles`/`get_candles` cover one bounded request.
- Anything that actually calls `IngestCandles` on a schedule or via a
  CLI/API trigger — it exists and is tested, but nothing invokes it yet.
- OANDA Practice API connectivity.
- Historical data ingestion, candle aggregation, data quality checks.
- Strategy framework, backtester, regime detection.
- Any database models or migrations.

## Next

See [NEXT_STEPS.md](NEXT_STEPS.md).

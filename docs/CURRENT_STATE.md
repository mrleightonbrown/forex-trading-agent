# Current State

_Last updated: 2026-09-13 (FX-11H)_

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
- Async SQLAlchemy engine/session factory and declarative `Base`.
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
  OANDA credentials aren't configured — e.g. in CI). Note: these live
  tests are occasionally flaky when the full suite runs back-to-back
  (an intermittent 401 from OANDA) — they pass reliably in isolation.
  Root cause undetermined.
- A local `.env` with real OANDA practice credentials (gitignored, never
  committed) — connectivity confirmed working.
- `Granularity`, `Ohlc`, `Candle` domain value objects — bid *and* ask
  OHLC per candle (spread, per CLAUDE.md), `is_finalized` flag. `Candle`
  rejects crossed-market data (ask below bid at open or close).
- `candles` table (migration `91c1293c5760`) with a unique constraint on
  `(instrument, granularity, start_time)`, plus `CandleRepository`
  (application port: `upsert_many`, `get_range`) and
  `SqlAlchemyCandleRepository` — idempotent upsert via Postgres
  `ON CONFLICT DO UPDATE`.
- `MarketDataPort` (`get_candles`), separate from `BrokerPort`, implemented
  by `OandaMarketDataAdapter` against OANDA's `/v3/instruments/.../candles`
  endpoint (no account ID needed for this one). Bounded to what a single
  request can return (OANDA's own 5000-candle cap) — raises
  `CandleRangeTooLargeError` rather than silently truncating; pagination
  for larger backfills isn't built yet.
- `IngestCandles` and `AggregateCandles` (`application/use_cases/`): the
  former wires `MarketDataPort.get_candles` to
  `CandleRepository.upsert_many`; the latter reads a range via
  `get_range`, aggregates via the pure `aggregate_candles` domain
  function, and upserts the result.
- `find_gaps` (`forex_agent.domain.candle_gaps`) + `DetectDataGaps` use
  case: reports missing expected candle timestamps in a stored range.
  Rejects candles spanning more than one instrument (FX-11H — a candle
  from a different instrument could previously mask a real gap). No
  market-calendar awareness (weekends/holidays) — callers pass ranges
  already known to be within a trading session.
- `TradeHypothesis`, `Strategy` Protocol, `run_strategy`
  (`forex_agent.domain.strategy`) — the strategy framework. No I/O; lives
  in `domain/` alongside `aggregate_candles`/`find_gaps`. `run_strategy`
  structurally enforces "strategies must only evaluate finalized candles"
  before delegating to a strategy, rather than trusting each
  implementation to check it. No concrete strategy implementation exists.
- `run_backtest` (`forex_agent.domain.backtest`): walks candles to a
  `Strategy` one bar at a time (`candles[0:i+1]`, never further) and
  collects the `TradeHypothesis` values produced — the actual look-ahead
  prevention CLAUDE.md requires. Validates one instrument, one
  granularity, strictly ascending timestamps, that every returned
  hypothesis is timestamped at the current bar, and (FX-11H) that every
  returned hypothesis is for the same instrument as the candles being
  replayed. `O(n²)` reslicing, known and accepted for now.
- `SimulatedTrade` + `simulate_trades` (`forex_agent.domain.
  trade_simulation`): turns a backtest's hypotheses into simulated
  round-trip trades. **Next-bar execution (FX-11H)**: a hypothesis
  generated from bar N executes at bar N+1's open — never bar N's own
  close, which is unrealistic (that price is only known once the bar has
  already closed). Exit rule: close-and-reverse on an opposite-direction
  hypothesis (also executed at the next bar's open); same-direction
  repeat is a no-op; a hypothesis generated on the final candle in the
  dataset cannot execute at all (no next bar exists) and is silently
  not actionable; anything still open when the hypothesis list ends is
  force-closed using the *last* candle's close (there is no bar beyond
  the dataset to get a next-bar open from). `pnl` is a raw price delta
  per unit of base-currency notional — no position sizing yet.
  `simulate_trades` also now validates its inputs defensively (FX-11H):
  rejects mixed instrument/granularity, non-ascending or duplicate
  timestamps, non-finalized candles, out-of-order/duplicate hypothesis
  timestamps, hypothesis/candle instrument mismatches, and a hypothesis
  timestamp with no matching candle — rather than assuming it's only
  ever called with `run_backtest`'s own well-formed output.

## What does not exist yet

- Any concrete strategy implementation — the framework only.
- Regime detection.
- Position sizing / account-currency P&L — `simulate_trades`' `pnl` is
  per-unit only; multiplying by real position size is Risk Engine
  territory, not decided yet.
- Order placement of any kind — `BrokerPort` is read-only by design; see
  `docs/DECISIONS.md` (FX-3).
- Pagination for candle backfills larger than 5000 candles at a given
  granularity — `IngestCandles`/`get_candles` cover one bounded request.
- Anything that actually calls `IngestCandles`/`AggregateCandles` on a
  schedule or via a CLI/API trigger — they exist and are tested, but
  nothing invokes them yet.
- Backtest performance optimization for large candle sets (`O(n²)`
  reslicing in `run_backtest`) — not needed until real strategies exist.

## Next

See [NEXT_STEPS.md](NEXT_STEPS.md).

# Next Steps

Per CLAUDE.md's current phase (M0-M4) priority order:

1. ~~Repository foundation~~ — scaffolding complete (FX-0).
2. ~~PostgreSQL~~ — complete (FX-1): first migration (`pgcrypto`), UUID PK +
   tz-aware timestamp mixins, verified up/down/up against live Postgres.
3. ~~Domain primitives~~ — complete (FX-2): `Instrument`, `Price` (bid/ask,
   entry/exit per side), `Units`, `Money`, `UtcTimestamp`, all `Decimal`/UTC
   as required; domain-boundary purity enforced by an automated contract
   test.
4. ~~Broker adapter abstraction~~ — complete (FX-3): `BrokerPort` Protocol
   (`get_price`, `get_account_balance`), exception hierarchy, `FakeBrokerPort`
   test double. Deliberately no order-placement method yet — see
   `docs/DECISIONS.md`.
5. ~~OANDA Practice API connectivity~~ — complete (FX-4): `OandaBrokerAdapter`
   implements `BrokerPort` via `httpx` against the real practice API,
   refuses any non-practice host, verified against both a mocked transport
   and the live practice API.
6. Historical data ingestion — split into two stories:
   - ~~FX-5: Candle domain primitive + persistence~~ — complete.
     `Granularity`/`Ohlc`/`Candle`, `candles` table (unique constraint on
     instrument/granularity/start_time), `CandleRepository` port +
     idempotent SQLAlchemy upsert implementation.
   - FX-6: OANDA historical candle fetching — extend `BrokerPort` (or add a
     new port) for `get_candles`, implement in `OandaBrokerAdapter`, wire
     it to `CandleRepository.upsert_many` as the actual ingestion path.
7. Candle aggregation.
8. Data quality.
9. Strategy framework.
10. Backtester (must prevent look-ahead bias, evaluate only finalized
    candles, include spread, use bid/ask correctly per side).
11. Regime detection.

Do not start fundamentals, news intelligence, AI decision-making, or live
trading — out of scope until explicitly assigned per CLAUDE.md.

Each of these should be tracked as its own Jira story and worked per
CLAUDE.md's "Development rules" (tests first where practical, smallest
change satisfying acceptance criteria, one story per commit).

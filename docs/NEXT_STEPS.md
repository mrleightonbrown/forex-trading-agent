# Next Steps

Per CLAUDE.md's current phase (M0-M4) priority order:

1. ~~Repository foundation~~ — scaffolding complete (this commit).
2. **PostgreSQL** — first Alembic migration; confirm `docker compose up -d db`
   + `uv run alembic upgrade head` works end to end.
3. **Domain primitives** — value objects for instrument, price (bid/ask,
   Decimal), units (Decimal), timestamps (tz-aware UTC only, reject naive).
4. Broker adapter abstraction — define the `application/ports` interface a
   broker adapter must implement (place order, get price, get account
   state), independent of any specific broker.
5. OANDA Practice API connectivity — implement the port from (4) under
   `infrastructure/broker_oanda`, using `httpx` against
   `OANDA_API_BASE_URL`. Practice environment only — see CLAUDE.md safety
   rules.
6. Historical data ingestion.
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

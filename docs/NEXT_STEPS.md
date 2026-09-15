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
6. ~~Historical data ingestion~~ — complete, split into two stories:
   - FX-5: `Granularity`/`Ohlc`/`Candle`, `candles` table (unique
     constraint on instrument/granularity/start_time), `CandleRepository`
     port + idempotent SQLAlchemy upsert implementation.
   - FX-6: `MarketDataPort` (separate from `BrokerPort`), implemented by
     `OandaMarketDataAdapter`; `IngestCandles` use case wiring it to
     `CandleRepository.upsert_many`. Bounded to one request (≤5000
     candles) — pagination for larger backfills is explicit future work,
     not yet its own story.
7. ~~Candle aggregation~~ — complete (FX-7): pure `aggregate_candles`
   domain function, plus `CandleRepository.get_range` and the
   `AggregateCandles` use case wiring read → aggregate → persist.
8. ~~Data quality~~ — complete (FX-8): crossed-market validation on
   `Candle` (ask must not be below bid at open/close), plus pure
   `find_gaps` + `DetectDataGaps` use case for missing-candle detection.
   No market-calendar awareness (weekends/holidays) — callers pass ranges
   already known to be within a trading session.
9. ~~Strategy framework~~ — complete (FX-9): `TradeHypothesis`, `Strategy`
   Protocol, `run_strategy` (enforces finalized-candles-only structurally,
   not left to each strategy implementation). No concrete strategy yet —
   that's a separate future story.
10. Backtester — split into two stories:
    - ~~FX-10: backtest engine~~ — complete. `run_backtest` walks candles
      to a `Strategy` one bar at a time (the actual look-ahead-bias
      prevention, not just a naming convention); rejects mixed
      instrument/granularity, non-ascending timestamps, and a hypothesis
      timestamped anywhere but the current bar. Finalized-only inherited
      from `run_strategy`.
    - ~~FX-11: trade/P&L simulation~~ — complete. Exit rule: close-and-
      reverse on an opposite-direction hypothesis; same-direction repeat
      is a no-op; still-open position force-closed at the end.
      `simulate_trades` prices entry/exit via `Price.entry_price`/
      `exit_price` (FX-2, not reimplemented). `pnl` is a raw price delta
      per unit of base-currency notional — no position sizing (Risk
      Engine territory, not decided yet).
    - ~~FX-11H: backtest correctness hardening~~ — complete. Fixed a real
      look-ahead-adjacent bug ChatGPT's review caught: `simulate_trades`
      was executing at the *same* candle's close that generated the
      signal — unrealistic, since that price is only known once the
      candle has already closed. Now executes at the *next* candle's open.
      Also added defensive input validation `simulate_trades` was missing,
      an instrument-mismatch guard on `run_backtest`, and an
      instrument-mismatch guard on `find_gaps`. See `docs/DECISIONS.md`
      for the full reasoning.
11. ~~Regime detection~~ — complete (FX-12, hardened FX-12H):
    `classify_regime(candles) -> TrendRegime` (`TRENDING`/`RANGING`), via
    Wilder's ADX on a synthetic midpoint approximation (bid/ask OHLC
    averaged — not a true provider mid price; see `docs/DECISIONS.md`).
    Requires ≥ `2 × period` candles; `period ≥ 1` and `threshold` in
    [0, 100] are validated. Threshold defaults to 25 (Wilder's own
    convention), both configurable. Cross-checked against an
    independently written reference implementation of the same
    algorithm, not just threshold behavior. Extracted the candle-series
    validation (one instrument, one granularity, strictly ascending) —
    previously duplicated in `run_backtest` and `simulate_trades` — into
    `candle_series.require_consistent_series`, now shared by all three.

This closes out CLAUDE.md's current M0–M4 phase (items 1–11).

## Now underway: concrete strategy suite (FX-EPIC-03 + FX-EPIC-04)

Full roadmap, rationale, and epic mapping recorded in `docs/DECISIONS.md`
(2026-09-15 entries) — not repeated here. Proposed order:
- ~~Strategy metadata/hypothesis enrichment~~ — complete (FX-13):
  `TradeHypothesis` gained `timeframe`/`strategy_key`/`strategy_version`/
  `parameters` (all required), plus a `params_from_dict` helper.
  `parameters` is a tuple of string pairs, not a `dict`, so
  `TradeHypothesis` stays hashable.
- ~~EMA Trend v1 (`ema_crossover_v1`)~~ — complete (FX-14): the reference
  strategy. `EmaCrossoverStrategy` (`domain/strategies/ema_crossover.py`),
  20/50 SMA-seeded EMA crossover on synthetic-midpoint close, no ADX/RSI/
  confirmation/optimization, exactly per spec. Verified against an
  independent reference EMA calculation, through `run_backtest` +
  `simulate_trades` on an engineered synthetic series with hand-verified
  execution prices, and against live OANDA practice candles.
- ~~Close-Channel Breakout v1 (`close_channel_breakout_v1`)~~ — complete
  (FX-15). `CloseChannelBreakoutStrategy` (`domain/strategies/
  close_channel_breakout.py`): LONG when close exceeds the highest close
  of the `lookback` bars strictly before it, SHORT when below the lowest
  — close-based, not high/low, same FX-12H reasoning as before. Fires
  every qualifying bar (not edge-only); FX-11's same-direction no-op
  already absorbs repeats safely. Verified through `run_backtest` +
  `simulate_trades` on an engineered series with hand-traced prices
  (including a same-candle entry/force-close edge case), and against
  live OANDA practice candles.
- ~~Time-Series Momentum v1 (`time_series_momentum_v1`)~~ — complete
  (FX-16). `TimeSeriesMomentumStrategy` (`domain/strategies/
  time_series_momentum.py`): `return = current_close / close_N_bars_ago -
  1` against a single symmetric `threshold` (default 0, the pure
  baseline — a deadband is just `threshold > 0`, no constructor change
  needed). Fires every qualifying bar, same precedent as FX-15. Verified
  through `run_backtest` + `simulate_trades` on an engineered series that
  *naturally* (not contrived) exercised FX-11H's final-bar-not-actionable
  rule, and against live OANDA practice candles.
- ~~Backtest performance metrics~~ — complete (FX-17). `compute_metrics(
  trades) -> BacktestMetrics` (`domain/backtest_metrics.py`): trade/win/
  loss/breakeven counts, win rate, average win/loss, expectancy, profit
  factor, total P&L, max drawdown, Sharpe/Sortino (explicitly *not*
  annualized percentage-return ratios — per-unit `Money` P&L only, no
  position sizing yet). Deliberately composable, not a grouping engine:
  segmentation (long vs short, year/quarter, later trending vs ranging)
  is filtering the trade list before calling, not a feature of the
  function itself. Verified against an independent reference calculation
  for every field, including Sharpe/Sortino/max-drawdown.
- `TargetPosition`/FLAT semantics → Mean Reversion v1 → Volatility
  Expansion v1 → regime-conditioned experiments → Multi-timeframe Trend
  v1. None of this is built yet.

Do not start fundamentals, news intelligence, AI decision-making, or live
trading — out of scope until explicitly assigned per CLAUDE.md. The same
goes for the downstream epics not in this list at all (Decision Engine,
Risk Engine, Paper Trading Execution, Performance Analytics, Shadow
Trading) — none are part of the current phase.

Each of these should be tracked as its own Jira story and worked per
CLAUDE.md's "Development rules" (tests first where practical, smallest
change satisfying acceptance criteria, one story per commit).

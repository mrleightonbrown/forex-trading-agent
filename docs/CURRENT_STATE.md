# Current State

_Last updated: 2026-09-15 (FX-25H.1)_

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
  rejects crossed-market data (ask below bid at open or close). `Candle`
  also carries `source: CandleSource` (`NATIVE`/`AGGREGATED`, FX-24,
  defaults to `NATIVE`) — provenance, not just descriptive: see
  `candles` table below.
- `candles` table (migrations `91c1293c5760`, `635084cc3eb0`) with a
  unique constraint on `(instrument, granularity, start_time, source)`
  — `source` included since FX-24, so a native candle and a
  self-aggregated candle for the same logical slot can coexist in
  storage without colliding in an upsert. Plus `CandleRepository`
  (application port: `upsert_many`, `get_range`) and
  `SqlAlchemyCandleRepository` — idempotent upsert via Postgres
  `ON CONFLICT DO UPDATE`.
- `MarketDataPort` (`get_candles`), separate from `BrokerPort`, implemented
  by `OandaMarketDataAdapter` against OANDA's `/v3/instruments/.../candles`
  endpoint (no account ID needed for this one). Bounded to what a single
  request can return (OANDA's own 5000-candle cap) — raises
  `CandleRangeTooLargeError` rather than silently truncating; pagination
  for larger backfills isn't built yet. Sends `dailyAlignment=17`/
  `alignmentTimezone=America/New_York` explicitly (FX-24, confirmed
  live to already match the practice API's own default) and tags every
  candle `source=NATIVE`.
- `candle_boundary.candle_start_boundary`/`candle_end_time`
  (`forex_agent.domain.candle_boundary`, FX-25H): the one canonical,
  DST-aware definition of "when does a candle of a given granularity
  starting at a given instant actually close" — `H2`/`H3`/`H4`/`H6`/
  `H8`/`H12`/`D` anchor to 17:00 `America/New_York` via `zoneinfo`
  (matching OANDA's own native candles, confirmed live); `H1` and finer
  use plain epoch-floor arithmetic (no DST ambiguity there). Extracted
  after FX-25 independently reimplemented (and got wrong, for the
  fall-back case) its own fixed-duration H4 assumption — both
  `aggregate_candles` and `MultiTimeframeTrendStrategy` now import from
  here rather than each computing candle duration their own way.
- `aggregate_candles` (`forex_agent.domain.candle_aggregation`, FX-7,
  day-aligned bucketing fixed FX-24, completeness check hardened
  FX-25H/FX-25H.1): buckets for day-aligned granularities are DST-aware
  via `candle_boundary`; `H1` and finer are unaffected. A bucket's
  "complete" check (FX-25H) is exact expected-source-start-time-sequence
  matching, not a member count — a member count couldn't distinguish a
  genuinely DST-short bucket from one merely missing data, nor catch a
  duplicate-plus-missing source candle at the right total count (the
  original FX-7 edge case, now closed by the same fix). That expected
  sequence is itself only valid (FX-25H.1) if the last source candle
  lands exactly on the target bucket's own end — nominal duration
  divisibility (e.g. `H6 % H3 == 0`) doesn't guarantee NY wall-clock
  source boundaries stay nested inside the target boundary across a DST
  discontinuity (reproduced directly: an `H3`-sourced `H6` bucket on the
  spring-forward day pulled in an hour of data from outside its own
  canonical end); a bucket whose sources straddle rather than tile it is
  dropped, not the granularity pairing generally. Every aggregated
  candle is tagged `source=AGGREGATED`; mixing `NATIVE` and `AGGREGATED`
  source candles in one call raises, same as mixing instruments or
  granularities.
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
  implementation to check it. `TradeHypothesis` carries full provenance
  (FX-13): `timeframe`, `strategy_key`, `strategy_version`, `parameters`
  (a hashable tuple of string pairs, not a `dict` — `params_from_dict`
  builds it from a strategy's typed params), all required on every
  hypothesis. Its directional field is `target_position: TargetPosition`
  (`forex_agent.domain.target_position`, FX-18) — LONG/SHORT/FLAT,
  distinct from the execution-only `TradeSide` (LONG/SHORT) used by
  `Price`/`SimulatedTrade`: a strategy can ask to be flat, which
  `TradeSide` cannot express.
- `EmaCrossoverStrategy` (`forex_agent.domain.strategies.ema_crossover`,
  `strategy_key="ema_crossover_v1"`) — the first concrete `Strategy`
  (FX-14), and the reference strategy the roadmap in `docs/DECISIONS.md`
  is built around. 20/50 SMA-seeded EMA crossover on synthetic-midpoint
  close, deliberately minimal (no ADX/RSI/confirmation/optimization).
  Fires only on the bar the crossover actually happens, not every bar one
  EMA stays above the other. Verified: against an independent reference
  EMA calculation (same rigor as ADX), through `run_backtest` +
  `simulate_trades` on an engineered synthetic series with hand-verified
  execution prices, and against live OANDA practice candles.
- `CloseChannelBreakoutStrategy` (`forex_agent.domain.strategies.
  close_channel_breakout`, `strategy_key="close_channel_breakout_v1"`) —
  the second concrete `Strategy` (FX-15). LONG when the current close
  exceeds the highest close of the `lookback` bars strictly before it,
  SHORT when below the lowest — close-based, not high/low (FX-12H's
  synthetic-midpoint-extrema caveat applies to highs/lows, not closes).
  Fires every qualifying bar, not just the first breakout — FX-11's
  same-direction no-op absorbs repeats safely, so no edge-detection logic
  was needed. Verified the same way as EMA: through `run_backtest` +
  `simulate_trades` on an engineered series with hand-traced prices
  (including an edge case where entry and end-of-data force-close land on
  the same final candle), and against live OANDA practice candles.
- `TimeSeriesMomentumStrategy` (`forex_agent.domain.strategies.
  time_series_momentum`, `strategy_key="time_series_momentum_v1"`) — the
  third concrete `Strategy` (FX-16). `return = current_close /
  close_N_bars_ago - 1` against a single symmetric `threshold` (default
  `Decimal("0")`, the pure baseline — a deadband is just `threshold > 0`,
  no constructor shape change needed). Fires every qualifying bar, same
  precedent as the close-channel breakout. Verified through
  `run_backtest` + `simulate_trades` on an engineered series that
  *naturally* (not specifically contrived for it) exercised FX-11H's
  final-bar-not-actionable rule — the series' last hypothesis lands on
  the final candle and is correctly dropped — and against live OANDA
  practice candles.
- `MeanReversionStrategy` (`forex_agent.domain.strategies.
  mean_reversion`, `strategy_key="mean_reversion_v1"`) — the fourth
  concrete `Strategy` (FX-19), and the first to actually emit
  `TargetPosition.FLAT` (FX-18) rather than just carrying the renamed
  field. Bollinger-Bands-style z-score: LONG when the current close is
  `entry_threshold` population standard deviations below its own
  `period`-bar rolling mean (oversold), SHORT when that far above
  (overbought), FLAT when the z-score crosses back through zero — a real
  zero-crossing test (same technique as FX-14's EMA crossover), not a
  magnitude deadband, so it implements "exit z=0.0" literally. The
  rolling window includes the current bar (standard Bollinger
  definition, at the cost of a known self-referential-dampening
  trade-off — documented, not treated as a defect); stddev is
  population, not sample. `entry_threshold` must be strictly positive
  (FX-21H.1) — at `0` the FLAT zero-crossing branch would be
  unreachable. Verified against an independently hand-derived
  synthetic series with exact clean z-scores at every relevant bar,
  through `run_backtest` + `simulate_trades` (confirming FLAT-closes-
  without-reopening produces the right trade count end to end), and
  against live OANDA practice candles.
- `VolatilityExpansionBreakoutStrategy` (`forex_agent.domain.strategies.
  volatility_expansion`, `strategy_key="volatility_expansion_breakout_v1"`)
  — the fifth concrete `Strategy` (FX-20). LONG/SHORT when the current
  close breaks a Donchian high/low channel (built from actual highs/
  lows, unlike FX-15's close-based channel — a deliberate reversal,
  since ATR already requires and accepts the midpoint-averaged highs/
  lows anyway) *and* the short-period/long-period ATR ratio is at least
  `expansion_threshold` — a breakout with no expansion, or an expansion
  with no fresh breakout, opens nothing. FLAT when the expansion ends
  (ratio crosses back below `expansion_threshold`, reused directly as
  the exit boundary — no separate deadband parameter, same reasoning as
  FX-19). True Range/Wilder ATR smoothing duplicated locally from
  `regime_detection.py`'s own ADX logic (deliberate, documented, not
  shared via a helper — see `docs/DECISIONS.md`). Verified against an
  independently hand-derived synthetic series covering all five
  `evaluate()` outcomes, through `run_backtest` + `simulate_trades`
  (confirming FLAT-closes-without-reopening end to end), and against
  live OANDA practice candles.
- `MultiTimeframeTrendStrategy` (`forex_agent.domain.strategies.
  multi_timeframe_trend`, `strategy_key="multi_timeframe_trend_v1"`,
  FX-25, H4 visibility canonicalized FX-25H) — the sixth concrete
  `Strategy`, and the first needing two candle series at once. H1
  EMA-crossover entry, gated by H4's own EMA fast/slow *state* (not a
  crossover event): confirmed → `LONG`/`SHORT`; H1 fires but H4
  disagrees (or has insufficient history, or is neutral) → `FLAT`,
  resolving FX-21H's own flagged reversal-vs-FLAT question.
  `Strategy.evaluate(candles: list[Candle])`'s signature is unchanged —
  the full H4 series is a constructor argument, filtered on every call
  to only bars fully closed strictly before the current H1 bar, using
  `candle_boundary.candle_end_time` (FX-25H — the original version used
  a fixed "4 elapsed hours" assumption that disagreed with FX-24's own
  DST-aware logic and was wrong on a fall-back day; proven no-look-ahead
  via a mutation regression, same technique as FX-21H's). Also rejects a
  driving series that isn't `Granularity.H1` (FX-25H). Verified through
  a hand-derived synchronized H1+H4 series covering all four outcomes,
  through `run_backtest` + `simulate_trades`, and against live OANDA
  candles at both granularities. This closes out the original
  strategy-suite roadmap — see `docs/DECISIONS.md`'s FX-25/FX-25H
  entries.
- `RegimeSegmentedTrades` + `segment_trades_by_regime`
  (`forex_agent.domain.regime_segmentation`, FX-21, look-ahead fixed
  FX-21H): performs **entry-regime attribution** — buckets a strategy's
  already-executed `SimulatedTrade`s by the `TrendRegime` (FX-12) in
  effect strictly *before* each trade's `entry_time` (the entry candle
  itself is excluded: only its open, not its high/low/close, is known
  at the instant of entry) — `.trending`/`.ranging`/`.unclassified`
  (the last for trades too early to have `2 * period` candles of prior
  history, the normal case, not an error). This is attribution, not
  regime-*gating*: EMA runs unconditionally and takes every signal it
  normally would; regime only labels completed trades afterward. A true
  gating experiment (which would change which trades occur, and needs
  its own design pass) is a distinct, unbuilt future story. Connects
  `classify_regime` and `compute_metrics` for the first time;
  `compute_metrics` needed no changes, exactly the composable
  segmentation FX-17 was designed for. No strategy was modified —
  regime stays structurally external. First used by
  `tests/replay/test_ema_regime_conditioned.py` (a live-OANDA test
  asserting only structural properties, never a specific winner) to
  produce a real empirical finding, recorded in `docs/DECISIONS.md`.
  Second use (FX-23): `MeanReversionStrategy` vs. `RANGING`, same
  attribution framing, same ~90-day EUR/USD H1 window. Both experiments
  so far found the "obvious" regime pairing underperforming the "wrong"
  one — see `docs/DECISIONS.md` for both tables.
- `AlwaysLongStrategy`, `AlwaysShortStrategy`, `PreviousBarDirectionStrategy`,
  `NoTradeStrategy` (`forex_agent.domain.strategies.control`,
  `strategy_key`s `always_long_v1`/`always_short_v1`/
  `previous_bar_direction_v1`/`no_trade_v1`, FX-22) — control strategies,
  not trading ideas: a no-skill scoreboard every real strategy's
  `compute_metrics` output gets compared against on the same sample.
  Grouped in one file, a deliberate departure from every other
  strategy's one-file-per-strategy convention, since these are a
  matched baseline set. Always-long/always-short combine with FX-11's
  same-direction-no-op rule to become genuine buy-and-hold/sell-and-hold
  baselines (verified: firing every bar still produces exactly one
  trade). `PreviousBarDirectionStrategy` has no lookback or threshold
  (deliberately simpler than FX-16's momentum strategy). `NoTradeStrategy`
  always returns `None` — `compute_metrics` can't even be called on zero
  trades, which is the point.
- `BacktestMetrics` + `compute_metrics` (`forex_agent.domain.
  backtest_metrics`, FX-17): trade/win/loss/breakeven counts, win rate,
  average win/loss, expectancy, profit factor, total P&L, max drawdown,
  Sharpe/Sortino. Sharpe/Sortino are explicitly *not* annualized
  percentage-return ratios — computed on raw per-trade `Money` P&L (no
  position sizing exists yet), useful only for relative comparison
  between strategies on the same instrument/timeframe. Deliberately
  composable: no grouping/segmentation built in — "long vs short" etc. is
  filtering the trade list before calling `compute_metrics`, not a
  feature of the function itself. Requires all trades share one
  `instrument`, not merely one P&L currency (FX-21H.1) — `Instrument`
  equality already implies currency equality, so this is strictly
  stronger and catches e.g. `EUR_USD` + `GBP_USD` (both USD-quoted, but
  not comparable per-unit-notional). Verified against an independent
  reference calculation for every field.
- `run_backtest` (`forex_agent.domain.backtest`): walks candles to a
  `Strategy` one bar at a time (`candles[0:i+1]`, never further) and
  collects the `TradeHypothesis` values produced — the actual look-ahead
  prevention CLAUDE.md requires. Validates one instrument, one
  granularity, strictly ascending timestamps, that every returned
  hypothesis is timestamped at the current bar, that every returned
  hypothesis is for the same instrument as the candles being replayed
  (FX-11H), and that every returned hypothesis's `timeframe` matches the
  candles' granularity (FX-21H.1) — `TradeHypothesis.timeframe` (FX-13)
  is now structurally enforced, not advisory. `O(n²)` reslicing, known
  and accepted for now.
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
  ever called with `run_backtest`'s own well-formed output. Also rejects
  a non-empty `hypotheses` list with empty `candles` (FX-11H.1) rather
  than silently returning `[]`. **FLAT (FX-18):** a third
  `target_position`, distinct from the LONG/SHORT close-and-reverse
  behavior above — a no-op with no open position; with one open, closes
  it at the same next-bar-open execution price and does *not* reopen. A
  later LONG/SHORT hypothesis after a FLAT close opens fresh, exactly as
  it would from a flat start.
- `candle_series.require_consistent_series` (`forex_agent.domain.
  candle_series`): the "one instrument, one granularity, strictly
  ascending `start_time`" validation, extracted (FX-12) from being
  duplicated across `run_backtest`/`simulate_trades`/`classify_regime`
  into one shared helper.
- `TrendRegime` (`TRENDING`/`RANGING`) + `classify_regime`
  (`forex_agent.domain.regime_detection`): trend-vs-range classification
  via Wilder's ADX on a synthetic midpoint approximation — bid/ask OHLC
  averaged, *not* a true provider mid price, since bid's and ask's
  period-high/low can occur at different instants (FX-12H; a true mid
  OHLC, e.g. OANDA's `price=M`, is deferred — see `docs/DECISIONS.md`).
  Deterministic technical analysis, no ML. Requires ≥ `2 × period`
  candles (default period 14, threshold 25 — Wilder's own convention,
  both configurable; `period ≥ 1` and `threshold` in [0, 100] validated).
  Cross-checked against an independently written reference
  implementation of the same algorithm, not just qualitative
  trending/ranging behavior. This closes out CLAUDE.md's current M0–M4
  phase (items 1–11).

## What does not exist yet

- Any strategy beyond the six now built (`EmaCrossoverStrategy`,
  `CloseChannelBreakoutStrategy`, `TimeSeriesMomentumStrategy`,
  `MeanReversionStrategy`, `VolatilityExpansionBreakoutStrategy`,
  `MultiTimeframeTrendStrategy`) — the original strategy-suite roadmap
  is complete as of FX-25; anything further is a new roadmap, not
  planned yet.
- True regime-*gating* as a **general** concept (an entry filter that
  changes which trades occur based on an external market-state
  classification, distinct from the entry-regime attribution FX-21/
  FX-23 did) — FX-25's H4 confirmation is one concrete instance of this
  pattern using a second timeframe rather than `TrendRegime`, resolving
  the reversal-vs-FLAT question FX-21H flagged; a `TrendRegime`-based
  gating strategy specifically remains unbuilt.
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

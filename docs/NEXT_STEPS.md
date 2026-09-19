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
- ~~`TargetPosition`/FLAT semantics~~ — complete (FX-18).
  `TradeHypothesis.side: TradeSide` renamed and retyped to
  `target_position: TargetPosition` (`domain/target_position.py`, new
  LONG/SHORT/FLAT enum, distinct from the execution-only `TradeSide`).
  `simulate_trades` gained a third behavior: FLAT closes an open position
  without reopening it (no-op if already flat), alongside the existing
  same-direction no-op and opposite-direction close-and-reverse. All
  three existing strategies mechanically updated to construct
  `target_position=`; no behavior change, none emit FLAT yet — that's
  Mean Reversion v1, next.
- ~~Mean Reversion v1 (`mean_reversion_v1`)~~ — complete (FX-19).
  `MeanReversionStrategy` (`domain/strategies/mean_reversion.py`): a
  Bollinger-Bands-style z-score (window includes the current bar,
  population stddev) — LONG when `entry_threshold` standard deviations
  below the rolling mean, SHORT when that far above, FLAT on a genuine
  zero-crossing (detected the same way as FX-14's EMA crossover, not a
  deadband) — the first strategy to actually emit `TargetPosition.FLAT`
  (FX-18). Verified against an independently hand-derived synthetic
  series with exact z-scores at every stage, through `run_backtest` +
  `simulate_trades` (confirming FLAT-closes-without-reopening produces
  the right trade count), and against live OANDA practice candles.
- ~~Volatility Expansion Breakout v1
  (`volatility_expansion_breakout_v1`)~~ — complete (FX-20).
  `VolatilityExpansionBreakoutStrategy` (`domain/strategies/
  volatility_expansion.py`): LONG/SHORT on a Donchian high/low channel
  breakout combined with an ATR14/ATR50-style expansion filter (both
  required); FLAT when the expansion itself ends (ratio crosses back
  below `expansion_threshold`, reused as the exit boundary — no separate
  deadband parameter, same reasoning as FX-19). Verified against an
  independently hand-derived synthetic series covering all five
  `evaluate()` outcomes, through `run_backtest` + `simulate_trades`
  (confirming FLAT-closes-without-reopening end to end), and against
  live OANDA practice candles.
- ~~EMA entry-regime attribution~~ — complete (FX-21, look-ahead fixed
  FX-21H). `segment_trades_by_regime` (`domain/regime_segmentation.py`)
  buckets a strategy's already-executed simulated trades by the
  `TrendRegime` prevailing strictly before entry; `compute_metrics`
  needed zero changes (exactly the composable segmentation FX-17 was
  designed for). This is attribution (label trades after the fact), not
  gating (change which trades occur) — the two are explicitly distinct;
  a true gating experiment remains unbuilt (see FX-21H's entry in
  `docs/DECISIONS.md` for the reversal-vs-FLAT design question it
  raises). **Empirical finding** (see `docs/DECISIONS.md` for the full
  table and caveats): on a 90-day live EUR/USD H1 sample, EMA trades
  entered during `TRENDING` performed worse on every metric than both
  the unconditional baseline and `RANGING`-only trades — the opposite
  of the naive expectation, though `n=26` is too small to be conclusive
  either way. Confirms the value of keeping regime structurally external
  rather than assumed. Mean-Reversion-vs-RANGING attribution, true
  regime-gating, and control strategies all remain separate, undated
  follow-ups.
- ~~Small strategy-suite hardening batch~~ — complete (FX-21H.1).
  `run_backtest` now validates `hypothesis.timeframe` against the candle
  series' granularity (FX-13's provenance is now structural, not
  advisory); `MeanReversionStrategy.entry_threshold` must be strictly
  positive (was `>= 0`, which made the FLAT crossing branch unreachable
  at `0`); `compute_metrics` requires one `instrument`, not merely one
  P&L currency (`EUR_USD` + `GBP_USD`, both USD-quoted, previously
  passed unflagged despite being genuinely different instruments).
- ~~Control strategies~~ — complete (FX-22). `AlwaysLongStrategy`/
  `AlwaysShortStrategy`/`PreviousBarDirectionStrategy`/`NoTradeStrategy`
  (`domain/strategies/control.py`, one file for all four — a matched
  baseline set, not independent trading ideas). Always-long/always-short
  verified to be genuine buy-and-hold/sell-and-hold baselines (one held
  trade despite firing every bar); previous-bar-direction verified
  through an engineered flip-flop series; no-trade verified to produce
  zero hypotheses always. All four run through the unmodified
  `run_backtest`/`simulate_trades`/`compute_metrics` pipeline, and
  against live OANDA practice candles.
- ~~Mean-Reversion-vs-RANGING entry-regime attribution~~ — complete
  (FX-23). No new domain code — reused FX-21's `segment_trades_by_regime`
  with `MeanReversionStrategy`/`RANGING` in place of
  `EmaCrossoverStrategy`/`TRENDING`. **Empirical finding** (see
  `docs/DECISIONS.md` for the full table): on the same ~90-day EUR/USD
  H1 sample, filtering Mean Reversion's trades to `RANGING` — the regime
  it's naively expected to suit — made every metric worse, while
  `TRENDING`-only was the best-performing bucket either regime
  experiment has produced so far (profit factor 4.49). The mirror image
  of FX-21's own surprise; two independent experiments now agree the
  naive "strategy type should match regime type" intuition doesn't hold
  on the data observed so far. `n=57` is larger than FX-21's `n=26` but
  still not a basis for strategy-selection decisions.
- ~~Candle alignment / OANDA H4 reconciliation~~ — complete (FX-24).
  `aggregate_candles` (`domain/candle_aggregation.py`) now anchors
  `H2`/`H3`/`H4`/`H6`/`H8`/`H12`/`D` buckets to 17:00 `America/New_York`
  via `zoneinfo`, DST-aware — matching OANDA's own native candles for
  those granularities (confirmed against a live fetch of real H4/D
  candles, not assumed; also confirmed the explicit `dailyAlignment=17`/
  `alignmentTimezone=America/New_York` request params already match the
  practice API's default, sent explicitly anyway). `H1` and finer are
  unaffected — no DST ambiguity there. New `CandleSource`
  (`NATIVE`/`AGGREGATED`) provenance field on `Candle`, included in the
  DB unique constraint, so native and self-aggregated candles can't
  silently collide in storage; `aggregate_candles` itself also rejects
  mixing the two. Verified against the exact live-fetched OANDA boundary
  times as a golden-data regression, an EST (winter) case, and two
  synthetic DST-transition tests (spring-forward's genuinely-3-hour
  bucket, fall-back's genuinely-5-hour bucket) — a real correctness
  subtlety found while designing those tests: a DST-transition bucket's
  "complete" threshold has to be computed per bucket from real elapsed
  time, not a fixed constant, or such a bucket gets silently dropped as
  falsely "incomplete."
- ~~Multi-timeframe Trend v1~~ — complete (FX-25).
  `MultiTimeframeTrendStrategy` (`domain/strategies/
  multi_timeframe_trend.py`): an H1 EMA-crossover entry signal, gated
  by H4's own EMA fast/slow *state* (bullish/bearish/neutral, not a
  crossover event). First strategy needing two candle series at once —
  `Strategy.evaluate()`'s signature is unchanged; the full H4 series is
  a constructor argument, filtered on every call to only bars fully
  closed strictly before the current H1 bar (proven no-look-ahead via a
  mutation regression). Disagreement (or insufficient/neutral H4)
  closes to `FLAT` rather than being ignored, resolving FX-21H's own
  flagged reversal-vs-FLAT design question. Verified through a
  hand-derived synchronized H1+H4 series covering all four outcomes,
  through `run_backtest` + `simulate_trades`, and against live OANDA
  candles at both granularities.

- ~~Canonical candle boundary hardening~~ — complete (FX-25H). New
  `domain/candle_boundary.py` (`candle_start_boundary`/`candle_end_time`)
  is now the one DST-aware definition of candle duration, shared by
  `aggregate_candles` and `MultiTimeframeTrendStrategy` — closes two
  real bugs an external review caught: FX-25's H4 visibility filter used
  a fixed "4 elapsed hours" assumption that disagreed with FX-24's own
  logic (confirmed wrong on a fall-back day); FX-24's completeness check
  broke when the *source* granularity was itself day-aligned (confirmed:
  a spring-forward `H4` bucket built from `H2` source candles). Bucket
  completeness is now exact expected-boundary-sequence matching, not a
  member count — also closes the original FX-7 duplicate-plus-missing
  edge case in the same change. `MultiTimeframeTrendStrategy` also now
  rejects a non-`H1` driving series.
- ~~Source/target boundary nesting fix~~ — complete (FX-25H.1). One
  further gap the same review caught: nominal duration divisibility
  (`H6 % H3 == 0`) doesn't guarantee NY wall-clock source boundaries
  stay nested inside the target boundary across a DST discontinuity —
  reproduced directly (an `H3`-sourced `H6` bucket on the spring-forward
  day pulled in an hour of data past its own canonical end, real
  contamination). Fixed: the expected-boundary walk now requires exact
  termination on the target's own end; a bucket whose sources straddle
  rather than tile it is dropped, not the granularity pairing itself.
  Verified both as a targeted regression (confirmed to fail pre-fix,
  pass post-fix) and a broader structural test across five source/
  target pairings on both DST transition days, confirming the fix
  introduces no false negatives either.

**With FX-25H.1, the external review's full FX-24/FX-25 assessment is
resolved. This closes out the original diversity-first strategy-suite
roadmap** recorded in `docs/DECISIONS.md` (2026-09-15): six directional
strategies, `TargetPosition`/FLAT semantics, backtest metrics, control
strategies, two entry-regime-attribution experiments, and candle
alignment (now hardened) are all complete.

**Agreed next sequence** (per the same external review that produced
FX-25H), prioritizing a real research bottleneck over more strategies —
the ~90-day/26-trade samples used so far are enough to prove the
machinery works, not enough to judge whether any strategy has durable
expectancy:

1. ~~`FX-26` — Paginated, resumable historical backfill~~ — complete.
   `BackfillCandles` (`application/use_cases/backfill_candles.py`) pages
   arbitrarily large ranges via `domain/candle_pagination.py`
   (DST-aware, deterministic regardless of chosen page size — reuses
   `candle_boundary`, FX-25H/FX-25H.1), and tracks progress via a new
   per-`(instrument, granularity)` watermark (`ingestion_watermarks`
   table/`IngestionWatermarkRepository`) rather than a per-job
   checkpoint — the watermark *is* the resume state, extending forward
   or backward as later calls request more range. A disjoint request
   (no overlap/touch with existing coverage) raises explicitly rather
   than silently claiming an unfetched gap is covered. Also fixed a
   latent day-alignment bug in `find_gaps` (FX-8) — the same class of
   bug FX-24 already fixed elsewhere, verified and regression-tested.
   Verified against in-memory fakes for exhaustive branch coverage and
   against real Postgres for the core interruption/resume guarantee.
2. ~~`FX-27` — `CandleRepository.get_range(source=...)` provenance
   filtering~~ — complete. `get_range` gained `source: CandleSource |
   None = None`, where `None` explicitly means "all sources" — a
   deliberate choice, not an implicit pick of whichever provenance
   happens to exist. `AggregateCandles` now passes
   `source=CandleSource.NATIVE` explicitly, so it can never silently
   re-aggregate already-`AGGREGATED` rows (regression-tested: confirmed
   to fail pre-fix, pass post-fix). Verified against both the in-memory
   `FakeCandleRepository` and real Postgres.
3. ~~Research dataset build~~ — complete. `scripts/build_research_dataset.py`
   backfilled 10 years (2016-09-19 to 2026-09-19) of H1 and H4 candles for
   EUR/USD, GBP/USD, USD/JPY, USD/CAD, and XAU/USD (added to the original
   four-pair plan on request — needed no domain change: `Instrument`
   already accepts any 3-letter uppercase code, and "XAU" is gold's real
   ISO 4217 code, confirmed live against the OANDA practice API). 385,689
   candles total; 10/10 (instrument, granularity) series backfilled in one
   run with no interruption. Surfaced and fixed a real production bug in
   the process — see `FX-27H` below.
   - `FX-27H` — `CandleRepository.upsert_many` batching fix. The very
     first real backfill page (5000 candles) failed outright:
     asyncpg caps bound query parameters at 32767, and the unbatched
     `ON CONFLICT` insert needed 70,000 (14 params/candle). Fixed by
     batching the insert into 1000-row chunks per call, still one commit
     per call (preserves `BackfillCandles`' existing crash-safety unit).
     Regression-tested with a 3000-candle upsert (confirmed to fail
     pre-fix with the same `InterfaceError` seen live, pass post-fix).
3a. ~~Research dataset gap-check~~ — complete, at the user's request before
    `FX-28`. `scripts/check_research_dataset_gaps.py` ran `DetectDataGaps`
    over all 10 series' full backfilled ranges, filtered to the standard
    forex weekly closure (Friday 17:00–Sunday 17:00 `America/New_York`),
    and reported everything left over. Of 162,121 raw missing slots, 97%
    were ordinary weekly closures. The remaining 5,826 were investigated,
    not just filtered and forgotten: the four FX pairs' residuals cluster
    on named holidays (Christmas, New Year's, Thanksgiving) — expected,
    matches `find_gaps`' documented no-holiday-calendar scope. XAU_USD's
    much larger residual is dominated by a clean daily 17:00-NY gap on
    ordinary trading days (OANDA's commodities settlement/rollover quote
    gap) plus metals-specific holiday early-closes — both confirmed via a
    live OANDA re-fetch (Thanksgiving 2016 window returns zero candles at
    the flagged hours, matching what's stored: genuinely absent upstream,
    not a backfill bug). No unexplainable scattered gaps found anywhere.
   - `FX-27H.1` — `DetectDataGaps` false-positive fix, found by the gap
     check's own first run. A non-boundary-aligned `start` (e.g. a
     watermark's wall-clock `earliest_ingested`) made it report its
     rounded-down boundary candle as missing even when present — `get_
     range`'s `>= start` filter and `find_gaps`' own boundary-rounding
     disagreed on a misaligned `start`. Fixed by snapping `start` to its
     candle boundary once, before either call. Regression-tested
     (confirmed to fail pre-fix with the exact false positive seen live,
     pass post-fix).
4. ~~`FX-28` — true `TrendRegime`-based gating~~ — strategy complete,
   **performance table WITHDRAWN, pending FX-29**.
   `EmaCrossoverTrendRegimeGatedStrategy` built; ran the three-way
   comparison (unconditional / entry-regime attribution / actual gating)
   across all 5 research-dataset instruments, full 10-year H1 history.
   **Central finding, still valid**: proved (not just observed) that
   "gated" and "TRENDING-only attribution" trades are entry/exit/P&L-
   identical for this specific pairing — a base strategy with no native
   FLAT, gated at the same decision bars attribution already inspects,
   structurally cannot diverge from post-hoc filtering. Locked in as a
   regression test that runs on one continuous series, unaffected by the
   issue below. **Per-instrument performance numbers withdrawn**:
   external review caught, independently confirmed, that chunking the
   10-year backtest into ~6,000-candle windows (for `run_backtest`'s
   documented O(n²) scaling) force-closes open positions and reseeds
   every strategy's EMA/ADX state at each artificial boundary — a real
   change to the simulated trade path, not the "<1%" cost originally
   claimed. See `docs/DECISIONS.md`'s correction entry for the
   independent confirmation (228 continuous vs. 226 chunked trades on
   the same 12,000-candle window). The specific "helped X, hurt Y"
   claims are provisional until `FX-29` reruns them on a continuous
   engine.
5. `FX-29` — Scalable Continuous Backtest Engine. Replaces FX-28's
   chunking workaround with a real fix: process the full ~62,000-candle
   H1 series per instrument continuously (no artificial chunk
   boundaries), preserving open-position state and EMA/ADX indicator
   state across the whole run. Must produce byte-identical hypotheses
   and trades to the existing `run_backtest`/`simulate_trades` on small
   datasets — golden parity tests required, trade-for-trade (side, entry
   time/price, exit time/price, P&L). `simulate_trades` itself is
   already O(n) (a single indexed pass) and needs no change; the O(n²)
   cost is entirely `run_backtest`'s full-history reslice plus each
   strategy's own from-scratch EMA/ADX recompute per call — an
   incremental engine needs strategies that maintain O(1)-per-bar state
   instead. Once built: rerun FX-28's five-instrument comparison and
   replace the withdrawn table with continuous-history results. Not yet
   started as of this writing.

No new technical strategies are planned — six directional strategies
plus four controls is enough; the project's focus shifts from
building trading ideas to evaluating which of them survive more history,
more pairs, more regimes, and out-of-sample testing.

Do not start fundamentals, news intelligence, AI decision-making, or live
trading — out of scope until explicitly assigned per CLAUDE.md. The same
goes for the downstream epics not in this list at all (Decision Engine,
Risk Engine, Paper Trading Execution, Performance Analytics, Shadow
Trading) — none are part of the current phase.

Each of these should be tracked as its own Jira story and worked per
CLAUDE.md's "Development rules" (tests first where practical, smallest
change satisfying acceptance criteria, one story per commit).

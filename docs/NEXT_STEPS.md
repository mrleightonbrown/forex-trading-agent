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
4. ~~`FX-28` — true `TrendRegime`-based gating~~ — complete.
   `EmaCrossoverTrendRegimeGatedStrategy` built; ran the three-way
   comparison (unconditional / entry-regime attribution / actual gating)
   across all 5 research-dataset instruments, full 10-year H1 history.
   **Central finding**: proved (not just observed) that "gated" and
   "TRENDING-only attribution" trades are entry/exit/P&L-identical for
   this specific pairing — a base strategy with no native FLAT, gated at
   the same decision bars attribution already inspects, structurally
   cannot diverge from post-hoc filtering. Locked in as a regression
   test. Its own performance table was briefly withdrawn (chunking bug,
   see FX-29) and has since been rerun for real.
5. ~~`FX-29` — Scalable Continuous Backtest Engine~~ — complete.
   Replaced FX-28's chunking workaround with a real fix: `Incremental
   SmaSeededEma`/`IncrementalAdx` (O(1)-per-bar, proven bit-for-bit
   identical to the slow recompute), `IncrementalStrategy`/
   `run_backtest_incremental` (one O(n) forward pass), and incremental
   counterparts to the two `EmaCrossover*` strategies (same
   `strategy_key`s, golden-parity-tested trade-for-trade against the
   unmodified slow originals). `simulate_trades` needed no change — it
   was already O(n); the O(n²) cost was entirely `run_backtest`'s
   reslicing plus each strategy's own from-scratch recompute per call.
   Measured: a full 62,194-candle H1 series in 0.19s (EMA) / 0.47s
   (gated), down from an extrapolated 35-40 minutes each. Reran FX-28's
   comparison continuously, all 5 instruments, full 10-year H1 history
   — the corrected table (replacing the withdrawn one) is in
   `docs/DECISIONS.md`: gated == TRENDING-only again, confirming the
   structural equivalence is independent of execution strategy;
   TRENDING-conditioning helps GBP_USD/USD_JPY/XAU_USD, hurts EUR_USD,
   is roughly neutral for USD_CAD. Trade counts shifted modestly from
   the withdrawn table (confirming the chunking bug was real, if modest
   in this case), qualitative conclusions unchanged.
   - ~~`FX-29H` — incremental strategy lifecycle hardening~~ — complete.
     Second-round external review found (and this session independently
     reproduced before fixing) two real bugs: reusing a stateful
     `IncrementalStrategy` instance across `run_backtest_incremental`
     calls silently gave different results each time (no reset), and a
     failed validation mid-series left the strategy partially mutated.
     Fixed: `IncrementalStrategy.reset()`, called unconditionally before
     every replay; `candles` validated in full (including finalized
     status) before `reset()`/`on_candle` is ever called.
     - Third-round follow-up: `reset()` wasn't actually called for an
       empty `candles` list (the early return happened first), despite
       the docstring already claiming "unconditionally" — caught by a
       further review pass, confirmed directly, fixed by moving the
       call to the literal first line of the function.
6. ~~`FX-30` — ingestion watermark boundary semantics~~ — complete.
   `BackfillCandles` now floors both `earliest_ingested` and
   `latest_ingested` to genuine candle boundaries (never rounds up — a
   mid-candle `end` may still be forming) — closes the root cause behind
   FX-27H.1's `DetectDataGaps` symptom rather than leaving every future
   consumer to defend against it. No change to what's actually fetched
   from the provider, only to what the watermark records.
7. ~~`FX-31` — ingestion watermark concurrency protection~~ — complete,
   **reopened and corrected as FX-31H**. FX-31's first attempt put an
   advisory lock on `IngestionWatermarkRepository`, issued through the
   same session `candles`/`watermarks` use — external review correctly
   identified this as unsafe (a Postgres advisory lock belongs to the
   physical connection, not the SQLAlchemy session, and `Session.
   commit()` checks connections back into the pool). Confirmed directly
   before fixing: traced pool checkin/checkout events, then reproduced
   a real failure under forced contention with the original design.
   Fixed with a dedicated `BackfillLock` port; `PostgresBackfillLock`
   pins one dedicated connection for the lock's whole held duration,
   verified under a deliberately constrained, heavily-churning pool the
   lock itself stays isolated from.
   - Third-round follow-up: a further, distinct pool-starvation
     deadlock risk (the lock's own blocking `pg_advisory_lock` holds a
     connection while waiting; sharing a pool with the worker sessions
     under real concurrency can starve the lock-holder of the
     connection it needs to finish and release the lock). Confirmed
     directly that the actual composition root
     (`scripts/build_research_dataset.py`) shared one engine for both —
     not currently triggered (that script runs sequentially), but a
     latent structural risk for the future scheduler FX-31 was meant to
     make safe. Fixed with a new, dedicated `get_lock_engine()`, never
     shared with the engine backing `candles`/`watermarks` sessions;
     updated everywhere `PostgresBackfillLock` is constructed.

No new technical strategies are planned — six directional strategies
plus four controls is enough; the project's focus shifts from
building trading ideas to evaluating which of them survive more history,
more pairs, more regimes, and out-of-sample testing. The research
dataset and backtest engine are now both trustworthy at full scale —
FX-28's rerun table is real evidence, not an exploratory approximation.

## Running every existing strategy across the full research dataset

Per the same external review's closing recommendation: pause
infrastructure hardening, use the now-trustworthy capability. Six
strategies (the ones FX-28/29 didn't already cover) each get their own
story — a real empirical run across all 5 instruments' full 10-year H1
history, findings recorded in `docs/DECISIONS.md`. Ordered by actual
computational cost, timed directly before committing to an order (not
assumed): cheap ones first (existing slow engine, no new code needed),
expensive ones last (need a new incremental engine first, same
discipline as FX-29's).

1. ~~`FX-32` — control strategies~~ — complete. All four are O(1)/call
   (~30s/instrument on the existing slow engine, no incremental engine
   needed). `AlwaysLong`/`AlwaysShort` behaved exactly as designed (one
   buy-and-hold/sell-and-hold trade each, every instrument net
   favorable to long over this window — real macro history, not a
   finding about skill). `NoTradeStrategy` trivially produces zero
   trades by definition, not run. **`PreviousBarDirectionStrategy` is
   the project's first genuinely decisive result**: unprofitable on
   every single instrument, profit factor 0.58-0.78, at n=30,000-32,000
   trades per instrument — several orders of magnitude past FX-21/23's
   own flagged-as-too-small samples. Naive previous-bar momentum-
   chasing is not a free edge at H1; the effect is large and consistent
   enough to trust. Full table in `docs/DECISIONS.md`.
2. ~~`FX-33` — `TimeSeriesMomentumStrategy` (FX-16)~~ — complete. O(1)/
   call (direct indexing, no full-list rescans), ~30s/instrument, no
   incremental engine needed. Default params (lookback=20, threshold=0):
   unprofitable on 4 of 5 instruments (profit factor 0.73-0.97) at
   n=6,000-6,500 trades each; `XAU_USD` the one exception, marginally
   profitable (profit factor 1.057) — a thin margin, not a strong edge.
   Directionally consistent with FX-32: simple H1 momentum doesn't
   clear transaction costs on FX pairs in this dataset; gold comes
   closest to (here, just past) breakeven. Full table in
   `docs/DECISIONS.md`.
3. ~~`FX-34` — `CloseChannelBreakoutStrategy` (FX-15)~~ — complete.
   O(n)/call, ~10.7 min/instrument actual (~53 min total), no
   incremental engine needed. Default `lookback=20`: genuinely mixed —
   unprofitable on `EUR_USD`/`GBP_USD`/`USD_CAD` (profit factor
   0.84-0.88), profitable on `USD_JPY`/`XAU_USD` (profit factor
   1.08/1.20), at n=1,900-2,100 trades each. No obvious pattern
   separates the winners from the losers — the first strategy in this
   batch where the answer genuinely depends on the instrument. Full
   table in `docs/DECISIONS.md`.
4. ~~`FX-35` — `MeanReversionStrategy` (FX-19)~~ — complete. Same
   O(n)/call profile as FX-34, ~10.5 min/instrument actual (~53 min
   total). Default `period=20`, `entry_threshold=2.0`: unprofitable on
   **every single instrument** (profit factor 0.74-0.98) at
   n=2,200-2,555 trades each — decisive, like FX-32. Notable failure
   mode: a consistently HIGH win rate (0.60-0.63) throughout, despite
   the net loss — many small wins, fewer larger losses, the classic
   mean-reversion signature. Full table in `docs/DECISIONS.md`.
5. ~~`FX-36` — `VolatilityExpansionBreakoutStrategy` (FX-20)~~ — complete.
   Needed a new incremental engine first (~92 min/instrument
   extrapolated on the slow path, genuinely impractical) — new
   `IncrementalWilderAtr` primitive + `IncrementalVolatilityExpansion
   BreakoutStrategy`, golden-parity-tested including a hand-constructed
   exact-ATR-ratio-threshold boundary case (closed a real gap: a `>`
   vs `>=` bug passed every naturally-varied-data parity test
   undetected until that specific test was added). Measured: full
   62,194-candle series in ~2.5s, down from ~92 minutes. Empirical
   result, default params: only n=11-27 trades per instrument over 10
   years (the double breakout-AND-expansion condition is rare) — closer
   to FX-21/23's own flagged-as-too-small samples than this batch's
   other runs; 4 of 5 instruments show poor profit factors (0.06-0.45),
   `USD_JPY` near breakeven (1.003) but not a confident finding at that
   n. Full table in `docs/DECISIONS.md`.
6. ~~`FX-37` — `MultiTimeframeTrendStrategy` (FX-25)~~ — complete.
   Needed a new incremental engine first (~41 min/instrument
   extrapolated, the most complex of the six since it combines H1 and
   H4 series) — `IncrementalMultiTimeframeTrendStrategy` keeps the H4
   series as a constructor argument (same shape as the slow strategy)
   with an internal cursor advancing into it as H1 time progresses,
   golden-parity-tested including a real gap closed (the slow
   strategy's H4-bias gate needs `slow_period + 1` visible candles, one
   more than raw EMA readiness). Measured: ~3s/instrument, down from
   ~41 minutes. Empirical result, default params: n=425-462 trades per
   instrument — a solid sample. Genuinely mixed, like FX-34:
   unprofitable on `EUR_USD`/`GBP_USD`/`USD_CAD` (profit factor
   0.90-0.92), profitable on `USD_JPY`/`XAU_USD` (profit factor
   1.25-1.31); consistently low win rate (0.28-0.34) everywhere, the
   classic trend/breakout-confirmation signature. Full table in
   `docs/DECISIONS.md`.

**This batch is now complete (FX-32 through FX-37)** — every remaining
concrete strategy has a real empirical run across the full 10-year,
5-instrument research dataset. See `docs/DECISIONS.md`'s FX-37 (results)
entry for a cross-strategy summary.

## FX-38 + FX-38H + FX-38H.1: pre-development historical holdout (all complete) — resulting research questions

FX-38H.1 (external review of FX-38H itself) closed the last
methodological gap — holdout warm-up bounded below by each series' own
`earliest_usable_research_candle` (previously could reach slightly
before it), plus explicit `CandleSource.NATIVE` filtering everywhere.
Rerun confirmed the effect is exactly as small as predicted: XAU_USD's
two candidates are bit-for-bit identical to FX-38H (no pre-existing
data there to leak in the first place); USD_JPY's shift by ~0.001 PF.
No result below changed materially, no sign flip anywhere was created
or removed — the questions this raises are therefore unchanged from
FX-38H's own list.

FX-38 extended the research dataset back to each instrument's true
earliest OANDA candle (FX pairs ~2002, XAU/USD 2006) and evaluated
`EmaCrossoverStrategy`, `EmaCrossoverTrendRegimeGatedStrategy`,
`MultiTimeframeTrendStrategy`, and `CloseChannelBreakoutStrategy` — all
unchanged default parameters — on the newly-available pre-2016 data as
a historical holdout. External review found two real methodological
gaps (holdout started at the raw technical earliest candle rather than
an objective usable-history threshold; a single continuous run sliced
by `entry_time` could let a boundary-straddling trade leak an
out-of-period price into the wrong period's metrics). FX-38H fixed
both — objective, locked-before-running usable-history threshold
(`scripts/determine_usable_history_start.py`), economically sealed
evaluation windows applied to BOTH periods (`domain.sealed_window_
backtest`, `scripts/run_fx38h_analysis.py`), a direct audit of FX-38's
original boundary-straddling exposure, and a machine-readable results
artifact (`research_results/fx38h/results.json`) — same unchanged
parameters throughout, nothing tuned. Full results, the four-candidate
FX-38-vs-FX-38H comparison table (exactly what changed and why), the
straddling audit, and the corrected time-stability conclusion are all
in `docs/DECISIONS.md`.

**Headline, confirmed not overturned by the more rigorous rerun**: none
of this story's four candidate combinations (`USD_JPY`/`XAU_USD` ×
`CloseChannelBreakoutStrategy`/`MultiTimeframeTrendStrategy`) flip sign
under either methodology — if anything, the two USD_JPY combinations
look slightly BETTER under FX-38H (ramp-up-era noise and one
boundary-straddling trade removed), and the two XAU_USD combinations
are essentially unchanged (XAU/USD's usable-history start turned out to
equal its raw earliest candle — a genuine correction to FX-38's own
first-pass density read, not a tuning choice). Two comparison
strategies on the same two instruments DO sign-flip, also unchanged by
the rerun. Time-stability analysis found the apparent USD_JPY/XAU_USD
pattern predates 2016; FX-38's own "concentrated in an unusually strong
2022-2025 stretch across all eight series" claim was itself overstated
(external review, criterion 12) — corrected: `2024-2025` specifically
(not the pair) is near-best in 7 of 8 series, `2022-2023` is mid-pack-
to-weak in 7 of 8. One case (XAU_USD/`EmaCrossoverTrendRegimeGated
Strategy`) leans almost entirely on a single 2020-2021 episode.

**Research questions this raises — not parameter changes, and none of
these should be acted on by tuning any of the strategies above**:

1. Why is `2024-2025` specifically (not 2022-2023) near-best in most of
   the eight series studied? Is this a genuine feature of recent FX/
   gold macro conditions, or a statistical artifact of having more/
   cleaner recent data? Not investigated in FX-38/FX-38H — a real
   question, not a reason to prefer recent-only backtests going
   forward.
2. `EmaCrossoverTrendRegimeGatedStrategy` on XAU_USD leans on one
   2020-2021 episode for essentially its entire apparent edge, in both
   FX-38 and FX-38H's rerun. Would a PROPER out-of-sample check (data
   after 2026-09-19, not yet available) also fail to reproduce that
   episode's magnitude? This is exactly the situation the "pre-
   development holdout" framing warned about — a real prospective
   holdout, when new data eventually exists, would answer this more
   directly than any further slicing of already-seen history can.
3. `CloseChannelBreakoutStrategy` still has no incremental engine.
   FX-38 and FX-38H each needed roughly 2-3 hours of slow-engine
   compute; a future story exercising it further (a genuine prospective
   holdout once new data accrues, or a statistical-significance rerun
   per question 4) would benefit from one, following the same golden-
   parity-tested pattern as FX-36/FX-37 — not attempted here, this
   story's scope was evaluation, not infrastructure.
4. **ANSWERED by FX-39** (block-bootstrap significance testing,
   complete): no. None of the four candidates' holdout profit factors
   are statistically distinguishable from noise under the moving-block
   bootstrap (objectively-selected block length — three of the four
   selected `block_length=1`, i.e. no detected autocorrelation, so an
   ordinary rather than dependence-adjusted bootstrap for those three;
   only USD_JPY/`MultiTimeframeTrendStrategy` selected a larger block)
   and multiple-comparison correction (Holm, across the four
   candidates) — approximate percentile-bootstrap one-sided p-values
   0.13-0.19, Holm-adjusted p=0.53 for all four. One nuance, not a
   reversal: XAU_USD/`MultiTimeframeTrendStrategy`'s SECONDARY
   regime-block robustness check (only ~6 available 2-year blocks,
   explicitly not read as an equally-precise significance test) barely
   excludes zero. Given the observed effect sizes, variability, and
   available holdout samples, neither the positive candidates nor the
   negative controls are distinguishable from zero. Full results in
   `docs/DECISIONS.md`'s FX-39 entry.
5. None of the four strategies studied here show a result strong
   enough, in EITHER period, under EITHER backtesting methodology, OR
   once statistical significance is properly accounted for, to justify
   moving toward position sizing, risk management, or paper-trading
   execution for any of them specifically. FX-39 makes this more
   certain, not less — the platform still has no strategy anywhere in
   its results log that would be reasonable to deploy, even on paper,
   based on evidence alone.

## FX-14 through FX-39: pure-technical-strategy research phase — closed

FX-39's result is the natural close of this phase (agreed with the
user 2026-09-21): every concrete technical strategy this project built
(EMA crossover, its ADX-gated variant, close-channel breakout, mean
reversion, time-series momentum, volatility-expansion breakout,
multi-timeframe trend, and the control strategies) has now been run
across the full research dataset, re-evaluated on a genuine historical
holdout with hardened methodology, and statistically tested for
significance — and none reached a result strong enough to build
further infrastructure around. That is a real, useful, honest
conclusion, not a dead end: the platform's own roadmap always treated
technical signals as ONE evidence layer among several (regime,
fundamentals, event risk, news/intelligence, and eventually decision/
risk machinery), not a phase to keep optimizing in isolation — and
FX-39's own explicit, locked prohibition (no parameter tuning triggered
by these results) forecloses the tempting-but-wrong path of trying yet
another breakout lookback or ATR filter to chase significance.

No further work of any kind has been requested; check in before
starting anything new — including, explicitly, do not respond to any
of the above by tuning a strategy's parameters, adding a new technical
strategy, or unilaterally starting the next architectural phase
(regime/fundamentals/news/decision-engine work) without being asked.

## FX-40: backtest run report export + static HTML results viewer (complete)

Observability/reporting only, built to close out the pure-technical-
strategy research phase: `scripts/export_backtest_report.py` exports
any of 7 concrete strategies' backtest runs as canonical JSON reports;
`fta_dashboard_sketch.html` (repo root) displays them with no server,
no build step, and no new dependency — open it directly from disk.
Three real runs are committed in `reports/` as a working demonstration.
Full details in `docs/DECISIONS.md`'s FX-40 entry.

**Per this story's own explicit stop instruction**: do not proceed into
a broader dashboard, database-backed report storage, live monitoring,
paper-trading UI, strategy-editing UI, or API work as a result of
completing this story. If a future story wants the dashboard to cover
more strategies, that is a small, explicit addition to `STRATEGIES` in
the export script, not a reason to generalize it into a plugin
architecture.

No further work has been requested; check in before starting anything
new here or elsewhere — including the next architectural phase
(regime/fundamentals/news/decision-engine work) mentioned as the reason
this story was requested now.

## FX-41: point-in-time fundamental data model (complete)

Architecture/foundation only, under `FX-EPIC-06 Fundamental Analysis`:
`domain/macro_series_definition.py`/`macro_observation_vintage.py`
give the codebase a provider-independent way to represent a macro/
fundamental fact and query it point-in-time-safely —
`MacroObservationRepository.latest_available_as_of`/
`observation_as_known_at` can never return a vintage whose
`released_at` is after the query's `as_of`, and `PointInTimeSafety`
fails closed (`UNKNOWN` by default, not treated as safe). No provider
is integrated, no ingestion pipeline exists, and no strategy or scoring
logic consumes this data — this is the data model and its safety
invariant only. Full details in `docs/DECISIONS.md`'s FX-41 entry
(including a numbering note: this codebase's committed FX-40 is the
backtest-report-viewer story above, so the spec's own "FX-40" is
recorded here as FX-41, and its "FX-41" becomes FX-42 if picked up).

**Per this story's own explicit stop instruction**: do not proceed
into policy-rate ingestion, a FRED/central-bank API client, CPI/GDP/
employment feeds, an economic calendar, a carry or rate-differential
strategy, a fundamental score, or any BUY/SELL decision logic as a
result of completing this story.

No further work has been requested; check in before starting anything
new here or elsewhere.

## FX-41H: macro vintage integrity hardening (complete)

Hardens `add_vintage`'s idempotency contract before real macro-data
ingestion begins: a same-identity `(series_key, observation_period,
revision_sequence)` write with a different value/released_at/
effective_at/source now raises `MacroVintageConflictError` instead of
silently no-opping, and both point-in-time queries gained
`revision_sequence DESC` as a deterministic tie-breaker after
`released_at DESC`. No point-in-time semantics changed; no provider,
rate data, strategy, or decision logic added. Full details in
`docs/DECISIONS.md`'s FX-41H entry.

**Per this story's own explicit stop instruction**: no external
provider, no rate data, no strategy, no scoring, and no decision logic
follows this story.

No further work has been requested; check in before starting anything
new here or elsewhere.

## FX-42: canonical central-bank policy-rate registry (complete; see
FX-42H immediately below for corrections)

Defines, for USD/EUR/GBP/JPY/CAD, one canonical policy-rate concept per
currency plus its provider/source mapping — semantics only, no
ingestion, no persistence, no strategy. Introduces the explicit split
FX-41 deferred: `MacroSeriesDefinition` stays provider-independent;
`ProviderSeriesMapping` (new) records which provider/identifier(s)
supply a definition. USD is split into two effective-dated
`PolicyRateDefinition`s (single target point through December 16, 2008;
target range midpoint from then on, with an explicit, versioned
`TARGET_RANGE_MIDPOINT` transformation) — the required effective-dated/
transformed example. `validate_registry` enforces registry-wide
invariants at import time. FX-42's initial EUR choice (Deposit Facility
Rate continuously) and its claim that JPY is one continuous definition
were both corrected by FX-42H below before this registry was relied on
for anything further. Full details in `docs/DECISIONS.md`'s FX-42 entry.

## FX-42H: policy-rate registry semantic hardening (complete)

Corrects FX-42's factual/semantic weaknesses before FX-43 ingestion,
without changing FX-42's domain architecture. Point-in-time safety is
now tracked SOLELY on `ProviderSeriesMapping` (`MacroSeriesDefinition.
point_in_time_safety` and `require_point_in_time_safe` are removed
entirely), guarded by the new combined `require_research_usable_mapping`
(fails closed unless a mapping is BOTH `verified` AND
`POINT_IN_TIME_SAFE` — every mapping in the registry still fails this,
by design). USD's target-point era now starts 1994-02-04, not 1954
(the earlier `DFEDTAR` history is a retrospective reconstruction, not
point-in-time-safe). EUR's canonical scalar is now the ECB MRO
minimum-bid/fixed rate, not DFR continuously — DFR is documented as a
candidate future regime-aware feature, explicitly not to be silently
substituted back in. JPY no longer claims one continuous definition:
five distinct rate-target eras with INTENTIONAL GAPS during its two
quantitative-easing eras (2001-2006, 2013-2016), where
`definition_as_of` correctly returns `None`. `validate_registry` now
allows gaps and checks full `MacroSeriesDefinition` equality per
currency, not just the same key string. CAD's boundary now starts
1999-02-01, not 1991-02-01, with provider ID `V39079` replacing the
placeholder. BoJ mapping remains entirely unresolved by design. Full
details, including exactly what FX-43 must still verify before
ingestion, in `docs/DECISIONS.md`'s FX-42H entry.

**Per this story's own explicit stop instruction**: no ingestion,
differential calculation, carry strategy, parameter research, or
trading follows this story.

## FX-42H.1: policy-rate gap and JPY boundary hardening (complete)

Replaces FX-42H's blanket gap tolerance with explicitly declared,
auditable gaps, and corrects two further JPY factual weaknesses.
`DeclaredPolicyRateGap` (new) requires a currency, half-open
`start`/`end`, and a non-empty `reason`; `validate_registry` now rejects
any undeclared gap between consecutive definitions, any declared gap
overlapping an actual definition, and any declared gaps overlapping each
other. JPY's 2006-2013 overnight-call-rate era is split at October 5,
2010 (the BoJ's "Comprehensive Monetary Easing" switch from a
single-point target to a ~0-0.1% range, now `TARGET_RANGE_MIDPOINT`).
JPY's Policy-Rate Balance era now starts February 16, 2016 (the -0.10%
rate's EFFECTIVE date) rather than January 29, 2016 (its announcement
date) — tied explicitly, in the definition's own notes, to FX-41's
`released_at`/`effective_at` distinction for FX-43. A stale
`PolicyRateDefinition` docstring still describing JPY as needing only
one continuous definition was also corrected. Full details in
`docs/DECISIONS.md`'s FX-42H.1 entry.

**Per this story's own explicit stop instruction**: no provider
verification, ingestion, rate differential, strategy, parameter
research, or trading follows this story.

## FX-43: first real external fundamental data — policy-rate backfill
(complete)

The first use case and infrastructure in this codebase that ingest
real, external fundamental data. Backfills real policy-rate history
for USD (FRED), EUR (ECB Data Portal), GBP (Bank of England), and CAD
(Bank of Canada, but only from 2009-04-21 — no earlier source was
found and this gap is explicitly documented, not backfilled) into real
`MacroObservationVintage` rows, via a new pure anti-interpolation
algorithm (`extract_change_points` — one observation per genuine
policy-rate change, never a fabricated daily series) and the existing,
unmodified FX-41H idempotent `MacroObservationRepository.add_vintage`.
JPY is not attempted (still unresolved). 258 real vintages now in
Postgres, spot-checked against known historical facts and proven to
answer as-of queries correctly across a real historical transition
(USD's December 2008 near-zero-rate cut). `released_at` is an
effective-date proxy, not a verified announcement timestamp — no
mapping is promoted to point-in-time-safe; establishing genuine
announcement timestamps remains the explicit next review gate. Live
verification found and fixed two real bugs (an ECB request-path
double-prefix, and a coverage report showing the requested window
instead of actual data) and one live blocker (the Bank of England's
WAF rejecting httpx's default User-Agent). Full details, including
exactly what a future story would need to establish genuine release
timestamps, in `docs/DECISIONS.md`'s FX-43 entry.

**Per this story's own explicit instruction**: this data is never
called "carry" anywhere in this codebase. No rate differential is
computed, no strategy or decision logic follows this story.

## FX-43H: policy-rate backfill hardening (complete)

Hardens FX-43 before any rate-differential research reads this data.
Half-open era boundaries (`[valid_from, valid_to)`) are now enforced
against the provider fetch itself, not merely assumed from a
provider's own behavior — proven with the story's own exact required
scenario (two eras sharing a boundary date, both providers given a row
on it, proven to belong only to the later era). Raw provider coverage
(`earliest_raw_observation`/`latest_raw_observation`) is now tracked
separately from change-point span, and `coverage_start`/`coverage_end`
correctly reflect the former — a stable rate that stops changing but
keeps being published daily now reports coverage extending to the
present. `add_vintage` now returns `VintageWriteOutcome`
(`INSERTED`/`ALREADY_PRESENT`), reported accurately by the backfill use
case — confirmed live: real data cleared, hardened script run twice,
first run 258 inserted/0 already-present, second run 0 inserted/258
already-present, zero duplicate rows. `MacroObservationVintage` gained
`released_at_is_verified`; every backfilled vintage is now explicitly
marked `False`, and `MacroObservationRepository.
replace_provisional_release_timing` is the new, explicit, safe
replacement path a future story can use once a genuine announcement
timestamp is established — narrowly scoped to timestamp metadata only,
never the economic value, never represented as a revision. Duplicate
raw observations of the same date now fail/report explicitly on a
genuine value conflict rather than "last value wins". FRED
documentation corrected: `DFEDTAR` does not cover "1954-present" — it
is discontinued, ending 2008-12-15. Full details in
`docs/DECISIONS.md`'s FX-43H entry.

**Per this story's own explicit stop instruction**: no rate
differential, no carry strategy, no parameter research, no JPY
provider work, no invented release timestamps, and no decision logic
follows this story.

## FX-43H.1: provisional timestamp fail-closed hardening (complete)

Hardens FX-43H's own `released_at_is_verified`/
`replace_provisional_release_timing` mechanisms themselves — no new
provider, no verified announcement timestamp, no rate/carry/JPY work.
`released_at_is_verified` now DEFAULTS to `False` (was `True`) at both
the domain and SQLAlchemy-model layers, so a caller must explicitly
pass `released_at_is_verified=True` to claim verification rather than
that going unnoticed. New migration `80c0ae20257b` changes the
column's `server_default` to `'false'` AND unconditionally
reclassifies every pre-existing row to `False` in the same migration —
not relying on manually clearing/reloading the database, per the
story's own explicit constraint; confirmed against real Postgres.
`replace_provisional_release_timing` in
`SqlAlchemyMacroObservationRepository` is now a single atomic
conditional `UPDATE ... WHERE ... AND released_at_is_verified = false
... RETURNING id`, replacing the old SELECT-then-UPDATE, so two
concurrent replacement attempts against the same identity cannot both
succeed — proven by a new concurrency regression test racing two
independent database sessions. All existing guarantees preserved: no
`value` parameter, no `revision_sequence` update, verified rows still
cannot be rewritten. Full details in `docs/DECISIONS.md`'s FX-43H.1
entry.

**Per this story's own explicit stop instruction**: no providers, no
verified announcement timestamps, no rate differential, no carry
research, no JPY work, no release-time sourcing, no strategy changes
follow this story.

## FX-44: point-in-time policy-rate release verification (complete)

The first real use of FX-43H/FX-43H.1's replacement mechanism: real
primary-source research into USD/EUR/GBP/CAD central-bank
release-timing conventions (Federal Reserve, ECB, Bank of England,
Bank of Canada — JPY stays out of scope), applied only where
genuinely defensible. Of the 258 real change points FX-43 backfilled:
USD 30 exact/54 conservative/8 unresolved (of 92); EUR 44/0/18 (of
62); GBP 65/0/6 (of 71); CAD 0/30/3 (of 33) — zero conflicts, and a
second live run reproduced identical figures with zero newly
classified (idempotent, confirmed live). New `ReleaseTimingConfidence`
(`EXACT` vs a deliberately late, safe-but-inexact `CONSERVATIVE_SAFE_
BOUND`) and the new `released_at_is_conservative_bound` field keep the
two outcomes structurally distinct — `released_at_is_verified=True` is
never overloaded to mean "we guessed a safely late time". EUR's real
announcement-before-effective-date split is modeled explicitly
(`released_at` before `effective_at`, both DST-correct). No
`ProviderSeriesMapping` is promoted to `POINT_IN_TIME_SAFE` for any
currency — every currency still has unresolved change points across
its full history; interval-specific safety is represented explicitly
instead, in `research_results/fx44/
policy_rate_release_verification.json`. New `domain.research_
readiness.require_research_ready_interval` is the mandatory pre-flight
check a future FX-45 must call — fails closed on a single provisional
observation anywhere in the selected interval. Full details in
`docs/DECISIONS.md`'s FX-44 entry.

**Per this story's own explicit stop instruction**: no pair-rate
differential, no carry strategy, no technical-signal filtering, no
performance research, no JPY provider ingestion, no COT, no
macro-event surprises, no news, no decision logic follows this story
— the differential experiment (FX-45) does not start automatically.

## FX-44H: release-timing semantic hardening (complete)

Fixed a real bug FX-44 shipped (USD's modern EXACT tier conflated the
stored FRED date with the FOMC announcement date; it is actually the
operational EFFECTIVE date — corrected via an explicit, individually-
Fed-calendar-verified `date -> date` mapping, not a formula, after
proving 2 of the 30 affected dates break a naive `-1 day` rule) plus
four related structural gaps: a new, deliberately separate
`correct_verified_release_timing` repository method and `Remediate
ReleaseTiming` use case corrected all 30 already-written USD rows live
(idempotent, concurrency-safe); `require_research_ready_interval` now
accounts for carry-in state (a provisional observation before an
interval can make the whole interval unsafe even with zero changes
inside it) via new `select_research_candidates`, and fails closed on
an empty candidate set; exact/conservative mutual exclusivity is now
structurally enforced at both the domain and persistence layers;
ECB citations now point to the ECB's own official press release, and
`_resolve_eur` fails closed on any non-Wednesday date without an
explicit override. Full details in `docs/DECISIONS.md`'s FX-44H entry.

**Per this story's own explicit stop instruction**: no pair
differential, no carry strategy, no JPY provider, no news/event-
surprise work, no technical filtering follows this story.

## FX-44H.1: USD effective-date correction (complete)

A narrow factual correction to FX-44H: it correctly separated the
FOMC decision date from the provider-stored date, but silently assumed
the stored date always equals the genuine EFFECTIVE date too — wrong
for the same two rows FX-44H had already flagged (2015-12-16
"liftoff", 2016-12-14). The Federal Reserve's own Implementation Notes
place both rows' true effective date one day after the decision date,
the same gap every other mapped USD meeting has.
`USD_EFFECTIVE_TO_DECISION_DATE: dict[date, date]` is replaced by
`USD_POLICY_TIMINGS: dict[date, UsdPolicyTiming]` — a new domain type
keeping `stored_date`/`decision_date`/`effective_date` as three
genuinely independent fields, never assumed equal by a formula, so
this class of bug cannot silently recur for a future USD meeting.
Remediation went through FX-44H's existing `RemediateReleaseTiming`/
`correct_verified_release_timing` completely unmodified: it corrected
exactly the 2 affected rows (28 already matched, untouched), and a
second run reported both `ALREADY_CORRECT` with zero writes. Full
details in `docs/DECISIONS.md`'s FX-44H.1 entry.

**Recorded but explicitly not solved (this story's own point 7)**: if
an observation currently classified EXACT later becomes UNRESOLVED
because further research invalidates its timing entirely (not merely
corrects a value within the tier), this codebase will eventually need
a safe way to REVOKE research-ready status. No declassification
mechanism exists yet — `correct_verified_release_timing` can only
correct an EXACT row's timestamps within the EXACT tier; nothing can
move a row from EXACT back to provisional or to CONSERVATIVE_SAFE_
BOUND once classified. Neither correction in this story needed one.
A future story must not assume this capability already exists.

**Per this story's own explicit stop instruction**: no pair-rate
differential, no carry strategy, no JPY provider work, no technical
filtering, no news/event-surprise logic, no expected-rate differential,
no decision engine changes follow this story.

## FX-45: pair-relative policy-rate differential (complete)

A deterministic, fully-auditable monetary-policy feature --
`differential = base_currency_rate - quote_currency_rate`, `Decimal`
only, never called "carry" -- for EUR/USD, GBP/USD, USD/CAD, built on
two structurally-separate rate-state notions (new `domain.policy_rate_
state`): ANNOUNCED (market-known, `released_at <= T`, deliberately
including a future-effective-but-already-announced rate) and EFFECTIVE
(operationally in force, a POPULATED `effective_at <= T`, never a
fallback guess). New `domain.policy_rate_differential` is pure domain
logic; new `application.use_cases.compute_policy_rate_differential.
ComputePolicyRateDifferential` orchestrates it, running every
historical read through the unmodified FX-44H `require_research_ready_
interval` first, padded by a new 14-day `_AXIS_SAFETY_MARGIN` covering
the gap between FX-44H's `observation_period`-based readiness axis and
this story's `released_at`/`effective_at`-based state-selection axis.
Two kinds of "no answer" are deliberately not conflated:
`ResearchIntervalNotReadyError` RAISED for unsafe/insufficient data
(JPY, via the gate's own `no_baseline` case); `DifferentialUnavailable`
RETURNED for a structurally unsupported request (XAU has no canonical
policy rate; GBP and CAD's EFFECTIVE semantics is currently
unavailable with present effective-date coverage — confirmed directly
via SQL before any code was written). Full details in `docs/
DECISIONS.md`'s FX-45 entry.

**This story's own real diagnostic finding, via `scripts/report_
policy_rate_differential_coverage.py`** (live against real Postgres,
`research_results/fx45/policy_rate_differential_coverage.json`):
EUR/USD 49 usable/105 blocked ANNOUNCED, 43 usable/111 blocked
EFFECTIVE; GBP/USD 78 usable/84 blocked ANNOUNCED, 0 usable/162
blocked EFFECTIVE (not ready in this scan — not a bug, GBP's exact
tier has never had `effective_at` populated); USD/CAD 44 usable/79
blocked ANNOUNCED, 0 usable/123 blocked EFFECTIVE (not ready in this
scan — CAD is 100% conservative-tier). FX-45H (below) revisits these
same numbers with corrected point-in-time semantics and a semantics-
aware diagnostic axis. These blocked windows are the evidence a future
decision about which irregular dates are worth researching
individually should be made from — this story deliberately did not
resolve or delete any of them (its own point 11), and deliberately did
not start the historical rate-differential experiment (FX-46, not yet
started).

**Per this story's own explicit stop instruction**: no automatic
resolution of the blocked crisis dates, no historical rate-
differential experiment, no trading rules, no backtest performance
research, no optimized thresholds, no technical-signal gating, no JPY
ingestion work, no actual broker financing/roll/forward-points/OIS
logic, no event-surprise logic, no news intelligence, no decision
engine changes follow this story.

## FX-45H: policy-rate differential point-in-time & coverage hardening (complete)

Three real point-in-time gaps found in FX-45 itself, fixed without
touching accepted FX-45 architecture or terminology. (1) `effective_
state_as_of` selected the latest `effective_at <= T` without also
requiring `released_at <= T` -- a revision can carry an OLD `effective_
at` but a `released_at` still in the future; new `domain.policy_rate_
state.known_as_of` is the shared PIT filter every function in the
module now applies first. (2) An OLD decision with a populated
`effective_at` could still be reported as the effective state when a
NEWER decision was already released with its own `effective_at`
unestablished -- both `effective_state_as_of` and `previous_effective_
state` now detect this and return `None` instead of silently keeping
the old rate. (3) The readiness window previously padded 14 days
forward from `as_of` unconditionally, letting a genuinely not-yet-
released vintage block a historical query -- confirmed on a real
committed row (USD, 1998-10-15, wrongly blocked a GBP/USD query at
1998-10-08, per this story's own example). `ComputePolicyRateDifferential`
now narrows history to `known_as_of(history, as_of)` before state
selection AND the readiness check both run; the window's baseline no
longer pads unconditionally. (4) `_AXIS_SAFETY_MARGIN`'s documentation
no longer claims 14 days is provably sufficient merely because six is
the largest gap seen -- correctness now rests on `known_as_of`'s exact
filter, the margin is defensive padding only. Terminology: GBP/CAD's
EFFECTIVE-semantics unavailability is now described as "currently
unavailable with present effective-date coverage," not "permanently
unavailable." Full details in `docs/DECISIONS.md`'s FX-45H entry.

**Live diagnostic re-run, same path, now semantics-aware** (ANNOUNCED
samples `released_at` transitions, EFFECTIVE samples populated
`effective_at` transitions): GBP/USD ANNOUNCED improved 78→80 usable
(2 previously-wrong blocks lifted); EUR/USD EFFECTIVE improved 43→44
usable with earliest-ready moving from 2016-03-10 to 2015-12-17
(FX-44H.1's own "liftoff" effective date) once sampled on the correct
axis; EUR/USD ANNOUNCED and USD/CAD ANNOUNCED unchanged, confirming
the fixes are surgical. 1145 tests pass (full suite, up from 1131).

**Per this story's own explicit stop instruction**: no historical
rate-differential experiment, no trading rules, no backtest
performance research, no optimized thresholds, no technical-signal
gating, no JPY ingestion, no news, no event-surprise work follows this
story.

## FX-45H.1: policy-rate readiness & revision semantics hardening (complete)

A narrow further hardening pass on FX-45H, correcting this codebase's
own logic -- no new external research. State selection and research
readiness no longer share one destructively filtered view: a
provisional vintage's `released_at` may be an uncorroborated proxy
(FX-43H), not verified knowability, so `known_as_of` (now private,
renamed `_released_at_on_or_before`) is used only by state selection;
`ComputePolicyRateDifferential` now hands BOTH state selection and
`require_research_ready_interval` the SAME complete, unfiltered
history. `announced_state_as_of`/`previous_announced_state` now select
by observation identity (latest knowable observation_period, then its
own latest admissible revision) rather than raw `released_at`, so a
later-republished correction to an OLDER observation can no longer
wrongly resurrect it as current. A same-observation higher revision
with unresolved `effective_at` now also blocks EFFECTIVE, not only a
later, different observation_period. Full details in `docs/
DECISIONS.md`'s FX-45H.1 entry.

**Diagnostic re-verified, not assumed.** The story's own explicit
instruction was not to assume FX-45H's `GBP/USD ANNOUNCED 78→80`
increase remained valid -- a full before/after diff of the
regenerated report confirms every headline number is unchanged (zero
verdict flips), and the two specific instants FX-45H unblocked hold
for the same legitimate, window-bound reason the real 1998 regression
does, not because of the (now-corrected) unsafe proxy-trust. A real,
previously-uncaught instance of the actual bug DID surface on
regeneration -- several already-blocked entries now correctly list an
additional offending observation FX-45H's design had silently pruned
(verdict unchanged, reason now complete). 1150 tests pass (full suite,
up from 1145).

**Per this story's own explicit stop instruction**: no FX-return
research, no trading/backtesting, no carry, no JPY ingestion, no new
macro providers, no news/event-surprise logic, no technical gating, no
decision-engine changes, no broad macro-vintage-model redesign follow
this story.

## FX-46: historical policy-rate differential research (complete)

The first real research EXPERIMENT against the hardened feature -- not
a trading strategy, no thresholds, no scoring, no signal, no execution
logic. Two pre-registered hypotheses (LEVEL: differential sign vs.
subsequent base-currency return, one ISO-calendar-week sample;
CHANGE: INCREASED vs. DECREASED vs. subsequent return, every D-bar,
no change inferred across a blocked/unavailable gap), run separately
per pair (EUR/USD, GBP/USD, USD/CAD) and semantics (ANNOUNCED/
EFFECTIVE), reading policy-rate state through EXACTLY one seam
(`evaluate_feature` -> `ComputePolicyRateDifferential`, never
reconstructed from raw macro rows). New `scripts/aggregate_d_candles.py`
materialized real daily candles (none existed natively) via the
existing FX-7 `AggregateCandles` use case; `domain/block_bootstrap.py`
gained a calendar-year cluster-bootstrap contrast primitive, reusing
FX-39's own resample-count convention. Full details, architecture, and
the complete results table in `docs/DECISIONS.md`'s FX-46 entry and
`docs/ARCHITECTURE.md`'s own FX-46 section.

**Real results, honestly reported, not graded on direction.** GBP/USD
and USD/CAD EFFECTIVE are entirely unavailable (0 usable observations,
confirming FX-45H's coverage diagnostic at full experimental scale --
not a new finding). EUR/USD EFFECTIVE has real usable coverage and
every usable LEVEL observation is `NEGATIVE` (EUR's effective rate
never exceeded USD's in the covered window). The large majority of
ANNOUNCED contrasts have a 95% CI including zero -- this data does not
establish a reliable association between the raw differential (level
or change) and subsequent return at these three pairs/horizons over
this period. One result (USD/CAD ANNOUNCED/CHANGE, 20d) has a 95% CI
excluding zero in the direction OPPOSITE the pre-registered hypothesis
at a small sample size -- reported as exactly that, not reinterpreted.
A real bug in the script's own summary-reporting code (not the
pre-registered analysis) was found after seeing results, fixed, and
every artifact regenerated from a clean run, per this story's own
explicit instruction never to regenerate selectively. Regression-proof
discipline applied to all 5 named mechanisms. 1182 tests pass (full
suite, up from 1150). **Superseded in part by FX-46H below**: the
"large majority of ANNOUNCED contrasts have a 95% CI including zero"
claim above turned out to include a contrast (EUR/USD ANNOUNCED/LEVEL)
whose reported CI was actually computed from a bootstrap bug -- see
FX-46H for the corrected result (that contrast has no CI at all).

**Per this story's own explicit, doubly-emphasized stop instruction**:
no FX-47, no trading rules, no execution logic, no threshold/parameter
tuning of anything this story reported, no re-running this analysis
with a different configuration follows this story.

## FX-46H: bootstrap validity & research artifact reproducibility (complete)

An external review of FX-46 found a real statistical defect (the
calendar-year cluster bootstrap fabricated a zero mean for an empty
resampled arm -- material for EUR/USD ANNOUNCED/LEVEL, whose
`POSITIVE` group is a single calendar-year cluster) and a real
provenance defect (the committed artifacts recorded a stale
`git_commit` and a query bound mislabeled as the data cutoff). Fixed:
`calendar_year_cluster_bootstrap_differences` now redraws a
replication whose drawn years would leave an arm empty, and reports a
whole contrast `NOT_ESTIMABLE` -- never fabricating a value -- when an
arm has fewer than 2 distinct calendar-year clusters, or the redraw
cap is exhausted. The script now also records `git_commit_dirty`
(scoped to the actual dependency paths, not repo-wide), the real max
D-candle timestamp used per pair, and a deterministic fingerprint of
the policy-rate vintage history read. Full FX-46 experiment re-run
from the clean, corrected commit: 41,008 rows, identical to the
original; exactly the 3 EUR/USD ANNOUNCED/LEVEL cells changed (point
estimates unchanged, CIs now `NOT_ESTIMABLE`) -- no other contrast
affected. Full details in `docs/DECISIONS.md`'s FX-46H entry. 1185
tests pass (full suite, up from 1182).

**Per this story's own explicit stop instruction**: no FX-47, no
trading rules, no execution logic, no re-running this analysis with a
different configuration follows this story.

## FX-47: rate differential x existing technical/regime evidence (complete)

ATTRIBUTION (not gating) of the policy-rate differential against trades
`MultiTimeframeTrendStrategy` and `CloseChannelBreakoutStrategy`
generate unconditionally on EUR/USD, GBP/USD, USD/CAD -- these two
candidates' original FX-38/39 holdout pair, USD/JPY, has zero ingested
policy-rate data (FX-42H.1's provider mapping left unresolved), so this
story ran on the three differential-covered pairs instead, a scope
decision made explicitly with the user before implementation. Exactly
FX-21/FX-21H's own entry-regime-attribution shape: no strategy
parameter changed, no trade gated or suppressed, every trade bucketed
after the fact by LEVEL (differential sign SUPPORTS/OPPOSES/NEUTRAL
relative to trade direction) and CHANGE (FX-46's own per-D-bar
INCREASED/DECREASED/UNCHANGED classification), reported separately.
New `IncrementalCloseChannelBreakoutStrategy` (O(n) sibling to the
existing O(n^2) strategy, parity-tested) was needed for this story's
own ~138,000-candle-per-pair full-history backtest scale -- the same
fix FX-29 already applied to every other strategy in this suite.

**Real result**: level/change bucket totals match each strategy's own
trade count exactly in all 12 (strategy, instrument, semantics) cells.
**Superseded by FX-47H below**: the per-bucket bootstraps summarized
here didn't actually test whether buckets differ from each other, and
the "roughly 150 CIs" claim was wrong (actual: 89) -- see FX-47H for
the corrected primary-contrast methodology and result.

## FX-47H: attribution validity & provenance hardening (complete)

An external review of FX-47 found its per-bucket bootstraps tested only
"is this bucket's own mean distinguishable from zero?", never "do two
buckets actually differ?" -- FX-47's own headline EUR/USD result didn't
survive a proper joint contrast (`mean(SUPPORTS) - mean(OPPOSES) =
-0.0004732`, 95% CI `[-0.00119, +0.00009]` via FX-46H's own joint
calendar-year cluster bootstrap -- crossing zero). Fixed: each cell now
computes that joint contrast as the PRIMARY inferential result;
per-bucket stats remain, relabeled descriptive-only. Also restored the
FX-46H-style provenance FX-47 had regressed on (actual max H1/H4/D
timestamp per instrument, macro fingerprint/count/max `released_at`),
corrected the multiplicity count (89 descriptive CIs, 13 excluding
zero -- computed dynamically now, never hardcoded again), and fixed
`IncrementalCloseChannelBreakoutStrategy`'s complexity description
(O(`lookback`) per bar, not O(1)).

**Real, corrected result**: of 24 primary contrast attempts (12 cells x
LEVEL + CHANGE), 15 are estimable; exactly ONE excludes zero -- GBP/USD
`MultiTimeframeTrendStrategy` ANNOUNCED/LEVEL (SUPPORTS n=238 vs.
OPPOSES n=237, 95% CI `[-0.00323, -0.00040]`) -- roughly consistent
with the ~5% base rate expected by chance across that many tests. The
original EUR/USD "exception" is gone under the correct methodology.
Reported factually, not investigated further (that would itself be the
kind of post-hoc search this epic's protocol forbids). Full details in
`docs/DECISIONS.md`'s FX-47H entry.

**Per this story's own explicit stop instruction**: no FX-48 (already
scoped, awaiting this story's close), no gated/filtered strategy built
from the GBP/USD result above, no further investigation of that
result, no threshold/parameter tuning.

## FX-48: tradable carry / financing feasibility (complete)

A feasibility investigation, not an assumed build -- see this project's
first ADR, `docs/adr/0001-tradable-carry-financing-data-sourcing.md`,
for the full findings; summarized in `docs/DECISIONS.md`'s FX-48 entry.
Also folded in, per the user's own instruction: a minor FX-47 cleanup
(`git_dirty_paths` wasn't actually stored despite the markdown
referencing it; fixed, artifact regenerated, no statistic changed).

Three candidates investigated, verified directly rather than assumed:
**market-quoted FX forward/swap points** -- NOT VIABLE (no free/legal
historical source meeting this project's requirements was found; OANDA
doesn't even quote FX forwards). **OANDA's own historical financing/
rollover** -- NOT VIABLE for backtesting (verified live: the API
exposes only a current snapshot, and this project's own practice
account has zero historical financing transactions -- it has never held
a real position; the Wednesday-vs-Thursday triple-roll difference by
instrument is a concrete exception to the usual convention, not a
contradiction of OANDA's own docs). **Overnight benchmark rate
differential** (SOFR/€STR/SONIA/CORRA) -- VIABLE, all four available
from the same four providers already used for policy rates, with better
instrument coverage than the existing policy-rate differential -- but
with two real methodology breaks (SONIA reformed 2018-04-23, CORRA
reformed 2020-06-15) and a real secured-vs-unsecured heterogeneity
across the four legs (SOFR/CORRA are repo-secured, €STR/SONIA are
unsecured), which is why it's named "overnight benchmark rate
differential" rather than "funding-rate differential." Decision: don't
pursue the first two; a minimal ingestion design for the third is
PROPOSED in the ADR but not implemented, pending separate sign-off --
and even if built, it would still not be literal tradable carry (no
cross-currency basis, no broker markup) and must never be labeled
"carry" or a homogeneous "funding-rate differential."

**Per this story's own explicit stop instruction**: no ingestion code
for the overnight benchmark rate differential without a separate,
explicit go-ahead; no relabeling of `policy_rate_differential` as
"carry."

## FX-49: rate-expectations data-source feasibility (DEFER)

A pure source-feasibility investigation, not a build -- see this
project's second ADR, `docs/adr/0002-rate-expectations-data-source-
feasibility.md`, for full findings; summarized in `docs/DECISIONS.md`'s
FX-49 entry. Investigated whether a defensible, point-in-time-safe
historical record of market-EXPECTED (not current/observed) future
policy rates is obtainable for EUR/GBP/USD/CAD, at 3/6/12-month
horizons, to eventually gate an FX-50 "expected-rate differential."

A real, liquid futures instrument exists for every currency (Fed Funds/
SOFR futures for USD, SONIA futures for GBP, Euribor/€STR futures for
EUR, CORRA futures for CAD), not all long-established (CAD's cleanest
instrument dates only to 2020, EUR's most comparable one only to 2023),
and a settlement price is genuinely point-in-time-safe (a
contemporaneous exchange-determined settlement value). But the
multi-year historical backfill this project would need is gated behind
a paid commercial subscription for every currency (current/same-day
publication is often free; multi-year depth is not) -- CME DataMine/
ICE Data Services/TMX Datalinx -- with redistribution-restricted
licensing, unlike FX-48's own overnight-benchmark-differential finding,
which had a free alternative. A PIT trap was found and avoided: CME's
derived "Term SOFR" benchmark only really launched 2021-04-21 for its
1M/3M/6M tenors and 2021-09-21 for its 12-month tenor (2022-05-19 was
the ARRC's later, separate endorsement of the already-live 12-month
tenor, not its first publication) -- any "historical" value dated
before its own tenor's real launch would be a back-calculated
reconstruction, not a genuine observation. EUR has an additional
depth-vs-comparability tension (Euribor futures: ~28y but a
credit-premium-bearing term rate; €STR futures: improves on Euribor by
pricing an overnight risk-free rate, but still doesn't match SOFR/
CORRA's secured-repo character, and is <3 years old).

**Decision: DEFER** -- not NO-GO, not GO. Reopening requires an
explicit commercial-licensing/cost decision this story has no
authority to make, a deliberate EUR instrument choice, and resolving
several UNRESOLVED technical items (see the ADR). **FX-50 (expected-
rate differential) remains explicitly gated on these conditions and
has NOT been started.**

**Per this story's own explicit stop instruction**: FX-50 not started;
no commercial data subscription added or authorized; no relabeling of
any existing feature as "expected rate" or "carry."

## FX-51: point-in-time economic event model (complete)

First story of a new epic, `FX-EPIC-07 Economic Event Risk` (older
architecture notes may call this story FX-49 -- this codebase's FX-49
is the rate-expectations feasibility story above, so this one is
FX-51). Provider-neutral, point-in-time-safe domain and persistence
model for scheduled economic events and their released values --
explicitly NOT an economic-calendar ingestion story: no calendar
provider was chosen or integrated, no real data was populated.

New domain types (`domain/economic_event_*.py`): `EconomicIndicatorDefinition`
(pure in-memory, never persisted -- mirrors FX-41's own
`MacroSeriesDefinition`), `EconomicEventOccurrence` (identity is
`(indicator_key, reference_period)`, deliberately never a scheduled
timestamp), and three vintage types --
`EconomicEventScheduleVintage`/`EconomicEventConsensusVintage`/
`EconomicEventActualValueVintage` -- each an immutable one-row-per-
revision fact, the same shape `MacroObservationVintage` (FX-41)
already established, with no UPDATE path anywhere in this story: a
reschedule/consensus revision/value revision is always a new row with
a later `availability` and a higher `revision_sequence`.
`EconomicEventActualValueVintage` deliberately has no `previous_value`/
`surprise` field -- a provider's own "previous" is a known PIT trap,
and a raw surprise must be derived later (FX-53) from this same
vintage history, never stored as a single mutable value a later
revision could silently rewrite. `domain/economic_event_state.py`
provides the pure PIT-selection functions
(`latest_schedule_as_of`/`latest_consensus_as_of`/
`latest_actual_as_of`/`first_release_as_of`), mirroring
`domain/policy_rate_state.py`'s own shape.

Persistence: 4 new tables via Alembic migration `bb7551fcef3a` --
`economic_event_occurrences` plus its three vintage tables, each
vintage table referencing its occurrence through a genuine composite
`FOREIGN KEY` on the natural key `(indicator_key, reference_period)`
(the same natural-key-reference pattern `MacroObservationVintage`
already uses), a `CHECK` constraint enforcing `availability IS NULL`
iff `availability_confidence = 'UNKNOWN'`, and an index on
`(indicator_key, reference_period, availability)` supporting every
`*_as_of` query. `application/ports/economic_event_repository.py` /
`infrastructure/db/economic_event_repository.py` implement the
Section-14 PIT query contract (`schedule_as_of`/`consensus_as_of`/
`actual_value_as_of`/`first_release_as_of`/`known_events_in_window`),
and `application/use_cases/get_economic_event_state.py` assembles all
four for one occurrence at one instant. Full details, including the
worked point-in-time examples this story's own tests exercise, in
`docs/DECISIONS.md`'s FX-51 entry. No new ADR -- this is an
implementation of an already-approved conceptual model, not a fresh
durable architectural trade-off decision the way ADR 0001/0002 were.

**Per this story's own explicit stop instruction**: FX-52 (economic
calendar + surprise ingestion) has NOT been started; no calendar
provider was chosen or integrated; no real economic-event data was
populated; no surprise calculation was implemented; no trading rule,
risk weight, or auto-block was added for any event or its provider-
supplied importance label.

## FX-51H: point-in-time economic event model hardening (complete)

Hardens FX-51's own conceptual model in place -- before FX-52 began --
per an explicit set of gaps identified in FX-51's original design.
Six changes: (1) occurrence identity moved from `(indicator_key,
reference_period)` onto a single stable `occurrence_key`, with
`reference_period` now optional so a qualitative/irregular event (an
FOMC press conference, meeting minutes) can exist without a fabricated
period; (2) a new `EconomicEventReleaseVintage` type records "this
occurrence actually happened," independent of whether it has a numeric
value -- fixing FX-51's own gap where a qualitative event had no
honest way to record its own occurrence; (3) `known_events_in_window`
now resolves TRUE timezone instants (an exact UTC instant for a
known-time schedule, a full local-day UTC range for a date-only one)
via a new pure `schedule_within_window` function, replacing FX-51's
own local-date-vs-UTC-date comparison; (4) `release_group_key` may now
be attached to an occurrence after creation via a second narrowly-
scoped legitimate mutation, `attach_release_group` (idempotent,
conflict-detecting); (5) the repository/use-case PIT contract gained a
`release`/`release_as_of` axis; (6) every existing FX-51 invariant
(insert-only vintages, fail-closed unknown availability, no persisted
`previous_value`/`surprise`, provider neutrality) is preserved
unchanged. Migration `76a4b23b2129` re-keys all four tables and adds
`economic_event_release_vintages`; verified up/down/up against live
Postgres. 67 domain unit tests + 32 live-Postgres integration tests,
all passing. Full details in `docs/DECISIONS.md`'s FX-51H entry. No
new ADR -- this hardens an already-approved conceptual model per
explicit instruction, not a fresh durable architectural trade-off.

**Per this story's own explicit stop instruction**: FX-52 still has
NOT been started; no calendar provider was chosen or integrated; no
real economic-event data was populated; no surprise calculation was
implemented; no trading rule or risk weight was added.

## FX-51H.1: economic event model final integrity patch (complete)

Two small, final gaps closed on FX-51H's own model -- no redesign of
occurrence identity, release vintages, timezone handling, or PIT
semantics. (1) `attach_release_group` now rejects a non-string/empty/
whitespace-only `release_group_key` with `ValueError` before any SQL
runs, mirroring `EconomicEventOccurrence.__post_init__`'s own
validation of the same field. (2) Migration `76a4b23b2129`'s downgrade
limitation -- previously only documented, not enforced -- is now a
runtime guard (`_raise_if_downgrade_would_lose_data`) that checks all
five tables the migration touches and raises `RuntimeError` naming the
offending table before any destructive DDL runs; this is a PERMANENT
limitation once real economic-event data exists (no old-schema
equivalent for `economic_event_release_vintages`; the old schema
cannot represent a `NULL` `reference_period` or two `occurrence_key`s
sharing one `(indicator_key, reference_period)` pair), verified both
against live Postgres and via a new mock-`op` unit test module
mirroring this project's existing migration-testing precedent. 14 new
tests (6 integration + 8 unit); full details in `docs/DECISIONS.md`'s
FX-51H.1 entry. No new ADR.

**Per this story's own explicit stop instruction**: FX-52 still has
NOT been started; no calendar provider was chosen or integrated; no
real economic-event data was populated.

## FX-52: economic calendar + surprise ingestion (DEFER)

A source-feasibility investigation with an explicit GO/DEFER/NO-GO
gate -- not an assumed build -- into whether the FX-51/FX-51H/FX-51H.1
model can be populated with real, provider-backed economic-calendar
data. This project's third ADR:
`docs/adr/0003-economic-calendar-data-source-feasibility.md`. Three
candidate classes investigated (commercial calendar APIs, official
government/central-bank sources, consumer/aggregator sites) -- nothing
cleared the gate. Trading Economics is structurally closest (a
documented Point-in-Time endpoint, a stable `CalendarId`, UTC
timestamps, a TBD-time flag) but its own schema-reference page defines
`Actual` as "latest released value," directly contradicting the
Point-in-Time endpoint's own claim of preserving pre-revision
snapshots -- an unresolved documentation contradiction, plus no free
tier and no confirmed real pricing. Financial Modeling Prep's calendar
endpoint has a genuine free tier but is self-tagged `"staging"` with
zero documented PIT semantics. Finnhub gates historical calendar data
to unpriced Enterprise access AND has no event-type or occurrence ID
field of any kind. Official government/central-bank sources
structurally cannot supply consensus/forecast at all (a private-sector
survey product, confirmed absent everywhere, as expected), but ALFRED
(US-only) is a verified genuine point-in-time vintage mechanism for
actual values; EUR/GBP/CAD official-source vintage mechanisms remain
UNKNOWN, not ruled out. All 5 consumer/aggregator sites (ForexFactory,
Investing.com, DailyFX, Econoday, Nasdaq Data Link) were ruled out --
no permitted API, explicit ToS reuse prohibition, permanent site
closure, or unpriced enterprise-only access.

**Decision: DEFER**, not NO-GO and not GO. Reopening requires, in
order: (1) resolving Trading Economics' own Point-in-Time-vs-schema
contradiction directly with the vendor, or finding a provider whose
documentation unambiguously establishes historical consensus-freeze
and first-release-actual semantics; (2) obtaining real quoted pricing
for whatever tier is actually required and putting that number to the
user for explicit approval -- this story has no authority to commit to
a subscription cost, the same constraint FX-48/FX-49 already
established; (3) confirming internal-research-use/redistribution
rights at that tier are compatible with this project's own non-
redistributive use; (4) a deeper dive into EUR/GBP/CAD official-source
vintage mechanisms not found in this pass; (5) an explicit, non-
unilateral decision about whether any narrower scope (e.g. dropping
consensus, which no official source can ever supply) would still
satisfy FX-52's own stated purpose. No FX-53 implementation contract
was written (only required on GO, per this story's own instruction).
Full details in `docs/DECISIONS.md`'s FX-52 entry.

**Per this story's own explicit stop instruction**: FX-53 (Macro
Surprise and Post-Release Drift Research) remains gated on FX-52's own
DEFER reopening conditions above and has NOT been started; no
economic-calendar provider was chosen or integrated; no commercial data
subscription or trial requiring payment was started or authorized; no
real event data was populated; no production ingestion code, HTTP
client, provider-mapping table, canonical indicator registry instance,
or migration was written. **Correction (2026-09-26, FX-54): the
original wording here also gated FX-54 (Event-Risk Evidence Snapshot)
on this same DEFER -- FX-54 has since been explicitly authorized and
completed as a TIMING-ONLY story, deliberately built on FX-52A/FX-52AH/
FX-52AH.1's own official-source timing evidence alone, without
reopening or needing FX-52's own commercial consensus/surprise DEFER at
all. See this file's own FX-54 section below.**

## FX-52A: official economic calendar timing ingestion (complete)

Deliberately separate from FX-52 -- does NOT reopen or weaken FX-52's
own DEFER (ADR 0003, unchanged). Real, OFFICIAL-source-only ingestion
of forward SCHEDULE timing and positive RELEASE-occurrence evidence:
no consensus, no numeric actual values, no commercial provider. This
project's fourth ADR: `docs/adr/0004-official-economic-calendar-
timing-sources.md`.

Four sources adopted after re-verifying every ADR-0003 lead directly
against its own live feed: BLS's public ICS schedule feed (US CPI +
Employment Situation, the latter split into `US_NONFARM_PAYROLLS`/
`US_UNEMPLOYMENT_RATE` sharing one `release_group_key` -- this story's
own worked release-package-split demonstration); ONS's public RSS
schedule feed (UK, `GBP_GDP_QOQ` only -- the one release series
directly confirmed against a real live item); Bank of Canada's public
ICS schedule feed AND its separate public press-release feed (CAD,
`CAD_POLICY_RATE_DECISION`, both schedule and release evidence). Five
sources explicitly excluded, each for a different documented reason:
BEA (no stable ID, no reference-period signal); Eurostat (a real
iCalendar mechanism exists but its actual URL is client-side-button-
generated with no stable static URL discoverable -- EUR therefore has
ZERO FX-52A coverage, an honestly-reported gap, not an oversight); ECB
(still HTML-only, no timezone); Bank of England (no forward feed,
though its general news RSS has a clean, matchable release-evidence
title pattern -- the most immediately actionable follow-up increment,
deferred purely for story-budget reasons); Statistics Canada (HTTP 500
on every fetch attempt).

Occurrence identity was originally (FX-52A) a pure, deterministic
function of `(source, external_event_id, indicator_key)` -- corrected
by FX-52AH below. Two real, confirmed findings surfaced by this
story's own REQUIRED real-source validation (Section 43), neither of
which synthetic-fixture unit tests could have caught: (1) Bank of
Canada's schedule feed 301-redirects, and an earlier version silently
"succeeded" while parsing an empty redirect body -- fixed with
`follow_redirects=True` on every adapter; (2) BLS's own feed returns
HTTP 403 to a plain server-side request even with realistic browser
headers -- confirmed NOT a parsing/licensing problem, left as an
honestly-FAILING, documented live test rather than hidden, matching
this project's own existing weekend-market-closure-OANDA-test
precedent. **BLS is implemented and unit-tested but operationally
BLOCKED by this 403 -- it must not be treated as a live source of US
CPI/Employment-Situation timing, and must not be used for real
ingestion, until this is resolved.**

73 new tests (parsers, occurrence-identity helper, indicator registry,
4 mocked-HTTP adapter suites, 16 live-Postgres integration tests, 4
real-source validation tests -- 3 passing, 1 honestly failing per the
BLS finding). 1411 tests pass overall. Full details in
`docs/DECISIONS.md`'s FX-52A entry.

## FX-52AH: official calendar identity & source-safety hardening (complete)

A hardening pass on FX-52A, required before FX-54 could safely build
on it. Corrects four defects: (1) occurrence identity is now
provider-neutral (`mint_occurrence_key`, an `indicator_key:uuid4`
string) plus a genuinely persisted many-to-one mapping table,
`economic_event_source_mappings` (migration `df99b7796566`, new port
`EconomicEventSourceMappingRepository`) -- so Bank of Canada's ICS
schedule feed and RSS release feed, or any future multi-source case,
can correctly resolve to the SAME canonical occurrence, which FX-52A's
original source-derived-key design made structurally impossible; (2)
date-based release/schedule correlation now requires EXACTLY ONE
candidate (zero mints a new occurrence; more than one is an explicit
`AMBIGUOUS_CORRELATION` disposition that writes nothing, never a
silent choice) and PERSISTS a successful correlation so it is never
re-run for the same external identity; (3) Bank of Canada's RSS
`dc:date` is no longer promoted to exact `released_time` (preserved
instead as `source_published_at` provenance; `released_time` for BoC
release evidence is honestly `None`; `released_date` prefers the
CBWiki `cb:news/cb:occurrenceDate` element when present); (4) malformed
HTTP-200 responses now fail closed (`MalformedIcsError`/
`MalformedFeedError` -> `EconomicCalendarSourceUnavailableError`),
distinct from a genuinely well-formed empty result, and parser/adapter
results now carry `mapped_count`/`unmapped_count`/`invalid_count`.
A new `pytest.mark.live_source` marker + `addopts -m "not live_source"`
means ordinary `pytest`/CI never depends on a real network call; the
four adopted sources' live-validation tests run separately (`pytest -m
live_source`: 3 passing, 1 honestly failing -- BLS 403, re-confirmed
unresolved). Full deterministic suite: 1423 passed, 4 `live_source`-
deselected; failures are exactly the pre-existing, unrelated
Saturday-weekend live-OANDA-candle set. Full details in
`docs/DECISIONS.md`'s FX-52AH entry.

**Per this story's own explicit stop instruction**: FX-52 remains
DEFER, untouched; FX-53 remains BLOCKED; FX-54 has NOT been
implemented; no consensus, numeric actual value, or surprise was
ingested or calculated; no event-risk score or trading rule was added;
no Decision/Risk Engine integration was made; all of FX-52A's own
successful behaviour is preserved unchanged.

## FX-52AH.1: official calendar final timing & integrity patch (complete)

A narrowly-scoped final integrity patch closing five specific gaps
found after FX-52AH -- mirrors FX-51H.1's role relative to FX-51H.
(1) Fixed a real timezone bug: `OnsScheduleSource` took `.date()`/
`.time()` straight off `pub_date` (always UTC-normalized by
`rss_parsing`) while claiming `schedule_timezone = "Europe/London"` --
silently relabeling a UTC instant as London local time, wrong by
London's own UTC offset for every item published during BST; fixed by
explicitly converting to `Europe/London` before reading date/time
components, with new BST- and GMT-dated regression tests proving the
observation round-trips through `schedule_within_window` back to the
original UTC instant. (2) `economic_event_source_mappings.
occurrence_key` gains a genuine `FOREIGN KEY` onto `economic_event_
occurrences.occurrence_key` (migration `ecdb152af0a8`) -- FX-52AH's
own original design deliberately omitted this, but both ingestion use
cases already commit `add_occurrence` before calling `record_mapping`
(this repository layer commits after every statement), so the FK is
safely satisfiable with no deferred-constraint machinery; verified a
dangling `occurrence_key` insert now fails with a real FK violation.
(3) `df99b7796566`'s downgrade now refuses (`RuntimeError`) when the
mapping table is non-empty rather than silently discarding resolved
cross-source identity, mirroring `76a4b23b2129`'s own guard (FX-51H.1
precedent) -- verified by inserting a real mapping row and confirming
the guard fires, leaving the schema untouched. (4) `source_published_at`
is now genuinely persisted (a nullable column on `economic_event_
release_vintages`, also migration `ecdb152af0a8`) rather than computed
and silently discarded on every real poll, as it was after FX-52AH
introduced the field but never carried it through. (5) All of FX-52AH's
own behaviour preserved unchanged. Full deterministic suite: 1435
passed (up from 1423), 4 `live_source`-deselected, same pre-existing
Saturday-weekend live-OANDA-candle failures. Live-source validation run
separately: 3 passing (ONS -- now exercising the corrected timezone
conversion against the real live feed -- BoC schedule, BoC release), 1
failing (BLS 403, unchanged, not a regression from this story). Both
migrations verified up/down/up against live Postgres, including a
manual guard-firing check with a real inserted mapping row. Full
details in `docs/DECISIONS.md`'s FX-52AH.1 entry.

**Per this story's own explicit stop instruction**: FX-52 remains
DEFER, untouched; FX-53 remains BLOCKED; FX-54 had NOT yet been
implemented at the time this section was written -- see the FX-54
section immediately below, since FX-54 was explicitly authorized and
completed as its own subsequent story.

## FX-54: event-risk evidence snapshot, timing-only (complete)

Explicitly authorized by this story's own prompt, which stated plainly
that any prior documentation saying "FX-54 not requested" or that
FX-54 is blocked solely by BLS's 403 is superseded by that
authorization. Scoped down to exactly what FX-52A/FX-52AH/FX-52AH.1's
existing timing evidence supports -- deliberately does NOT implement
the surprise-related portion of FX-54's original long-term vision.
FX-52 remains DEFER and FX-53 remains BLOCKED, both entirely untouched
by this story; FX-54 needed neither to be reopened.

`application.use_cases.get_event_risk_evidence_snapshot.
GetEventRiskEvidenceSnapshot` answers "given this FX pair, at this
exact instant, what economic-event TIMING evidence did the system
know?" This is EVIDENCE, not POLICY: it never computes a risk score,
importance label, trade veto, blackout window, or directional/
bullish/bearish interpretation -- every new domain type
(`EventScheduleEvidence`/`EventReleaseEvidence`/`EventEvidenceGroup`/
`EventCoverageEvidence`/`EventRiskEvidenceSnapshot`) has a dedicated
unit test asserting no such field exists on its own dataclass fields.

Explicit input contract (`Instrument`, `as_of: UtcTimestamp`,
`lookahead: timedelta`, `lookback: timedelta`, all caller-supplied) --
never a hidden `datetime.now()` call and never an invented 15/30/60-
minute policy window; negative horizons raise `ValueError` before any
repository call is made. Pair relevance is resolved exclusively
through the canonical registry (`pair_role_by_indicator_key`, backed by
a small new `indicators_by_currency` registry addition -- never a
second, competing currency mapping); `PairCurrencyRole` is
deliberately non-directional, structural evidence only.

Forward-schedule evidence reuses `known_events_in_window`/
`schedule_within_window` completely unchanged. Release evidence needed
the identical shape applied to release vintages instead of schedule
vintages, so a new, structurally identical repository method
(`known_releases_in_window`) and domain function
(`release_within_window`) were added -- duplicated by direct analogy
rather than generalized into one callback-parametrized query.
Timezone/date/time resolution was centralized into two shared
functions (`resolve_exact_instant`/`resolve_local_day_utc_range`),
with `schedule_within_window` refactored onto them (behavior-
preserving, all pre-existing tests still pass unchanged) -- closing off
FX-52AH.1's own ONS-timezone-bug class of mistake permanently, since
there is now exactly one place in this codebase that performs this
arithmetic at all.

Exact-vs-date-only timing is enforced as a first-class state at
construction time (a `ValueError` if an exact instant exists without
its own local time being known, or if it disagrees with its paired
duration field about being `None`) -- `time_until_event`/
`elapsed_since_release` are plain `timedelta`s, never a pre-rounded
"minutes until" value this story does not need to invent a rounding
rule for. Release grouping cannot invent an aggregate fact by
construction: `EventEvidenceGroup[T]` carries only `group_key`/
`members`, with structurally nowhere to put a "primary member" or a
group-level exact time; grouping is by `EconomicEventOccurrence.
release_group_key` only, never by coincidental matching timestamps
(verified directly with a dedicated test). Groups and members both
sort deterministically -- groups by the earliest member's own resolved
instant (an internal-only helper, never exposed on the public evidence
type, so no fabricated instant leaks out even for ordering purposes),
members by `(indicator_key, occurrence_key)`, never by an invented
"primary" member.

`EventCoverageEvidence` (always present, even when both evidence
tuples are empty) is this story's own answer to "empty must never mean
safe": it reports every tracked indicator key for each of the pair's
two currencies plus which currencies (if any) have zero tracked
indicators at all -- EUR, for any EUR pair, today. Deliberately reports
NO source-health/freshness signal at all: no durable source-health/
poll-state metadata exists anywhere in this repository for the
economic-calendar subsystem, so this is stated honestly in the type's
own docstring rather than invented (the closest analog,
`IngestionWatermarkRepository`, belongs to the unrelated OANDA-candle-
backfill bounded context). No `all_clear`/`safe_to_trade`/
`no_event_risk` field exists anywhere in this story's own types,
checked by a dedicated test.

Performs NO network I/O of its own (verified by a signature-inspection
unit test proving the constructor accepts only the repository port);
BLS's live HTTP 403 remains purely an ingestion-layer limitation,
confirmed unchanged by this story -- every FX-54 deterministic test
persists event data directly via the repository using REAL canonical
indicator keys (`GBP_GDP_QOQ`, `US_NONFARM_PAYROLLS`,
`US_UNEMPLOYMENT_RATE`, `CAD_POLICY_RATE_DECISION`, `US_CPI_YOY`), so
pair-relevance filtering is exercised against genuine registry
resolution, never a fake/unrecognized key. No new migration --
`EventRiskEvidenceSnapshot` is computed on request from already-
persisted canonical event data, never persisted itself; the only
addition is the `known_releases_in_window` repository method, with no
schema change at all.

63 new tests (42 domain unit + 4 application unit + 6 `known_releases_
in_window` live-Postgres integration + 12 end-to-end `GetEventRiskEvidenceSnapshot`
live-Postgres integration tests, including this story's own Section 34
release-PIT worked example verbatim: released 09:47, availability
09:50, `as_of` 09:48 excludes the release, `as_of` 09:51 includes it).
1523 tests pass overall (up from 1435); failures are exactly the
pre-existing, unrelated Saturday-weekend live-OANDA-candle set. Live-
source validation re-run separately: unchanged, 3 passing / 1 failing
(BLS 403). `ruff check`/`ruff format --check`/`mypy .`/`pre-commit run
--all-files` all clean. `pyproject.toml`'s own version was left at its
existing `0.1.0` -- this repository has never actually followed a
story-number-aligned version scheme through any prior FX-51..FX-52AH.1
story, so none was invented here either.

Full details in `docs/DECISIONS.md`'s FX-54 entry.

**Per this story's own explicit stop instruction**: FX-52 remains
DEFER; FX-53 remains BLOCKED; no Decision/Risk-Engine integration was
added; no blackout/trade-blocking logic was implemented; FX-EPIC-08
(News Intelligence) was not started.

## FX-54V: fundamental & economic-event evidence visualization (complete)

A read-only "Market Context" dashboard over evidence FX-EPIC-06/
FX-EPIC-07 already produce -- the first trader-facing visualization in
this project. Explicitly NOT a Decision Engine, Risk Engine, trading
signal, fundamental-strength model, or event-risk scorer; answers "what
does the system know," never "what should I trade."

Inspected existing architecture first: a minimal FastAPI app already
existed (`/health` only) alongside a hand-built, framework-free static
dashboard precedent (`fta_dashboard_sketch.html`, inline CSS/vanilla
JS/SVG, no build chain, no charting library, no `package.json`, no
template engine anywhere in this repository). FX-54V's own dashboard
(`GET /market-context` plus small JSON routes under `apps.api.routers.
market_context`) follows that exact convention rather than introducing
a JS framework or build chain.

Two new, deliberately narrow use cases, `GetFundamentalRateEvidence`/
`GetPolicyRateHistory`, deliberately bypass FX-45's own `research_
readiness` gate (a research-safety requirement for a differential-
CHANGE feature, not a "can we truthfully show today's already-known
rate" requirement) while reusing the SAME pure domain functions FX-45/
FX-45H.1 are built on -- plus two new domain functions,
`announced_history_as_of`/`effective_history_as_of`
(`domain.policy_rate_state`), and a new domain type,
`FundamentalRateEvidence`, which lets either leg of a pair be
individually missing (with an explicit reason) while the OTHER leg's
real evidence still renders. FX-46's own committed research artifact
gets a typed, validating, read-only loader (never reruns the research,
parses every statistical field via `Decimal` never `float`,
`infrastructure.research.fx46_research_artifact`) and its own view
model, whose `RESEARCH_CONCLUSION_NOTE` reproduces FX-46's own null/
general-negative conclusion verbatim in substance -- never
reinterpreted as a signal, even where one isolated confidence interval
happens to exclude zero.

Every new domain/view-model type has a dedicated test asserting a
fixed list of forbidden policy-field names (`risk_score`,
`should_trade`, `blackout`, `fundamental_advantage`, `signal`, ...) is
structurally absent from its own fields. An empty event window renders
"No tracked PIT-visible events in this window" -- never "all clear"/
"safe to trade." Performs NO network I/O from any route; the ONLY
place `datetime.now()` is ever called is an explicit UI convenience
default when `as_of` is omitted, with every use case still receiving
an explicit, already-resolved instant; a malformed/naive explicitly-
supplied `as_of` returns `400`. `apps.api.pairs.SUPPORTED_PAIRS`
(EUR/USD, GBP/USD, USD/CAD) is this dashboard's own presentation-
facing pair registry, not a domain concept.

Manually verified end-to-end against the real dev database and the
real committed FX-46 artifact for all three pairs, including seeding
and then immediately deleting temporary, clearly-prefixed test event
data to verify grouping/TBD-time/cancellation/pair-role rendering (no
fake evidence left in any shared table). No new migration, no schema
change of any kind. ~72 new tests. 1595 tests pass overall (up from
1523); failures are exactly the pre-existing, unrelated Saturday-
weekend live-OANDA-candle set. Live-source validation re-run
separately: unchanged, 3 passing / 1 failing (BLS 403). `ruff check`/
`ruff format --check`/`mypy .`/`pre-commit run --all-files` all clean.
No ADR added -- this story's own layering is a direct application of
CLAUDE.md's already-documented architecture, not a new durable
trade-off. Full details in `docs/DECISIONS.md`'s FX-54V entry.

**Per this story's own explicit stop instruction**: FX-49 remains
DEFER; FX-52 remains DEFER; FX-53 remains BLOCKED; no Decision/Risk-
Engine integration was added; no BUY/SELL/blackout/trade-recommendation
logic was implemented anywhere; FX-EPIC-08 (News Intelligence) was not
started.

## FX-55: News Intelligence source feasibility, rights & scope (complete)

FX-EPIC-08's own first story, explicitly authorized and explicitly
documentation-only: determine what source material FTA may
responsibly build future news-evidence ingestion on. Four parallel
research passes investigated (A) primary/official government and
central-bank NEWS feeds -- re-verified independently of FX-52A's own
SCHEDULE/RELEASE timing work, since the two remain separate evidence
categories even at the same institution; (B) general financial news
providers (Reuters/LSEG, Dow Jones/Factiva, Bloomberg, AP, FT); (C)
news APIs/aggregators (GDELT, NewsAPI, Alpha Vantage, Finnhub, FMP,
Marketaux, Polygon/Massive); (D) dedicated FX/macro commentary
publishers (FXStreet, ForexLive/InvestingLive, Action Forex,
MarketPulse, DailyFX, ING THINK, others). Every material property
(automated-access rights, internal-use permission, storage/retention,
derived-processing rights, stable identity, publication/update/
correction semantics, cost, rate limits) classified VERIFIED/
PARTIALLY_VERIFIED/UNKNOWN/UNSUITABLE strictly from each vendor's own
primary documentation, per this project's own FX-49/FX-52 evidentiary
discipline; every source given an independent ADOPT_PROSPECTIVE/
ADOPT_HISTORICAL/DEFER/REJECT verdict, never collapsed into "an API
exists = licensed."

Deliverable: `docs/adr/0005-news-intelligence-source-feasibility.md`.
**Verdict: PARTIAL_GO.** A bounded, rights-clear prospective source
set is adoptable using official sources only -- the Federal Reserve,
the ECB's combined press/speech/interview feed, the Bank of England,
the GOV.UK Content API (HM Treasury -- the single strongest source
found: a UUID decoupled from its URL, genuinely separate first-
published/updated timestamps, an explicit correction log, retraction
representation, and OGL v3.0 "any purpose, no agreement needed"
terms), Statistics Canada's Daily feeds, and the Bank of Canada's
press-releases feed (adopted only with mandatory timestamp
remediation -- its `dc:date` mislabels America/Toronto local time as
`+00:00`, independently reconfirming FX-52AH's own prior decision not
to trust it as an exact `released_time`; its separate speeches feed
was found to carry future-dated entries and is explicitly NOT
adopted). This mirrors FX-52A's own official-source-only precedent in
FX-EPIC-07 after FX-52's commercial DEFER. No general financial news
provider, commercial news API/aggregator, or dedicated FX-commentary
publisher currently clears the rights/PIT/identity bar -- each is
either commercially gated with no public price or storage terms, or
blocked by a resolvable rights conflict (source-specific clarification
questions were prepared per DEFER candidate and explicitly NOT sent,
per this story's own hard prohibition on contacting vendors, starting
trials, or entering payment information). GDELT's bulk metadata
channel has unrestricted, fee-free rights, but structurally carries no
headline or article text, so it is classified ADOPT_AUXILIARY_METADATA
and excluded from the text-bearing adopted set entirely (corrected by
FX-55H -- see below).

No source investigated across any of the four classes -- **GOV.UK's
own Content API included** -- exposes FTA's own directly verifiable
ingestion/first-seen timestamp; only FTA's own retrieval process can
produce one (corrected by FX-55H; an earlier pass wrongly exempted
GOV.UK). First-seen/retrieval time is therefore the required default
FTA availability anchor everywhere, without exception, extending
FX-51-54's own PIT discipline into this new evidence category. Independently
reconfirmed two operational findings that sit outside this story's own
scope but matter to the epic: BLS now returns HTTP 403 on every path,
including its own `robots.txt`, from this research environment
(FX-52A's already-adopted `bls.ics` calendar feed should be re-checked
from the real production egress IP); and ONS's own timestamps were
independently confirmed roughly eight hours off the true release
instant via two separate primary endpoints.

Baseline re-established per this story's own instruction, not assumed
from a prior story: initial run, `pytest --no-cov -q` -> 1601 passed,
1 failed (`test_get_account_balance_against_live_practice_api`, a
live-OANDA 307-redirect/non-JSON-response failure -- a different
signature than the previously-reported weekend candle-empty set,
confirming a stale baseline claim would have been wrong here), 4
deselected. A same-session retry of the full suite -- performed for
FX-55H's own re-verification, not to discard the first result --
returned 1602 passed, 0 failed, 4 deselected: the live-OANDA failure
did not reproduce, consistent with a transient live-network condition
rather than a codebase regression. Both results are recorded; neither
supersedes the other. `ruff check`/`ruff format --check`/`mypy .` all
clean on both runs. No production code,
schema, migration, or dependency changed -- verified unchanged by this
story. No purchase, paid trial, credential signup, or scraping past
any bot-protection/robots.txt/terms boundary was performed anywhere;
where a publisher's own `robots.txt` named this project's agent class
with `Disallow: /` (discovered for ForexLive's successor domain,
InvestingLive), that boundary was honored without further probing.
Full details in `docs/DECISIONS.md`'s FX-55 entry and in ADR 0005
itself.

**Per this story's own explicit stop instruction**: FX-49 remains
DEFER; FX-52 remains DEFER; FX-53 remains BLOCKED; no news ingestion,
deduplication, classification, sentiment, dashboard, or Decision/
Risk-Engine work was started; **FX-56 (Point-in-Time News Evidence
Model) may begin**, scoped exactly to ADR 0005's own stated
adopted-source set and assumptions -- see that ADR's own "FX-56
readiness" section.

## FX-55H: news source PIT & admission semantics hardening (complete)

A documentation-only correction pass on FX-55/ADR 0005, performed
before starting FX-56 -- mirroring FX-52AH's own role correcting FX-52A
before FX-53 was attempted. Two categories of correction, both
verified against this ADR's own governing rule that an unresolved
critical rights/access property blocks ADOPT status, never inferred
favorably:

**PIT-anchor corrections.** FX-55's own initial pass treated GOV.UK's
`first_published_at` as an exception letting it stand in directly for
FTA's own availability anchor, and treated a corrected Toronto-local
reinterpretation of BoC's `dc:date` as an alternative to first-seen
time. Both were wrong. **FTA availability is now stated, without
exception, as FTA's own `first_seen_at`/retrieval timestamp for every
prospectively collected news item from every source** -- a new "FTA
availability invariant" section in ADR 0005 makes this the ADR's own
governing statement, superseding every conflicting sentence elsewhere
in that document. GOV.UK's own rich metadata
(`first_published_at`/`public_updated_at`/`updated_at`/
`change_history`/`withdrawn_notice`) is preserved as verified SOURCE
provenance -- exactly why it must be persisted in full -- but is never
a substitute for FTA's own observation time. A verified Toronto-local
reinterpretation of BoC's `dc:date`, if produced, is SOURCE provenance
to store alongside, never instead of, the raw as-received (malformed)
`dc:date` string. FX-56 must now model at least five separate,
never-conflated concepts per item: authoritative FTA `first_seen_at`;
source published timestamp; source updated timestamp where available;
source revision/correction metadata where available; and raw provider
timestamp/provenance. The same invariant governs historical backfill:
a source's own publication timestamp establishes documented
publication timing only, never that FTA itself possessed the item at
that historical moment -- a backfilled row must record its own actual
backfill/ingestion time, or be explicitly flagged as backfill-derived,
never silently stamped with the source's historical publish time as
if equivalent to real-time prospective knowledge.

**Source-admission corrections.** Three statuses had collapsed an
unresolved critical rights property into an ADOPT verdict, which this
ADR's own discipline forbids regardless of otherwise-clean technical
fit: **BEA** (`rss.xml`, ADOPT_PROSPECTIVE -> **DEFER** -- reuse/
storage rights are UNKNOWN from any BEA primary source); **ECB's bulk
speeches CSV** (ADOPT_HISTORICAL -> a new **DEFER_HISTORICAL** label --
whether the ECB's own Working/Occasional-Paper written-authorisation
carve-out reaches named, author-attributed speeches remains genuinely
ambiguous); **GOV.UK's own Search API** (implicit ADOPT_HISTORICAL ->
**DEFER** -- its own terms and rate limits were never separately
verified from the Content API's, despite functioning). **GDELT** is
given one canonical disposition, a new **ADOPT_AUXILIARY_METADATA**
label, replacing the original "ADOPT_PROSPECTIVE and ADOPT_HISTORICAL"
framing that wrongly implied parity with a text-bearing source; GDELT
is explicitly excluded from FX-56's initial text-bearing source set
and is not counted toward the "official sources only" claim. Vendor
clarification questions for the three newly-DEFER'd official sources
were added to ADR 0005's own appendix, **prepared and NOT sent**, per
the same prohibition FX-55 itself operated under.

**Verification documentation corrected, not overwritten.** FX-55's own
initial baseline (`pytest --no-cov -q` -> 1601 passed, 1 failed, 4
deselected) is kept on record alongside a same-session retry performed
for this hardening pass (1602 passed, 0 failed, 4 deselected -- the
live-OANDA failure did not reproduce, consistent with a transient
live-network condition rather than a codebase regression); neither
result supersedes the other. `ruff check`/`ruff format --check`/
`mypy .`/`pre-commit run --all-files` all clean.

**Unchanged by this correction**: the overall PARTIAL_GO verdict; Fed,
ECB press feed, Bank of England, GOV.UK Content API, Statistics
Canada, and Bank of Canada press-releases (with mandatory timestamp
handling) as the adopted prospective set; FX-49 DEFER; FX-52 DEFER;
FX-53 BLOCKED; every class B/C/D DEFER/REJECT verdict this pass did
not specifically revisit. No production code, schema, migration, or
dependency change of any kind; no vendor was contacted; no FX-56
implementation was started. Full details in `docs/DECISIONS.md`'s
FX-55H entry and inline throughout ADR 0005 itself.

**Per this story's own explicit stop instruction**: FX-49 remains
DEFER; FX-52 remains DEFER; FX-53 remains BLOCKED; **FX-56 (Point-in-
Time News Evidence Model) may still begin**, scoped exactly to ADR
0005's own now-corrected adopted-source set and assumptions; no FX-56
implementation, news ingestion, deduplication, classification,
sentiment, dashboard, Decision/Risk-Engine work, or vendor outreach was
started.

## FX-56: Point-in-Time News Evidence Model (complete)

FX-EPIC-08's second story, explicitly authorized: the provider-
neutral, immutable, point-in-time STORAGE MODEL a future source
adapter (FX-57) will target -- it ingests nothing itself. Inspected
ADR 0005 + FX-55H (never the pre-hardening wording), the FX-51/FX-51H/
FX-52A/FX-52AH economic-event PIT model, and this project's own
SQLAlchemy/Alembic/UUID/repository conventions before coding.

**Domain**: `NewsItem` (internal identity; immutable `first_seen_at`/
`first_observation_mode`), `NewsItemVintage` (one append-only, FTA-
observed fact per revision -- `availability` is ALWAYS FTA's own
observation time, never a source timestamp, enforced by the type's
own `__post_init__`, not merely documented), `NewsSourceIdentity`
(`source_key`/`external_item_id` -- never a URL, never a timestamp, as
required), `NewsSourceTimestampProvenance` (raw provider timestamp
string + an optional, separately-stored verified reinterpretation --
the raw value is never overwritten by a remediation),
`NewsSourceRevisionFact`/`NewsSourceRevisionKind` (provider-neutral
structured correction/withdrawal history, e.g. GOV.UK's own `change_
history`), `NewsObservationMode` (`PROSPECTIVE`/`BACKFILL`, mirrors the
story's own backfill-safety requirement), `NewsEvidenceDisposition`
(`EVIDENCE_ELIGIBLE`/`QUARANTINED`, independent of) `NewsSourceStatus`
(`ACTIVE`/`WITHDRAWN`, requiring positive evidence -- never inferred
from feed absence), `mint_news_item_key` (mirrors `mint_occurrence_
key`), and a six-entry `news_source_registry` confirming exactly ADR
0005/FX-55H's own adopted text-bearing set (Fed, ECB, BoE, GOV.UK/HM
Treasury, StatCan, BoC) -- BEA/GDELT/every commercial provider has NO
entry, exactly like the economic-indicator registry's own "EUR has no
entry" convention.

**Application**: `NewsRepository` port (`register_source_item`/
`get_item`/`get_item_by_source_identity`/`add_vintage`/`list_vintages`/
`latest_vintage_as_of`/`latest_evidence_eligible_vintage_as_of`),
`NormalizedNewsObservation` DTO (mirrors `RawScheduleObservation`'s
own role -- performs no network I/O; a future FX-57 adapter produces
it), and `RecordNewsObservation` (mirrors `IngestOfficialCalendar
Schedule`'s own change-detection shape: compares the latest stored
vintage field-by-field against a new observation via a private
`_same_modeled_facts` helper, writing a new revision only when
something genuinely differs -- a repeated identical poll returns
`UNCHANGED`, never a duplicate vintage).

**The atomic-registration correction (this story's own single most
important design decision).** FX-52A/FX-52AH's own two-step "mint an
occurrence, commit it, THEN record its mapping" design has a known
race: two workers registering the SAME never-before-seen external
identity for the first time can each durably commit their OWN
candidate occurrence, with the loser's mapping insert then conflicting
against the winner's and raising an error -- leaving the loser's
occurrence a PERMANENT ORPHAN with no mapping ever pointing to it (see
`application.ports.economic_event_source_mapping_repository`'s own
module docstring, and `EconomicEventSourceMappingRow`'s own docstring,
which explicitly relies on "commit-per-call discipline" for its FK to
be satisfiable -- the very discipline that causes the race).
`SqlAlchemyNewsRepository.register_source_item` does NOT repeat this:
the candidate `NewsItemRow` and its `NewsSourceMappingRow` are inserted
(flushed, not committed) in ONE transaction; they are committed
TOGETHER only if the mapping insert's own `ON CONFLICT DO NOTHING`
actually wins. A losing attempt rolls the WHOLE transaction back --
discarding its own candidate item insert along with it -- then
resolves to the winner's already-registered identity. This is safe
under Postgres's own `READ COMMITTED` isolation with no extra
synchronization: a second session's conflicting mapping insert blocks
on the first session's row lock until that transaction commits or
rolls back, then resolves correctly either way once unblocked.
**Verified against live Postgres with two genuinely concurrent
sessions** (`asyncio.gather`, real separate connections), run
repeatedly with no flakiness observed -- not merely argued from the
SQL shape. `news_source_mappings` also enforces the REVERSE
cardinality `EconomicEventSourceMappingRow` deliberately does not
(one internal item has exactly one external identity; FX-56 models
one source item, never a real-world story spanning sources --
cross-source correlation is explicitly FX-58's own future job).

**Infrastructure**: `NewsItemRow`/`NewsSourceMappingRow`/`NewsItem
VintageRow` (UUID PK + business-key unique constraints + FK
constraints, mirroring `EconomicEventOccurrenceRow`'s own shape
exactly), `SqlAlchemyNewsRepository` (same idempotent `INSERT ... ON
CONFLICT DO NOTHING ... RETURNING id` discipline as `SqlAlchemyEconomic
EventRepository` for every write that is not the atomic registration
itself -- no method anywhere issues an `UPDATE` against a vintage,
item, or mapping row), and migration `504030474987` (`news_items` ->
`news_source_mappings` -> `news_item_vintages`, in FK-dependency
order). **This project's first use of `JSONB`** (`authors`/`source_
timestamp_provenance`/`source_revision_metadata` -- no prior
convention existed to reuse); every read reconstructs validating
domain objects via dedicated serialization helpers, raising a new
`MalformedNewsVintageRowError` loudly on a malformed stored shape
(verified directly: a manually-corrupted `authors` column is caught on
the next read, not silently coerced).

**Migration downgrade guard ships from the start** -- learning
directly from FX-51H.1/FX-52AH.1's own after-the-fact corrections
rather than repeating that mistake a third time: `downgrade()` checks
all three tables' row counts BEFORE any destructive DDL and refuses
with a `RuntimeError` naming every non-empty one if any holds a row.
Verified three ways against the real dev database, not only via the
mocked-`op` unit test: a genuinely empty set of tables downgrades and
re-upgrades cleanly; an inserted test row forces the exact documented
refusal naming `news_items`; the row was then removed and `alembic
current` reconfirmed at head.

**PIT worked examples from the story itself, each pinned by its own
integration test**: the correction example (Section 48 -- a source
`source_updated_at` earlier than FTA's own observation never backdates
the new revision's visibility); the withdrawal example (Section 47 --
the withdrawal becomes visible only at FTA's own observation instant,
never the source's own claimed withdrawal time); the quarantine
example (Section 46 -- `latest_vintage_as_of` can return a quarantined
revision while `latest_evidence_eligible_vintage_as_of` returns `None`
for the exact same `as_of`); the backfill guardrail (Section 50/74 --
a `BACKFILL` vintage is invisible to a historical `as_of` query before
its own backfill time, and excluded from evidence-eligible queries
unless explicitly opted in, even though no backfill adapter exists
yet); and the "first poll after several source-side corrections"
example (Section 49 -- GOV.UK-style `change_history` with three prior
corrections, first retrieved by FTA after all three, produces exactly
ONE FTA-observed revision, never three fabricated ones).

Baseline re-established, not assumed: `pytest --no-cov -q` ->
**1702 passed, 4 deselected** (up from 1602 passed/4 deselected before
this story -- 100 new tests, no regressions). `ruff check`/`ruff
format --check`/`mypy .`/`pre-commit run --all-files` all clean.
`pyproject.toml` remains at its own existing `0.1.0`, matching FX-54's/
FX-54V's own precedent of inspecting current convention rather than
inventing one.

No production code performs any network I/O to any news source; no
source adapter, RSS/Atom/JSON parser, HTTP retry/rate-limiting, or
scheduler was built (FX-57's own job). No cross-source deduplication,
fuzzy/content matching, or clustering (FX-58's own job) -- two
different `(source_key, external_item_id)` pairs describing what looks
like the same real-world story always create two separate `NewsItem`s,
verified directly. No currency/pair/topic/relevance classification, no
sentiment, no source-reputation/credibility/trust score anywhere
(FX-59/FX-EPIC-09's own future territory) -- `NewsSourceDefinition`
carries zero such fields by construction. No `GetNewsEvidenceSnapshot`
or equivalent (FX-60's own job). No `/market-context` or dashboard
change of any kind (FX-61's own job). No Decision/Risk Engine
integration, no BUY/SELL/trade-recommendation/blackout logic anywhere.
Full details in `docs/DECISIONS.md`'s FX-56 entry.

**Per this story's own explicit stop instruction**: FX-49 remains
DEFER; FX-52 remains DEFER; FX-53 remains BLOCKED; no FX-57 source
ingestion, FX-58 deduplication, FX-59 classification, FX-60 snapshot,
FX-61 visualization, or FX-EPIC-09 source-reputation work was started;
no Decision/Risk Engine work was started; no live news provider was
called anywhere in this story.

## FX-56H: first-observation atomicity & PIT ordering hardening (complete)

A focused hardening pass on FX-56, performed before FX-57 is
authorized to begin. FX-56 was functionally complete but had a real
atomicity gap: `register_source_item` made IDENTITY registration
atomic (item+mapping together), but a first observation's revision-0
vintage was still written in a SEPARATE, later transaction via a plain
`add_vintage` call -- so a failure between those two steps (a crash, a
validation error, an injected fault) could leave a durably-committed
`NewsItem` with no revision 0 at all, and a naive retry would then
mint revision 0 at the retry's OWN `observed_at`, violating "revision
0's own `availability` must equal `NewsItem.first_seen_at`."

**The fix**: a new repository method, `register_source_item_with_
first_vintage`, extends the EXACT SAME atomicity discipline
`register_source_item` already established one step further -- item,
mapping, AND revision 0 are inserted (flushed, not committed) in ONE
transaction, and committed together only once all three are known to
succeed. `build_vintage(candidate_key)` constructs (and therefore
fully domain-validates) the first vintage BEFORE any database write is
attempted, so a malformed observation leaves zero rows of any kind. A
shared private helper, `_insert_item_and_mapping`, factors the
identity-race handling out of both `register_source_item` and the new
method so it cannot drift between them. `RecordNewsObservation` now
calls ONLY the new combined method for every observation (first or
not) -- it never calls bare `register_source_item` followed by a
separate `add_vintage` for a first observation.

**Validate before durable mutation**: `NormalizedNewsObservation`
itself now validates its own headline/quarantine-reason invariants in
`__post_init__`, mirroring `NewsItemVintage`'s own checks -- a
malformed observation never reaches `RecordNewsObservation`, let
alone any repository call, at all. This is defense in depth alongside
the transactional guarantee above, not a replacement for it (the
transactional guarantee also covers a genuine infrastructure-level
failure after validation already succeeded, which DTO validation
alone cannot catch).

**PIT ordering guard**: once an item already has a latest vintage, a
CHANGED observation whose `observed_at` is EARLIER than that latest
vintage's own `availability` is refused outright
(`NewsObservationOutOfOrderError`) rather than silently appended as a
backdated revision. This check only applies to a genuinely NEW fact --
an observation identical to the latest vintage is always `UNCHANGED`
regardless of its own timing, since no append happens in that case at
all (getting this ordering backward was an early design mistake,
caught and corrected during this story's own implementation: checking
timing BEFORE checking for an identical repeat would have falsely
rejected a benign "lost the first-observation race" retry whose own
`observed_at` happens to be marginally earlier than the race's
winner). Equal `availability` values between consecutive revisions
remain explicitly permitted, tie-broken by `revision_sequence` --
matching `NewsItemVintage`'s own PIT-query ordering (`availability
DESC, revision_sequence DESC`).

**Truthful idempotent outcomes**: `RecordNewsObservation` now inspects
`add_vintage`'s own write outcome instead of discarding it -- if a
concurrent identical writer already inserted the exact revision this
call was about to write (`NewsVintageWriteOutcome.ALREADY_PRESENT`),
the result is `UNCHANGED`, never `REVISION_ADDED` (which this caller
did not actually cause). A genuine same-identity, different-payload
conflict still raises `NewsVintageConflictError` and fails closed,
unchanged from FX-56's own original behaviour.

**Database constraint hardening**: new migration `b2bbebf8ee3b`
(revises `504030474987`, purely additive, unguarded downgrade -- every
row this codebase has ever written already satisfies all four new
constraints) adds `CHECK` constraints mirroring the remaining domain
`__post_init__` enum/range checks in storage: `news_items.first_
observation_mode` and `news_item_vintages.observation_mode` against
`NewsObservationMode`; `news_item_vintages.source_status` against
`NewsSourceStatus`; `news_item_vintages.evidence_disposition` against
`NewsEvidenceDisposition`; `news_item_vintages.revision_sequence >=
0`. Deliberately does NOT attempt a cross-table `CHECK` for "revision
0's own `availability` equals `NewsItem.first_seen_at`" (Postgres
cannot reference another table in a `CHECK`) -- that invariant stays
a transactional guarantee, proven by integration test instead, exactly
as this story's own instructions required. Verified via up/down/up
against the real dev database (both the new migration alone, and a
two-step down/up through `504030474987` as well) and via a mocked-`op`
unit test proving the original table-drop guard still runs correctly.

**Tests**: ~20 new tests -- DTO validation (blank headline, invalid
quarantine state), a strengthened version of the existing
registration-race test proving no orphan `NewsItem` survives under
ANY key (not merely that the winning key's own row count is 1), and a
new integration suite covering: a malformed first observation leaves
zero durable rows; an INJECTED first-vintage persistence failure
(monkeypatching a dedicated, separately-named `_insert_vintage_row`
helper so a test can simulate an unexpected infra fault without
faking a lower-level database error) also leaves zero durable rows; a
successful first observation creates item+mapping+revision-0
atomically; revision 0's own `availability`/`observation_mode` equal
the item's own `first_seen_at`/`first_observation_mode`; two
genuinely concurrent sessions submitting the FULL first-observation
path (not merely bare `register_source_item`) for an identical,
never-before-seen observation leave exactly one item/mapping/
revision-0, both resolving to the same key; two concurrent identical
CHANGED observations of an already-existing item never both report
`REVISION_ADDED`; a changed, out-of-order observation raises and adds
nothing; equal-timestamp revisions remain deterministically ordered
by `revision_sequence`; and raw-SQL attempts to insert a negative
`revision_sequence` or an invalid enum value are rejected by the new
`CHECK` constraints. **A real test-authoring bug was caught and fixed
during this story's own "run concurrency tests repeatedly"
verification step** (explicitly required by this story's own
instructions, not merely run once): two new concurrency tests
correctly used two independent, real sessions of their own (the
scenario needs genuinely separate connections, not one shared fixture
session) but never ran the file's own cleanup fixture as a result, so
their own rows silently survived past the test into every later run
-- a second run of the SAME test then raised `NewsObservationOutOf
OrderError` against the FIRST run's own un-cleaned-up revision
history. A first attempted fix introduced a SECOND bug (deleting
`news_items` before `news_source_mappings`, violating that table's
own foreign key, since both reference `news_items`); the final,
correct fix is an explicit `try`/`finally` cleanup helper deleting in
proper FK-dependency order, verified clean across 10 consecutive runs
with no flakiness and confirmed via direct inspection that the dev
database returns to zero rows after each run.

Baseline re-established, with the actual command and actual combined
output recorded rather than split across two misleadingly separate
claims (an inconsistency FX-56H.1 corrects, see that story's own
entry below): `pytest --no-cov -q` -> **7 failed, 1716 passed, 4
deselected**, in that one single combined summary line. The 7
failures are `test_close_channel_breakout_live`/`test_control_
strategies_live`/`test_ema_crossover_live`/`test_ema_crossover_trend_
regime_gated_live`/`test_mean_reversion_live`/`test_time_series_
momentum_live`/`test_volatility_expansion_live` -- the project's own
pre-existing, unrelated weekend-market-closed condition (confirmed by
direct inspection of each failure's own assertion: zero live candles
returned; today was a Saturday), not something this story introduced,
touches, or needs to fix. A deterministic subset run excluding those
7 files (`pytest --no-cov -q --ignore=<those 7 files>`) reports a
clean **1716 passed, 4 deselected** (up from 1702 passed before this
story -- ~20 new tests less 6 reclassified/consolidated along the
way, no regressions). `ruff check`/`ruff format --check`/`mypy .`/
`pre-commit run --all-files` all clean.

**Unchanged by this correction**: the six-source admitted registry;
every ADR 0005 source verdict; the FTA-availability-equals-FTA-
observation invariant itself (only its ENFORCEMENT boundary moved
earlier, into the same transaction as identity registration); the
cross-source dedup boundary (still none, still FX-58's own job);
quarantine semantics; `BACKFILL` semantics; the source revision/
provenance model; the `JSONB` representation (no column or shape
changed, only new `CHECK` constraints on existing columns); the
dashboard (still untouched); FX relevance/topic classification,
sentiment, and source reputation (still none anywhere); Decision/Risk
Engine integration (still none). FX-49 remains DEFER; FX-52 remains
DEFER; FX-53 remains BLOCKED. Full details in `docs/DECISIONS.md`'s
FX-56H entry.

**Per this story's own explicit stop instruction**: FX-49 remains
DEFER; FX-52 remains DEFER; FX-53 remains BLOCKED; no FX-57 source
ingestion, FX-58 deduplication, FX-59 classification, FX-60 snapshot,
FX-61 visualization, or FX-EPIC-09 source-reputation work was started;
no Decision/Risk Engine work was started; no live news provider was
called anywhere in this story.

## FX-56H.1: final PIT ordering & item-creation contract patch (complete)

A narrowly-scoped correction on top of FX-56H, performed before FX-57
is authorized to begin.

**Corrected PIT-ordering precedence.** `RecordNewsObservation`
checked modeled-fact equality BEFORE checking observation ordering --
wrong for PIT semantics: an incoming observation whose `observed_at`
is earlier than the latest known vintage's own `availability` must
fail closed EVEN IF its modeled facts are identical to that latest
vintage, because an earlier `observed_at` is itself an assertion that
FTA possessed those facts earlier than the stored PIT history
currently says; silently returning `UNCHANGED` would knowingly
preserve an availability history already known to be wrong. The
corrected processing order is: (1) obtain the latest vintage; (2) if
`observed_at < latest.availability`, raise `NewsObservationOutOf
OrderError` unconditionally; (3) only once ordering is confirmed
non-violating, compare modeled facts and return `UNCHANGED` if
identical; (4) otherwise append a new revision. Equal `availability`
timestamps remain explicitly permitted (the check is `<`, never
`<=`), tie-broken by `revision_sequence`. Neither existing row is ever
backdated or rewritten -- a violating observation is rejected outright.

**Pinned the concurrent first-seen case.** Added a regression test
representing: worker A at `observed_at = T1`, worker B at `observed_at
= T2`, `T1 < T2`, where the T2 worker wins the identity race. When the
T1 observation subsequently resolves against the already-created
item, it must fail closed as out-of-order, not silently return
`UNCHANGED`. True concurrency cannot force a specific winner
deterministically, so this test reproduces the exact state a "T2
wins" race leaves behind (registering T2 first, then submitting T1
afterward) and proves what happens to the losing observation --
exactly the property actually under test. The stored `first_seen_at`/
revision-0 `availability` remain immutable; no retroactive correction
is attempted, confirmed directly.

**Removed the partial-item creation contract from the public port.**
`NewsRepository` previously permitted a bare, content-less
`register_source_item` to create `NewsItem`+`NewsSourceMapping`
without revision 0 -- contradicting `RecordNewsObservation`'s own
post-FX-56H invariant that an existing item always has a revision-0
vintage. For production/application semantics, a NEW `NewsItem` can
now only be created as part of the atomic first-observation
transaction (item + mapping + revision 0), via `register_source_
item_with_first_vintage` -- this story's `NewsRepository`'s own SOLE
public creating operation. `get_item_by_source_identity` remains the
read-only resolution path. `SqlAlchemyNewsRepository` keeps a renamed
PRIVATE, test-only equivalent, `_register_source_item_for_test_setup`
(sharing the same identity-race handling, `_insert_item_and_mapping`,
so it cannot drift from the real public operation), for repository-
level tests that need bare identity resolution in isolation -- never
called by `RecordNewsObservation` or any other production code path.
No revision 0 is ever synthesized later from an earlier `first_seen_
at` -- the contract eliminates that possibility structurally rather
than guarding against it after the fact.

**Strengthened the zero-row failure test to really detect orphan
items.** The existing `_counts_for_identity` helper derives its own
`item_count` via a JOIN through `news_source_mappings`, which by
construction can only ever find an item that already HAS a mapping --
it cannot detect a hypothetical orphan `NewsItem` with no mapping at
all. The injected-failure/atomicity test now uses a dedicated
`source_key` prefix and a new, separate helper (`_raw_item_count_by_
prefix`) that counts `news_items` rows directly, independent of the
mapping table, proving after a failed first observation: raw item
count = 0, mapping count = 0, vintage count = 0.

**Kept unchanged, per this story's own explicit instruction**: the
atomic item+mapping+revision-0 transaction itself; the revision-0
invariant; the six-source admitted registry; the source provenance
model; quarantine semantics; `BACKFILL` semantics; the `JSONB`
shapes; the cross-source dedup boundary; the relevance/topic
classification boundary; the dashboard; every ADR 0005 verdict;
Decision/Risk integration. FX-49 remains DEFER; FX-52 remains DEFER;
FX-53 remains BLOCKED.

**Documentation correction.** Two prior inaccuracies, corrected here
rather than left standing: (1) FX-56H's own migration `b2bbebf8ee3b`
adds FIVE new `CHECK` constraints, not "four" as earlier entries
stated -- `news_items.first_observation_mode` plus four on `news_
item_vintages` (`revision_sequence >= 0`, `observation_mode`,
`source_status`, `evidence_disposition`); no migration change was
needed for this wording-only correction. (2) FX-56H's own
verification reporting stated "1716 passed, 4 deselected" as if that
were a run's complete result, while separately also mentioning "the
same 7 failures" -- self-contradictory, since the actual single
command produces both in ONE combined summary line. Rerun and
recorded here precisely: `pytest --no-cov -q` -> **7 failed, 1716
passed, 4 deselected**, confirmed as one command's one result, not
assumed or carried forward from a prior story's own report. A
deterministic subset run excluding the 7 weekend-sensitive live-OANDA
test files (`pytest --no-cov -q --ignore=tests/integration/test_
close_channel_breakout_live.py --ignore=tests/integration/test_
control_strategies_live.py --ignore=tests/integration/test_ema_
crossover_live.py --ignore=tests/integration/test_ema_crossover_
trend_regime_gated_live.py --ignore=tests/integration/test_mean_
reversion_live.py --ignore=tests/integration/test_time_series_
momentum_live.py --ignore=tests/integration/test_volatility_
expansion_live.py`) reports a clean `1716 passed, 4 deselected`.

**Tests**: ~10 new/strengthened. A new, DB-free unit suite
(`tests/unit/application/test_record_news_observation.py`) against
an in-memory `FakeNewsRepository` -- deliberately implementing EXACTLY
the `NewsRepository` Protocol's own methods, with no bare `register_
source_item`, so the fake itself is a structural proof that no
production code path depends on one -- pinning the corrected ordering
precedence quickly and in isolation (identical-but-earlier fails
closed; changed-but-earlier fails closed; identical-equal-timestamp
is `UNCHANGED`; identical-later is `UNCHANGED`; changed-later adds a
revision). Three new live-Postgres integration tests: identical-but-
earlier fails closed; identical-equal-timestamp is `UNCHANGED`; and
the later-wins-race-then-earlier-fails-closed scenario, which also
confirms `first_seen_at`/revision-0 `availability` remain untouched
after the rejected attempt. The injected-failure test strengthened as
described above. All renamed `test_news_repository.py` call sites
(`register_source_item` -> `_register_source_item_for_test_setup`)
updated and re-verified; the two most directly misleading test names
renamed (`test_register_source_item_creates_new_item_and_mapping` ->
`test_bare_identity_registration_creates_new_item_and_mapping`, and
similarly for the idempotency test) so a reader cannot mistake them
for testing a still-public operation.

Verification: `pytest --no-cov -q` on the deterministic subset ->
**1726 passed, 4 deselected** (up from 1716 before this story on the
same deterministic basis -- 10 new/strengthened tests net, no
regressions); the full command including the 7 pre-existing weekend-
sensitive live-OANDA tests -> **7 failed, 1726 passed, 4 deselected**.
Concurrency-sensitive tests re-run repeatedly (8+ consecutive times)
with no flakiness observed, and the dev database confirmed to return
to zero rows for this story's own test identities after each run.
`ruff check`/`ruff format --check`/`mypy .`/`pre-commit run
--all-files` all clean. Full details in `docs/DECISIONS.md`'s
FX-56H.1 entry.

**Per this story's own explicit stop instruction**: FX-49 remains
DEFER; FX-52 remains DEFER; FX-53 remains BLOCKED; no FX-57/FX-58/
FX-59/FX-60/FX-61/FX-EPIC-09 work was started; no Decision/Risk
Engine work was started; no live news provider was called anywhere
in this story.

No further work has been requested; check in before starting anything
new here or elsewhere — including FX-53 (gated, still not started),
FX-50 (gated on FX-49's own reopening conditions, not started), the
proposed overnight-benchmark-rate-differential ingestion from FX-48
(scoped in ADR 0001 but not started), the future declassification-
mechanism need noted above (not yet needed, not yet built), the 18
still-provisional pre-2006 EUR change points, the 8 USD/6 GBP/3 CAD
known-irregular dates left unresolved, JPY provider mapping, the
pre-2009 CAD gap, the documented BoE-news-RSS follow-up increment or
any other FX-52A coverage extension, or any carry-strategy/
tradability work (explicitly out of scope for FX-46/FX-46H/FX-47/
FX-47H/FX-48/FX-49's own research, per FX-46's own section 14).

Do not start news source INGESTION (an HTTP client/parser/scheduler --
FX-57), cross-source deduplication (FX-58), relevance/topic
classification or sentiment (FX-59), a news evidence snapshot (FX-60),
dashboard visualization (FX-61), or source-reputation scoring
(FX-EPIC-09), general AI decision-making, rate-differential/carry
TRADING strategies, execution logic, live trading, commercial
economic-calendar or commercial news-provider integration, consensus/
surprise ingestion, or event-risk trading rules — out of scope until
explicitly assigned per CLAUDE.md. FX-41/FX-41H/FX-42/FX-42H/FX-42H.1/
FX-43/FX-43H/FX-43H.1/FX-44/FX-44H/FX-44H.1/FX-45/FX-45H/FX-45H.1/
FX-46/FX-46H/FX-47/FX-47H/FX-48/FX-49/FX-51/FX-51H/FX-51H.1/FX-52/
FX-52A/FX-52AH/FX-52AH.1/FX-54/FX-54V/FX-55/FX-55H/FX-56/FX-56H/
FX-56H.1 above are the explicitly-scoped exceptions (domain model, storage-integrity
hardening, canonical registry/provider-mapping definitions, real
policy-rate ingestion, hardening and correction rounds, genuine
release-timing verification, a deterministic, auditable, scoring-free
policy-rate differential feature plus two rounds of its own
point-in-time hardening, one pre-registered, honestly-reported RESEARCH
experiment against it, a correction to that experiment's own bootstrap
validity and artifact reproducibility, a pure attribution
cross-reference against existing technical strategies, a correction to
that cross-reference's own inferential methodology and provenance, a
data-sourcing feasibility investigation for tradable carry, a
data-sourcing feasibility investigation for rate expectations, a
provider-neutral point-in-time economic-event domain/persistence
model, a hardening pass on that model's identity/release/timezone
semantics, a final integrity patch closing two remaining validation/
migration-safety gaps, a data-sourcing feasibility investigation for
economic-calendar ingestion, official-source-only schedule/
release-timing ingestion built on top of that model, a hardening
pass correcting that ingestion's own occurrence-identity and
source-safety semantics, a final integrity patch closing a
timezone bug plus three remaining schema/persistence gaps, and a
deterministic, provider-neutral, TIMING-ONLY event-risk evidence
snapshot consuming that timing evidence per FX pair, a read-only
visualization of that evidence plus already-committed fundamental
research, introducing no new charting/UI framework, and a
documentation-only news-source feasibility/rights investigation
reaching PARTIAL_GO on an official-source-only set, a documentation-
only correction pass on that investigation's own PIT-anchor wording and
three source-admission statuses (BEA, ECB's bulk speeches CSV, GOV.UK's
Search API) plus a single canonical disposition for GDELT, and a
provider-neutral, immutable, point-in-time NEWS EVIDENCE STORAGE MODEL
(no source adapter, no network I/O, no ingestion job), a hardening
pass on that storage model's own first-observation atomicity/PIT
ordering (first-vintage-write transactional guarantee, an out-of-order
guard, truthful idempotent outcomes, five additive DB `CHECK`
constraints), and a final narrowly-scoped patch correcting that
hardening pass's own ordering precedence and narrowing the storage
model's public item-creation contract to one atomic operation -- still
no strategy, no decision logic, no "carry"/"expected rate" framing, no
tradability claim, no commercial calendar/news provider, no consensus,
no surprise, no event-risk scoring, no cross-source deduplication, no
relevance/topic/sentiment classification, no source-reputation score)
and do not open the door to the rest of this phase. **FX-57 (News
Source Ingestion & Raw Provenance) is the next gated story**: ADR 0005
(FX-55, hardened FX-55H) authorizes FX-EPIC-08 to continue, but each
remaining story is its own gate, strictly scoped to what ADR 0005 and
FX-56/FX-56H/FX-56H.1 themselves name -- none of FX-56's, FX-56H's,
nor FX-56H.1's own completion is a general license to build an
adapter, deduplication, classification, a snapshot, or a dashboard
beyond what FX-56's own "Explicitly NOT built in FX-56" list permits.
The same "do not open the door" rule applies to the downstream epics
not in this list at all (Decision Engine, Risk Engine, Paper Trading
Execution, Performance Analytics, Shadow Trading) — none are part of
the current phase.

Each of these should be tracked as its own Jira story and worked per
CLAUDE.md's "Development rules" (tests first where practical, smallest
change satisfying acceptance criteria, one story per commit).

## FX-57A: News Ingestion Foundation + Federal Reserve RSS (complete)

FX-57's own first incremental sub-story, explicitly authorized.
FX-57 (News Source Ingestion & Raw Provenance) is deliberately split
into FX-57A (this story) through FX-57F, one adopted source at a
time, rather than one large story for all six -- this story builds
ONLY the reusable abstraction the Fed implementation actually needs,
no speculative abstraction for ECB/BoE/GOV.UK/StatCan/BoC ahead of
need.

Inspected first, per this story's own mandate: CLAUDE.md, ADR 0005
(the FX-55H-corrected final version), all of FX-56/FX-56H/FX-56H.1's
own domain/application/persistence surface, and the existing FX-52A/
FX-52AH economic-calendar source-ingestion precedent (`bls_schedule_
source.py`'s httpx client/retry-free/observed-at-once pattern,
`rss_parsing.py`'s structural ElementTree technique, `boe_client.py`'s
`_USER_AGENT`/timeout convention). Confirmed no retry library exists
in this project (`pyproject.toml` has only `httpx>=0.27`) and no
"Clock" abstraction exists -- both introduced here, minimally.

**Built (provider-neutral, reusable by FX-57B-F)**:
`infrastructure.news_sources.http_fetch.fetch_text` -- one GET with
bounded retry (transport error/429/5xx only, max 3 attempts by
default, `Retry-After` respected, never retries an ordinary 4xx or a
parse failure) and an injected `ClockFn` that captures FTA's own
`retrieved_at` EXACTLY ONCE per response, immediately after it is
received and before any parsing. `infrastructure.news_sources.
rss_item_parsing.parse_news_rss_items` -- a dedicated RSS 2.0 `<item>`
parser for NEWS evidence, NOT a reuse of `economic_calendar_sources.
rss_parsing`: that parser's rule ("guid AND title AND a successfully-
parsed pubDate, else the whole item is invalid") is wrong for news,
where `pubDate` is source provenance, never FTA availability -- an
item here is invalid ONLY for a missing/blank guid or title.
`application.use_cases.ingest_news_source_once.IngestNewsSourceOnce`
-- the provider-neutral one-shot orchestration: given a tuple of
zero-argument channel fetchers, fetch each in turn, deduplicate
within each response (`ConflictingDuplicateExternalIdError` fails
closed for a genuinely conflicting duplicate guid within one
response; an identical duplicate is silently deduplicated), persist
every valid observation via `RecordNewsObservation`, and return a
factual, count-only `NewsIngestionResult`. A single channel's own
fetch failure is recorded in `errors` and skipped; it never aborts
the other configured channels. An unexpected system failure (e.g.
`NewsObservationOutOfOrderError`, a repository error) is never
swallowed -- it propagates and aborts the call. No daemon, worker, or
scheduler of any kind.

**Federal Reserve adapter** (`infrastructure.news_sources.
fed_rss_source.FedRssSource`) implements exactly the three adopted
aggregate feeds (live-reconfirmed: `/feeds/press_monetary.xml`,
`/feeds/speeches.xml`, `/feeds/testimony.xml`, all RSS 2.0, HTTP 200,
`content-type: text/xml`) under the already-registered `source_key=
"FED"` -- never per-governor feeds, yearly HTML archive scraping, or
Fed article-page fetching. `external_item_id` is the RSS `<guid>`
(live-confirmed identical to `<link>`, no `isPermaLink` attribute on
any sampled item, zero duplicate guids within any single feed sampled).
Content mapping: `title`->`headline` (required; blank/missing fails
that item closed, no placeholder), `link`->`canonical_url`,
`description`->`summary` (a genuine short snippet, present on 100% of
45 live-sampled items; never AI-summarized or fetched from the linked
page), `body_text` always `None` (RSS metadata only, no article-page
fetch), `authors` always `()` (Fed RSS supplies no `<author>` element
anywhere, confirmed live), `language` always `"en"` (the feed's own
declared channel-level language, a static, documented fact -- not a
per-item heuristic), `source_content_type` set per-channel
(`monetary_policy_release`/`speech`/`testimony`).

**No schema change**: FX-56's existing `source_content_type` field
already lets FTA tell which Fed channel produced an item, since each
Fed feed maps 1:1 to one content type -- a genuinely separate
`source_channel` concept is deliberately deferred until a future
source (ECB's own single combined feed serves several content types
through ONE channel) actually demonstrates the two axes diverge. See
`docs/DECISIONS.md`'s FX-57A entry for this decision in full,
including its consequence for cross-channel duplicate-guid handling
(a genuine content-type difference across channels for the same guid
is treated as a deliberate provenance change -- a second vintage of
the SAME item, never a second item, per ADR-style Section 35/36
reasoning recorded there).

**pubDate handling**: parsed via `email.utils.parsedate_to_datetime`
(RFC-822/2822), preserved raw via `NewsSourceTimestampProvenance`
regardless of parse outcome, NEVER promoted to FTA's own `observed_at`
(which is always the exact retrieval instant). A malformed pubDate
leaves `source_published_at=None` with the raw value and a failure
note preserved -- never fabricated as `observed_at`/midnight/now.

**Live-evidence finding, newly discovered, not in ADR 0005**: the
Fed's own `testimony.xml` feed contains items whose `pubDate` is the
literal sentinel value `"Sat, 30 Dec 1899 ..."` -- syntactically valid
(parses without raising via `parsedate_to_datetime`) but semantically
impossible, almost certainly a CMS default for an empty date field.
A plausibility floor (`year < 1900`, provider-neutral, not Fed-only)
in `rss_item_parsing` catches this and treats it exactly like a parse
failure. Confirmed present in 3 of 15 live-sampled testimony items;
absent from the 15-item `press_monetary`/`speeches` samples. This is
a clarifying live-evidence fact, not a change to ADR 0005's own
ADOPT_PROSPECTIVE verdict for Fed. **Corrected by FX-57AH**: ADR 0005
WAS amended with a short, clarifying addendum recording this finding
in place (the ADR's own hour-granularity finding and this sentinel-
date finding are compatible, not contradictory, and the verdict did
not change) -- also recorded in `docs/DECISIONS.md`.

**Other PIT/lifecycle semantics, live-verified**: `source_updated_at`
always `None` (no verified Fed correction/update field exists);
`source_status` always `ACTIVE` (feed disappearance never implies
`WITHDRAWN` -- Fed feeds are rolling/shallow, only positive source
evidence could); `evidence_disposition` always `EVIDENCE_ELIGIBLE`
for a structurally valid item (no quarantine logic added for Fed --
no future-dating anomaly was observed live, unlike BoC's own known
problem); `observation_mode` always `PROSPECTIVE` (a rolling feed's
older-looking items on first poll are correctly prospective, not
`BACKFILL` -- no historical archive scraping was done).

**Manual one-shot runner**: `scripts/ingest_fed_news.py` (plain
script, `uv run python scripts/ingest_fed_news.py`, no scheduler, no
startup hook, no dedicated test suite of its own, same precedent as
`scripts/backfill_policy_rate_history.py`). Run live against the real
Fed feeds and Postgres during this story: first run created 45 items
across all three feeds with zero invalid items and zero errors; an
immediate second run reported `created=0, unchanged=45`, confirming
idempotency end-to-end against real production-shaped data, not just
fixtures.

**Tests**: 54 new (corrected by FX-57AH -- the original report's "93"
did not match the sum of its own listed categories, verified by
counting actual `def test_`/`async def test_` functions added in
commit `fb8cf25`: 15+8+17+8+5+1 = 54) (15 deterministic RSS-parser-
fixture unit tests covering normal/multi-item/missing-description/
malformed-pubDate/
sentinel-pubDate/missing-pubDate/missing-guid/missing-title/blank-
title/duplicate-guid/one-malformed-among-valid/valid-empty/malformed-
XML/HTML-masquerading-as-feed/unrecognized-root; 8 transport unit
tests covering clock-exactly-once, transport-error-retry, 429-retry,
5xx-retry, ordinary-4xx-no-retry, retries-exhausted, `Retry-After`
respected; 17 Fed-adapter unit tests covering every field mapping,
content-type-per-channel, valid/malformed/sentinel pubDate, missing-
guid/title skip, HTML-200/500 fail-closed, valid-empty-feed; 8
orchestration unit tests against an in-memory fake repository covering
create/unchanged/revision-added, one-channel-failure-does-not-abort-
others, item-invalid aggregation, identical-duplicate-guid dedup,
conflicting-duplicate-guid fail-closed-per-response, out-of-order
propagation-not-swallowed; 5 Postgres end-to-end integration tests
covering single-poll persistence, repeated-identical-poll idempotency,
same-guid-changed-content revision, one-malformed-response-writes-
zero-evidence, duplicate-guid-across-two-channels resolving to one
item with a deliberate second vintage; 1 separately-marked
`live_source` Fed test run via `pytest -m live_source`, asserting
shape only, never exact titles/counts/dates).

**Verification, reported separately per this story's own instruction**:
deterministic subset (`pytest`, default `-m "not live_source"`): `7
failed, 1780 passed, 5 deselected` -- the 7 failures are the
pre-existing, documented OANDA-practice-candle strategy-live gap
(unrelated to this story, confirmed unchanged). `live_source` subset
(`pytest -m live_source`): `1 failed, 4 passed` -- the 1 failure is
BLS's own pre-existing, documented 403 (unrelated to this story,
confirmed unchanged); this story's own new Fed `live_source` test is
among the 4 passes. `ruff check .`, `ruff format --check .`, `mypy .`,
and `pre-commit run --all-files` all pass clean across the whole repo.

No cross-source deduplication (FX-58), relevance/topic classification
or sentiment (FX-59), news evidence snapshot (FX-60), dashboard
visualization (FX-61), or source-reputation scoring (FX-EPIC-09) --
all explicitly out of scope and untouched. No Decision/Risk Engine
work. `/market-context` unchanged. FX-49/FX-52/FX-53's own own gated
status unchanged. Full details in `docs/DECISIONS.md`'s FX-57A entry.

**Per this story's own explicit stop instruction**: do not start
FX-57B (ECB)/FX-57C (BoE)/FX-57D (GOV.UK)/FX-57E (StatCan)/FX-57F
(BoC, with its own known timestamp-remediation need), FX-58/FX-59/
FX-60/FX-61/FX-EPIC-09, or any Decision/Risk Engine work. FX-49/FX-52
remain DEFER; FX-53 remains BLOCKED.

Do not start any of the FX-57B-F sources, cross-source deduplication
(FX-58), relevance/topic classification or sentiment (FX-59), a news
evidence snapshot (FX-60), dashboard visualization (FX-61), or
source-reputation scoring (FX-EPIC-09) -- out of scope until each is
explicitly assigned in turn, per CLAUDE.md. FX-57A above is the
explicitly-scoped exception (common ingestion foundation plus exactly
one adopted source, Federal Reserve RSS) and does not open the door
to the rest of FX-57 or any later FX-EPIC-08 story.

## FX-57AH: common news ingestion contract hardening (complete)

A narrowly-scoped hardening pass on FX-57A, found by review, before
FX-57B is authorized. Four reusable-foundation fixes to the common
ingestion pipeline every future FX-57B-F adapter will reuse -- the
Fed adapter's own field mappings, endpoints, source key, and lifecycle
semantics are explicitly unchanged, verified by re-running the full
Fed-specific test suite (all 17 adapter unit tests, all 5 Postgres
end-to-end tests, the `live_source` test) after every edit below.

1. **Enforced the retrieval-time invariant as code.**
   `NewsSourceFetchOutcome.__post_init__` now requires `observation.
   observed_at == retrieved_at` for every observation in one
   response, raising `NewsSourceFetchContractError` (never silently
   rewriting the mismatch) if violated -- checked at the common
   construction boundary every adapter passes through, not left to
   each future adapter to remember.
2. **Enforced source-key isolation.** `IngestNewsSourceOnce` now
   raises `SourceKeyMismatchError` -- an explicit exception, not a
   plain assertion -- if any observation's own `source_key` disagrees
   with the run's configured source key, before that observation ever
   reaches deduplication or `RecordNewsObservation`. Propagates
   uncaught (treated as an unexpected system failure, like
   `NewsObservationOutOfOrderError`), never swallowed into `errors`:
   a mis-wired fetcher can never make a `"FED"` run persist
   `"ECB"`/`"BOE"`/`"GOVUK_HMT"`/`"STATCAN"`/`"BOC"` evidence.
3. **`rss_item_parsing` is now RSS-only.** The original version also
   recognized an Atom `<feed>` root as "valid" while only ever
   extracting RSS `<item>` elements -- so a genuine Atom response was
   silently read as a valid, empty RSS feed (fail-open data loss, the
   opposite of this parser's own stated philosophy). Fixed: root must
   be exactly `rss`, AND must contain a `<channel>` child -- an Atom
   `<feed>` and an `<rss>` with no `<channel>` both now fail closed
   with `MalformedNewsFeedError`; a genuinely empty `<rss><channel/>
   </rss>` remains correctly valid-empty. Statistics Canada's own
   Atom parser (FX-57E) stays a separate, future module -- this one
   is never extended to understand Atom.
4. **Explicit, unambiguous item counters.** `NewsIngestionResult`'s
   single, ambiguous `items_seen` is now three fields:
   `items_fetched` (every raw item, including invalid/duplicate),
   `items_normalized` (valid, pre-dedup), `items_processed` (post-
   dedup, actually persisted) -- pinned against this story's own
   three worked examples (identical duplicate, conflicting duplicate,
   one-valid-plus-one-invalid). `scripts/ingest_fed_news.py`'s own
   printout updated to match; no backwards-compatibility alias kept,
   since this is an internal, not-yet-externally-consumed result type.

**Two documentation errors in the FX-57A report corrected, not left
standing**: ADR 0005 WAS amended with a short sentinel-pubDate
addendum during FX-57A itself (confirmed still present in `docs/
adr/0005-news-intelligence-source-feasibility.md`'s own Federal
Reserve entry) -- the FX-57A report's own claim that "no ADR 0005
text amendment was made" was simply wrong, now fixed here and in
`docs/DECISIONS.md`. FX-57A added 54 new tests, not 93 -- its own
listed test categories (15+8+17+8+5+1) never summed to 93; verified
independently by counting actual test functions in commit `fb8cf25`'s
own diff, which also gives exactly 54. No new number was guessed.

No schema or migration change. 13 new tests (4 retrieval-time
contract + 4 source-key isolation + 4 RSS-only-root + 1 counter
worked-example), on top of FX-57A's own corrected 54 -- 67 total for
FX-57/FX-57AH. Verification, reported separately: focused suite
(`pytest tests/unit/infrastructure/news_sources/ tests/unit/
application/test_ingest_news_source_once.py tests/unit/application/
test_news_source_fetch_outcome.py tests/integration/
test_fed_news_ingestion.py`): `66 passed`. Fed `live_source` test
alone: `1 passed`. Deterministic default suite (`pytest`): `7 failed,
1793 passed, 5 deselected` -- the same seven pre-existing, documented,
unrelated OANDA-practice-candle strategy-live failures, confirmed
unchanged. Full `live_source` suite (`pytest -m live_source`): `1
failed, 4 passed` -- the same pre-existing, documented BLS 403,
confirmed unchanged. `ruff check .`, `ruff format --check .`, `mypy .`
(417 source files), and `pre-commit run --all-files` all pass clean.
The 45 genuinely-ingested Fed rows were left untouched; no additional
fake/demo rows were added; re-running `scripts/ingest_fed_news.py`
live after all changes confirmed `created=0, unchanged=45` still
holds, and that neither new hardening check ever fires against
genuine Fed data (every real Fed observation already satisfies both).

Full details in `docs/DECISIONS.md`'s FX-57AH entry; `docs/
ARCHITECTURE.md`'s FX-57A section amended in place with a hardening
addendum; `docs/CURRENT_STATE.md` carries its own FX-57AH entry. No
new ADR.

**Per this story's own explicit stop instruction**: do not start
FX-57B (ECB)/FX-57C (BoE)/FX-57D (GOV.UK)/FX-57E (StatCan)/FX-57F
(BoC), FX-58/FX-59/FX-60/FX-61/FX-EPIC-09, or any Decision/Risk Engine
work. FX-49/FX-52 remain DEFER; FX-53 remains BLOCKED. Return FX-57AH
for review.

## FX-57B: ECB combined press/speech/interview RSS ingestion (complete)

FX-57's second incremental sub-story, explicitly authorized. Proves
the common ingestion foundation generalizes to a source whose channel
and content type are NOT the same concept.

Inspected first, per this story's own mandate: CLAUDE.md, ADR 0005,
all current FX-57A/FX-57AH code (`http_fetch.py`, `rss_item_
parsing.py`, `fed_rss_source.py`, `ingest_news_source_once.py`,
`record_news_observation.py`, the news persistence models/repository,
current migrations, the Fed deterministic/live/Postgres tests).

**Live re-verification of `/rss/press.html`** (direct Python/httpx,
no `curl` in this sandbox): HTTP 200, `content-type: application/
rss+xml`, RSS 2.0 with `<channel>`, exactly 15 items (matching ADR
0005's own "~15 items" finding). Per item: `title`/`link`/`guid`/
`pubDate` only -- no `<description>`, no `<author>`, no per-item
`<language>`. `guid` == `link` on every item, no `isPermaLink`
attribute, all 15 guids distinct. `pubDate` carries an explicit
`+0200` offset with genuine SUB-HOUR precision (`17:45`, `04:20`,
`18:30` observed) -- refining, not contradicting, ADR 0005's own
"scheduled-hour granularity" phrasing (addendum added to the ADR).

**Material live finding beyond ADR 0005's documented `pr`/`sp`/`in`
trio**: a fourth URL-slug code, `gc` ("Governing Council" decision
notices). Reasoned through explicitly rather than silently guessed:
a Governing Council decision notice bears no individual author's
name, so it cannot fall inside the ECB's own Working/Occasional-
Paper written-authorisation carve-out, and it is served through the
SAME single feed URL ADR 0005 already blanket-adopted -- admitted as
`press_release`. Recorded as an ADR 0005 addendum (clarifies, does
not change, the ADOPT_PROSPECTIVE verdict) and in `docs/
DECISIONS.md`. Any OTHER, still-unrecognized code continues to fail
closed as an invalid item -- the content-class mapping is a
WHITELIST, never a blocklist, so a Working Paper/Occasional Paper
would be refused automatically without a separate exclusion list.

**`source_channel` added as a genuinely separate, required field**
(migration `a95058f88727`) -- the model refinement FX-57A's own
decision memo anticipated: ECB's ONE feed serves THREE content types,
proving channel and content type are not the same concept in general
(they only coincided 1:1 for Fed). Added to `NewsItemVintage`/
`NormalizedNewsObservation` as a required, non-empty string (same
discipline as `headline`), participating in modeled-fact equality --
a genuine channel change for the same external identity is a new
vintage of the SAME item, never a new item (pinned by a new unit
test). The migration backfills every pre-existing (Fed-only) row
deterministically from its own `source_content_type`
(`monetary_policy_release -> press_monetary`, `speech -> speeches`,
`testimony -> testimony`) before making the column `NOT NULL`,
refusing to proceed if any row has an unexpected content type rather
than guessing; downgrade refuses while any row exists (mirrors
`504030474987`'s own blanket guard). Verified against live Postgres:
all 45 pre-existing Fed rows survived the migration unchanged (row
count, content types, and now also their own correct channel values),
and a clean up/down/up cycle was verified on a separate, empty
database. Fed's own adapter now sets `source_channel=feed.channel`
going forward -- a pure provenance refinement; the full Fed
regression suite (17 adapter unit + 5 Postgres end-to-end + 1
`live_source` test) passes unchanged.

**ECB adapter** (`infrastructure.news_sources.ecb_rss_source.
EcbRssSource`) implements exactly the one feed as an explicit
`EcbFeedDefinition` (channel=`"ecb_press"`, path=`/rss/press.html`) --
no dynamic feed discovery, no crawling. Reuses the common transport
and the common RSS parser completely unchanged (confirmed compatible
by live re-verification). `source_key="ECB"` (the existing registry
entry); `external_item_id` is the RSS guid. Content mapping:
`title->headline` (required; parser-level invalid if missing/blank);
`link->canonical_url` (ECB's own double-slash URL quirk, `https://
www.ecb.europa.eu//press/...`, preserved verbatim, never "fixed");
`summary=item.description` (always `None` live, since ECB supplies no
`<description>`); `body_text=None` (no article-page fetch);
`authors=()`; `language="en"` (static, channel-level);
`source_content_type` derived per-item from the URL-slug code;
`source_updated_at=None`; `source_status=ACTIVE`; `evidence_
disposition=EVIDENCE_ELIGIBLE`; `observation_mode=PROSPECTIVE`.

**No historical ECB ingestion of any kind** -- the bulk speeches CSV
remains exactly `DEFER_HISTORICAL`, untouched; no yearly archive
scraping. **No article-page fetch**. **Operational caveat,
documented, no scheduler added**: the feed's own shallow depth (15
items) means a future operational poller must run frequently enough
that a burst of more items than the feed retains between polls cannot
create a silent evidence gap -- this module cannot detect such a gap
itself and makes no completeness claim beyond "the response returned
N items."

**Manual one-shot runner**: `scripts/ingest_ecb_news.py` (plain
script, no scheduler, no startup hook, same precedent as `scripts/
ingest_fed_news.py`). Run live against the real ECB feed and Postgres
during this story: first run created 15 items (`items_fetched=15,
items_invalid=0`); an immediate second run reported `created=0,
unchanged=15`, confirming idempotency end-to-end against real
production-shaped data. These 15 real rows were intentionally left in
the dev database, same treatment as Fed's own 45 rows.

**25 new tests** (verified via `git diff` test-function count, not
estimated -- see `docs/DECISIONS.md`'s FX-57B entry): 16 deterministic ECB-adapter unit tests (guid/
headline/link mapping, all four content classes mapping to the
correct type while sharing one channel, unknown content class
rejected as invalid rather than guessed, `+0200` pubDate
normalization, malformed pubDate, missing guid/title, no description/
author, language/source_updated_at, disposition/status/mode, valid-
empty feed, HTML/500 fail-closed); 5 Postgres end-to-end integration
tests (single-poll persistence with full field verification, repeated
-poll idempotency, same-guid-changed-content revision, different-
guid-same-headline stays separate, the Section 41 channel-vs-content-
type matrix proving three synthetic items share one channel with
distinct content types and distinct GUID identities); 1 separately-
marked `live_source` ECB test (shape-only assertions, reports any
newly-observed content class rather than asserting a closed set);
plus 3 more in existing files: 1 in `test_record_news_observation.py`
pinning that a `source_channel` change alone adds a revision, never a
new item, and 2 required-field-validation tests mirroring `headline`'s
own pattern (`test_source_channel_is_required_non_empty` in `test_
news_item_vintage.py`, `test_blank_source_channel_is_rejected` in
`test_normalized_news_observation.py`). 16+5+1+1+2 = 25.

**Verification, reported separately**: deterministic default suite
(`pytest`): `7 failed, 1817 passed, 6 deselected` -- the same seven
pre-existing, documented, unrelated OANDA-practice-candle failures,
confirmed unchanged. `live_source` suite (`pytest -m live_source`):
`1 failed, 5 passed` -- the same pre-existing, documented BLS 403,
confirmed unchanged; both Fed's and ECB's own live tests are among the
5 passes. `ruff check .`, `ruff format --check .`, `mypy .` (423
source files), and `pre-commit run --all-files` all pass clean.
Migration verified three ways: against the real dev database holding
45 live Fed rows (upgrade succeeded, backfill correct, row count and
content preserved, downgrade correctly refused with a clear error);
against a separate, empty throwaway Postgres container (full migration
chain from scratch, then a clean downgrade/upgrade cycle, both
succeeding).

No cross-source deduplication (FX-58), relevance/topic classification
or sentiment (FX-59), news evidence snapshot (FX-60), dashboard
visualization (FX-61), or source-reputation scoring (FX-EPIC-09) --
all explicitly out of scope and untouched. No Decision/Risk Engine
work. `/market-context` unchanged. FX-49/FX-52/FX-53's own gated
status unchanged.

Full details in `docs/DECISIONS.md`'s FX-57B entry; `docs/
ARCHITECTURE.md` carries a new ECB section; `docs/CURRENT_STATE.md`
carries its own FX-57B entry; ADR 0005 amended with the sub-hour-
precision and `gc`-content-class addendum.

**Per this story's own explicit stop instruction**: do not start
FX-57C (Bank of England)/FX-57D (GOV.UK)/FX-57E (Statistics Canada)/
FX-57F (Bank of Canada), FX-58/FX-59/FX-60/FX-61/FX-EPIC-09, or any
Decision/Risk Engine work. FX-49/FX-52 remain DEFER; FX-53 remains
BLOCKED. Return FX-57B for review.

## FX-57BH: source-channel contract & ECB live-drift hardening (complete)

A narrowly-scoped hardening pass on FX-57B, before FX-57C is
authorized. The common fetch contract now guarantees THREE aligned
response-level facts for every observation a source adapter produces,
not two:

1. `observation.observed_at == outcome.retrieved_at` (FX-57AH).
2. `observation.source_key == <this ingestion run's own source key>`
   (FX-57AH).
3. `observation.source_channel == outcome.source_channel` (FX-57BH,
   new).

**1/2. `NewsSourceFetchOutcome.source_channel` is now REQUIRED** --
changed from `str | None` to `str`, validated non-empty/non-
whitespace in `__post_init__`, alongside a NEW check that every
observation's own `source_channel` matches the response's own. Both
raise `NewsSourceFetchContractError` and never silently rewrite the
offending value. A valid empty feed still requires and accepts a
real channel (`source_channel="ecb_press", observations=()` is
valid) -- there is no such thing as an anonymous response, now that
`source_channel` is itself a required field on every `Normalized
NewsObservation`/`NewsItemVintage` (FX-57B). `IngestNewsSourceOnce`'s
own `if outcome.source_channel is not None:` guard was removed as no
longer needed -- `outcome.source_channel` is unconditionally
collected into `NewsIngestionResult.source_channels`.

**3. Location**: both checks live in `NewsSourceFetchOutcome.__post_
init__`, alongside the existing retrieved-at invariant -- so every
future adapter (FX-57C-F) inherits the protection automatically,
without needing to remember it or implement it per-adapter.

**4. Ingestion result consistency**: `NewsIngestionResult.source_
channels` now necessarily describes exactly the channels that were
actually persisted, since a mismatched observation can never
construct a valid `NewsSourceFetchOutcome` in the first place. No
channel rewriting or normalization was introduced anywhere in
orchestration.

**5. Tests** (7 new, verified via `git diff`, not estimated): in
`tests/unit/application/test_news_source_fetch_outcome.py` --
matching channel succeeds; mismatched channel fails at outcome
construction; blank response `source_channel` fails; whitespace-only
response `source_channel` fails; a valid empty response still
requires and accepts a real channel; multiple observations must ALL
match the same response channel; the pre-existing retrieved-at tests
continue to pass unchanged. In `tests/unit/application/test_
ingest_news_source_once.py` -- a response/observation channel
mismatch never reaches `RecordNewsObservation` (the repository stays
empty; the error propagates uncaught out of `IngestNewsSourceOnce.
__call__`, exactly like `SourceKeyMismatchError`/`NewsObservationOut
OfOrderError`).

**6. ECB live test tightened**: `tests/integration/test_ecb_rss_
source_live.py` now asserts `items_invalid == 0`, with the actual
invalid reasons included in the failure message, rather than merely
printing them. A live ECB item going invalid can mean a newly
introduced content class, an identity-schema change, a missing
headline/guid, or another source-contract change -- any of which
needs human review, not a quietly-green live test. This does NOT
relax the production adapter's own fail-closed behavior in any way;
re-run live against the real feed to confirm it still passes
(`items_invalid=0` on the current real feed, 15 items, all three
known content types observed).

**7. The `gc -> press_release` decision was NOT reopened** -- it was
discovered live, explicitly reasoned, whitelisted, documented in ADR
0005, and rights-reviewed within the existing ECB adopted feed
boundary during FX-57B; this hardening patch leaves
`_CONTENT_CLASS_TO_TYPE` completely untouched. Any code beyond
`pr`/`sp`/`in`/`gc` continues to fail closed until separately
reviewed.

**8. No schema or migration change** -- migration `a95058f88727`,
its `NOT NULL` `source_channel` persistence, the existing 45 Fed
rows, and the existing 15 ECB rows are all exactly as FX-57B left
them; untouched by this story.

**9. Fed regression**: re-ran the full Fed suite since Fed also
constructs `NewsSourceFetchOutcome` -- Fed already supplied matching
channel values (`feed.channel`, set in FX-57B), so behavior is
unchanged; no Fed source semantics were modified to satisfy the new
contract. 22 Fed tests (17 unit + 5 integration) and 21 ECB tests (16
unit + 5 integration) all pass unchanged.

**10. Verification, reported separately**: focused suites (common
contract + orchestration + ECB unit + ECB Postgres + Fed unit + Fed
Postgres): all green. Deterministic default suite (`pytest`): `7
failed, 1824 passed, 6 deselected` -- the same seven pre-existing,
documented, unrelated OANDA-practice-candle failures, confirmed
unchanged. `live_source` suite (`pytest -m live_source`): `1 failed,
5 passed` -- the same pre-existing, documented BLS 403, confirmed
unchanged; both Fed's and ECB's own live tests (the latter now
stricter per Section 6) pass. `ruff check .`, `ruff format --check .`,
`mypy .` (423 source files), and `pre-commit run --all-files` all
pass clean.

**11. Documentation**: this entry; `docs/ARCHITECTURE.md`'s ECB
section amended in place with the hardening; `docs/CURRENT_STATE.md`
carries its own FX-57BH entry; `docs/DECISIONS.md` carries the full
FX-57BH entry. No ADR change -- nothing discovered here was a new
source-feasibility/rights/PIT fact; the `gc` decision and sub-hour-
precision finding from FX-57B remain exactly as recorded.

**Per this story's own explicit stop instruction**: do not start
FX-57C (Bank of England)/FX-57D (GOV.UK)/FX-57E (Statistics Canada)/
FX-57F (Bank of Canada), FX-58/FX-59/FX-60/FX-61/FX-EPIC-09, or any
Decision/Risk Engine work. FX-49/FX-52 remain DEFER; FX-53 remains
BLOCKED. Return FX-57BH for review.

## FX-57C: Bank of England news/speeches/publications RSS ingestion (complete)

FX-57's third incremental sub-story, explicitly authorized.

Inspected first, per this story's own mandate: CLAUDE.md, ADR 0005,
and the full current news infrastructure (`NormalizedNewsObservation`,
`NewsSourceFetchOutcome`/`NewsSourceFetchContractError`,
`NewsSourceChannelFetcher`, `IngestNewsSourceOnce`/
`SourceKeyMismatchError`, `RecordNewsObservation`, `NewsItem`/
`NewsItemVintage`, `source_channel` persistence, `SqlAlchemyNews
Repository`, `http_fetch.fetch_text`, `rss_item_parsing.
parse_news_rss_items`, `FedRssSource`, `EcbRssSource`, the Fed/ECB
manual runners, and the full deterministic/Postgres/live_source test
suites) -- confirming none of the FX-57AH/FX-57BH common contracts
needed any weakening before writing BoE code.

**Live re-verification of all three official endpoints** (direct
Python/httpx): `https://www.bankofengland.co.uk/rss/news`, `/rss/
speeches`, `/rss/publications` -- all HTTP 200, `content-type: text/
xml`, RSS 2.0 with `<channel>`, exactly 50 items each, matching ADR
0005's own finding precisely. Item tag set consistent across all
three: `description`/`guid`/`link`/`pubDate`/`title` -- zero missing
fields across all 150 sampled items, zero `<author>` elements
anywhere, channel-level `<language>en</language>` on all three.

**Cross-channel GUID overlap check (this story's own hard
architectural gate, Section 9) -- result: ZERO overlap.** Before
finalizing the adapter design, all 150 live GUIDs (50 per feed) were
compared pairwise across all three feeds. None repeated across
channels, and none repeated within a single feed either. This clears
the gate the story itself raised: if the same GUID could legitimately
belong to more than one BoE channel simultaneously, forcing it through
the standard single-`source_channel`-per-vintage model would have
misrepresented simultaneous multi-channel membership as a false
sequential revision history, and the story would have had to STOP for
architectural review instead of proceeding. Since no overlap exists,
the standard FX-56/FX-57 model applies unmodified. A synthetic
integration test (`test_same_guid_across_two_boe_channels_resolves_
to_one_item`) still pins what the model WOULD do if this ever
changed (the channel difference becomes a genuine provenance-change
vintage of the same item, never a fabricated second item) -- a
documented contingency, not a claim about BoE's current behavior.

**External identity -- the strongest among all RSS sources adopted so
far.** `external_item_id` is the RSS `<guid>`, live-confirmed to be a
genuinely OPAQUE CMS identifier (e.g. `{B641CC4F-0AD7-46E2-9965-
B44629C6E93E}`), with `isPermaLink="false"` on every sampled item,
and completely decoupled from the canonical `<link>` -- unlike Fed
and ECB, where `guid == link`. A slug rename of the linked article
cannot break this identity.

**Material live finding, exactly as ADR 0005 predicted, resolved with
ZERO new code: mixed pubDate timezone format.** The `/rss/speeches`
feed mixes RFC-822 numeric offsets (`+0100`, British Summer Time)
with the bare military-zone form (`Z`, i.e. literal UTC+0/GMT) WITHIN
THE SAME document (35 `+0100` items, 15 `Z` items in the live
sample); `/rss/news` and `/rss/publications` were `+0100`-only in
this sample. Both forms were independently verified, directly in
Python, to parse correctly through the EXISTING, completely
unmodified shared `email.utils.parsedate_to_datetime` (the same
function Fed/ECB already use) -- `"...16:00:00 Z"` parses to a real
UTC instant, `"...09:00:00 +0100"` parses to the correctly-shifted
UTC instant. Checked WHY the split exists: every `Z`-tagged item's
date falls in GMT-season months (Jan-Mar) and every `+0100`-tagged
item's date falls in BST-season months (Apr-Oct) in the live sample
-- confirming this is BoE's CMS simply rendering the zulu-letter form
during GMT season instead of a literal `+0000` offset, a cosmetic
formatting quirk, not a timestamp defect requiring any BoE-specific
normalization code. Both deterministic fixture tests
(`test_bst_plus_0100_pubdate_normalizes_to_utc`, `test_gmt_z_pubdate_
normalizes_to_utc`) pin both observed forms exactly.

**Future-dated/upcoming item check (Section 20) -- result: NONE
found.** For every one of the 150 live-sampled items across all three
feeds, `source_published_at` was computed and compared against the
live retrieval instant; all 150 were strictly in the past. Documented
as a negative finding -- no speculative future-date tolerance or
quarantine threshold was invented. The `live_source` test actively
re-checks this comparison on every run (not relying on this one-time
research finding alone), so a genuine future-dating anomaly appearing
later would fail the live test immediately rather than silently
ingesting as ordinary eligible evidence.

**Content mapping**: `title->headline` (required; parser-level
invalid if missing/blank, never a placeholder); `link->canonical_url`
(never identity, never followed, never fetched); `description->
summary` (confirmed live to be a genuine, substantive per-item
summary on every sampled item, not boilerplate -- preserved
faithfully, never AI-summarized); `body_text=None` always (no
article/PDF/slides/appendix/chart fetch anywhere in this adapter);
`authors=()` always (zero `<author>` elements observed on any sampled
item -- a speaker's name inside a speech title, e.g. "Sasha Mills:
speech at...", is never parsed into a structured author field);
`language="en"` always (the feed's own declared, static channel-
level value); `source_updated_at=None` always (no verified BoE
correction/update field exists); `source_status=ACTIVE` always (feed
disappearance is never withdrawal -- no explicit retraction field was
found, and none was assumed); `observation_mode=PROSPECTIVE` always
(no historical ingestion of any kind -- no yearly archive, no
sitemap, no search-based backfill).

**Rights boundary, live-reconfirmed, unchanged from ADR 0005**:
`https://www.bankofengland.co.uk/legal` was re-fetched directly
during this story and still states, word for word, that site
Resources may be used "for personal use or internal use within an
individual organisation for non-commercial purposes" -- exactly FTA's
current research/paper-trading use; redistribution and commercial use
still require separate permission. No rights reinterpretation or
expansion was made or is implied; this adapter ingests only the
feed-supplied metadata fields above, never the linked article or any
PDF/report/slides/chart.

**Manual one-shot runner**: `scripts/ingest_boe_news.py` (plain
script, no scheduler, no startup hook, same precedent as the Fed/ECB
runners). Run live against the real BoE feeds and Postgres during
this story: the first run created exactly 150 items across all three
channels (`items_fetched=150, items_invalid=0, errors=()`); an
immediate second run reported `created=0, revisions_added=0,
unchanged=150`, confirming idempotency end-to-end against real
production-shaped data. These 150 real rows were intentionally left
in the dev database, the same treatment given to Fed's 45 and ECB's
15 -- the database now holds 210 real news rows across three
distinct `source_key`s, confirmed via a direct SQL query grouping by
`source_key`/`source_channel` after this story's own work concluded.

**25 new tests** (verified by directly counting `def test_`/`async
def test_` lines in each new file, not estimated): 17 deterministic
BoE-adapter unit tests
(`tests/unit/infrastructure/news_sources/test_boe_rss_source.py` --
guid/headline/link/description mapping, opaque-guid-distinct-from-
link, content-type-and-channel per feed, both observed pubDate
timezone forms normalizing correctly, malformed pubDate, missing
guid, missing description, missing title, authors-empty/language-en/
source-updated-at-None, disposition/status/mode always eligible/
active/prospective, valid-empty feed, HTML-200 and HTTP-500 both fail
closed, feed paths/source key match the registry exactly); 7 Postgres
end-to-end integration tests
(`tests/integration/test_boe_news_ingestion.py` -- single-poll
persistence with full field verification including the opaque-guid-
independent-of-link check, repeated-poll idempotency, same-guid-
changed-content produces a second vintage, two different guids with
the same headline remain two separate items, one malformed response
writes zero evidence, the same-guid-across-two-channels fallback
pin, and an explicit PIT worked-example test pinning that a query
strictly between the source pubDate and FTA's own retrieval instant
sees nothing while a query at-or-after retrieval sees the evidence);
1 separately-marked `live_source` test
(`tests/integration/test_boe_rss_source_live.py`, run via `pytest -m
live_source`, covering all three channels in one test -- strict
`items_invalid == 0` per channel following ECB's own FX-57BH
precedent, plus an active future-dated-item re-check on every run).

**Verification, reported separately, as genuinely different commands
with genuinely different results**: Fed regression
(`tests/unit/infrastructure/news_sources/test_fed_rss_source.py` +
`tests/integration/test_fed_news_ingestion.py`): `22 passed`,
unchanged. ECB regression (`test_ecb_rss_source.py` + `test_ecb_
news_ingestion.py`): `21 passed`, unchanged. Deterministic default
suite (`pytest`): `7 failed, 1848 passed, 7 deselected` -- the same
seven pre-existing, documented, unrelated OANDA-practice-candle
failures, confirmed unchanged by name. `live_source` suite (`pytest
-m live_source`): `1 failed, 6 passed` -- the same pre-existing,
documented BLS 403, confirmed unchanged; Fed's, ECB's, and this
story's own new BoE live test are all among the 6 passes. `ruff check
.`, `ruff format --check .`, `mypy .` (428 source files), and
`pre-commit run --all-files` all pass clean across the whole
repository.

**Confirmed, explicitly, as this story's own required negative
checklist**: no historical BoE ingestion of any kind; no BoE article/
PDF scraping; no FX-57D (GOV.UK)/FX-57E (StatCan)/FX-57F (BoC) work
started; no cross-source deduplication (still FX-58's own future
job); no relevance/topic/currency classification or sentiment of any
kind (still FX-59's own future job); no source-reputation/
credibility scoring (still FX-EPIC-09's own future job); no news
evidence snapshot (still FX-60's own future job); `/market-context`
and every existing route/template unchanged (still FX-61's own future
job); no Decision/Risk Engine integration, trade signal, or BUY/SELL
logic anywhere; FX-49/FX-52 remain DEFER; FX-53 remains BLOCKED.

**No schema or migration change** -- migration `a95058f88727`, its
`NOT NULL` `source_channel` persistence, and the existing 45 Fed + 15
ECB rows are all exactly as FX-57BH left them; no `alembic` revision
was authored by this story.

Full details in `docs/DECISIONS.md`'s FX-57C entry; `docs/
ARCHITECTURE.md` carries a new BoE section; `docs/CURRENT_STATE.md`
carries its own FX-57C entry. **No ADR update** -- every live finding
either confirmed ADR 0005's own prior characterization exactly
(opaque GUID, mixed timezone format, non-commercial rights boundary,
~50-item depth) or resolved a question the ADR had left open without
contradicting it (zero cross-channel overlap, zero future-dated
items) -- none of these are a NEW source-feasibility/rights/PIT fact
requiring the ADR's own text to change.

**Per this story's own explicit stop instruction**: do not start
FX-57D (GOV.UK)/FX-57E (Statistics Canada)/FX-57F (Bank of Canada,
with its own known timestamp-remediation need), FX-58/FX-59/FX-60/
FX-61/FX-EPIC-09, or any Decision/Risk Engine work. FX-49/FX-52
remain DEFER; FX-53 remains BLOCKED. Return FX-57C for review.

## FX-57CH: cross-channel identity collision fail-closed hardening (complete)

A narrowly-scoped hardening pass on FX-57C, found by review, before
FX-57D is authorized.

**Principal defect**: FX-57C correctly identified simultaneous cross-
channel GUID overlap as a hard architectural gate, live-checked it
for BoE (found none), but its own implementation still PINNED an
unsafe fallback -- the SAME `(source_key, external_item_id)` observed
under two DIFFERENT `source_channel`s within ONE `IngestNewsSource
Once` call was modeled as `revision 0 channel=A, revision 1
channel=B`. If the source genuinely presented that item under both
channels SIMULTANEOUSLY, that history is FALSE: nothing in a single
run can establish which channel should be treated as "first," and
`test_same_guid_across_two_boe_channels_resolves_to_one_item` pinned
exactly this wrong contingency behavior.

**New common fail-closed rule, enforced in `IngestNewsSourceOnce`
itself, not any adapter**: within ONE `__call__` invocation, if the
same identity appears under more than one DISTINCT `source_channel`
among the run's own successfully-fetched, non-conflicting responses,
the WHOLE run fails closed with a new `CrossChannelIdentityCollision
Error` -- before ANY observation from ANY channel in that run is
persisted, not just the colliding ones. Never: pick the first or last
channel, mint a second `NewsItem`, append a fabricated channel-change
vintage, concatenate channel names, or silently drop one side.

**The rule is explicitly RUN-SCOPED (Section 3)**: this guard does
NOT prohibit a genuine sequential channel change across SEPARATE
polling runs. The same GUID observed only under channel A in run 1,
then only under channel B in run 2, remains an ordinary new vintage --
that is still consistent with a real sequential provenance change.
Only SIMULTANEOUS membership -- the same identity under two different
channels within the SAME run -- is ambiguous and rejected. Pinned
explicitly by test F in the new matrix below.

**Prefetch before persistence -- `IngestNewsSourceOnce` refactored to
two phases**: Phase 1 fetches every configured channel, enforces
source-key isolation, and dedupes within each response, collecting
everything WITHOUT persisting anything; Phase 1b then checks every
collected identity for a cross-channel collision across the WHOLE
run; only once that check passes does Phase 2 begin persisting. The
original single-pass design validated-then-persisted one response at
a time, which meant an EARLIER channel's evidence could already be
durably written in Postgres before a LATER channel's response
revealed a collision with it -- impossible now, since Phase 2 is
never reached until every channel in the run has been checked. No new
transaction framework was introduced.

**Existing, unrelated semantics explicitly preserved**: one channel's
own fetch failure (`NewsSourceUnavailableError`) still does not abort
other healthy channels in the same run -- it is recorded in `errors`
and that channel is simply absent from the collision check, same as
before. Within-one-response duplicate-guid handling
(`ConflictingDuplicateExternalIdError` -- idempotent for identical
facts, fail-closed for conflicting facts) is completely unchanged,
since the new guard operates on a different axis entirely (same
identity, different CHANNEL, never within one response).

**Required test matrix (Section 9), all six added to `tests/unit/
application/test_ingest_news_source_once.py`**: (A) a single identity
in one channel succeeds; (B) disjoint identities across two channels
both succeed; (C) the same identity in two channels within one run
fails closed BEFORE persistence, with the raised error naming the
identity and both channels; (D) one channel's fetch failure plus two
disjoint successful channels still ingest those two; (E) one
channel's fetch failure plus a collision between the two REMAINING
successful channels fails closed and persists NOTHING, confirmed by
checking the repository directly; (F) the same identity across two
SEPARATE `ingest(...)` calls remains an ordinary sequential vintage,
completely unaffected by the new guard.

**The SAME unsafe pattern was found and fixed in Fed's own test
suite too, not just BoE's** -- `test_duplicate_guid_across_two_
channels_resolves_to_one_item` in `tests/integration/test_fed_news_
ingestion.py` pinned the identical wrong fallback (a Fed GUID shared
across the `speeches` and `testimony` channels within one run,
expected to produce a second vintage). Renamed to `test_duplicate_
guid_across_two_channels_fails_closed` and corrected to expect
`CrossChannelIdentityCollisionError` with nothing persisted -- this
was not mentioned explicitly in the hardening brief, but the new
common rule applies to every adapter equally, and leaving Fed's own
test pinning the old, now-wrong behavior would have been a latent,
undetected regression the very next time anyone touched that test
file.

**BoE's own replacement test** (`tests/integration/test_boe_news_
ingestion.py`, renamed `test_same_guid_in_two_boe_channels_within_
one_run_fails_closed`) proves: the collision raises with the correct
identity and channel names; the repository holds NO `NewsItem`,
mapping, or vintage for the colliding identity; AND an UNRELATED,
perfectly good observation from a THIRD, non-colliding channel in the
SAME run was also not partially persisted -- directly exercising
Section 8's own explicit requirement.

**BoE `live_source` test strengthened (Section 7)**: after fetching
all three feeds, every pairwise intersection of their own GUID sets
is now computed and asserted empty, naming any offending GUID and
the channels it was found in -- the test now FAILS if BoE's own feed
shape ever stops being cross-channel-disjoint, rather than merely
printing the finding. Re-run live: zero overlap confirmed again today
across all three feeds.

**Documentation correction (Section 10)**: `boe_rss_source.py`'s own
module docstring previously claimed that a future cross-channel
overlap would be deliberately represented as a provenance-change
vintage -- removed. Corrected wording: current live validation found
zero overlap; simultaneous overlap within one ingestion run is now
explicitly rejected, because a single-valued `source_channel` per
vintage cannot represent simultaneous membership without inventing a
false temporal transition. A genuinely sequential channel change
across separate runs remains representable as a new vintage.

**Everything else about BoE is explicitly unchanged**: source key,
all three endpoints and channels, content types, opaque GUID
identity, canonical URL semantics, description mapping, `body_text=
None`, `authors=()`, `language="en"`, `+0100`/`Z` timestamp parsing,
raw pubDate provenance, `source_updated_at=None`, `ACTIVE` status,
`PROSPECTIVE` mode, the future-date live drift check, no historical
ingestion, no article/PDF fetching -- none of this was touched.

**No schema or migration change** -- the existing 45 Fed + 15 ECB +
150 BoE rows are untouched; verified by re-running `scripts/ingest_
fed_news.py` and `scripts/ingest_boe_news.py` live against the real
feeds and Postgres after all changes: both ran idempotently
(`created=0, unchanged=45` for Fed; `created=0, unchanged=150` for
BoE) with zero collisions, since real Fed and BoE identities remain
genuinely channel-disjoint today -- confirming the new guard does not
interfere with normal operation against real multi-channel data.

**8 new/replaced test functions** (verified via `git diff 3f37aac --
tests/`, not estimated): 6 brand-new common-orchestration tests (the
A-F matrix above) plus 2 corrected tests replacing their own unsafe
prior versions 1-for-1 (Fed's and BoE's own cross-channel tests) --
net +6 to the suite's total test count.

**Verification, reported separately**: focused suite (common
ingestion + Fed + ECB + BoE, unit and Postgres together): `97
passed`. Deterministic default suite (`pytest`): `7 failed, 1854
passed, 7 deselected` -- the same seven pre-existing, documented,
unrelated OANDA failures, confirmed unchanged. `live_source` suite
(`pytest -m live_source`): `1 failed, 6 passed` -- the same pre-
existing, documented BLS 403, confirmed unchanged; Fed's, ECB's, and
BoE's own live tests (the latter now running the strengthened
pairwise-overlap check) all pass. `ruff check .`, `ruff format
--check .`, `mypy .` (428 source files), and `pre-commit run
--all-files` all pass clean.

Full details in `docs/DECISIONS.md`'s FX-57CH entry; `docs/
ARCHITECTURE.md` carries a new section describing the hardened
contract; `docs/CURRENT_STATE.md` carries its own FX-57CH entry. **No
ADR 0005 update** -- the live `live_source` re-run reconfirmed the
existing zero-overlap finding; no new source fact was discovered.

**Per this story's own explicit stop instruction**: do not start
FX-57D (GOV.UK)/FX-57E (Statistics Canada)/FX-57F (Bank of Canada,
with its own known timestamp-remediation need), FX-58/FX-59/FX-60/
FX-61/FX-EPIC-09, or any Decision/Risk Engine work. FX-49/FX-52
remain DEFER; FX-53 remains BLOCKED. Return FX-57CH for review.

## FX-57D: GOV.UK Content API / HM Treasury prospective news ingestion (complete)

FX-57's fourth incremental sub-story, explicitly authorized.

Inspected first: CLAUDE.md, ADR 0005's HM Treasury section, and the
full current news infrastructure (including FX-57CH's two-phase
`IngestNewsSourceOnce`, `NewsSourceFetchOutcome`'s channel contract,
and the Fed/ECB/BoE adapters/manual runners/test suites), confirming
none of the existing common contracts needed weakening before writing
GOV.UK code.

**Live re-verification of the two-stage design.** The GOV.UK Content
API (`https://www.gov.uk/api/content/<path>`) is a lookup-by-path
endpoint -- fetching it directly confirms it has no item-enumeration
capability of its own. The official HM Treasury Atom discovery feed
was re-fetched live and found to expose 20 entries, each with `id`/
`title`/`link`/`updated` only -- no `published`, no identity beyond an
opaque Atom entry ID, no body/correction/retraction data at all,
exactly matching ADR 0005's own prior finding that the Atom feed alone
is insufficient as an evidence source. Hydrating a live sample of
those 20 paths through the Content API confirmed the full richer
schema this story's spec required: `content_id` (a stable UUID,
confirmed decoupled from the URL slug across several items),
`base_path`, `title`, `description`, `document_type` (several distinct
values observed, e.g. `news_story`/`speech`/`press_release`/
`official_statement` -- confirming `document_type` must be preserved
broadly, never whitelisted), `locale` (100% `"en"` across all 20),
`details.body` (present, Govspeak/HTML markup, preserved faithfully,
never re-fetched from the public page), `details.change_history`
(ordered newest-first; a genuine live multi-entry example was found --
`first-ever-entrepreneurship-advisor-appointed-to-the-treasury`,
carrying both a 2025 "First published." entry and a 2026 "Updated with
information of reappointment." entry, together on a single item's
FIRST poll -- an exact live confirmation of the "one FTA revision 0
carries all pre-existing history" scenario), `withdrawn_notice` (an
empty dict `{}`, never `null`, confirmed on every live-sampled active
item), `links.organisations` (structured HM Treasury base-path
membership, confirmed present and the correct way to verify source
membership rather than title matching), and a small number of items
carrying `publishing_scheduled_at` (none in the future relative to
retrieval). `first_published_at`/`public_updated_at`/`updated_at`
were confirmed to genuinely diverge on at least one live item
(`updated_at` newer than `public_updated_at`), confirming the
three-timestamp separation this story's spec required is not merely
theoretical for this source.

**Cross-path content_id collision check (this story's own hard
architectural gate, Section 14/55) -- result: ZERO collisions.** All
20 live-discovered paths were hydrated and their `content_id`s
compared pairwise; all 20 were unique. This clears the gate the story
itself raised, the same way FX-57C's own BoE cross-channel check did:
since no collision exists live, the standard model applies
unmodified. A narrow, explicitly-permitted extension to
`IngestNewsSourceOnce` (Phase 1c: a whole-run, cross-response,
same-channel dedupe/collision check, reusing the existing
`_dedupe_observations`/`ConflictingDuplicateExternalIdError`) still
pins what the model WOULD do if this ever happens, deterministically,
in both a benign-alias and a genuinely-conflicting shape -- proven a
no-op for Fed/ECB/BoE by re-running their full 94-test regression
suite unchanged after the extension.

**Rate limit reconfirmed live**: GOV.UK's own developer documentation
still states 10 requests/second/client for the Content API; `GovUkHmt
Source` paces itself to at most one request per 0.15s (discovery
included), via an injectable monotonic clock/async sleep so the
deterministic unit test proves the pacing math (two scripted elapsed-
time scenarios: one requiring a wait, one not) without ever actually
waiting wall-clock time. No 429 was ever encountered live.

**Rights reconfirmed live**: `gov.uk` content remains OGL v3.0-
licensed; this adapter ingests only the Content API's own supplied
metadata/body fields, never a linked attachment, PDF, or the rendered
public HTML page.

**No ADR 0005 amendment.** Every live finding above reconfirms,
rather than contradicts, ADR 0005's existing HM Treasury section: the
Atom-insufficiency finding, the Content API's richer schema, the 10
req/s limit, the beta/self-described-drift caveat, the OGL v3.0
rights, and the two-stage design were all already anticipated there;
nothing discovered during this story's own research requires that
text to change.

**Verification, reported separately**: focused suite (GOV.UK
discovery + Content-API/adapter unit tests + GOV.UK Postgres
integration tests + the full common-orchestration test file,
including its 2 new Phase 1c tests): `85 passed` (deterministic);
GOV.UK's own `live_source` test, run separately: `1 passed`.
Deterministic default suite
(`pytest`): `7 failed, 1919 passed, 8 deselected` -- the same seven
pre-existing, documented, unrelated OANDA failures, confirmed
unchanged; deselected rose by exactly 1 (the new GOV.UK `live_source`
test). `live_source` suite (`pytest -m live_source`): `1 failed, 7
passed` -- the same pre-existing, documented BLS 403 (FX-EPIC-07,
unrelated to news intelligence), confirmed unchanged; Fed's, ECB's,
BoE's, and now GOV.UK's own live tests all pass. `ruff check .`,
`ruff format --check .`, `mypy .` (435 source files), and `pre-commit
run --all-files` all pass clean. 66 new test functions total
(verified per-file via `grep -cE '^(async )?def test_'` on each new
file, since 4 of the 5 touched test files are new/untracked and so
invisible to a plain `git diff`; the 1 modified file's own `git diff`
confirms exactly 2 added): 13 (discovery parser) + 39 (Content API
parser/adapter, including rate-pacing) + 11 (Postgres integration) + 1
(`live_source`) + 2 (common-orchestration Phase 1c matrix, G/H).

`scripts/ingest_govuk_hmt_news.py` run live, twice, against the real
feed and dev Postgres: run 1 discovered 20 paths, hydrated 20, 0
invalid, created 20; run 2 discovered the same 20 paths, created 0,
20 unchanged -- fully idempotent. Database spot-check (`news_source_
mappings`/`news_item_vintages` grouped by `source_key`) confirmed the
pre-existing 45 Fed + 15 ECB + 150 BoE rows (210 total) remained
exactly untouched, alongside the 20 new, genuine `GOVUK_HMT` rows.

No schema or migration change -- FX-56's model was deliberately built
with GOV.UK-like evidence in mind (three-timestamp provenance,
structured revision metadata, source status/withdrawal, body text,
free-form source content type) and held exactly as designed under
real GOV.UK data.

Full details in `docs/DECISIONS.md`'s FX-57D entry; `docs/
ARCHITECTURE.md` carries a new "GOV.UK / HM Treasury news ingestion"
section; `docs/CURRENT_STATE.md` carries its own FX-57D entry.

**Per this story's own explicit stop instruction**: do not start
FX-57E (Statistics Canada)/FX-57F (Bank of Canada, with its own known
timestamp-remediation need), FX-58/FX-59/FX-60/FX-61/FX-EPIC-09, or
any Decision/Risk Engine work. FX-49/FX-52 remain DEFER; FX-53 remains
BLOCKED. Return FX-57D for review.

## FX-57DH: GOV.UK source-drift & identity-guard hardening (complete)

A narrowly-scoped hardening pass on FX-57D, found by review, before
FX-57E was authorized. Git HEAD at story start: `545f82c`.

**Five independent gaps, each in the same direction**: a malformed or
drifted source response was too easily absorbed by the existing FX-57D
code as if nothing unusual had happened, rather than surfacing loudly.
None of the five touches the two-stage discovery/hydration
architecture, Phase 1c, or any other FX-57D design decision itself --
every fix is a narrowing of what the parser/adapter accepts as valid,
never a redesign.

**1. Discovery invalid entries can no longer disappear silently.**
`parse_govuk_discovery_atom` (unchanged) already computed `invalid_
count`/`invalid_reasons` correctly, but `GovUkHmtSource.discover_
current_paths` discarded both and returned only the valid paths. A
single malformed entry in an otherwise-healthy 20-entry discovery
response could therefore silently drop exactly one currently-published
HMT item from every subsequent poll, while the manual runner and the
`live_source` test both stayed green -- an operational blind spot with
no signal at all. Fixed: `discover_current_paths` now raises `NewsSource
UnavailableError`, with the invalid reasons embedded in the message,
whenever `invalid_count` is non-zero. FTA cannot know WHICH content
item an invalid entry was supposed to identify, so it refuses to
proceed on the remaining N-1 valid entries rather than guess which one
is safe to drop.

**2. English-locale identity gate, now enforced in production code,
not only asserted in the live test.** FX-57D's own live research
established `locale == "en"` on every one of the 20 live-sampled HMT
items, and the story's own spec explicitly required that a non-
English item under the same bare `content_id` identity model needed
an architecture conversation before deciding whether identity must
become `content_id`+`locale` -- but the production adapter never
actually checked this; only the live test did. `fetch_content_item`
now checks `item.locale != "en"` itself and returns an ordinary
item-level invalid (counted via `items_invalid`, never ingested) --
never silently normalizing a non-English item under the existing bare
identity, never auto-switching identity schemes, never translating
content.

**3. `base_path` structural validation, before `canonical_url` is
ever built from it.** The parser previously required only a non-empty
string. A malformed provider `base_path` -- an absolute URL carrying
its own scheme, a scheme-relative `//...` path, or any value not
starting with exactly one leading `/` -- could previously flow
straight into `f"{_BASE_URL}{base_path}"` and produce a bogus
`canonical_url` pointing somewhere other than `gov.uk`. `_validate_
base_path` now rejects all three shapes at parse time
(`MalformedContentApiResponseError`), before any `canonical_url` is
constructed.

**4. `change_history` schema drift now fails the item closed, instead
of silently becoming "no history."** The original `_parse_change_
history` mapped a non-list value to `()` and silently skipped any
non-dict list entry -- both turned a genuine structural anomaly (the
API returning something FX-57D's own live research never actually
observed) into a false "this item has no revision history" signal,
exactly the kind of drift this hardening pass exists to catch. New
policy: the key being absent entirely (`None`) remains a valid empty
history (GOV.UK's own documented optionality, unchanged); a PRESENT
value that is not a list now raises; any list entry that is not an
object now raises. `kind=UPDATE` for every entry, and `CORRECTION`
never inferred from note text, remain exactly as FX-57D decided --
this pass only tightens what counts as a parseable entry, never the
semantic mapping.

**5. `withdrawn_notice` must now be STRUCTURALLY positive evidence to
set `WITHDRAWN`.** The original `_parse_withdrawn_notice` treated "any
non-empty dict" as a withdrawal and silently defaulted anything else
(including a wrong TYPE -- a string, a list, `null`) to `ACTIVE`. That
is too permissive for a field that changes a vintage's own lifecycle
status: a wrong-type value is now a parse failure
(`MalformedContentApiResponseError`), never a silent `ACTIVE`; the
only accepted ACTIVE shape remains the live-confirmed empty dict
`{}`; and a non-empty dict must now carry its own non-empty,
genuinely-parseable `withdrawn_at` timestamp (checked via the same
`_parse_utc_timestamp` the adapter already uses for normalization) to
be trusted as a real withdrawal claim -- a populated notice with a
missing or malformed `withdrawn_at` fails closed rather than being
accepted on faith. The already-correct PIT invariant from FX-57D is
explicitly UNCHANGED and reverified green: withdrawal becomes visible
at FTA's own observation time of it, never the source's own claimed
`withdrawn_at`; withdrawal remains ordinary `EVIDENCE_ELIGIBLE`
evidence, never auto-quarantined.

**`live_source` test strengthened, two new structural checks on every
run** (Section 8/9): every sampled item's `content_id` must still
parse as a Python `uuid.UUID` (a live PROVIDER-SHAPE check only --
`external_item_id` remains a generically opaque string everywhere
else in the domain, this is not a new global identity rule); every
sampled item's `first_published_at`/`public_updated_at`/`updated_at`
provenance must still be present and normalize to a valid
timezone-aware timestamp, matching exactly what FX-57D's own live
research found on all 20 sampled items. Both re-ran clean against the
real feed: 20/20 valid UUIDs, all three timestamp fields present and
normalized on every item.

**Verification, reported separately**: focused suites -- GOV.UK
discovery unit (`13 passed`), GOV.UK Content API unit (`56 passed`,
up from 39 -- the 17 new tests below), GOV.UK Postgres integration
(`11 passed`, unchanged), common orchestration (`22 passed`,
unchanged -- Phase 1c untouched by this pass), Fed regression (`22
passed`), ECB regression (`21 passed`), BoE regression (`24 passed`),
GOV.UK `live_source` (`1 passed`). Deterministic default suite
(`pytest`): `7 failed, 1936 passed, 8 deselected` -- the same seven
pre-existing, documented, unrelated OANDA failures, confirmed
unchanged; deselected count unchanged at 8 (no new `live_source` test
was added, only the existing one strengthened). `live_source` suite
(`pytest -m live_source`): `1 failed, 7 passed` -- the same
pre-existing, documented BLS 403, confirmed unchanged. `ruff check .`,
`ruff format --check .`, `mypy .` (435 source files), and `pre-commit
run --all-files` all pass clean. 17 new test functions, verified via
`git diff <FX-57D commit> -- tests/ | grep '^\+.*def test_'` -- unlike
FX-57D's own count, every touched test file this time was already
tracked, so a plain `git diff` was sufficient on its own.

`scripts/ingest_govuk_hmt_news.py` re-run live once, after the
hardening, against the real feed and dev Postgres: `created=0,
unchanged=20` -- confirms this pass introduced no behavioral drift
against real, already-ingested data. Database spot-check confirmed
the existing 45 Fed + 15 ECB + 150 BoE + 20 GOV.UK rows (230 total,
unchanged from FX-57D) remain exactly untouched.

No schema or migration change.

**No ADR 0005 update.** Every change in this pass is a pure
application-layer parsing/validation hardening -- no new source fact
was discovered that would justify touching the ADR.

Full details in `docs/DECISIONS.md`'s FX-57DH entry; `docs/
ARCHITECTURE.md` carries a new "GOV.UK source-drift & identity-guard
hardening" section; `docs/CURRENT_STATE.md` carries its own FX-57DH
entry.

**Per this story's own explicit stop instruction**: do not start
FX-57E (Statistics Canada)/FX-57F (Bank of Canada, with its own known
timestamp-remediation need), FX-58/FX-59/FX-60/FX-61/FX-EPIC-09, or
any Decision/Risk Engine work. FX-49/FX-52 remain DEFER; FX-53 remains
BLOCKED. Return FX-57DH for review.

## FX-57E0: multi-channel news provenance model (complete)

FX-57E (Statistics Canada "The Daily" prospective ingestion) was
explicitly authorized and begun. Git HEAD at FX-57E0's own start:
`ef5d5a8` (the FX-57DH commit).

**Why FX-57E paused.** Before wiring any adapter into production
ingestion, FX-57E's own spec required a pre-implementation gate: live-
fetch all four adopted StatCan subject feeds (prices, labour, economic
accounts, international trade) and compare every pairwise intersection
of their own Atom entry ids, because StatCan's feeds are SUBJECT feeds
and the same Daily release could plausibly belong to more than one.
That check found genuine, reproducible overlap -- NOT zero, as every
prior FX-57 source's own equivalent check had found:

| Pair | Overlap |
|---|---|
| prices ∩ labour | 0 |
| prices ∩ economic_accounts | 2 |
| prices ∩ international_trade | 3 |
| labour ∩ economic_accounts | 2 |
| labour ∩ international_trade | 0 |
| economic_accounts ∩ international_trade | 3 |

Every overlapping pair was the exact same Atom id, title, and content
-- e.g. `dq260903a` ("Canadian international merchandise trade, July
2026") appears, byte-identically, in both the `prices` and
`international_trade` feeds. Re-fetched fresh, independently, hours
apart, with the same result both times. Per the spec's own explicit
instruction ("IF ANY same identity appears in more than one selected
feed: STOP FX-57E IMPLEMENTATION. Return for architecture review") and
CLAUDE.md's "stop before implementing an architectural change"
discipline, FX-57E paused at this exact point -- no adapter was wired
into `IngestNewsSourceOnce`, no manual runner was written, no Postgres
write was ever attempted for StatCan data. The partially-built pieces
(`statcan_atom_parsing.py`, `statcan_source.py`, plus a provider-
neutral `before_attempt` pacing hook added to `http_fetch.fetch_text`
for StatCan's own `Crawl-delay: 2` requirement, with its own
deterministic tests) were left in place, uncommitted, exactly as
built -- preserved for FX-57E's own later resumption, deliberately
EXCLUDED from this story's own commit.

**The architectural correction, now accepted as ADR 0006.** The
existing model (`NewsItemVintage.source_channel: str`, singular,
participating in modeled-fact equality) could not represent legitimate
simultaneous multi-channel membership without either inventing a
false "revision 0 channel=A, revision 1 channel=B" transition (the
exact failure mode FX-57CH's own `CrossChannelIdentityCollisionError`
was designed to PREVENT) or permanently blocking StatCan ingestion by
treating every real cross-listed release as a fatal collision. Full
reasoning, the decision, and every rejected alternative (pick one
channel; concatenate channel names; add channel to identity; keep the
old guard with a StatCan-specific exemption) are recorded in the new
`docs/adr/0006-multi-channel-news-provenance.md`.

**The fix, in one sentence**: `source_channel` keeps its exact prior
meaning (which channel produced THIS vintage's own observation); a
new, separate field, `observed_source_channels: tuple[str, ...]`, now
carries the canonical, CUMULATIVE, monotonically-growing set of every
channel FTA has observed the item through by this vintage's own
availability, and THAT field -- not the bare `source_channel` -- now
participates in modeled-fact equality.

**Precise behavioral rules, each pinned by a dedicated test:**

- Re-observing an ALREADY-known channel, with otherwise-identical
  content, is still `UNCHANGED` -- the cumulative set does not grow,
  so nothing new happened.
- Observing a GENUINELY NEW channel mints a `REVISION_ADDED` even
  when every other field is byte-identical -- FTA's own cumulative
  provenance knowledge grew, which is itself worth a vintage, on
  exactly the same discipline as any other content change. This is
  NEVER documented as "the publisher reclassified the item" -- it is
  FTA learning an ADDITIONAL, independently-true fact.
- A content change via an ALREADY-known channel still adds a revision
  for the content change itself, but leaves the cumulative channel set
  untouched (`channel_added=False`).
- Channel membership is strictly MONOTONIC: nothing anywhere in this
  codebase ever removes a channel from `observed_source_channels` --
  an item's disappearance from one feed proves nothing about whether
  its publisher classification changed.
- `CrossChannelIdentityCollisionError` is RETIRED outright (removed,
  not kept as a parallel concept -- CLAUDE.md's own "don't keep
  unused/overlapping abstractions" discipline). `IngestNewsSourceOnce`
  now groups a run's own whole-run observation list by external
  identity: a distinct channel whose own NON-CHANNEL facts agree with
  every other channel already seen for that identity is genuine
  additional provenance and is KEPT -- both observations reach
  `RecordNewsObservation`'s own cumulative merge. Only a genuine
  disagreement on a NON-CHANNEL fact -- regardless of whether the
  colliding observations share a channel or not -- still fails the
  WHOLE run closed, via the EXISTING, broadened `ConflictingDuplicate
  ExternalIdError` (its own docstring updated to cover this third
  case explicitly).
- Surviving observations are persisted in `observed_at` ASCENDING
  order (ties broken by original configured-fetch order, never
  channel name), so cumulative channel knowledge accumulates in the
  actual order FTA learned it -- pinned by a dedicated exact-
  timestamp-tie test proving the result is deterministic, not
  dict/set-iteration-order-dependent.
- New, additive observability: `RecordNewsObservationResult.channel_
  added: bool` and `NewsIngestionResult.channel_memberships_added:
  int` -- both `False`/excluded for a brand-new item's own first-ever
  observation (there is no prior "already known" set to add to), so
  `created` and `channel_added` remain mutually distinguishing
  signals, exactly like `created`/`revisions_added`/`unchanged`
  already are. No existing counter was removed or redefined.

**Fed and BoE regression, corrected, not merely re-run.** Both
adapters had their own pre-existing cross-channel test from FX-57CH,
and both needed genuine correction, not just an exception rename:
Fed's own test's mock data turned out to ALREADY genuinely conflict
under the new rule (Fed's `source_content_type` is set from each
feed's own static metadata -- `speech` for the speeches feed,
`testimony` for the testimony feed -- so the same guid observed
through both channels always differs on that non-channel fact, even
with byte-identical XML) -- it still fails closed, correctly, now via
`ConflictingDuplicateExternalIdError`. BoE's own test used genuinely
DIFFERING titles across its two colliding channels, so it too still
fails closed for the same reason, simply re-pointed at the new
exception. Both adapters' own `live_source` tests keep actively
re-checking their own currently-observed channel-disjointness --
reframed as a drift DIAGNOSTIC worth a human look if it ever changes,
no longer as something ingestion correctness depends on (per the
spec's own Section 23).

**Migration `73b1423a5949`** adds `observed_source_channels` (`NOT
NULL` JSONB) to `news_item_vintages`. Backfill is CUMULATIVE per item,
walking each item's own vintages in `revision_sequence` order and
UNION-ing every `source_channel` seen on revisions `0..N` -- never
merely `[that row's own source_channel]`, since a genuinely sequential
cross-run channel change was always legal before this story even
though no currently-stored row happens to have one. Verified three
ways: (1) a pure-function unit test of the cumulative-backfill helper
itself, proving it is a true running union, not per-row; (2) a
downgrade-guard unit test (mocked `alembic.op`, no real DB) proving the
guard refuses ONLY when a row actually carries more than one channel,
naming every offending `news_item_key`/`revision_sequence`, and that
nothing is dropped before the guard runs; (3) a full live upgrade ->
downgrade -> re-upgrade round-trip against the REAL 230-row dev
database (45 Fed + 15 ECB + 150 BoE + 20 GOV.UK), confirming every row
count, every `observed_source_channels` value (`[source_channel]` for
every one of the 230 rows, exactly as expected since no existing
history has ever recorded more than one channel), and a clean
downgrade (every row single-channel, so the guard correctly allowed
it) followed by a clean re-upgrade reproducing the identical state.

**Verification, reported separately**: focused suites -- domain
(`test_news_item_vintage.py`, 19 passed, up from 13), common
application unit (`test_record_news_observation.py` 14 passed, up
from 8; `test_ingest_news_source_once.py` 24 passed, up from 22),
migration unit (`test_migration_observed_source_channels_backfill.py`,
new, 6 passed), repository integration (`test_news_repository.py`, 22
passed, unchanged count), `test_record_news_observation.py`
integration (18 passed, unchanged count). Fed regression: 22 passed.
BoE regression: 24 passed. ECB regression: 21 passed. GOV.UK
regression: 80 passed. Deterministic default suite (`pytest`): `1965
passed, 8 deselected`, with ZERO failures this run -- the seven
previously-documented OANDA live-practice-candle failures (unrelated
to news intelligence, tracked separately) happened to pass in this
run; reported as actually observed, not assumed stale. `live_source`
suite (`pytest -m live_source`): `1 failed, 7 passed` -- the same
pre-existing, documented BLS 403 (FX-EPIC-07, unrelated), confirmed
unchanged; Fed's, ECB's, BoE's, and GOV.UK's own live tests all pass.
`ruff check .`, `ruff format --check .`, `mypy .` (439 source files),
and `pre-commit run --all-files` all pass clean across the whole
repository, StatCan's own uncommitted WIP files included (they type-
check and lint cleanly even though nothing yet imports or tests them
as production code).

**Test counts, verified via per-file BEFORE/AFTER `grep -cE
'^(async )?def test_'` net totals** -- deliberately NOT a raw `git
diff ... | grep '^\+.*def test_'` line count this time, because 3
tests were RENAMED (not added) as part of correcting their own
behavior, which a plain added-line count would have misattributed as
new: **20 new test functions** -- 2 in `test_ingest_news_source_
once.py` (22 -> 24), 6 in `test_record_news_observation.py` (8 -> 14),
6 in `test_news_item_vintage.py` (13 -> 19), 6 in the new migration
test file.

**No schema change beyond the one migration above.** No ADR 0005
amendment (ADR 0005 is about source feasibility/rights, not the PIT
domain model) -- this story's own finding instead justified a NEW
ADR, 0006, exactly as its own spec anticipated.

**Explicitly confirmed NOT done in FX-57E0**: no StatCan adapter wired
into production ingestion; no StatCan manual runner; no StatCan write
to Postgres, ever, in this story; no resumption of FX-57E's own
remaining work (deterministic/Postgres/live-source tests for the
StatCan adapter itself, the manual runner, live ingestion); FX-57F
(Bank of Canada) not started; no FX-58+ (dedup/classification/
snapshot/dashboard/source-reputation) work; no Decision/Risk Engine
integration; no StatCan-specific concept added to the domain
(`statcan_subjects`/`statcan_channels`/`is_cross_listed` all
explicitly absent).

Full details in `docs/adr/0006-multi-channel-news-provenance.md` and
`docs/DECISIONS.md`'s FX-57E0 entry; `docs/ARCHITECTURE.md` carries a
new "Multi-channel news provenance model" section; `docs/CURRENT_
STATE.md` carries its own FX-57E0 entry.

**Per this story's own explicit stop instruction**: commit/push
FX-57E0 SEPARATELY from FX-57E's own StatCan WIP (which remains
uncommitted) and STOP. Do not resume FX-57E (Statistics Canada) in
this same pass; do not start FX-57F (Bank of Canada)/FX-58/FX-59/
FX-60/FX-61/FX-EPIC-09, or any Decision/Risk Engine work. FX-49/FX-52
remain DEFER; FX-53 remains BLOCKED. Return FX-57E0 for architectural
review.

## FX-57E: Statistics Canada "The Daily" prospective news ingestion (complete)

Resumed on top of the accepted ADR 0006/FX-57E0 model correction. Git
HEAD at this resumption's own start: `2dca97f` (the FX-57E0 commit),
with FX-57E's own prior WIP (`statcan_atom_parsing.py`, `statcan_
source.py`, the `http_fetch.py` `before_attempt` hook and its 2 tests)
intact, uncommitted, exactly as preserved.

**First action on resumption: re-verify the end-to-end flow against
real data under the NEW model**, before writing a single additional
test. Running the existing adapter through `IngestNewsSourceOnce`
against all four real live feeds confirmed: 164 items fetched, 121
genuine Daily-release observations normalized, 43 catalogue-reference
items correctly excluded, 111 unique items created, and -- the
critical confirmation -- exactly 10 revisions added, all attributable
to `channel_added=True` (a newly-learned channel), zero attributable
to ordinary content change, and zero exceptions raised. This is a
direct, live, end-to-end proof that the FX-57E0 architectural fix
actually resolves the original blocking finding for real StatCan data,
not only for synthetic common-layer fixtures.

**One stale claim found and corrected during resumption**:
`statcan_source.py`'s own module docstring, written before the FX-57E0
pause, still claimed "ZERO cross-subject overlap" and referenced the
now-retired `CrossChannelIdentityCollisionError`. Corrected to state
the actual live finding (genuine, reproducible overlap) and the actual
mechanism (`observed_source_channels` cumulative merge, `Conflicting
DuplicateExternalIdError` only on a genuine content conflict) --
worth remembering: a module docstring written mid-story, before a
pause-and-correct cycle, needs its own re-read before resuming, not
just the code.

**One genuine implementation gap found and fixed during resumption**:
`StatCanSource.fetch_feed` called `http_fetch.fetch_text` with the new
`before_attempt` pacing hook but did NOT pass its own injectable
`sleep` through to `fetch_text`'s own `sleep` parameter -- meaning
`fetch_text`'s OWN internal 5xx/429 retry backoff was still using the
REAL `asyncio.sleep` by default. A deterministic retry-pacing test
(Section 48.C) caught this immediately: it took 2+ real wall-clock
seconds to run, which should be structurally impossible for a fully-
injected deterministic test. Fixed by also passing `sleep=self._sleep`
to `fetch_text`; the same test now runs in under 0.15s. This did not
change real production behavior (both before and after the fix,
actual retries still pace correctly in a live run) -- it fixed
TESTABILITY, surfaced by writing the exact test the spec's own Section
48 required.

**Daily-release vs recurring catalogue-reference entries, resolved
exactly as the pre-pause research found**: `statcan_atom_parsing.py`
validates every entry's own `<id>` against the dated Daily-release
URL shape (`https://www.statcan.gc.ca/daily-quotidien/<YYMMDD>/dq
<YYMMDD><letter(s)>-eng.htm`); anything else (the recurring `cgi-bin/
IPS/display?cat_num=...` catalogue reference, confirmed live to
recur 7/21/14 times across Labour/Economic-accounts/International-
trade with a fresh `updated` value each time, same id every time) is
an ordinary item-level invalid, counted, never ingested, never
raised as a response-level error -- a narrow, adapter-local content-
shape filter, never a common-contract change. This parser performs
NO same-identity dedupe of its own, exactly like `rss_item_
parsing.py` -- that remains the common `IngestNewsSourceOnce` layer's
job uniformly, now correctly extended (by FX-57E0) to merge rather
than reject a benign cross-channel duplicate.

**Field mappings, each pinned by a deterministic test**: `title`
(flattened from its own `type="xhtml"` nested `<div>`, sometimes
containing an inner `<span class="refper">` for the reference period)
-> `headline`, required; `summary` (same flattening) -> `summary` if
present; no `<content>` or entry-level `<author>` ever found live, so
`body_text`/`authors` are always `None`/`()`; `<link>` -> `canonical_
url`, mapped from a genuinely separate field than identity even though
the two coincide for every live-sampled entry; `locale` is implicit
(`*-eng.atom` feeds only, never language-detected) -> `language="en"`;
`source_content_type` held constant at `"daily_release"` for all four
feeds, deliberately NOT varying by channel (Section 31/32) -- exactly
what lets a genuine cross-subject release merge as additional
provenance instead of conflicting, in direct contrast to Fed's own
per-channel `source_content_type`. `<updated>` (Case B: no
`<published>` field exists at all) maps to `source_published_at` ONLY,
never simultaneously to `source_updated_at` (which stays `None`), with
the raw value also unconditionally preserved as its own timestamp-
provenance entry -- live-reconfirmed to represent The Daily's own
release instant (every same-day entry across all four feeds shares
one identical `08:30:00-04:00` value, matching the date embedded in
that same entry's own id). A live `-05:00` (EST/winter) example was
not found within the live 100-day window (all sampled entries fell in
EDT season), but ordinary ISO-8601 parsing handles any valid numeric
offset without special-casing -- pinned by a deterministic test using
a synthetic `-05:00` fixture, with NO Toronto-local reinterpretation
(the Bank of Canada story's own known defect; StatCan does not inherit
it). The sequence letter (`dq260929a`/`g`) is treated as fully opaque
identity, never reconstructed, and never used to fabricate sub-second
timing precision -- pinned by a dedicated sequence-id test proving two
same-day letter-suffixed entries share the identical source timestamp.

**Rate pacing, robots.txt reconfirmed live, unchanged from ADR 0005's
own finding**: `www150.statcan.gc.ca/robots.txt` still sets `User-
agent: * / Crawl-delay: 2`, covering none of `/n1/rss/dai-quo/`.
`StatCanSource` paces every request -- including `fetch_text`'s own
internal retry attempts, via the new `before_attempt` hook described
above -- to at least 2.0 seconds apart. Feeds are fetched strictly
sequentially (never concurrently) by construction: `IngestNewsSource
Once` already iterates its fetchers one at a time, so no additional
guard was needed. The full robots/rate test matrix (Section 48.A-E)
is pinned deterministically with an injected monotonic clock and
sleep -- confirmed to run with zero real wall-clock wait after the
gap above was fixed.

**Verification, reported separately**: focused suites -- StatCan
Atom parser unit (`22 passed`), StatCan adapter unit (`27 passed`),
StatCan Postgres integration (`10 passed`, including the genuine
cross-subject merge and genuine-conflict-still-fails scenarios),
`http_fetch.py`'s own transport tests (`10 passed`, up from 8),
common application unit (`38 passed`, unchanged -- Phase 1c/
`RecordNewsObservation` untouched by this story), Fed regression
(`22 passed`), ECB regression (`21 passed`), BoE regression (`24
passed`), GOV.UK regression (`80 passed`). StatCan's own `live_
source` test, run separately: `1 passed` -- confirmed, live, that any
cross-subject overlap found (10 instances this run, matching the
original pre-pause research exactly) is BENIGN (identical titles
across the overlapping channels), and that zero items carry an
UNEXPECTED invalid reason (only the known catalogue-reference
pattern). Deterministic default suite (`pytest`): final verification
run was `2024 passed, 9 deselected`, zero failures (an OANDA live-
practice-candle test flickered failed on an earlier pass this same
session -- FX-EPIC-06, environment/network-dependent, unrelated to
news intelligence -- then passed cleanly on re-run; reported per the
actual final run). Full `live_source` suite (`pytest -m live_source`): `1
failed, 8 passed` -- the same pre-existing, documented BLS 403
(FX-EPIC-07, unrelated), confirmed unchanged; deselected count rose
by exactly 1 (StatCan's own new live test). `ruff check .`, `ruff
format --check .`, `mypy .` (444 source files), and `pre-commit run
--all-files` all pass clean. 62 new test functions total (2 in the
modified `test_http_fetch.py`, verified via before/after net `grep
-c`; 60 across four new test files, verified via direct per-file
`grep -c`, since none of those four existed before this resumption).

`scripts/ingest_statcan_news.py` run live, twice, against the real
four feeds and dev Postgres: run 1 -- 164 fetched, 121 normalized, 43
invalid (expected catalogue references), 111 created, 10 revisions
added (all 10 attributable to a newly-learned channel), 0 unchanged;
run 2 -- identical fetch/normalize/invalid counts, 0 created, 0
revisions added, 121 unchanged, 0 channel memberships added -- fully
idempotent. Direct SQL confirmed the existing 45 Fed + 15 ECB + 150
BoE + 20 GOV.UK rows (230 total) remained exactly untouched throughout,
alongside the 111 new, genuine `STATCAN` items (121 vintage rows); a
direct query for every StatCan vintage with more than one observed
channel returned exactly the same 10 release ids the live research
and the live test both independently found, each with the correct
cumulative two-channel set.

No schema or migration change beyond the one FX-57E0 already made.

**ADR 0005 addendum added** (live-reconfirmed): the official feed-
index page now lists 33 total `dai-quo` rows (32 subjects + "All
subjects"), not 34 -- a taxonomy/feed-index change, not a rights/PIT
one; the four adopted feeds are unchanged at their original URLs, and
every other ADR 0005 StatCan finding (licence, `Crawl-delay`, 100-day
window, same-day-shared-timestamp) was independently reconfirmed live
and is unchanged. The cross-subject-overlap SOURCE-SHAPE finding
itself, and the application-layer model correction it required, were
already recorded in ADR 0006 during FX-57E0 and are not duplicated
here.

Full details in `docs/DECISIONS.md`'s FX-57E entry; `docs/
ARCHITECTURE.md` carries a new "Statistics Canada 'The Daily'
prospective news ingestion" section; `docs/CURRENT_STATE.md` carries
its own FX-57E entry; `docs/adr/0005-...md` carries the feed-count
addendum.

**Per this story's own explicit stop instruction**: do not start
FX-57F (Bank of Canada, with its own known timestamp-remediation
need), FX-58/FX-59/FX-60/FX-61/FX-EPIC-09, or any Decision/Risk Engine
work. FX-49/FX-52 remain DEFER; FX-53 remains BLOCKED. Return FX-57E
for review.

## FX-57EH: StatCan live-drift & known-exclusion hardening (complete)

A narrowly-scoped hardening pass on FX-57E, found by review, before
FX-57F was authorized. Git HEAD at this pass's own start: `ca2e19a`
(the FX-57E commit).

**1. The catalogue-reference exclusion was too broad a catch-all.**
The original FX-57E parser treated "any id that fails the Daily-
release URL contract" as presumptively the already-understood
recurring "Product/Study" catalogue-reference noise, producing a
diagnostic that merely SAID "likely a recurring product/catalogue
reference." The `live_source` test, in turn, only checked that this
diagnostic STRING contained that phrase -- meaning a genuinely NEW,
unrecognized non-Daily id shape (real future source-schema drift)
would receive the exact same diagnostic and pass the live test
silently, exactly the failure mode a drift test exists to prevent.
Fixed: `statcan_atom_parsing.is_known_catalogue_reference_id` is now
an exact, narrow, EXPORTED predicate matching the live-verified shape
only (`https://www.statcan.gc.ca/cgi-bin/IPS/display?cat_num=
<value>` -- scheme, host, exact path, and query-string shape all
checked); the parser itself now branches on this predicate to choose
between two genuinely DIFFERENT diagnostics ("id matches the known
recurring StatCan Product/Study catalogue-reference shape... out of
this story's own adopted evidence scope, not source drift" vs.
"unexpected non-Daily StatCan entry id shape... may be genuine
source-schema drift needing review"). The `live_source` test now
extracts the ACTUAL offending id from each invalid reason (via `ast.
literal_eval` on the trailing `repr()`, never a substring/regex match
on the surrounding prose) and re-checks it against the SAME exported
predicate -- so a truly novel shape now fails the live test loudly,
by construction, not by wording coincidence.

**2. The live overlap-benignity check was weaker than production.**
The original `live_source` test's own cross-channel benignity check
compared ONLY the headline/title for a shared identity -- strictly
weaker than `IngestNewsSourceOnce`'s own `_same_non_channel_facts`,
which compares EVERY non-channel field (summary, canonical_url,
language, source_content_type, both source timestamps and their
provenance, source status/disposition, revision metadata). Per the
spec's own explicit instruction, this was fixed by REUSE, not
re-implementation: the live test now imports `_same_non_channel_
facts` directly from `ingest_news_source_once.py` (a package-internal
private-helper import, the same precedent this session already
established for `test_migration_observed_source_channels_backfill.
py`'s own direct import of a migration's private `_compute_
cumulative_channels` helper) -- no new public domain concept was
created solely for the test. A new Postgres integration test,
`test_same_headline_but_differing_summary_across_channels_still_
conflicts`, proves headline equality alone is insufficient: the SAME
external id, the SAME headline, but a genuinely DIFFERENT summary
across two StatCan channels still raises `ConflictingDuplicate
ExternalIdError` and fails the whole run closed before persistence.

**3. Live timestamp-normalization drift was not actively re-checked.**
The original live test checked `source_published_at <= retrieved_at`
only when `source_published_at` happened to be non-`None` -- it never
asserted that every accepted Daily-release observation SHOULD have
one, even though this story's own live research established exactly
that for every sampled item. The live test now asserts, for every
accepted observation: `source_published_at is not None`; exactly one
`"updated"` provenance entry exists; its `raw_value` is non-empty;
and its `normalized_at` is not `None`. This is a live DRIFT assertion
only -- the parser's own fail-soft behavior for a malformed OPTIONAL
source timestamp (preserve the raw value, leave `normalized_at=
None`, never raise) is explicitly unchanged; Section 7's own
instruction was followed precisely on this point.

**Explicitly unchanged, confirmed by full regression**: the four
adopted feeds, `source_key="STATCAN"`, the multi-channel cumulative-
provenance model (ADR 0006), `source_content_type="daily_release"`
held constant across channels, the `<updated>` -> `source_published_
at`-only timestamp mapping, PIT semantics, the 2-second crawl-delay
pacing architecture (including its own retry-path coverage), and
every one of the 111 pre-existing genuine StatCan items (121
vintages). No schema or migration change. Per the spec's own
explicit, deliberate choice (Section 8): the known catalogue-
reference entries remain counted in the EXISTING `items_invalid`
counter (no new `items_excluded` cross-cutting counter was
introduced) -- this doc, and the parser's own module docstring, now
explicitly call out that this counter's own meaning for StatCan
includes this known, understood, adapter-local out-of-scope shape,
not only genuine malformed/drifted data.

**Verification, reported separately**: focused suites -- StatCan
Atom parser unit (`29 passed`, up from 22), StatCan adapter unit
(`27 passed`, unchanged count, one assertion's own wording corrected
to match the new diagnostic), StatCan Postgres integration (`11
passed`, up from 10, the new non-title-conflict regression), common
application unit (`38 passed`, unchanged -- Phase 1c/`RecordNews
Observation` untouched), `http_fetch.py`'s own transport tests (`10
passed`, unchanged), Fed regression (`22 passed`), ECB regression
(`21 passed`), BoE regression (`24 passed`), GOV.UK regression (`80
passed`). StatCan's own `live_source` test, run separately, TWICE
(once right after the parser/live-test changes, once again after the
full regression pass): `1 passed` both times -- live-reconfirmed 10
cross-subject overlapping ids this run, matching the original
research exactly, every one proven benign by the EXACT production
compatibility rule, and zero invalid entries whose own id failed to
match the exact known catalogue-reference predicate. Deterministic
default suite (`pytest`): final verification run was `2032 passed, 9
deselected`, zero failures -- an OANDA live-practice-API test
flickered failed on an earlier pass this same session (FX-EPIC-06,
environment/network-dependent, unrelated to news intelligence) and
then passed cleanly on re-run; reported per the actual final run.
Full `live_source` suite (`pytest -m live_source`): `1 failed, 8
passed` -- the same pre-existing, documented BLS 403 (FX-EPIC-07,
unrelated), confirmed unchanged; deselected count unchanged at 9 (no
new `live_source` test was added, only the existing one strengthened).
`ruff check .`, `ruff format --check .`, `mypy .` (444 source files),
and `pre-commit run --all-files` all pass clean.

**Test counts, verified via per-file BEFORE/AFTER `grep -cE '^(async
)?def test_'` net totals** (both touched test files that gained new
tests were already-tracked, modified files, so a plain count
sufficed): **8 new test functions** -- 7 in `test_statcan_atom_
parsing.py` (22 -> 29: the exact-recognizer unit tests A-D plus the
two-diagnostics-are-genuinely-different tests), 1 in `test_statcan_
news_ingestion.py` (10 -> 11: the non-title-conflict regression).

`scripts/ingest_statcan_news.py` re-run live once, after the
hardening, against the real four feeds and dev Postgres:
`created=0, revisions_added=0, unchanged=121, channel_memberships_
added=0, items_invalid=43` -- reported as the ACTUAL result observed
(matching the expected "no behavioral drift" outcome exactly, since
live StatCan data had not changed in the intervening minutes).
Database spot-check confirmed the existing 341 rows across all five
sources (45 Fed + 15 ECB + 150 BoE + 20 GOV.UK + 111 STATCAN) remain
exactly untouched.

**No ADR 0005 or ADR 0006 update** -- every change in this pass is a
pure application-layer parsing/validation hardening inside `statcan_
atom_parsing.py` and its own `live_source` test coverage; no new
source fact was discovered.

Full details in `docs/DECISIONS.md`'s FX-57EH entry; `docs/
ARCHITECTURE.md` carries a new "StatCan live-drift & known-exclusion
hardening" section; `docs/CURRENT_STATE.md` carries its own FX-57EH
entry.

**Per this story's own explicit stop instruction**: do not start
FX-57F (Bank of Canada, with its own known timestamp-remediation
need), FX-58/FX-59/FX-60/FX-61/FX-EPIC-09, or any Decision/Risk Engine
work. FX-49/FX-52 remain DEFER; FX-53 remains BLOCKED. Return FX-57EH
for review.

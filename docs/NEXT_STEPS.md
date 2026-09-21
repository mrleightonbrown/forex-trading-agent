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


Do not start fundamentals, news intelligence, AI decision-making, or live
trading — out of scope until explicitly assigned per CLAUDE.md. The same
goes for the downstream epics not in this list at all (Decision Engine,
Risk Engine, Paper Trading Execution, Performance Analytics, Shadow
Trading) — none are part of the current phase.

Each of these should be tracked as its own Jira story and worked per
CLAUDE.md's "Development rules" (tests first where practical, smallest
change satisfying acceptance criteria, one story per commit).

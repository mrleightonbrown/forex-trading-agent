# Decisions

Lightweight running log of technical decisions. Once a decision is significant
and stable enough to need a fuller record (context/options/consequences),
promote it to `docs/adr/NNNN-title.md`.

## 2026-09-12 — Toolchain and dependency stack

**Decision:**

- Python 3.12, managed via `uv` (provisioned with `uv python install 3.12`,
  not the system/Homebrew Python).
- Package/dependency manager: `uv` (`pyproject.toml` + `uv.lock`). Installed
  via the official standalone installer (`astral.sh/uv/install.sh`), not
  Homebrew — see note below.
- Web framework: FastAPI (per CLAUDE.md).
- Database: PostgreSQL, accessed via SQLAlchemy 2 async engine, driver
  `asyncpg`. Migrations via Alembic.
- HTTP client for the OANDA Practice API adapter: `httpx` (async).
- Config loading: `pydantic-settings`, one typed `Settings` object that
  validates `TRADING_MODE=PAPER`, `BROKER_ENVIRONMENT=PRACTICE`,
  `LIVE_TRADING_COMPILED=false` at startup and fails closed otherwise.
- Lint + format: Ruff (single tool, replaces Black/Flake8/isort).
- Type checking: mypy.
- Testing: pytest, pytest-asyncio, pytest-cov, httpx `AsyncClient` for API
  tests.
- Local enforcement: pre-commit hooks (ruff lint, ruff format, mypy, basic
  hygiene, `detect-private-key`).
- CI: GitHub Actions — lint, type-check, pytest (with a Postgres service
  container) on push/PR.

**Why:** matches CLAUDE.md's fixed technologies (FastAPI, PostgreSQL,
SQLAlchemy 2, Alembic, Docker, pytest, OANDA Practice API) and fills the gaps
it deliberately leaves open. `uv` and Ruff chosen for speed and low
config-file overhead; async stack chosen throughout so the FastAPI app,
SQLAlchemy engine, and OANDA client share one concurrency model.

**Note on `uv` installation:** this machine is Intel x86_64 macOS, which
Homebrew stopped shipping prebuilt bottles for as of August 2025. `brew
install uv` falls back to building from source, which requires Xcode Command
Line Tools. Installed via `uv`'s own standalone installer script instead,
which ships a prebuilt binary — no compiler needed. Installed to
`~/.local/bin`, added to `PATH` via `~/.zprofile`.

## 2026-09-12 — FX-1: PostgreSQL primary key and timestamp conventions

**Decision:** every future table's primary key is a server-generated UUID
(`gen_random_uuid()`, requiring the `pgcrypto` extension), via a shared
`UUIDPrimaryKeyMixin`. Every table also gets `created_at`/`updated_at` as
`TIMESTAMPTZ`, populated server-side by Postgres, via a shared
`TimestampMixin`. Both live in
`forex_agent.infrastructure.db.mixins`.

**Why:** UUIDs avoid leaking row-count/ordering information (relevant for a
financial system) and need no coordination across services or replayed
backtests. Server-side, tz-aware timestamps directly enforce CLAUDE.md's
"All persisted timestamps use timezone-aware UTC values. Naive datetimes
must be rejected." — the column type is `TIMESTAMPTZ` and the value is never
supplied by application code, so a naive datetime can't reach the column in
the first place.

**Also recorded:** `asyncio_default_fixture_loop_scope` /
`asyncio_default_test_loop_scope` are both set to `"session"` in
`pyproject.toml`. Without this, pytest-asyncio's default per-test-function
event loop breaks `get_engine()`'s cached singleton engine (correct in
production, where one event loop lives for the process's whole lifetime) —
its asyncpg connections stay bound to whichever loop created them, so the
next test's loop can't use them. A session-scoped test loop matches
production's actual loop lifetime.

## 2026-09-13 — FX-3: BrokerPort scoped to read-only, as a Protocol

**Decision:** `BrokerPort` (`application/ports/broker_port.py`) defines only
`get_price(instrument) -> Price` and `get_account_balance() -> Money`. No
order-placement/execution-intent method. Implemented as a `typing.Protocol`,
not an ABC.

**Why no order placement yet:** CLAUDE.md's current M0–M4 priority list
(items 1–11) stops at regime detection — Risk Engine, Decision Engine, and
Paper Trading Execution (Jira epics 10–12) are not part of the current
phase. CLAUDE.md is also explicit that no code may reach an order without
first going through risk approval and execution-intent creation, neither of
which exists yet. Adding a `place_order` method now would be a capability
with no safety mechanism behind it — easy for future code to call directly
and bypass the risk pipeline entirely by construction, simply because
nothing else exists yet to stop it. Add it deliberately when Risk
Engine/Paper Trading Execution is actually assigned, alongside whatever
execution-intent type gates it.

**Why `Protocol` over `ABC`:** structural typing means FX-4's real OANDA
adapter and any test double (`tests/fakes/broker_port.py`) only need to
match the method shapes, not inherit from a shared base. Verified working:
`FakeBrokerPort` satisfies `BrokerPort` under mypy with zero inheritance.

**Also established:** the domain-boundary contract-test pattern from FX-2
now has a shared helper (`tests/contract/_boundary.py`) and a second
instance guarding `application/` the same way
(`tests/contract/test_application_boundary.py`) — `application` may not
import FastAPI/SQLAlchemy/httpx/the OANDA SDK either, since
`infrastructure` depends on `application` (to implement its ports), never
the reverse.

## 2026-09-13 — FX-4: OANDA practice account access

**Decision:** created a personal OANDA fxTrade Practice account and a
personal access token (My Account → My Services → Manage API Access).
Credentials live only in the local, gitignored `.env` — never shared in
chat, never committed. Connectivity confirmed directly against
`GET /v3/accounts/{id}/summary` before any adapter code was written.

**Also confirmed against OANDA's own docs:** practice REST base URL
`https://api-fxpractice.oanda.com` (already in `.env.example` since FX-0);
live is `https://api-fxtrade.oanda.com`. OANDA returns balance/price fields
as JSON *strings*, so `OandaBrokerAdapter` converts straight to `Decimal`
from the string — never via `float`.

## 2026-09-13 — FX-4: OandaBrokerAdapter design

**Decision:** `OandaBrokerAdapter` takes `api_key`/`account_id`/`base_url`
as explicit constructor parameters (plus an optional injectable
`httpx.AsyncClient`) rather than reading `Settings` itself. The `apps`
composition root is responsible for pulling those three values out of
`Settings` when it wires the adapter up.

**Why:** keeps `infrastructure/broker_oanda` fully decoupled and trivially
testable in isolation (a mocked `httpx.AsyncClient` is enough — see
`tests/unit/infrastructure/broker_oanda/test_adapter.py`). Note this is a
mild inconsistency with FX-1's `infrastructure/db/session.py`, which *does*
import `apps.settings` directly for its process-lifetime singleton engine.
Not fixing that now — flagging it as a pre-existing wrinkle, not repeating
it here, since this adapter doesn't need a singleton the way the DB engine
does.

**Also decided:** the `Authorization` header is attached per-request
(`self._headers`, passed to every `.get()` call), not baked into the
client at construction time. This was forced by a real bug an early test
caught: when a test injects its own `httpx.AsyncClient` (as
`test_get_price_success` etc. do), a client-level default header set only
in the "adapter builds its own client" branch never reaches that injected
client, so the request left the auth header off entirely. Per-request
headers fixed it and are more correct regardless of test/production use.

**Also decided:** a defensive host check independent of `Settings`' own
PAPER/PRACTICE validation — `OandaBrokerAdapter` refuses to construct
against any host other than `api-fxpractice.oanda.com`
(`NonPracticeHostError`), since `OANDA_API_BASE_URL` is a separately
configurable value that could be pointed at the live host by mistake even
while `TRADING_MODE`/`BROKER_ENVIRONMENT` stay correct.

**Also decided:** the live integration test
(`tests/integration/test_oanda_broker_adapter.py`) auto-skips via
`pytest.mark.skipif` when `Settings.oanda_api_key`/`oanda_account_id` are
unset, so CI (which has no OANDA secrets) skips it cleanly rather than
failing, while a developer machine with `.env` populated runs it for real.
Adding OANDA secrets to GitHub Actions so CI exercises this too is a
reasonable future improvement, not done here.

## 2026-09-13 — FX-5: Candle domain primitive and persistence

**Decision:** `Candle` carries `bid: Ohlc` and `ask: Ohlc` (two full OHLC
sets), not a single mid-price OHLC. `Ohlc` validates that `high`/`low` are
actually the max/min of open-high-low-close, rejecting bad data before it
reaches storage. `Granularity` values match OANDA's own naming (`M1`,
`H4`, `D`, ...) — same reasoning as `Instrument.symbol` already matching
OANDA's instrument format, no translation table needed when FX-6 fetches
candles.

**Why bid+ask, not mid:** CLAUDE.md: "Backtests must include spread."
Collapsing to a single mid price at ingestion time would make that
impossible to recover later — the backtester (item 10) needs both sides
available from the start.

**Persistence:** `candles` table has a unique constraint on `(instrument,
granularity, start_time)`. `CandleRepository.upsert_many` (application
port) is implemented via Postgres `ON CONFLICT DO UPDATE` keyed on that
constraint — this is what makes re-running ingestion safe: the same
candle upserted twice produces one row, and a forming candle later
finalizing (same key, new values) updates in place rather than erroring or
duplicating. Verified by dedicated regression tests, since CLAUDE.md
explicitly calls out "duplicate events" and "provider duplication" as
required test coverage.

**Also decided:** the repository commits its own transaction inside
`upsert_many` rather than leaving commit control to a caller. Reasonable
for now since nothing yet composes multiple repository calls into one
transaction — FX-6's ingestion logic will just call this once per batch.
Worth reconsidering if a future story needs multi-repository atomicity.

**Also decided:** used `alembic revision --autogenerate` (previous
migrations were hand-written) now that a real ORM model exists to diff
against — reviewed the generated DDL before applying, per CLAUDE.md's
"review the diff" rule; only cosmetic changes made (docstring, import
order/formatting).

## 2026-09-13 — FX-6: MarketDataPort as a separate port; OANDA candle fetching

**Decision:** `MarketDataPort` (`get_candles`) is a new, separate `Protocol`
from `BrokerPort` (FX-3), not a method added to `BrokerPort`. Implemented
by `OandaMarketDataAdapter` against OANDA's
`/v3/instruments/{instrument}/candles`.

**Why separate from BrokerPort:** live quote/balance connectivity and
historical/bulk candle fetching are different shapes of concern (ranged,
potentially backfill-heavy) even though one provider (OANDA) implements
both for now. Confirmed live that this endpoint needs no account ID at
all, unlike `BrokerPort`'s two methods — a further sign it's a genuinely
different capability, not an extension of the same one.

**Confirmed live against the practice API before writing any adapter
code** (same discipline as FX-4):
- The endpoint takes no account ID — just `granularity`/`from`/`to`/`price`.
- Its `time` field (nanosecond-precision, e.g.
  `"2026-09-11T20:57:00.000000000Z"`) parses directly with Python 3.12's
  `datetime.fromisoformat` — no manual truncation/reformatting needed.
- OANDA caps `count` at 5000 and returns HTTP 400
  (`"Maximum value for 'count' exceeded"`) for a `from`/`to` range
  implying more, rather than silently truncating the response. Confirmed
  the distinct error text for an invalid instrument
  (`"Invalid value specified for 'instrument'"`) so the adapter can tell
  the two 400 cases apart and raise the right exception for each.

**Decision:** `get_candles` is bounded to one request and raises
`CandleRangeTooLargeError` if the range would exceed OANDA's cap, rather
than silently truncating or auto-paginating. Pagination for backfills
larger than 5000 candles at a given granularity is explicit future work,
not built here — keeps this story to one coherent piece.

**Decision:** ingestion stores every candle OANDA returns, finalized or
not. A still-forming candle gets `is_finalized=False` and updates in place
once OANDA later reports it complete, via FX-5's upsert-on-conflict.
CLAUDE.md's "strategies must only evaluate finalized candles" is a filter
applied when *reading* candles later, not a reason to withhold forming
ones from storage now.

**Decision:** reused FX-3's `BrokerPortError` hierarchy (adding one new
member, `CandleRangeTooLargeError`) rather than a parallel hierarchy for
`MarketDataPort` — same failure shapes. Renamed the module docstring to
reflect both ports use it. Worth revisiting the "Broker" naming if a
third, differently-shaped port ever needs its own failure modes.

**Also decided:** extracted `OandaBrokerAdapter` and `OandaMarketDataAdapter`'s
shared plumbing (the practice-host guard, JSON parsing/error-message
extraction) into `infrastructure/broker_oanda/_shared.py` rather than
duplicating it in the new adapter — refactored `OandaBrokerAdapter` to use
it too; all 19 of its existing tests still pass unchanged.

## 2026-09-13 — FX-8: crossed-market validation and gap detection

**Decision:** `Candle` now rejects `ask.open < bid.open` and
`ask.close < bid.close` at construction. Deliberately *not* checking
high/low the same way: `bid.high` and `ask.low` can occur at different
instants within the same candle, so `bid.high > ask.low` doesn't imply
anything is wrong — only open and close are each a single instant, where
ask ≥ bid is a hard market-structure guarantee. One existing test fixture
(`tests/integration/test_candle_repository.py`'s `_candle` helper) had a
fixed `ask.close` independent of its varying `bid_close` parameter and
would have violated this the moment `bid_close` exceeded it — fixed to
derive `ask.close` from `bid_close` with a consistent spread, same pattern
already used elsewhere.

**Decision:** `find_gaps` (pure, domain) and `DetectDataGaps` (use case,
wired to `CandleRepository.get_range`) detect missing expected candles in
a stored range. Deliberately no market-calendar awareness — forex session
boundaries shift with daylight saving and vary by broker, real complexity
this cuts rather than approximating badly. Callers must pass ranges
already known to be within a trading session (e.g. filter out weekends
themselves). A future story can add that filtering if it's actually
needed.

## 2026-09-13 — FX-9: strategy framework — domain, not application; runner enforces finalized-only

**Decision:** `Strategy` (Protocol) and `TradeHypothesis` live in
`domain/`, not `application/ports/` alongside `BrokerPort`/
`CandleRepository`/`MarketDataPort`. Those three cross a real I/O boundary
something in `infrastructure/` implements; a strategy is a pure
computation over already-fetched candle data, no I/O at all — same
category as `aggregate_candles`/`find_gaps`.

**Decision:** CLAUDE.md's "strategies must only evaluate finalized
candles" is enforced by `run_strategy`, not left to each strategy
implementation to check itself. `run_strategy(strategy, candles)` raises
if any candle isn't finalized, before ever calling `strategy.evaluate(...)`
— every future concrete strategy gets this protection automatically.
Same reasoning as the architecture-boundary contract tests: turn a rule
into something structural rather than trusting every future
implementation to remember it.

**Explicitly out of scope:** any concrete strategy implementation (a
separate future story), and any execution-intent/order type —
`TradeHypothesis` carries zero authority on its own; CLAUDE.md's pipeline
requires a risk decision and approved execution intent first, neither of
which exists yet (Risk Engine / Paper Trading Execution aren't in the
current M0–M4 phase).

## 2026-09-13 — FX-10: backtest engine, split from trade/P&L simulation

**Decision:** split CLAUDE.md's "backtester" item into two stories, same
pattern as FX-3/4 and FX-5/6/7. FX-10 (this one) is the look-ahead-safe
engine: `run_backtest(strategy, candles) -> list[TradeHypothesis]`.
Trade/P&L simulation (spread-aware entry/exit, `Money`-based P&L) is
FX-11, deliberately deferred — closing a backtest position needs its own
design decision (next opposite signal? fixed holding period? end of
window?) with no live risk/execution engine to do it, and that decision
shouldn't be bundled into the engine story.

**How look-ahead bias is actually prevented:** `run_backtest` walks
`candles` one bar at a time; at step `i`, `strategy.evaluate(...)` (via
`run_strategy`, so finalized-only enforcement is inherited, not
duplicated) is only ever given `candles[0:i+1]`. Verified by a test whose
fake strategy raises immediately if it can see a value that's only
supposed to appear in the final bar, before the step where that's
supposed to happen — not just a length check.

**Decision:** a returned hypothesis's `generated_at` must equal the
current bar's `start_time`, or `run_backtest` raises. Catches a strategy
fabricating a hypothesis timestamped outside the window it was actually
shown — a real look-ahead bug class. Consequence: every future concrete
strategy must derive its hypothesis's timestamp from the last candle it
was given, never wall-clock time.

**Also decided (input validation):** candles must be one instrument, one
granularity, and strictly ascending by `start_time` — out-of-order input
is rejected, not silently sorted, since silent reordering could mask a
caller bug that let future-dated data leak into the series in the first
place.

**Known, accepted limitation:** `candles[:i+1]` reslicing is O(n) per
step, O(n²) overall. Fine for now (tests, small backtests); a real
year-long M1 backtest would be far too slow this way. A windowed/
incremental approach is future work once real strategies exist and
performance actually matters — premature optimization avoided here.

## 2026-09-13 — FX-11: backtest exit rule — close-and-reverse

**Decision (user's call, not mine):** a backtest position stays open
until the strategy emits a hypothesis in the *opposite* direction, which
closes it and immediately opens the reverse position. A same-direction
repeat while already in a position is a no-op. Anything still open when
the hypothesis list ends is force-closed at the last candle's price.

**Why this over the alternatives considered:** self-contained — needs no
new parameter (unlike a fixed holding period, which would need an
arbitrary N with nothing in the domain model to derive it from) and uses
only what `TradeHypothesis` already carries. "Close-only, no auto-reverse"
was the other real option (sits out one signal every direction change);
close-and-reverse was preferred as always-in-the-market between signals.

**Decision:** `SimulatedTrade.pnl` is the raw price delta in the quote
currency — P&L per single unit of base-currency notional, not multiplied
by any position size. Multiplying by real position size is a Risk Engine
concern that doesn't exist yet; not invented here to fill the gap.
`simulate_trades` reuses FX-2's `Price.entry_price`/`exit_price` for the
correctly-sided price rather than reimplementing that rule — prices come
from each hypothesis's matching candle's `bid.close`/`ask.close`
(matched via FX-10's `generated_at == candle.start_time` invariant).

## 2026-09-13 — FX-11H: backtest correctness hardening (external review)

An external review (ChatGPT, given the FX-10/FX-11 code) caught a real
bug and several missing defensive checks. Worth recording where it came
from: this wasn't found by our own tests, which is exactly why the fix
matters.

**The bug:** `simulate_trades` was executing a hypothesis at the *same*
candle's close that generated it. A hypothesis generated from bar N's
finalized close is only known once bar N has already closed — by
definition, that price is already in the past by the time the decision
exists. Executing at bar N's own close let a strategy "trade on a price
it had already seen close," not a realistic fill. This is look-ahead-bias
adjacent, even though FX-10's own `run_backtest` walk-forward loop was
never violated (the strategy genuinely never saw future *candles* — the
bug was in when the resulting *trade* could realistically fill, one layer
downstream).

**Fix:** `simulate_trades` now executes at the *first* price of bar N+1 —
`ask.open` for a long entry, `bid.open` for a short entry (and the same
values, reused, for a reversal's close-then-reopen at bar N+1). A
hypothesis generated on the final candle in the dataset has no N+1 to
execute from and is not actionable at all — no fill is invented for it;
any already-open position simply carries through unaffected to the
end-of-dataset close.

**End-of-dataset close, decided and documented explicitly:** a position
still open when the hypothesis list ends is force-closed using the
*last* candle's **close** (not a next-bar open, since none exists beyond
the end of the dataset — there's no more realistic price available).
This is the one place a close price is still used for execution, and
it's a deliberate, unavoidable exception, not an oversight.

**Also fixed — defensive validation gaps:**
- `run_backtest` now rejects a hypothesis whose `instrument` doesn't
  match the candles being replayed (previously unchecked — a buggy
  strategy could silently return a hypothesis for the wrong pair).
- `simulate_trades` now validates its own inputs (mixed instrument/
  granularity, non-ascending or duplicate candle timestamps,
  non-finalized candles, out-of-order or duplicate hypothesis
  timestamps, hypothesis/candle instrument mismatch, and a hypothesis
  timestamp with no matching candle) instead of assuming it's only ever
  called with `run_backtest`'s own well-formed output — it's a public
  domain function, callable directly with hand-built data.
- `find_gaps` now rejects candles spanning more than one instrument.
  Previously, `present = {candle.start_time for candle in candles}` was
  built purely from timestamps with no instrument check — a candle from
  a *different* instrument at the right timestamp could silently mask a
  real gap in the one being checked.

**Nothing about FX-10/FX-11's core design changed**: still domain-only
(no infrastructure/FastAPI/SQLAlchemy dependency), still the
close-and-reverse exit rule, still `pnl` as a per-unit price delta, still
no position sizing/concrete strategies/regime detection — all of that
remains exactly as decided. This story only corrected execution timing
and added missing input validation.

## 2026-09-13 — FX-11H.1: small follow-ups from FX-11H review

**Decision:** `simulate_trades` now raises if given a non-empty
`hypotheses` list alongside empty `candles` — previously returned `[]`
silently, which could mask a real caller bug (hypotheses that can't be
matched to any candle at all, not even a wrong one).

**Documented, not changed:** the end-of-dataset forced close's
`exit_time` is the *identifying timestamp* of the candle that produced
the exit price (its `start_time`, consistent with every other timestamp
in this module) — not the precise instant that candle closed
(`start_time` + the granularity's duration). `Candle` carries no separate
close-instant field to use instead. Noted inline at the one call site
this applies to.

**Softened:** the OANDA live-test flakiness note in `CURRENT_STATE.md`
previously asserted "an apparent rate limit... not a code defect" — that
was an inference, not a confirmed diagnosis. Now reads "root cause
undetermined."

**Deferred design note (user's, recorded for later — not blocking
FX-12):** `TradeHypothesis.generated_at` is actually the *start*
timestamp of the candle that produced the decision, not the real instant
the decision became computable (which is closer to that candle's close,
i.e. `start_time` + the granularity's duration). FX-11H's next-bar
execution logic makes the simulator correct despite this — the hypothesis
is never executed before a realistic price exists — but the distinction
between "which bar produced this" (`decision_bar_start`) and "when the
decision was actually available" (`decision_time`) is currently
collapsed into one field. This will matter once technical signals need
to be combined with timed macro/news events, which have their own
precise availability times unrelated to any candle boundary. Revisit
when that work starts; `TradeHypothesis`'s single-timestamp shape is
correct for now.

## 2026-09-13 — FX-12: regime detection — trending/ranging via ADX

**Decision (all three confirmed with the user before implementing):**
regime is a single trending-vs-ranging axis (not also a separate
volatility axis, and not both combined into one story); classification is
via Wilder's ADX, the standard deterministic technical-analysis measure
of trend strength — no ML, consistent with the current phase excluding
AI/ML decision-making; the function classifies a single trailing window
per call (`classify_regime(candles) -> TrendRegime`), mirroring how
`Strategy.evaluate` consumes candles, rather than producing a full
historical series the way `aggregate_candles`/`find_gaps` do.

**Decision: ADX computed from a synthetic midpoint approximation**
(bid/ask OHLC averaged — `(bid.high + ask.high) / 2` and so on), not one
side. Trend/regime is a market-structure question, not an execution-price
one — picking bid or ask arbitrarily would introduce a directional bias
with nothing to do with the actual indicator. Confirmed with the user
before implementing, since it's the first domain code to average bid/ask
at all (everything before this used them directly, on purpose —
CLAUDE.md's "backtests must include spread"). **Terminology corrected in
FX-12H**: this average-of-extrema is not the same as a true provider mid
price, since bid's high/low and ask's high/low can occur at different
instants within a candle — the average of the two period extrema isn't
necessarily what a genuine mid-price series' own high/low would have been
over that period. See the FX-12H entry below.

**Decision:** binary classification only, per the user's call — `ADX >=
threshold` (default 25, Wilder's own convention) → `TRENDING`, else
`RANGING`. No third "developing trend" state, even though traditional ADX
interpretation sometimes treats 20–25 as ambiguous.

**Verification approach:** rather than trusting a single implementation
of a nontrivial recursive algorithm (Wilder smoothing has two different-
looking but algebraically equivalent forms — a sum-based accumulator for
TR/+DM/-DM, an average-based one for ADX-from-DX — easy to get subtly
wrong), wrote a second, independent reference implementation of the same
standard algorithm (float-based, in a scratch script) against a small
fixed synthetic price series, and asserted the actual Decimal
implementation agrees with it to the precision the reference supports.
This is `test_adx_matches_independent_reference_calculation` — it checks
the arithmetic itself, not just qualitative trending/ranging behavior
(which the other tests cover separately, since a wrong-but-monotonic ADX
calculation could still happen to pass a purely qualitative check).

**Also decided:** extracted the "one instrument, one granularity,
strictly ascending `start_time`" validation — duplicated across
`run_backtest` (FX-10) and `simulate_trades` (FX-11) — into
`candle_series.require_consistent_series`, now shared by those two and
`classify_regime`. Behavior is unchanged for the first two; confirmed by
their existing test suites passing unmodified against the refactor.

**Requires ≥ `2 × period` candles**, matching exactly what Wilder's
smoothing needs to produce one real ADX value (`period` bars to seed
smoothed TR/+DM/-DM, then `period` more DX values to smooth into the
first ADX) — raises otherwise rather than computing a number on data too
thin to mean anything.

This closes out CLAUDE.md's current M0–M4 phase (items 1–11). Everything
downstream (fundamentals, news intelligence, AI decision-making, live
trading, and epics not in the M0–M4 list at all — Decision Engine, Risk
Engine, Paper Trading Execution, Performance Analytics, Shadow Trading)
remains explicitly out of scope until assigned.

## 2026-09-13 — FX-12H: regime detection hardening (external review)

Another external review (ChatGPT, given the FX-12 code) caught missing
input validation and an imprecise terminology claim — no algorithm or
architecture change.

**Decision:** `classify_regime` now rejects `period < 1` and `threshold`
outside `[0, 100]`. Neither was checked before. `period <= 0` would have
divided by zero (or a negative number) inside Wilder's smoothing
recurrence without ever raising a clear error; a `threshold` outside
ADX's own valid range would silently produce an always-TRENDING or
always-RANGING result with no indication the configuration itself was
nonsensical.

**Corrected, not changed:** every place describing what ADX is computed
from previously said "mid prices"/"mid OHLC" — imprecise. `Candle` has no
true mid OHLC field; the value used is `(bid.X + ask.X) / 2` per OHLC
point, a *synthetic midpoint approximation*. Bid's high and ask's high
(same for low) can occur at different instants within one candle, so
averaging the two period extrema isn't necessarily equal to what a
genuine mid-price series' own high/low would have been over that period.
The classification behavior is unaffected — only the documentation and
comments describing it were wrong. Corrected in
`regime_detection.py`'s module/function docstrings and in this file's
own FX-12 entry above.

**Recorded as deferred work, not implemented here:** OANDA's v20 API can
supply a true mid OHLC directly via its `price` query parameter (`M` for
mid, or `BAM` for bid+ask+mid together) — FX-6's `OandaMarketDataAdapter`
currently only requests `BA` (bid+ask), so no true mid price is ingested
or stored anywhere yet. Switching `classify_regime` (and `candles`
storage generally) to use a real mid OHLC instead of the bid/ask-average
approximation is future work, not needed to unblock FX-12/FX-12H's scope.

**Explicitly not touched, per the review's own scope:** the ADX
algorithm itself, `TrendRegime`, the shared `candle_series` validation
extracted in FX-12, and every downstream module (`run_backtest`,
`simulate_trades`, the strategy framework) — none of that changed.

## 2026-09-14 — FX-12H.1: regime detection parameter type validation

A follow-up review found FX-12H's new value checks (`period < 1`,
`threshold` outside `[0, 100]`) didn't check *types* first — `period=3.5`
passed the range check and failed later with an opaque slice error;
`period=True` was silently accepted since `bool` is a Python subclass of
`int`; `threshold=25.0` (a `float`) silently worked despite CLAUDE.md's
"never use float for prices, balances, units, or P&L," which this
indicator's threshold is close enough to that the same rule should apply;
`threshold="25"` (a `str`) failed later with a generic comparison
`TypeError`.

**Decision:** `classify_regime` now checks types before values —
`period` must be `int` and explicitly not `bool` (`isinstance(period,
bool) or not isinstance(period, int)`, since `bool` passes a plain
`isinstance(x, int)` check), `threshold` must be `Decimal`. Raises
`TypeError` with the actual type named, before any of the existing
`ValueError` range checks run. Confirmed via mypy that the `bool` case
needed no `# type: ignore` in its test — mypy's static type system
accepts `bool` wherever `int` is expected (that's exactly the dynamic gap
being guarded against; the static type system doesn't see it as a gap at
all).

## 2026-09-14 — Deferred: regime detection beyond trend/range (roadmap only, nothing built)

FX-12/FX-12H built exactly one regime axis: `TrendRegime` (`TRENDING`/
`RANGING`) via ADX. ChatGPT's review of that work gave two *different*
lists worth keeping distinct, since they don't map onto each other:

**What ADX itself does not tell you** (a caveat, not a roadmap): trend
*direction*, volatility regime, risk-on/risk-off, event regime, liquidity
regime. ADX measures trend *strength* only.

**Independent dimensions actually proposed as a future roadmap** — only
four, not the same four as above:
- Trend: `TRENDING`/`RANGING` — done (FX-12).
- Trend direction: `UP`/`DOWN`/`NEUTRAL` — not built.
- Volatility: `LOW`/`NORMAL`/`HIGH` — not built.
- Event state: `NORMAL`/`EVENT_RISK` — not built.

Explicitly **not implemented, and not on this roadmap either** —
mentioned only in the caveat list above, not proposed as something to
build: risk-on/risk-off, liquidity regime.

**Decision: none of this is built now.** Two of the four roadmap
dimensions (trend direction, volatility) are deterministic technical
indicators computable from candles already stored — same category as
`classify_regime` itself, genuinely in current-phase scope whenever
picked up. The other two (event state, and the caveat-list's
risk-on/risk-off and liquidity regime) depend on data nothing in this
repo ingests yet — an economic calendar, cross-asset/macro data,
order-book depth — and map to epics explicitly outside the current
M0–M4 phase (Economic Event Risk, News Intelligence, Signal Source
Intelligence). CLAUDE.md: don't start those until assigned.

**Design intent already in place for when this is picked up:** keep each
dimension an independent, separately-classified value (as `TrendRegime`
already is) rather than merging them into one combinatorial enum like
`HIGH_VOL_BEAR_TREND_EVENT_RISK` — the current narrow, single-axis design
leaves room for that without any rework.

Recording this here specifically so it doesn't get lost — this entry
exists to be found later, not to be acted on now.

## 2026-09-15 — Concrete strategy suite roadmap (user's plan, agreed; nothing built yet)

CLAUDE.md's M0–M4 phase (items 1–11) is done. From here the operative
question changes from "is the platform correct?" to "does a strategy add
predictive value after spread, under conditions it wasn't tuned on?" —
that shift is why everything below is deliberately diversity-first and
measurement-first rather than strategy-count-first.

**Numbering note:** the FX-numbers below are a *proposed backlog order*,
not fixed final IDs — same reason FX-11H/FX-11H.1/FX-12H/FX-12H.1 exist
outside strict sequence: hardening follow-ups get inserted as real issues
turn up. The order and grouping is what's being committed to here, not
exact numbers.

**The suite, in order, and why this order:**

1. **EMA Trend v1** (`ema_crossover_v1`) — 20/50 EMA crossover on the
   synthetic-midpoint close (same convention as ADX). The deliberately
   boring reference strategy: easy to independently verify, exercises the
   close-and-reverse exit rule exactly as designed, and will surface any
   remaining strategy/backtest integration defects fast. Named
   `ema_crossover_v1`, not `trend_strategy` — there will be more than one
   trend strategy eventually.
2. **Close-Channel (Donchian) Breakout v1** — close breaks the highest/
   lowest *close* of the prior 20 bars. Deliberately close-based, not
   high/low-based: FX-12H already established that our synthetic
   bid/ask-averaged highs/lows are an approximation (the two sides' period
   extrema can occur at different instants), while bid-close and ask-close
   are the same instant and average cleanly. True high/low Donchian
   channels become testable once real provider mid OHLC is stored — still
   deferred, see the FX-12H entry above.
3. **Time-Series Momentum v1** — N-bar return vs. a threshold (starting
   at `threshold=0` as the pure baseline, a deadband tested later, not
   assumed upfront). Deliberately minimal — not RSI+MACD+ROC+stochastic
   combined into one "momentum" strategy, where nothing would be
   attributable. Academic FX momentum evidence is a legitimate reason to
   include this family; the same literature argues for testing it after
   transaction costs before trusting it, which is exactly what this
   backtester already forces (spread-aware fills, look-ahead-safe replay).
4. **Mean Reversion v1** (Bollinger/z-score) — requires `TargetPosition`/
   FLAT semantics first (below); a mean-reversion thesis needs to exit
   when the mispricing closes, not wait for the opposite extreme to
   trigger close-and-reverse.
5. **Volatility Expansion Breakout v1** — ATR14/ATR50 ratio (compression
   → expansion) combined with a range breakout. Overlaps with Donchian by
   construction; the point is finding out whether the extra
   "regime changed" condition adds anything over breakout alone — another
   thing to measure, not assume.
6. **Multi-timeframe Trend Confirmation v1** — H1 signal gated by H4
   trend agreement. Deliberately last, and blocked on resolving the H4
   candle-alignment question first (below) — building multi-timeframe
   sophistication on timeframe boundaries we haven't verified would be
   compounding an unresolved unknown.

**Explicitly not started, and why:** carry (needs policy rates, forward
points/swap, rate expectations — belongs with the fundamentals/economic-
data phase, FX-EPIC-06/07, not assigned yet). Economic-momentum-style
fundamentals signals, for the same reason.

**Control strategies** (always-long, always-short, previous-bar-direction,
no-trade) — not "a strategy," a sanity baseline every real strategy's
metrics get compared against on the same sample. Without them, a modest
positive Sharpe can't be distinguished from sample drift. Not deployed;
built to sit next to FX-17 (metrics) since their only value is having a
scoreboard to appear on — see the sequencing note below.

**Two structural changes needed along the way, sequenced deliberately
early:**

- **Strategy metadata/hypothesis enrichment** (`strategy_key`,
  `strategy_version`, `timeframe`, `parameters` — likely additions to
  `TradeHypothesis` or an adjacent type). Sequenced *first*, before any
  concrete strategy exists, specifically because retrofitting identity/
  versioning across six already-built strategies is far more invasive
  than building it into the first one. Needs its own design pass — a
  `parameters` field in particular breaks the "frozen dataclass is
  hashable" pattern every other domain value object follows unless its
  shape is chosen deliberately.
- **`TargetPosition` (LONG/SHORT/FLAT) semantics**, sequenced after the
  first three directional strategies (EMA, Donchian, momentum — all of
  which work fine under today's close-and-reverse model) and before mean
  reversion (which doesn't). This is a bigger change than the enum
  suggests: `TradeSide` currently does double duty as both "what the
  strategy believes" and "which side to execute on" — `Price.entry_price`/
  `exit_price` only make sense for LONG/SHORT. Once FLAT exists,
  `simulate_trades`'s exit logic needs a third behavior (close without
  reopening) distinct from today's two (same-side no-op, opposite-side
  close-and-reverse). Real design work, not a trivial addition — gets its
  own conversation when picked up, same as every other story here.

**Regime stays structurally separate from strategies, tested as an
experiment, not assumed:** no strategy above checks `TrendRegime`
internally. Instead, a later comparison story (`EMA alone` vs. `EMA when
TRENDING`, `Mean Reversion alone` vs. `Mean Reversion when RANGING`)
answers "does regime filtering actually help?" as data. Baking regime
into each strategy would make that question unanswerable and violate the
same "one subsystem doesn't need to know about every other subsystem"
principle `BrokerPort`/`MarketDataPort`/`CandleRepository` were already
kept separate for.

**Two known dependencies flagged now, not discovered mid-story:**
- **H4 candle-alignment**, referenced above: `aggregate_candles`'s bucket
  boundaries are epoch-UTC-aligned by construction; never verified
  against what OANDA's *own* H4 candles (`get_candles(granularity=H4)`)
  actually align to. If they differ, a multi-timeframe strategy mixing
  self-aggregated H4 with OANDA-native H4 would silently compare
  misaligned bars. Needs its own small reconciliation story before
  multi-timeframe confirmation (item 6), not folded silently into it.
- **Candle backfill pagination**: FX-6 already documented `get_candles`
  as bounded to 5000 candles per request, pagination deferred. The
  metrics epic's planned year/quarter segmentation needs more history
  than that bound provides at most granularities (5000 M1 candles ≈ 3.5
  days; even H1 only reaches ≈ 7 months) — pagination is a likely
  prerequisite for that specific metric, not optional polish.

**Epic mapping:**

| Story (proposed order) | Epic |
|---|---|
| Strategy metadata/hypothesis enrichment | FX-EPIC-03 Technical Strategies |
| EMA Crossover v1 | FX-EPIC-03 |
| Close-Channel Breakout v1 | FX-EPIC-03 |
| Time-Series Momentum v1 | FX-EPIC-03 |
| Backtest performance metrics | FX-EPIC-04 Backtesting |
| `TargetPosition`/FLAT semantics | FX-EPIC-03 |
| Mean Reversion v1 | FX-EPIC-03 |
| Volatility Expansion v1 | FX-EPIC-03 |
| Regime-conditioned experiments | FX-EPIC-05 Market Regime Detection + FX-EPIC-04 (dual) |
| Multi-timeframe Trend v1 | FX-EPIC-03 |

FX-EPIC-05 (Market Regime Detection) is considered V1-complete as of
FX-12/FX-12H/FX-12H.1 (`TrendRegime`, ADX classifier). Its only further
item on this roadmap is the regime-conditioned experiment story above,
which depends on strategies and metrics existing first.

Recording this here so the plan survives past this conversation — nothing
in this entry has been implemented yet.

## 2026-09-15 — FX-13: strategy metadata/hypothesis enrichment

First story of the roadmap above, implemented as planned. `TradeHypothesis`
gained four required fields:

- `timeframe: Granularity` — the granularity the signal was generated on.
- `strategy_key: str` — identifies the algorithm (e.g. `"ema_crossover_v1"`
  — the `_v1` is part of the algorithm's own identity).
- `strategy_version: str` — tracks revisions to that algorithm's
  implementation/parameterization independently of `strategy_key`, per
  the decision recorded above.
- `parameters: tuple[tuple[str, str], ...]` — deliberately a tuple of
  string pairs, not a `dict`: a `dict` field would make this frozen
  dataclass unhashable, breaking the pattern every other domain value
  object follows. A `hash()` regression test confirms `TradeHypothesis`
  stays hashable. `params_from_dict` converts a strategy's own typed
  parameters (e.g. `{"fast_period": 20}`) into this shape by
  stringifying each value, so strategies don't hand-write tuple literals.

All four fields are required, no defaults — the entire point of this
enrichment is that no future concrete `Strategy` can omit its own
identity.

**Scope of the breaking change, as anticipated:** exactly 4 test files
constructed `TradeHypothesis` directly (`test_trade_hypothesis.py`,
`test_strategy.py`, `test_backtest.py`, `test_trade_simulation.py`) — no
production code, since no concrete strategy exists yet. All four updated;
all existing tests pass unchanged in behavior, only in construction
syntax.

## 2026-09-15 — FX-14: EMA Trend v1 (`ema_crossover_v1`) — the reference strategy

The first concrete `Strategy`, implemented exactly to spec: 20/50 EMA
crossover on synthetic-midpoint close, no ADX filter, no RSI, no extra
confirmation, no optimization. Lives in
`domain/strategies/ema_crossover.py`, named `ema_crossover_v1` (not
`trend_strategy` — there will be more than one trend strategy).

**Decision: SMA-seeded EMA**, as confirmed before implementing — first
value is the simple average of the first `period` closes, standard
recurrence (`multiplier = 2/(period+1)`) after. Same seeding style as
Wilder's smoothing in ADX (FX-12), chosen specifically so it's
independently verifiable against outside references.

**Verification, same rigor as ADX:** wrote a second, independent
reference implementation of SMA-seeded EMA (float-based scratch script)
against a fixed synthetic price series, confirmed the real `Decimal`
implementation matches it exactly at every step
(`test_ema_matches_independent_reference_calculation`). Then went
further than FX-12's verification did: engineered a full synthetic price
series producing exactly one clean bullish and one clean bearish
crossover at known bars, and traced it through the *entire* real
pipeline — `EmaCrossoverStrategy.evaluate()` directly, then
`run_backtest`, then `simulate_trades` — with hand-computed expected
entry/exit prices and times at each stage. All three levels agreed.

**Decision: crossover, not continuous stance** — fires only on the bar
where `sign(fast_ema - slow_ema)` flips (`previous_diff <= 0 and
current_diff > 0` → LONG; `previous_diff >= 0 and current_diff < 0` →
SHORT), never every bar one EMA simply stays above the other. This is
what pairs correctly with FX-11's close-and-reverse exit rule — a
continuous-stance signal would fire every bar and break that rule's
same-direction-repeat-is-a-no-op logic. Confirmed via the engineered
series: candle-by-candle evaluation returns `None` on every bar except
the two actual crossings.

**Decision: fully stateless** — recomputes the whole EMA sequence from
the given window on every `evaluate()` call, no remembered state between
calls. Doesn't add new asymptotic cost: `run_backtest`'s own reslicing is
already O(n²), so a per-call O(n) EMA recompute doesn't change the
complexity class. Consistent with "correctness over performance for now."

**Decision:** `evaluate()` returns `None` (never raises) with fewer than
`slow_period + 1` candles — the minimum needed for both a current and
previous slow EMA to compare. Different from `classify_regime`, which
raises on insufficient data: a `Strategy` is called by `run_backtest`
starting from window-length 1 and must handle every length gracefully,
not reject short windows.

**Also decided:** constructor validates `fast_period`/`slow_period` with
the same discipline as `classify_regime` (FX-12H.1) — `int`, not `bool`,
`>= 1`, and `fast_period < slow_period`. `strategy_key` is a class-level
constant (identifies the algorithm, independent of instance parameters);
`strategy_version` defaults to `"1"`; `parameters` embeds the actual
periods used via FX-13's `params_from_dict`.

## 2026-09-15 — FX-15: Close-Channel Breakout v1 (`close_channel_breakout_v1`)

The second concrete `Strategy`, implemented per spec: LONG when the
current close exceeds the highest close of the `lookback` (default 20)
bars strictly before it, SHORT when below the lowest. Lives in
`domain/strategies/close_channel_breakout.py`.

**Decision: deliberately close-based, not high/low.** Directly applies
FX-12H's finding forward: our synthetic bid/ask-averaged highs/lows are
an approximation (the two sides' period extrema can occur at different
instants), while bid-close and ask-close are the same instant and
average cleanly. A true high/low Donchian channel becomes testable once
real provider mid OHLC is stored — still deferred.

**Decision: `close_channel_breakout_v1`, not `donchian_breakout_v1`** —
confirmed before implementing. "Donchian" conventionally means high/low
channels; naming this close-based variant something distinct avoids
confusion with the true high/low version planned for later.

**Decision: current bar excluded from its own channel** — confirmed
before implementing. The window is the `lookback` closes strictly before
the current one; the current close is never part of computing the
channel it's tested against (the standard Donchian definition — a bar
can't break out of a channel it contributed to).

**Decision: fires every qualifying bar, not just the breakout moment** —
confirmed before implementing, and a deliberate difference from EMA
crossover. Unlike EMA (which is inherently an edge-detection signal — a
crossing either happened on this bar or it didn't), "current close vs.
rolling max/min" is re-evaluated fresh each bar with no edge-detection
concept in the spec, so re-firing while price stays beyond the channel
is the literal, correct behavior, not an oversight. No duplicate-position
risk: FX-11's same-direction-repeat-is-a-no-op already absorbs this
safely — verified directly in the integration test (a repeat LONG and a
repeat SHORT both appear in `run_backtest`'s output, and `simulate_trades`
correctly produces only 2 trades from the 4 hypotheses, not 4).

**Verification, same standard as EMA:** hand-traced an engineered price
series through `evaluate()` directly, then `run_backtest`, then
`simulate_trades`, with hand-computed expected prices at each stage —
including an edge case the trace surfaced: when a position enters on the
series' second-to-last bar's signal and there are no further hypotheses,
the resulting execution candle (the last one) is also the candle used for
the end-of-dataset force-close, so `entry_time == exit_time` on that
trade. Confirmed this is correct, expected behavior (SimulatedTrade's own
validation already permits equal entry/exit time), not a bug.

**Also decided:** constructor validates `lookback` with the same
discipline as every other parameterized indicator in this codebase now
(`classify_regime`, `EmaCrossoverStrategy`) — `int`, not `bool`, `>= 1`.

## 2026-09-15 — FX-16: Time-Series Momentum v1 (`time_series_momentum_v1`)

The third concrete `Strategy`, deliberately minimal per the roadmap: just
`return = current_close / close_N_bars_ago - 1` against a threshold — not
RSI+MACD+ROC+stochastic combined into one "momentum" strategy, where
nothing would be attributable. Lives in
`domain/strategies/time_series_momentum.py`.

**Decision: single symmetric `threshold: Decimal`**, not independent
positive/negative thresholds — confirmed before implementing. LONG if
`return > threshold`, SHORT if `return < -threshold`. Default
`Decimal("0")` is the pure baseline, exactly as specified; a later
deadband is just `threshold > 0`, no constructor shape change needed.
`threshold` is `Decimal`, validated `>= 0` — same "never use float"
discipline as every other threshold in this codebase (`classify_regime`'s
ADX threshold).

**Decision: fires every qualifying bar**, same precedent set by FX-15's
close-channel breakout and for the identical reason — "current return vs.
threshold" has no edge-detection concept in its definition, re-evaluated
fresh each bar, and FX-11's same-direction-repeat-is-a-no-op already
makes repeated firing architecturally safe.

**Verification:** no recursive-smoothing risk here (a plain ratio, unlike
EMA/ADX), so the independent-reference-implementation step wasn't needed
— but the same hand-tracing discipline was applied: an engineered price
series run through `evaluate()` directly, then `run_backtest`, then
`simulate_trades`, with hand-computed expected values at every stage.
This time the trace *naturally* produced an instance of FX-11H's
final-bar-not-actionable rule (the series' last hypothesis happened to
land on the final candle) rather than needing one specifically
engineered for it, as FX-15's edge case did — a good sign the rule
behaves correctly on realistic, not just contrived, data. Also verified
against live OANDA practice candles.

## 2026-09-15 — FX-17: backtest performance metrics

The scoreboard, sequenced deliberately before more strategies pile up
with no way to compare them, per the roadmap. `compute_metrics(trades:
list[SimulatedTrade]) -> BacktestMetrics` in `domain/backtest_metrics.py`.

**Decision: composable, not a grouping engine** — confirmed before
implementing. `compute_metrics` takes any `list[SimulatedTrade]` and
reports full stats for exactly that list; it has no concept of
instruments, timeframes, or regimes. "Long vs short" is filtering by
`side` and calling twice; the later regime-conditioned-experiments story
(FX-21) will filter by an external `classify_regime` result and call
twice, needing zero changes to this function. Verified directly: a test
computes metrics on a full trade list and again on a `side`-filtered
subset, confirming the pattern works as intended.

**Decision: Sharpe/Sortino included, explicitly not annualized
percentage-return ratios** — confirmed before implementing.
`SimulatedTrade.pnl` is per-unit notional (no position sizing exists
yet — FX-11's own decision entry), and trades occur at irregular
intervals with no clean annualization period, so a textbook Sharpe ratio
isn't achievable honestly right now. Computed instead as
`mean(trade P&L) / sample_stdev(trade P&L)` (Sharpe) and `mean(trade
P&L) / downside_deviation(trade P&L)` (Sortino, using 0 as the minimum
acceptable return) — same formula shape as the real thing, loudly
documented as a *relative* comparison tool between strategies on the same
instrument/timeframe, not a directly-comparable industry figure. `None`
when undefined: Sharpe needs ≥ 2 trades and nonzero variance; Sortino
needs nonzero downside deviation (mathematically well-defined even at a
single trade, an intentional asymmetry from Sharpe's ≥2 requirement, not
an inconsistency — documented in the docstring).

**Decision: `profit_factor` is `None`, not `Decimal('Infinity')`, when
there are no losing trades** — confirmed before implementing, matching
this codebase's established preference for explicit `None`/raise over
sentinel values.

**Also decided:** `total_pnl`/`average_win`/`average_loss`/`expectancy`/
`max_drawdown` are `Money` (currency-carrying); `win_rate`/
`profit_factor`/`sharpe`/`sortino` are plain `Decimal` (genuinely
unitless ratios). `compute_metrics` raises on an empty trade list (a
report on zero trades is meaningless, not a valid degenerate case) and on
mixed-currency trades — discovered during testing that `SimulatedTrade`
itself already enforces `pnl.currency == instrument.quote_currency`, so a
mixed-currency scenario can only legitimately arise from trades on
*different* instruments, not a single instrument with an inconsistent
currency; the test was adjusted to reflect that, not the implementation.

**Verification:** same rigor as ADX/EMA — an independent reference
calculation (Sharpe, Sortino, max drawdown, and every other field) on a
fixed hand-picked trade set, cross-checked against the real
implementation.

## 2026-09-15 — FX-18: TargetPosition/FLAT semantics

Prerequisite for Mean Reversion v1, per the roadmap — every strategy so
far can only say LONG or SHORT, with no way to express "go flat" as a
real signal. `TradeHypothesis.side: TradeSide` is renamed and retyped to
`target_position: TargetPosition`, a new enum in `domain/
target_position.py`.

**Decision: a new, separate enum, not a third value bolted onto
`TradeSide`** — confirmed before implementing. `TradeSide` (LONG/SHORT)
stays execution-only: `Price.entry_price`/`exit_price`, `SimulatedTrade`,
and `_OpenPosition` all keep using it unchanged, because a trade or an
open position is always LONG or SHORT and never FLAT — FLAT is the
*absence* of a position (`open_position = None`), not a new state those
types need to represent. `TargetPosition` (LONG/SHORT/FLAT) instead
belongs on `TradeHypothesis`, where it describes what a strategy *wants*
without giving it execution authority — CLAUDE.md's hypothesis -> risk
decision -> execution intent -> order pipeline is unaffected; this is
still only the first stage.

**Decision: full rename, not an added field** — `TradeHypothesis.side`
no longer exists; every hypothesis now carries `target_position`. Kept
side-by-side would have let old and new code disagree about which field
was authoritative; a hard rename forces every call site to make the
FLAT/LONG/SHORT distinction explicit up front. All three existing
strategies (`ema_crossover_v1`, `close_channel_breakout_v1`,
`time_series_momentum_v1`) were mechanically updated to construct
`target_position=TargetPosition.LONG/SHORT` — no behavioral change; none
of them emit FLAT yet. Mean Reversion v1 will be the first strategy to
actually use it.

**Decision: `simulate_trades` gains a third behavior for FLAT**,
alongside the existing two (same-direction no-op, opposite-direction
close-and-reverse): with no open position, FLAT is a no-op; with an open
position, FLAT closes it — same next-bar-open execution price as
everything else — and does **not** reopen. A later LONG/SHORT hypothesis
after a FLAT close opens a genuinely fresh position, exactly as it would
from a flat start. `run_backtest`, `SimulatedTrade`, `_OpenPosition`, and
`backtest_metrics.py` needed no changes — none of them reference
`TradeHypothesis.side`/`target_position` directly.

**Verification:** exhaustively grepped every `TradeHypothesis(`
construction site and every `.side` access before implementing, to state
the exact breaking-change footprint up front (6 source files, 10 test
files, mechanical rename) and confirm nothing was missed — including
checking the three live OANDA integration tests, which turned out not to
reference `.side` at all. New tests cover all three FLAT interactions
directly: no-op while already flat, close-without-reopen, FLAT as the
very first hypothesis, a fresh LONG open after a FLAT close, repeated
FLAT while already flat, and a FLAT close on a SHORT position exiting at
ask (not bid) — confirming CLAUDE.md's bid/ask-per-side rule still holds
through the new code path. Full suite (379 tests, including the three
live-OANDA strategy integration tests) passed; contract boundary tests
picked up `target_position.py` automatically and confirmed it has zero
forbidden imports and no env-var reads.

## 2026-09-15 — FX-19: Mean Reversion v1

The fourth concrete strategy (`domain/strategies/mean_reversion.py`,
`strategy_key="mean_reversion_v1"`), and the first to actually emit
`TargetPosition.FLAT` (FX-18) rather than just being renamed to carry
it. Bollinger-Bands-style z-score: LONG when the current close is
`entry_threshold` population standard deviations below its own
`period`-bar rolling mean (oversold), SHORT when that far above
(overbought), FLAT when the z-score crosses back through zero.

**Decision: the rolling window includes the current bar** — confirmed
before implementing (not FX-15's close-channel precedent of excluding
it). This is the standard Bollinger Bands definition, at the cost of a
known, accepted property of real Bollinger trading: an extreme move
slightly inflates the very standard deviation used to judge it
(self-referential dampening). Deliberately not treated as a defect.

**Decision: FLAT exit is zero-crossing detection, not a deadband** —
confirmed before implementing. The roadmap specified "exit z=0.0";
since a `Decimal` z-score will essentially never equal exactly 0, this
is implemented the same way as FX-14's EMA crossover (compare the
current bar's z-score against the previous bar's, fire on a sign flip or
exact zero) rather than introducing a made-up `exit_threshold` deadband
parameter. This delivers the literal spec, not an approximation of it,
and needed no new parameter. Entry always takes priority: the extreme
checks run before the crossing check, so a bar that's both extreme and
technically crossing is treated as a new entry, not a flat.

**Also decided:** standard deviation is *population* (divide by
`period`, not `period - 1`) — the conventional Bollinger definition,
computed with `Decimal.sqrt()` (same technique as `backtest_metrics.py`'s
Sharpe/Sortino). `period` must be `>= 2` (not `>= 1` like other
strategies' lookback parameters) — a 1-bar window has zero variance by
construction, so `period=1` would silently never fire; validated
explicitly rather than left to produce a confusing always-`None`
strategy. A zero-variance window (current or previous) suppresses the
corresponding z-score computation (`None`) rather than dividing by zero.

**Verification:** no seeded recurrence here (unlike EMA/ADX), but the
window-inclusion decision above makes the arithmetic collaborative
across the whole window rather than a simple ratio, so the same
hand-derivation discipline was applied as everywhere else: an
independently hand-derived synthetic series (period=5, a single +5/-5
spike against a flat 100-baseline, chosen so the population z-score
comes out to exact clean values — 2, -0.5, None, -2, 0.5 — at every
relevant bar, verified with a standalone scratch calculation before
writing the real implementation) exercises LONG entry, SHORT entry, a
genuine zero-crossing FLAT after each, and a "hold" bar where nothing
fires. The same series was then traced through `run_backtest` +
`simulate_trades`, confirming FX-18's FLAT-closes-without-reopening
behavior end to end (4 hypotheses produce only 2 trades). Also verified
against live OANDA practice candles.

## 2026-09-15 — FX-20: Volatility Expansion Breakout v1

The fifth concrete strategy (`domain/strategies/volatility_expansion.py`,
`strategy_key="volatility_expansion_breakout_v1"`). LONG/SHORT when the
current close breaks a Donchian high/low channel *and* the short-period/
long-period ATR ratio is at least `expansion_threshold`; FLAT when the
expansion itself ends. A breakout with no volatility expansion behind it
is not traded, and an expansion with no fresh breakout doesn't open
anything either — both filters are required, not either alone.

**Decision: the Donchian channel is built from actual highs/lows, not
FX-15's close-based channel** — confirmed before implementing, and a
reversal of FX-15's own reasoning. ATR already requires and accepts the
synthetic-midpoint-averaged highs/lows for True Range (FX-12H's
caveat), so using those same highs/lows for the breakout range is
consistent with an already-accepted trade-off, not a new one — and
"range breakout" is conventionally a high/low Donchian definition in
technical analysis, which FX-15's close-based channel deliberately
wasn't (it had no other reason to touch highs/lows at all). The
triggering price stays the current bar's *close* against that channel,
not the current high/low — keeps the trigger on the same close-based
footing as every other strategy; only the reference channel changed.

**Decision: FLAT exit reuses `expansion_threshold` itself as the
crossing boundary** — confirmed before implementing, same reasoning as
FX-19's zero-crossing exit: the previous bar's ratio was `>=
expansion_threshold` and the current bar's isn't, i.e. the expansion
that justified entry has literally ended. No separate `exit_threshold`
parameter, avoiding an arbitrary second default value. Entry always
takes priority structurally (the contraction check only runs when the
current ratio is *not* `>= expansion_threshold`, so there's no
overlapping-priority question to resolve, unlike FX-19 where both
checks could theoretically be reached the same bar).

**Also decided:** `expansion_threshold` must be `> 1`, not merely `>= 0`
— a ratio at or below 1.0 isn't expansion at all (short-term vol at/below
the long-term baseline), so `1.0` is rejected as a meaningless threshold
for this parameter specifically, not just a degenerate one.
`short_period < long_period` is required (same shape as FX-14's
`fast_period < slow_period`). True Range/Wilder-smoothing logic is
**duplicated locally**, not extracted from `regime_detection.py` into a
shared helper — matches every other strategy file's established
self-containment (none of the four prior strategies share their own
synthetic-midpoint-close one-liner either). Flagged here as a
deliberate, revisit-if-a-third-consumer-appears deferral, not an
oversight — `regime_detection.py`'s ADX only needs an internal
unscaled running-sum form of smoothed TR for its DI ratio (the
period-scaling cancels out), while this strategy needs the actual
divided-through ATR average reported per bar, so the two aren't even
quite the same shape without some rework either way.

**Verification:** an independently hand-derived synthetic candle series
(a quiet high=101/low=100/close=100.5 baseline with two wide single-bar
bursts — one up, one down — and one moderate bar that breaks the
channel without enough range to trigger expansion) computed via a
standalone scratch script before writing the real implementation,
covering all five `evaluate()` outcomes: LONG (breakout + expansion),
SHORT (breakdown + expansion), FLAT on contraction after each, a
"breakout without expansion" no-op, and an "expansion without a fresh
breakout" no-op. Same series then traced through `run_backtest` +
`simulate_trades`, confirming FLAT-closes-without-reopening end to end
(4 hypotheses produce only 2 trades). Also verified against live OANDA
practice candles.

## 2026-09-15 — FX-21: regime-conditioned experiment (EMA vs. EMA-when-TRENDING)

Connects `classify_regime` (FX-12) and `compute_metrics` (FX-17) for the
first time via a new `domain/regime_segmentation.py`:
`segment_trades_by_regime(trades, candles, *, period=14,
threshold=Decimal("25")) -> RegimeSegmentedTrades` (`.trending`/
`.ranging`/`.unclassified`, each `list[SimulatedTrade]`). No strategy
was modified; regime stays structurally external, exactly as decided
when regime detection was first built.

**Decision: control strategies stay a separate, later story** —
confirmed before implementing. This story answers "does regime
filtering change EMA's own metrics", which is meaningful without a
no-skill baseline; comparing against control strategies (always-long,
always-short, previous-bar-direction, no-trade) is a different question,
still flagged and undated.

**Decision: EMA-vs-TRENDING only, not also Mean-Reversion-vs-RANGING in
the same story** — confirmed before implementing, matching the
established one-strategy(-or-one-comparison)-per-story precedent. The
segmentation helper this story built is generic, so the Mean-Reversion/
RANGING follow-up needs no new infrastructure when picked up.

**Decision: a trade with insufficient preceding history (`< 2 * period`
candles at its `entry_time`) is `unclassified`, not an error** — the
normal case for early trades in any backtest. A trade whose
`instrument` or `entry_time` doesn't match the candle series *does*
raise — a mismatched pairing is caller error, same defensive philosophy
as `simulate_trades` (FX-11H).

**Decision: the live replay test (`tests/replay/test_ema_regime_
conditioned.py`) asserts only structural properties** (every trade
lands in exactly one bucket, `compute_metrics` doesn't raise on any
non-empty bucket) — never that one bucket's metrics "beat" another's.
Asserting a specific winner in a hard-coded test would be dishonest
against non-reproducible live market data; the actual empirical
question this story exists to answer is reported here, as data, not
baked into a pass/fail assertion.

**The empirical finding** (observed 2026-09-15, EUR/USD H1, default
`EmaCrossoverStrategy()` 20/50 EMA, default `classify_regime` period=14/
threshold=25, ~90 days / 1536 finalized candles):

| | n | win rate | expectancy | profit factor | Sharpe |
|---|---|---|---|---|---|
| Baseline (all trades) | 26 | 0.192 | -0.00029 USD | 0.838 | -0.060 |
| TRENDING-only | 10 | 0.100 | -0.00232 USD | 0.003 | -1.710 |
| RANGING-only | 16 | 0.250 | +0.00099 USD | 1.688 | +0.174 |

On this sample, filtering EMA's trades down to `TRENDING` did **not**
help — it made every metric measured worse than both the unconditional
baseline and the `RANGING`-only subset, which was the only one of the
three with positive expectancy. This is the opposite of the naive
"trend-following strategy should do better in a trending regime"
intuition the roadmap set out to test.

Read with real caution, not as a settled conclusion: `n=26` total
(`n=10` TRENDING) is far too small a sample to be statistically
meaningful either way — this is one 90-day window on one instrument at
one granularity, with the reference `EmaCrossoverStrategy()`
unmodified. What it *does* establish is exactly what this story set out
to establish: regime-conditioning is not a free win that can be assumed
into a strategy — on this sample it was actively counterproductive, so
keeping it structurally separate and testing it as a hypothesis (not
baking it into `EmaCrossoverStrategy` itself) was the right call. Worth
re-running with more history once candle-backfill pagination exists
(flagged in FX-13's roadmap entry) before drawing any firmer conclusion.

**Verification:** the segmentation helper reuses FX-12's own already-
verified trending/ranging fixtures directly (steadily increasing prices,
perfectly flat prices) rather than re-deriving ADX arithmetic — its job
is bucketing, not classification. Full suite (439 tests) passed,
including the new replay test against live OANDA data (the run that
produced the table above).

## 2026-09-15 — FX-21H: fixed regime look-ahead; corrected FX-21 framing

**Correction, not a silent edit — the table and framing above are
superseded by a confirmed bug**, caught by external review.
`segment_trades_by_regime` classified each trade using
`candles[:entry_index + 1]`, which includes the entry candle's own
high/low/close. Per FX-11H, a trade executes at its entry candle's
*open* — its high/low/close aren't known yet at that instant. This is
the exact class of look-ahead bug FX-11H fixed in `simulate_trades`
itself, just recurring one layer up in a story built on top of it.
Fixed to `candles[:entry_index]`: only candles fully completed strictly
before entry.

**Also corrected: FX-21's own framing overstated what it built.** What
exists is entry-regime *attribution* — EMA runs unconditionally, trades
are labeled by regime after the fact for comparison. It is not
regime-*gating* (an entry filter that would change which trades occur
at all). The distinction matters most at a reversal: if `TRENDING` were
a real entry filter and EMA produces a SHORT signal while LONG and the
regime is `RANGING`, should the position close to FLAT, get ignored
(stay LONG), or reverse anyway despite the filter? All three are
defensible; none is implemented. **True regime-gating is recorded here
as a distinct, unbuilt, undated future experiment** — not a rename of
FX-21, not a trivial follow-up. `docs/CURRENT_STATE.md`/`NEXT_STEPS.md`
updated to use "entry-regime attribution" throughout.

**New regression test**
(`test_entry_candles_own_ohlc_does_not_affect_classification`, FX-21H):
a choppy 29-bar `RANGING` prefix (ADX ~3.53) with a dramatically
mutated 30th (entry) bar, and a `threshold` chosen so that *including*
that mutated bar would tip ADX to ~8.00 — crossing into `TRENDING`.
Confirmed by temporarily reverting the fix that this test fails against
the old code and passes against the new — a real regression test, not
just a plausible-looking one.

**Rerun finding:** rerunning the live experiment after the fix
(EUR/USD H1, same ~90-day window shape, default `EmaCrossoverStrategy()`)
produced bucket counts identical to the original run
(`trending=10, ranging=16, unclassified=0`) and metrics differing only
in the last few decimal places (a different live data window, one hour
later than the original run — not the bug). For this specific sample,
no trade's regime label was close enough to the ADX threshold boundary
for the one extra (entry) candle to have flipped it. That does **not**
excuse the bug — the targeted regression test above proves it was real
and is now fixed — it just means this particular 90-day EUR/USD H1
sample happened not to be sensitive to it. The qualitative conclusion
from FX-21 stands, now on corrected machinery: `TRENDING`-only
performed worse than both baseline and `RANGING`-only, `n=26` is still
too small to be conclusive, and this is worth rerunning with more
history once candle-backfill pagination exists.

**Verification:** full suite (440 tests, one new regression test) and
the live replay test all passed.

## 2026-09-15 — FX-21H.1: strategy-suite hardening batch

Three small, independent validation gaps flagged by the same external
review that produced FX-21H — bundled into one story since none is
individually large enough to warrant its own (same precedent as FX-11H
bundling multiple validation additions across `run_backtest` and
`find_gaps`).

**1. `run_backtest` now validates `hypothesis.timeframe` against the
candle series' granularity**, alongside its existing instrument/
`generated_at` checks. `TradeHypothesis.timeframe` (FX-13) was
provenance in name only until now — a strategy claiming `H4` while
being fed `M1` candles previously passed through undetected.

**2. `MeanReversionStrategy.entry_threshold` must be `> 0`, not `>=
0`.** At `0`, `current_z <= -0` and `current_z >= 0` jointly cover the
entire real line, making the FLAT zero-crossing branch (the whole
reason this strategy exists — see FX-19) unreachable dead code. No
existing test exercised `entry_threshold=0`, so nothing else changed.

**3. `compute_metrics` now requires one `instrument`, not just one P&L
currency.** `Instrument` is a plain value type and `SimulatedTrade`
already enforces `pnl.currency == instrument.quote_currency`, so
requiring one instrument is strictly *stronger* than requiring one
currency (same instrument implies same currency, always) — the old
currency-only check is replaced, not kept alongside, since it would
otherwise be provably unreachable dead code once the instrument check
exists. Closes a real gap: `EUR_USD` and `GBP_USD` (both USD-quoted)
previously passed the currency check despite being genuinely different,
non-comparable per-unit-notional instruments. FX-17's own existing
mixed-currency test (`GBP_EUR` + `EUR_USD`) still raises, now on
"instrument" (checked first, since that scenario differs in both) —
renamed rather than left asserting a message that's no longer the
actual first reason for rejection; a new test isolates the
previously-unguarded same-currency/different-instrument case
(`EUR_USD` + `GBP_USD`).

**Verification:** 3 new/updated tests (443 total, up from 440), each
new fix verified to have 100% branch coverage from its own test.
Full suite, live integration tests, and pre-commit all passed.

## 2026-09-15 — FX-22: control strategies

**Renumbering note:** the external review that produced FX-21H/FX-21H.1
proposed calling the candle-alignment story `FX-22` and multi-timeframe
`FX-23`. Renumbered sequentially instead, matching this project's
existing convention of FX-N always reflecting actual build order:
control strategies is `FX-22`, Mean-Reversion-vs-RANGING attribution
(next) is `FX-23`, candle alignment becomes `FX-24`, multi-timeframe
becomes `FX-25`.

Four minimal `Strategy` implementations in one file,
`domain/strategies/control.py` — `AlwaysLongStrategy`
(`always_long_v1`), `AlwaysShortStrategy` (`always_short_v1`),
`PreviousBarDirectionStrategy` (`previous_bar_direction_v1`),
`NoTradeStrategy` (`no_trade_v1`). Not trading ideas: a no-skill
scoreboard every real strategy's `compute_metrics` output should be
compared against on the same sample, per the roadmap's own original
flag — without them, a modestly positive Sharpe can't be distinguished
from sample drift.

**Decision: one file, not four** — a deliberate departure from every
prior strategy's one-file-per-strategy convention (EMA, close-channel,
momentum, mean reversion, volatility expansion each got their own
file). These four are explicitly a matched baseline *set*, not
independently evolving trading ideas, and each is only a few lines;
grouping them keeps the shared rationale in one place instead of
repeated four times.

**Decision: always-long/always-short are genuine buy-and-hold
baselines, not degenerate repeated no-ops** — confirmed via
`run_backtest` + `simulate_trades`, not assumed: firing the same
direction every single bar combines with FX-11's existing same-
direction-no-op rule to open exactly one position that holds to the
end of the dataset (verified: 5 identical-direction hypotheses produce
exactly 1 trade). This is what makes them useful baselines — a
strategy that can't beat trivially holding a directional bet the whole
period isn't adding value.

**Decision: `PreviousBarDirectionStrategy` has no lookback or
threshold** — deliberately distinct from `TimeSeriesMomentumStrategy`
(FX-16), which already occupies the "N-bar return vs. threshold" design
space. This is the simplest possible directional baseline: did the
last completed bar close up or down. Verified through the full pipeline
on an engineered up/down/up/down/flat series, producing the expected
4-trade flip-flop sequence with hand-traced execution prices.

**Decision: `NoTradeStrategy` always returns `None`, and
`compute_metrics` can't even be called on its output** (it raises on
an empty trade list, per FX-17) — deliberately not special-cased to
report zero metrics. A real strategy must clear that bar (produce at
least one trade) just to be comparable at all; that friction is itself
part of the baseline's value, not a gap to paper over.

**Verification:** one consolidated live integration test
(`tests/integration/test_control_strategies_live.py`) covering all
four against real OANDA candles, rather than four near-duplicate live
files — none of the four have numerical logic worth a dedicated
live-data check beyond confirming they run cleanly and produce
well-formed output. Full suite (459 tests) passed.

## 2026-09-15 — FX-23: Mean-Reversion-vs-RANGING entry-regime attribution

The roadmap's other named example, now that `segment_trades_by_regime`
(FX-21, look-ahead fixed FX-21H) exists. No new domain code — reuses
the same infrastructure FX-21 built, swapping `EmaCrossoverStrategy`/
`TRENDING` for `MeanReversionStrategy`/`RANGING`. New
`tests/replay/test_mean_reversion_regime_conditioned.py`, structurally
identical to FX-21's own replay test (including the same entry-regime-
*attribution*, not gating, framing, stated explicitly in its docstring
this time rather than needing a correction afterward).

**The empirical finding** (observed 2026-09-15, EUR/USD H1, default
`MeanReversionStrategy()` period=20/entry_threshold=2.0, default
`classify_regime` period=14/threshold=25, same ~90-day / 1536-candle
window as FX-21's EMA experiment):

| | n | win rate | expectancy | profit factor | Sharpe |
|---|---|---|---|---|---|
| Baseline (all trades) | 57 | 0.649 | -0.000008 USD | 0.990 | -0.003 |
| TRENDING-only | 20 | 0.700 | +0.000904 USD | 4.490 | +0.598 |
| RANGING-only | 37 | 0.622 | -0.000501 USD | 0.567 | -0.182 |

On this sample, filtering Mean Reversion's trades down to `RANGING` —
the regime it's naively expected to work best in — made things **worse**
on every metric, while `TRENDING`-only was the standout performer
(profit factor 4.49, the best number any strategy has produced in
either regime experiment so far). This is the same shape of surprise as
FX-21's EMA finding, just inverted: both experiments now show the
"obvious" regime pairing underperforming the "wrong" one on their
respective samples.

Same caution as FX-21: `n=57` (`n=37` RANGING, `n=20` TRENDING) is a
larger sample than FX-21's `n=26` but still one 90-day window on one
instrument/granularity — not a basis for strategy-selection decisions.
Taken together, though, two independent experiments now agree that the
naive "strategy type should match regime type" intuition does not hold
on the data observed so far, which is exactly the kind of finding that
justifies keeping regime structurally external (FX-EPIC-05's original
design decision) rather than hard-coding a regime filter into either
strategy. Worth revisiting with more history once candle-backfill
pagination exists, and worth keeping in mind before any future strategy
bakes in a "should trade better in regime X" assumption without testing
it the same way.

**Verification:** full suite (460 tests) and the live replay test both
passed.

## 2026-09-15 — FX-24: candle alignment / OANDA H4 reconciliation

`aggregate_candles`'s bucket boundaries were pure epoch-UTC floor since
FX-7 — never reconciled against what OANDA's own day-aligned candles
actually align to, flagged as a known gap since FX-13's roadmap entry.
Flagged again, with much sharper detail, by the same external review
that produced FX-21H: OANDA's own documented granularity semantics say
`H1` is hour-aligned but `H2`/`H3`/`H4`/`H6`/`H8`/`H12`/`D` are
day-aligned to a 17:00 `America/New_York` anchor, which — being a
calendar concept, not a fixed duration — shifts in UTC terms across DST.

**Empirically verified against the live practice API before writing any
code, not assumed:**
- Fetched live `H4` candles: boundaries at `09:00`/`13:00`/`17:00` UTC
  on 2026-09-11 (EDT, UTC-4 — `17:00 EDT = 21:00 UTC`), with the day
  restarting at `21:00` UTC after the weekend gap. Fetched live `D`
  candles: daily boundary at `21:00` UTC, same anchor. Neither matches
  epoch-UTC-floored buckets (`00:00`/`04:00`/`08:00`/... for `H4`).
- Fetched with explicit `dailyAlignment=17`/`alignmentTimezone=
  America/New_York` vs. omitting them entirely: byte-identical
  responses — the practice API's default already matches. Sent
  explicitly anyway (confirmed live, not just in theory) so this
  codebase's own correctness doesn't silently depend on that default
  never changing.
- Fetched live `H4` candles spanning the actual 2026-03-08 US
  spring-forward transition: the transition (2am local, Sunday) falls
  entirely inside forex's weekend closure, so real OANDA data never
  actually contains a "3-hour" or "5-hour" H4 bucket. The underlying
  wall-clock arithmetic still has to be correct for that case though —
  a general-purpose aggregator can't assume "the market happens to be
  closed then" as an invariant.
- Independently derived the DST-aware bucket arithmetic with a scratch
  `zoneinfo` script *before* writing the real implementation, same
  discipline as every recursive/calendar calculation in this codebase:
  confirmed adding `timedelta(hours=4)` to an `America/New_York`-aware
  `datetime` correctly produces one 3-hour bucket on the spring-forward
  day and one 5-hour bucket on the fall-back day (PEP 495 wall-clock
  semantics), every other bucket a clean 4 hours.

**Decision: `H1` and finer are unaffected, unchanged** — confirmed
before implementing. `America/New_York`'s UTC offset is always a whole
number of hours, so an hour boundary is the same instant regardless of
which timezone names it; epoch-floored hour buckets already agree with
NY-local hour buckets. Only day-aligned granularities needed a new
bucketing path.

**Decision: a day-aligned bucket's expected member count is computed
per bucket from its own real elapsed time, not a single fixed
constant** — discovered while designing the DST test, not initially
planned. A bucket containing a DST transition genuinely spans 3 or 5
real hours; using a fixed `target_duration // source_duration` count
(the pre-existing scheme, still correct for non-day-aligned targets)
would incorrectly judge that bucket "incomplete" and silently drop
otherwise-valid data. `_expected_member_count` computes each bucket's
real span via the same `zoneinfo`-aware arithmetic used to find the
bucket itself.

**Decision: `CandleSource` (`NATIVE`/`AGGREGATED`) added to `Candle` as
a *defaulted* field (`= CandleSource.NATIVE`), not required** —
confirmed before implementing. A required field would have forced a
mechanical rename across every test file that constructs a `Candle`
without caring about provenance (dozens of them, by this point in the
project). Defaulting to `NATIVE` keeps that entire surface untouched;
only `aggregate_candles` (sets `AGGREGATED` explicitly) and the OANDA
adapter (sets `NATIVE` explicitly, for clarity even though it's already
the default) needed to change.

**Decision: `source` is part of the DB unique constraint** (now
`instrument`/`granularity`/`start_time`/`source`, was missing `source`)
— this is the actual "prevent native and derived H4 candles from
silently occupying the same logical dataset" fix, structural rather
than conventional: a native and a self-aggregated candle for the same
logical slot can now coexist in storage without colliding in an
upsert. New Alembic migration; no backfill needed (nothing has
persisted H2+ candles yet — `AggregateCandles` still isn't invoked on
any schedule).

**Decision: `aggregate_candles` itself now also rejects a mix of
`NATIVE` and `AGGREGATED` source candles** (alongside its existing
instrument/granularity consistency checks) — found while reasoning
through `AggregateCandles`' own `get_range` call, which doesn't filter
by `source`. Without this, a future scenario with both native and
aggregated candles stored at the same source granularity could get
silently blended by `aggregate_candles` itself, one layer earlier than
the storage-level fix above catches. A `get_range` filter parameter
was deliberately *not* added — nothing needs it yet (FX-25 is still
unbuilt), and this validation already converts silent blending into a
loud error, which is the actual safety property needed now.

**Verification:** the day-alignment logic is tested against the
exact live-fetched OANDA boundary times above (a golden-data-style
regression, not just a qualitative check), an EST (winter) case, a
plain `D`-granularity case, `H1`-still-unaffected regression, and two
synthetic continuous-data DST tests (spring-forward's 3-hour bucket,
fall-back's 5-hour bucket) each proving both that the short/long bucket
is correctly treated as *complete*, and that it's correctly dropped if
genuinely short by even one candle. `CandleSource` round-trips through
`aggregate_candles`, the OANDA adapter, and a live-Postgres DB test
proving native/aggregated coexistence without collision. Full suite
(474 tests) and live integration tests (OANDA + Postgres) all passed.

## 2026-09-15 — FX-25: Multi-timeframe Trend Confirmation v1

The last item on the original strategy-suite roadmap (`docs/DECISIONS.md`,
2026-09-15's original entry), deliberately sequenced last and blocked
on FX-24. `MultiTimeframeTrendStrategy`
(`domain/strategies/multi_timeframe_trend.py`,
`strategy_key="multi_timeframe_trend_v1"`): an H1 EMA-crossover entry
signal, gated by H4's own EMA fast/slow *state*.

**Decision: architectural note, not a silent redesign** — the first
strategy needing two candle series. `Strategy.evaluate(candles:
list[Candle])`'s signature is unchanged for every strategy, including
this one; the full H4 series is a **constructor** argument (legitimate
for backtesting, which always operates over already-fetched historical
data), and `evaluate()` internally filters it, every call, to only H4
bars fully closed strictly before the current H1 bar's `start_time`.
Confirmed H4 boundaries always land exactly on H1 boundaries (both
whole-UTC-hour quantized, post-FX-24), so `h4_start + 4h <=
h1_current_start` is exactly the right cutoff.

**Decision: H4 confirmation is the EMA relationship's current *state*,
not a crossover *event*** — confirmed before implementing (AskUserQuestion).
Reuses this codebase's own reference trend indicator (FX-14) rather than
introducing a second indicator family (e.g. ADX +DI/-DI direction) purely
for confirmation.

**Decision: disagreement closes to FLAT, not ignored** — confirmed
before implementing, resolving the reversal-vs-FLAT design question
FX-21H's own entry explicitly flagged as unresolved. Because EMA
crossovers structurally alternate direction, a disagreeing new H1
signal is always opposite to whatever's currently open — so
unconditional `FLAT` (FX-18) closes an opposing confirmed position and
no-ops if already flat, with no same-direction case to special-case.
Insufficient H4 history and a `NEUTRAL` H4 state (fast == slow exactly)
are both treated identically to disagreement — unconfirmed is
unconfirmed, not a distinct third case.

**Verification:** a hand-derived synchronized H1+H4 series (worked out
via a scratch script before implementing, same discipline as every
strategy needing coordinated multi-part synthetic data) exercising all
four outcomes — confirmed LONG, unconfirmed SHORT→FLAT, confirmed LONG
again, confirmed SHORT once H4 flips bearish — through `evaluate()`
directly and then through `run_backtest` + `simulate_trades` (4
hypotheses producing 3 trades, confirming FLAT-closes-without-reopening
end to end). A dedicated look-ahead regression
(`test_h4_candles_not_yet_closed_are_not_visible`) mutates only an
H4 bar not yet closed as of the decision bar and confirms the outcome
is unaffected — confirmed by temporarily weakening the visibility
filter and observing the test fail, same proof-of-regression discipline
as FX-21H's own look-ahead fix. Also verified against live OANDA
practice candles at both granularities simultaneously. Full suite (496
tests) passed.

This closes out the original diversity-first strategy-suite roadmap
recorded in this file's 2026-09-15 entry: six directional strategies
(EMA, close-channel breakout, time-series momentum, mean reversion,
volatility expansion, multi-timeframe trend), `TargetPosition`/FLAT
semantics, backtest metrics, control strategies, two entry-regime-
attribution experiments, and candle alignment all complete. Remaining
flagged, undated follow-ups: true regime-*gating* as a general concept
(FX-25 is one concrete instance of it; a generalized version is still
unbuilt), candle-backfill pagination, and the H4-alignment fix's own
`get_range` source-filter ergonomics (not needed by anything built yet).

## 2026-09-15 — FX-25H: canonical candle boundary hardening

External review of FX-24/FX-25 caught two real, confirmed correctness
bugs and one design gap — verified directly against computed boundaries
before implementing, same discipline as every prior DST fix.

**Bug 1 (confirmed): FX-25 reimplemented H4 duration and got it wrong.**
`MultiTimeframeTrendStrategy`'s H4 visibility filter used a fixed
`start + 4h` assumption instead of FX-24's own DST-aware boundary logic
— two independent interpretations of "how long is an H4 candle" existing
side by side, one of them wrong. Verified: an H4 candle starting
2026-11-01T05:00Z (fall-back day) actually closes at 10:00Z (5 real
hours), not the assumed 09:00Z — at 09:00Z, the old code would have
treated that candle as already visible, a real look-ahead.

**Bug 2 (confirmed): FX-24's own completeness check breaks when the
SOURCE granularity is itself day-aligned.** `real_span // source_
duration` assumed the source candle's own duration is fixed, which
isn't true when the source is e.g. `H2` feeding an `H4` aggregation.
Verified: the spring-forward `H4` bucket 06:00-09:00Z (3 real hours)
genuinely needs two `H2` candles — 06:00-07:00 (itself DST-shortened to
1 real hour) and 07:00-09:00 (a normal 2 hours) — but `3h // 2h = 1`
would have accepted just the first as "complete".

**Fix: one canonical boundary function, not two DST calculations.** New
`domain/candle_boundary.py`: `candle_start_boundary`/`candle_end_time`,
the exact `zoneinfo`-based logic FX-24 already proved correct, extracted
so `aggregate_candles` and `MultiTimeframeTrendStrategy` share one
definition of candle completion instead of each computing its own.

**Fix: completeness is now exact-boundary-sequence matching, not a
count.** `aggregate_candles` generates the expected source-candle
start-time sequence for a bucket (walking `candle_end_time` forward one
source candle at a time — correctly DST-aware even when the source
itself is day-aligned) and requires the actual member start-times to
match exactly. This closes Bug 2 *and* the original FX-7 edge case in
the same change: `12:00,12:01,12:02,12:02,12:04` (five records for a
five-minute bucket, but `12:02` duplicated and `12:03` missing) — a
count check accepts this; exact-sequence matching correctly rejects it.

**Also added: `MultiTimeframeTrendStrategy` now rejects a driving series
that isn't `Granularity.H1`.** Its parameters, docstring, and design are
explicitly H1/H4; a generic any-timeframe version is a different,
unbuilt strategy, not implied by this one silently accepting e.g. `M15`.

**Also corrected: a reversed docstring sentence** in the FX-24 code
(now in `candle_boundary.py`). The arithmetic is wall-clock (a
`zoneinfo`-aware `datetime + timedelta` advances the WALL-CLOCK reading
by exactly N hours, always) — and it's precisely that wall-clock
fidelity that makes the corresponding real/UTC-elapsed span become 3 or
5 hours across a DST transition, not the other way around. The code was
always correct; the explanation had the causality backwards.

**Verification:** both bugs reproduced and confirmed via direct
computation against `candle_boundary` before writing any fix (matching
the same "verify with an independent script before implementing"
discipline used throughout this project). Three new regressions, each
confirmed to fail against the pre-fix code and pass against the fix:
fall-back H4 visibility (05:00Z not visible at 09:00Z, visible at
10:00Z), spring-forward H2→H4 completeness (1 of 2 required H2 candles
→ dropped), and the duplicate+missing source-candle case. All existing
FX-24/FX-25 tests pass unchanged against the refactored shared logic —
confirms the fix is a correction, not a behavior change for every case
already covered. Full suite (502 tests), contract boundary tests (the
new `candle_boundary.py` module picked up automatically, confirmed
import-clean), and live integration tests (OANDA + Postgres) all
passed.

## 2026-09-15 — FX-25H.1: source/target boundary nesting fix

One further gap in FX-25H's own fix, caught by the same external review
and verified directly before implementing (reproduced end to end against
the pre-fix code, not just derived on paper).

**Bug (confirmed): nominal duration divisibility doesn't guarantee NY
wall-clock boundary nesting across a DST discontinuity.** FX-25H's
`_expected_source_starts` walked source candles forward from a target
bucket's start until reaching (or, it turned out, passing) the bucket's
end — with no check that it actually landed exactly on that end. `H6 %
H3 == 0` passes the existing "whole multiple" validation, but on the
2026-03-08 spring-forward day, `H3`'s own DST-shortened boundary lands
at 07:00-10:00Z while the `H6` bucket it's supposed to help build ends
at 09:00Z — the source candle straddles the target boundary by an hour
rather than nesting inside it. Reproduced directly: `aggregate_candles`
emitted an `H6` candle at 04:00Z whose close came from that overhanging
`H3` candle — real contamination/look-ahead, not hypothetical.

**Fix:** `_expected_source_starts` now returns `None` (treated by the
caller exactly like "incomplete") if the walk's final cursor doesn't
land exactly on the target bucket's own end. A specific DST-transition
bucket for a given source/target pairing is dropped — the granularity
*pairing* itself isn't rejected; an ordinary, non-transition `H3`→`H6`
bucket (or any other nominally-divisible pairing, most days) still
tiles perfectly and aggregates normally.

**Verification:** the exact contamination reproduced above is now a
regression test (`test_h3_source_does_not_exactly_tile_spring_forward_
h6_bucket`), confirmed to fail against the pre-fix code and pass
against the fix. A second, broader structural test
(`test_no_emitted_bucket_is_ever_over_or_under_covered_by_its_sources`)
builds a full, legitimately-tiled day of source candles (via the same
canonical `candle_boundary` walker, as correctly-shaped input data, not
a re-implementation of the logic under test) for five source/target
pairings across both DST transition days, and confirms every emitted
bucket's boundaries exactly match the target granularity's own
canonical boundaries with none spuriously dropped — proving the fix
doesn't introduce false negatives alongside the true-negative case
above. All existing FX-24/FX-25H tests pass unchanged. Full suite (504
tests), live integration tests, and pre-commit all passed.

With this, the external review's full FX-24/FX-25 assessment is
resolved. Per the agreed sequence in `docs/NEXT_STEPS.md`, work moves
next to `FX-26` (paginated historical backfill) after a break.

## 2026-09-19 — FX-26: paginated, resumable historical backfill

`IngestCandles` (FX-6) has always been bounded to whatever fits in one
`MarketDataPort.get_candles` request (OANDA's 5000-candle cap) —
flagged as a likely bottleneck once real empirical strategy evaluation
needed years of history across several pairs, not the ~90-day/26-trade
samples used so far. This story adds `BackfillCandles`, a use case that
splits arbitrarily large ranges into safe pages and tracks progress
durably enough to survive an interruption.

**Decision: a per-series watermark, not a per-job checkpoint** —
confirmed before implementing (AskUserQuestion). New
`ingestion_watermarks` table/`IngestionWatermarkRepository`: one row per
`(instrument, granularity)` tracking `[earliest_ingested,
latest_ingested)`, one contiguous covered interval, independent of any
particular call's own `start`/`end`. Directly matches the stated goal
("don't want to repeatedly refetch everything" as the dataset grows
over years) — a later call naturally extends the frontier forward (new
data) or backward (more history) without needing to remember the
original request's parameters. The watermark *is* the resume state;
there is no separate job/checkpoint object.

**Decision: a disjoint request raises, rather than silently creating a
false coverage claim** — worked through carefully during design, not
discovered as a bug afterward. A single contiguous interval can't
represent two genuinely separate covered ranges; naively extending the
stored interval's outer bounds to the union of an old and a new,
non-touching range would falsely claim the gap between them is covered
when it was never fetched. `BackfillCandles` checks `start <=
existing_latest and existing_earliest <= end` (overlap-or-touch) before
proceeding, and raises `ValueError` with a clear message otherwise.

**Decision: backward-extension pages are fetched in *descending* order
(closest to existing coverage first)** — the specific detail that makes
backward extension safe under interruption. Forward extension pages
naturally process ascending, advancing `latest_ingested` page by page
while `earliest_ingested` stays fixed. If backward pages were also
processed ascending (i.e. starting from the new, more-historical `start`
first), a crash partway through would leave a genuine gap between the
newly-fetched earliest pages and the pre-existing watermark — descending
order guarantees `earliest_ingested` only ever retreats into
contiguous, already-verified territory, one page at a time.

**Domain layer**: new `domain/candle_pagination.py::split_into_pages`
reuses `candle_boundary.candle_end_time` (FX-25H/FX-25H.1) to compute
exactly how much real time N candles span — a day-aligned granularity's
candle can be 3, 4, or 5 real hours depending on DST, so page sizing
can't be a fixed multiplication for those; a closed-form fast path is
used for non-day-aligned granularities where the ambiguity doesn't
exist. Pages are contiguous and non-overlapping by construction.

**Also fixed: `find_gaps` (FX-8) had the same day-alignment bug FX-24
already fixed elsewhere** — its "expected candle" generation predated
FX-24 entirely and used naive epoch-stepping. Verified directly: for a
range crossing a DST transition, that stepping diverges from the real
canonical boundary by an hour from the transition onward — `find_gaps`
would report false gaps (or miss real ones) for exactly the
granularities FX-24 made day-aligned. Now uses `candle_boundary`, the
same definition every other consumer shares. "Detect gaps after
backfill" (a stated FX-26 requirement) reuses the existing
`DetectDataGaps` use case as a separate, explicit follow-up step —
deliberately not baked into `BackfillCandles` itself, matching this
codebase's established composability preference (e.g. FX-17's metrics).

**Verification:** `split_into_pages` tested at the exact 5000-candle
cap boundary and 5001 (forcing a second page), across both DST
transitions (reusing FX-25H's own verified boundary values), and for
determinism regardless of chosen page size (no page boundary ever
lands mid-candle, whatever `max_candles_per_page` is). `find_gaps`'
fix is regression-tested using the same live-OANDA-confirmed boundaries
FX-24 established, and confirmed to fail against the pre-fix naive
stepping. `BackfillCandles` is tested against in-memory fakes for fast,
exhaustive branch coverage (fresh/forward/backward/both-direction
extension, disjoint rejection, already-fully-covered no-op) and
separately against real Postgres for the core interruption/resume
guarantee: a simulated mid-backfill failure (via a fake `MarketDataPort`
that raises on a specific page — a real provider failure can't be
deterministically triggered) leaves exactly the completed pages durably
stored, and a fresh use case instance resumes and completes without
re-fetching or duplicating anything. New Alembic migration verified
up/down/up. Full suite (539 tests) and pre-commit passed.

**Noted, not a regression**: 6 pre-existing live-OANDA strategy tests
(unrelated to this story — `EmaCrossoverStrategy`, control strategies,
etc.) failed when the full suite ran, each on the same assertion
("expected enough live candles for a meaningful run"). Diagnosed
directly, not assumed: today is a Saturday, forex markets are closed,
and a live fetch of the same "last 4 hours" window those tests use
returned zero finalized candles. All of this story's own new tests
(including the ones hitting live Postgres) passed; the six affected
tests would pass again once the market reopens. Recorded here rather
than silently ignored, per this project's established honesty norm
around environmental test flakiness.

## 2026-09-19 — FX-27: candle retrieval provenance filtering

**Decision: `get_range` gains `source: CandleSource | None = None`,
where `None` is an explicit "all sources", not an implicit "whichever
happens to exist"** — the design pinned down before implementation
started (this story was pre-scoped in detail ahead of FX-26). FX-24
already stops `NATIVE`/`AGGREGATED` rows from colliding in storage;
this story is the read-side complement, letting a caller that cares
about provenance say so explicitly rather than relying on `get_range`
happening to return only one kind of row because the other doesn't
exist yet. Implemented identically in `SqlAlchemyCandleRepository`
(an extra `WHERE source = ...` clause, only added when `source is not
None`) and `FakeCandleRepository` (the in-memory test double), so
callers see the same behavior against either.

**`AggregateCandles` now passes `source=CandleSource.NATIVE`
explicitly**, rather than the prior implicit "all sources" default.
Without this, a range containing both `NATIVE` and pre-existing
`AGGREGATED` candles for the same source granularity would be passed
straight to `aggregate_candles`, which already rejects mixed-provenance
input (FX-24) — so the failure mode wasn't silent corruption, but it
was an avoidable runtime error for a case `AggregateCandles` can just
never enter. Filtering to `NATIVE` at the read is the more precise fix:
`AggregateCandles`'s job is to aggregate *source* data, and
re-aggregating already-`AGGREGATED` rows would be a different,
unintended operation.

**Verification:** confirmed via the regression-proof discipline used
throughout this project — reverted `AggregateCandles`'s explicit
`source=CandleSource.NATIVE` argument, confirmed the new
`test_aggregate_candles_ignores_preexisting_aggregated_source_candles`
test fails (it did: `AggregateCandles` read the `AGGREGATED` rows and
tried to aggregate them, producing a non-zero write count where zero
was expected), restored the fix, confirmed the test passes. New
coverage: `FakeCandleRepository` filter behavior
(`tests/unit/application/test_fake_candle_repository.py`, all three of
`source=None`/`NATIVE`/`AGGREGATED`) and the same three cases against
real Postgres (`tests/integration/test_candle_repository.py`). Full
suite: 547 tests, 541 passed, the same 6 pre-existing weekend-related
live-OANDA strategy failures as FX-26 (confirmed identical signature —
0 candles returned for the live window; today is still Saturday,
markets still closed), not a regression. Lint/format/mypy/pre-commit
all clean.

## 2026-09-19 — Research dataset build (+ FX-27H: upsert batching fix)

**Decision: 10 years of history, EUR/USD + GBP/USD + USD/JPY + USD/CAD +
XAU/USD, H1 + H4** — the original roadmap only named the four FX pairs;
asked the user how much history to backfill (3/5/10 years/maximum
available, with data confirmed live back to at least 2005 for both
EUR/USD and XAU/USD before asking) and how to treat the requested
addition of XAU/USD. User chose 10 years. XAU/USD needed no domain
change: `Instrument.base_currency`/`quote_currency` validation
(`require_currency_code`) only requires a 3-letter uppercase code — "XAU"
already is gold's real ISO 4217 currency code, and OANDA's practice API
exposes it as `XAU_USD`, confirmed with a live fetch before committing to
the design. `pip_decimal_places` (currently unused anywhere in the
codebase) needed no special-casing either.

**Implementation: `scripts/build_research_dataset.py`**, a one-off
composition script (not a new use case or domain behavior) wiring
already-tested machinery — `BackfillCandles`, `SqlAlchemyCandleRepository`,
`SqlAlchemyIngestionWatermarkRepository`, `OandaMarketDataAdapter` — for
each of the 10 `(instrument, granularity)` combinations in turn. No
dedicated test suite, matching the existing precedent for composition-root
wiring (`apps/api/main.py`). Safe to re-run: resumable via FX-26's
watermark like any other `BackfillCandles` call.

**FX-27H: real bug found on the very first live run at full page size.**
`SqlAlchemyCandleRepository.upsert_many` built one `ON CONFLICT` insert
statement per call, with all of a page's candles as one `.values([...])`
list. Every prior test used small candle counts, so this never hit the
one thing that matters at real scale: asyncpg caps bound query parameters
at 32767 (its own wire-protocol limit, not Postgres' own). Each candle
row contributes 14 params; a full 5000-candle page (FX-26's own default
page cap) needs 70,000 — the very first `EUR_USD H1` backfill page
failed outright with `asyncpg.exceptions.InterfaceError: the number of
query arguments cannot exceed 32767`, confirmed to leave nothing written
(the statement fails at the protocol level before touching the table —
checked directly against Postgres, zero rows, zero watermarks, before
fixing anything).

**Fix**: batch `upsert_many`'s insert into 1000-row chunks (comfortably
under the cap regardless of how large a page callers request), while
keeping a single `commit()` at the end of the call — this preserves
`BackfillCandles`' existing crash-safety unit exactly: a page still only
counts as durably done once the whole `upsert_many` call returns, so
FX-26's interruption/resume guarantee needed no changes. Verified via the
same regression-proof discipline used throughout this project: reverted
the batching, confirmed a new 3000-candle `upsert_many` test fails with
the identical `InterfaceError` seen live, restored the fix, confirmed it
passes.

**Result**: full backfill completed cleanly on the next run — 385,689
candles across all 10 series, one run, no interruption:

| Instrument | H1 candles | H4 candles |
|---|---|---|
| EUR_USD | 62,199 | 15,556 |
| GBP_USD | 62,202 | 15,560 |
| USD_JPY | 62,216 | 15,573 |
| USD_CAD | 62,225 | 15,581 |
| XAU_USD | 59,112 | 15,465 |

Coverage: `2016-09-19` to `2026-09-19` for every series (the watermark's
`earliest`/`latest_ingested`, confirmed directly against Postgres).
XAU_USD has modestly fewer H1 candles than the FX pairs (59,112 vs.
~62,200) — a different daily trading-hours pattern on OANDA for
commodities vs. FX pairs, not an error; not investigated further since
it doesn't affect correctness of what *was* ingested.

**Not done as part of this step** (deliberately, to keep scope to what
was asked): no `DetectDataGaps` sweep across the new dataset, no
data-quality report. That's available as a natural next check before
`FX-28` uses this dataset, but wasn't requested here.

## 2026-09-19 — Research dataset gap-check (+ FX-27H.1: DetectDataGaps fix)

**Requested by the user** before proceeding to `FX-28`, following up on
the "not done as part of this step" note above.

**Decision: filter at the script level, not by adding a market calendar
to domain code.** `domain/candle_gaps.py` already documents this
explicitly: "Deliberately no market-calendar awareness ... Callers should
pass ranges already known to be within a trading session." A raw 10-year
range is not such a range. Rather than silently redesigning `find_gaps`/
`DetectDataGaps` to add calendar awareness (a real architectural change
CLAUDE.md says to flag and stop before making, not do quietly),
`scripts/check_research_dataset_gaps.py` is the caller-side
responsibility that docstring already describes: run `DetectDataGaps`
over each series' full range, then filter out the standard forex weekly
closure (Friday 17:00 to Sunday 17:00 `America/New_York`) before
reporting anything as a real gap — reusing the exact NY-17:00 session
boundary this codebase already anchors day-aligned candles to (FX-24),
not a new convention invented for this script.

**FX-27H.1: the gap check's own first run surfaced a real bug, not just
data findings.** Every series showed exactly one suspicious "unexplained"
gap at its very first candle slot. Checked directly against Postgres
before assuming anything: the flagged candle (e.g. `XAU_USD H1` at
`2016-09-19T19:00:00Z`) *was* present in the table. Root cause:
`DetectDataGaps` passed the watermark's raw `earliest_ingested`
(`2016-09-19T19:14:34Z` — a wall-clock reading from when the backfill
script ran, not a candle boundary) straight to both `get_range` and
`find_gaps`. `find_gaps` rounds this down to `19:00:00` when building its
expected-slot list, but `get_range`'s own `start_time >= start` filter
used the unrounded `19:14:34`, silently excluding the genuinely-present
`19:00:00` candle from `stored`. Any caller passing a non-boundary-
aligned `start` was guaranteed at least one false-positive gap at the
start of its range — an edge case none of the existing tests exercised,
since they all used already-aligned timestamps. Fixed: `DetectDataGaps`
now snaps `start` to its own candle boundary once, before either call, so
both see the same window. Regression-tested the usual way (reverted,
confirmed the new test reproduces the exact false positive, restored,
confirmed it passes) before trusting the rest of the gap-check results.

**Findings, re-run after the fix**: 162,121 raw missing candle slots
across the 10 series; 97% (156,295) were ordinary weekly closures. The
remaining 5,826 were investigated individually by category, not just
filtered and left unexplained:

- **The four FX pairs** (~420 H1 / ~102 H4 unexplained each): distribution
  by (weekday, NY hour) is spread thin across ~120 distinct buckets with
  no dominant peak (max count 14 in any one bucket) — the signature of
  scattered, date-shifting annual holidays (Christmas, New Year's,
  Thanksgiving — each lands on a different weekday each year), not a
  systematic or scattered-random problem. Matches `find_gaps`' documented
  no-holiday-calendar limitation exactly as expected.
- **XAU_USD** (3,524 H1 / 208 H4 unexplained — notably larger): distribution
  analysis showed ~2,607 of the H1 gaps concentrated in one clean,
  extremely regular bucket — every Monday/Tuesday/Wednesday/Thursday and
  Sunday at exactly 17:00 NY (confirmed: 521-522 occurrences each, ~5×
  ~522 ≈ the dominant share). This is OANDA's daily settlement/rollover
  quote gap specific to how it quotes commodities (gold trades don't
  continue through the NY 17:00 day-rollover the way FX pairs do) — the
  same explanation for the XAU_USD candle-count shortfall already noted
  when the dataset was built (59,112 vs. ~62,200 H1 candles for the FX
  pairs). The remaining ~918 H1 gaps cluster around specific holiday
  dates with *extra* missing hours beyond the daily 17:00 gap — spot-
  checked directly (not assumed): a live re-fetch of `XAU_USD` H1 for
  Thanksgiving 2016-11-24 (`12:00`–`23:00 UTC`) returned candles only
  through `17:00 UTC`, then nothing — confirming OANDA itself has no data
  for those hours (an early-close pattern specific to metals around US
  holidays), not a backfill defect.

**Conclusion**: no scattered, unexplainable single-candle dropouts found
anywhere in the dataset — every unexplained gap resolves into one of two
recognized, confirmed-not-assumed categories (calendar holidays or
XAU/USD's daily settlement gap). The research dataset is sound; `FX-28`
can proceed against it.

## 2026-09-19 — FX-28: TrendRegime-based gating — a proven equivalence, not a new result

New `EmaCrossoverTrendRegimeGatedStrategy` (`domain/strategies/
ema_crossover_trend_regime_gated.py`): the same SMA-seeded EMA crossover
event as `EmaCrossoverStrategy` (FX-14), gated by `classify_regime`
(FX-12) — a crossover only confirms if `TrendRegime.TRENDING`;
`RANGING`, or insufficient regime history (`< 2 * regime_period`
candles), closes to FLAT rather than being ignored, matching
`MultiTimeframeTrendStrategy`'s already-settled FLAT-vs-None precedent
(FX-25/FX-21H). Direction-agnostic gate, since ADX measures trend
strength, not direction — both LONG and SHORT crossovers require the
same `TRENDING` condition.

**Decision: the regime classification uses the exact same `candles`
prefix `evaluate()` receives** (through and including the signal bar),
not a further-truncated slice — verified, not assumed, to be exactly
equivalent to FX-21H's own established look-ahead-safe convention in
`segment_trades_by_regime` (`candles[:entry_index]`): since execution
happens at the *next* bar's open (FX-11H), `entry_index` there always
equals the signal bar's index + 1, so the two slices are identical.

**The central finding — discovered empirically, then proven, not just
observed**: running the three-way comparison (unconditional /
attribution / actual gating) against the full FX-26/27 research dataset
showed the "Gated" leg's metrics coming back numerically IDENTICAL to
the "TRENDING-only attribution" leg, for every one of the 5 instruments
— not just similar, matching to every decimal place shown. Checked
directly rather than trusted: compared the actual trade sets
(entry_time, exit_time, pnl) for a sample chunk — identical, not merely
same-count.

This is provable, not coincidental, given two properties of this
specific pairing: (1) `EmaCrossoverStrategy` never self-emits FLAT —
every crossover event is a direction reversal, so an unconditional
trade always closes exactly at the *next* crossover event, whatever its
regime; (2) the gate fires at those same event bars using the same
regime classification attribution already uses. Consequence: a gated
position opened on a TRENDING event always closes at the next event
bar too — either a TRENDING reversal into a new position, or a RANGING
gate to FLAT — and either way, that's the *identical* exit bar/price an
unconditional reversal would have used for that same trade. So "gated,
realized" trades and "unconditional trades entered during TRENDING"
are entry/exit/P&L-identical by construction, not by chance. Locked in
as a regression test (`tests/unit/domain/strategies/
test_ema_crossover_trend_regime_gated.py::
test_gated_trades_exactly_equal_the_trending_attribution_bucket`,
regression-proof discipline applied: reverted the gate condition,
confirmed the test fails, restored, confirmed it passes).

**This is a real finding about *this specific pairing*, not a general
law of regime-gating.** FX-25's H4-confirmation gate uses information
external to the H1 signal's own timing (a second timeframe) — an
attribution equivalent isn't even expressible the same way there. The
equivalence here is specific to gating a base strategy that (a) only
ever alternates LONG/SHORT with no native FLAT, and (b) is gated using
information available at the exact same decision bars attribution
already inspects.

**Decision, put to the user after discovering this**: extend to a
genuinely different mechanism (continuous regime monitoring — checking
every bar, not just at entry, and force-exiting a held position if the
regime deteriorates mid-trade) vs. accept the equivalence itself as the
finding and close the story. User chose to accept and close — the
proven equivalence is itself the answer to "does gating add anything
beyond attribution" for this construction: no, not by design, and now
that's known with certainty rather than assumed either way. Continuous
regime monitoring remains a distinct, unbuilt experiment if picked up
later.

**Performance note, confirmed before running, not assumed**: `run_
backtest`'s documented O(n²) scaling (full history reslice + full
EMA/ADX recompute every step) is fine at FX-21's ~1,500-candle sample
but was untested at real research-dataset scale. Timed directly: 4,000
H1 candles took ~9.4s (EMA) / ~10.0s (gated); extrapolating to a full
~62,000-candle series would be over half an hour per instrument per
strategy — impractical for one session. Confirmed 6,200 candles
(~1 year) at ~22s/~26s, consistent with the O(n²) extrapolation. Ran
the real comparison chunked into ~6,000-candle contiguous windows per
instrument (not exact calendar years — simpler, equally valid for this
purpose), trades pooled across chunks before computing metrics. The
~51-candle EMA warm-up "lost" at each chunk boundary is under 1% of
each chunk, not a change in what's being measured. This was a practical
choice for this one-off empirical run only, not a change to `run_
backtest`'s own architecture.

**Empirical results** (full 10-year H1 history, all 5 research-dataset
instruments, default `EmaCrossoverStrategy()` 20/50 EMA and default
`classify_regime`/gate period=14/threshold=25):

| Instrument | Leg | n | win rate | expectancy | profit factor | Sharpe |
|---|---|---|---|---|---|---|
| EUR_USD | Unconditional | 1157 | 0.318 | -0.00016 USD | 0.933 | -0.023 |
| EUR_USD | TRENDING-only | 295 | 0.308 | -0.00069 USD | 0.750 | -0.104 |
| EUR_USD | RANGING-only | 862 | 0.321 | 0.00002 USD | 1.009 | 0.003 |
| EUR_USD | Gated (actual) | 295 | 0.308 | -0.00069 USD | 0.750 | -0.104 |
| GBP_USD | Unconditional | 1169 | 0.293 | -0.00024 USD | 0.926 | -0.024 |
| GBP_USD | TRENDING-only | 304 | 0.322 | 0.00026 USD | 1.071 | 0.020 |
| GBP_USD | RANGING-only | 865 | 0.282 | -0.00042 USD | 0.868 | -0.047 |
| GBP_USD | Gated (actual) | 304 | 0.322 | 0.00026 USD | 1.071 | 0.020 |
| USD_JPY | Unconditional | 1106 | 0.314 | 0.02960 JPY | 1.096 | 0.028 |
| USD_JPY | TRENDING-only | 286 | 0.322 | 0.04519 JPY | 1.125 | 0.035 |
| USD_JPY | RANGING-only | 820 | 0.311 | 0.02417 JPY | 1.083 | 0.025 |
| USD_JPY | Gated (actual) | 286 | 0.322 | 0.04519 JPY | 1.125 | 0.035 |
| USD_CAD | Unconditional | 1195 | 0.269 | -0.00048 CAD | 0.829 | -0.062 |
| USD_CAD | TRENDING-only | 288 | 0.306 | -0.00049 CAD | 0.831 | -0.065 |
| USD_CAD | RANGING-only | 907 | 0.257 | -0.00047 CAD | 0.829 | -0.061 |
| USD_CAD | Gated (actual) | 288 | 0.306 | -0.00049 CAD | 0.831 | -0.065 |
| XAU_USD | Unconditional | 1125 | 0.295 | 1.07617 USD | 1.111 | 0.026 |
| XAU_USD | TRENDING-only | 308 | 0.308 | 2.25569 USD | 1.187 | 0.039 |
| XAU_USD | RANGING-only | 817 | 0.290 | 0.63151 USD | 1.072 | 0.018 |
| XAU_USD | Gated (actual) | 308 | 0.308 | 2.25569 USD | 1.187 | 0.039 |

(Gated rows equal their instrument's TRENDING-only row exactly — the
proven structural equivalence above, not a coincidence or a copy-paste
error in this table.)

Read with the same caution as FX-21/23: this is one specific base
strategy, one default parameter set, one gate. On this much larger
sample (n=1,100-1,200 unconditional trades per instrument, vs. FX-21's
n=26), TRENDING-conditioning is a mixed bag across instruments — it
helped GBP_USD, USD_JPY, and XAU_USD (higher win rate, expectancy,
profit factor, and Sharpe than the unconditional baseline) but hurt
EUR_USD, and was roughly neutral for USD_CAD. There is no single
instrument-independent answer to "should EMA crossover be
regime-gated" on this data — consistent with FX-21/23's own earlier,
smaller-sample finding that the naive "trend-following should do
better when ADX confirms a trend" intuition doesn't hold uniformly.

**Verification**: 16 unit tests (four `evaluate()` outcome categories
plus constructor validation plus the structural-equivalence regression,
all against oracle-verified fixtures — TRENDING/RANGING classifications
confirmed by running the already-independently-verified
`classify_regime`, FX-12, against each candidate series rather than
hand-deriving ADX arithmetic), a live-OANDA smoke test (same pattern as
every other concrete strategy), and a three-way structural replay test
(same pattern as FX-21's own — structural assertions only, no hard-coded
winner). Full suite: 562 passed; the same 6 pre-existing weekend-related
live-OANDA failures as FX-26/27, plus this story's own live-smoke test
failing with the identical "0 candles in the last 4 hours" signature
(today is still Saturday) — confirmed not a regression, same as every
prior story's weekend-timing note. Lint/format/mypy/pre-commit clean.

## 2026-09-19 — Correction: FX-28's per-instrument performance table is withdrawn

**Correction, not a silent edit — the empirical table above is
withdrawn, pending a rerun**, caught by external review and confirmed
independently before writing this (not taken on trust).

**The bug**: FX-28's own performance note claimed chunking the 10-year
backtest into ~6,000-candle windows only cost "under 1% [...] not a
change in what's being measured." That's wrong. Two things happen at
every artificial chunk boundary that don't happen in a real continuous
history: (1) `simulate_trades` force-closes any open position at the
end of its input (documented, correct behavior for a real end-of-data
— but a chunk boundary isn't real end-of-data), so a trade that would
have run through the boundary is instead cut short and a fresh,
independent trade starts flat in the next chunk; (2) every strategy's
own EMA/ADX state reseeds from scratch at the start of each chunk
(`evaluate()` only ever sees that chunk's own prefix), not just losing
~51 candles of opportunity but computing genuinely different indicator
values near each boundary than a continuous run would.

**Confirmed independently, not just accepted**: ran EUR/USD H1 candles
[0:12000) two ways — one continuous `run_backtest`, and split into two
6,000-candle chunks with results pooled (exactly FX-28's own method).
228 trades continuous vs. 226 chunked; 4 trades appear only in the
continuous run, 2 only in the chunked run, clustered around the
boundary. Not a rounding difference — genuinely different trades with
different entry/exit times and P&L.

**What remains valid**: the proven gated-equals-attribution structural
equivalence. That result doesn't depend on data continuity — it's a
property of the strategy pairing at every individual decision bar,
proven mathematically and locked in by a regression test
(`test_gated_trades_exactly_equal_the_trending_attribution_bucket`)
that runs on one single, non-chunked, deterministic synthetic series.
Nothing about the chunking bug touches that proof or that test.

**What's withdrawn**: every number in FX-28's "Empirical results" table
— win rate, expectancy, profit factor, Sharpe, and the specific claims
("TRENDING helped GBP_USD/USD_JPY/XAU_USD, hurt EUR_USD, neutral for
USD_CAD"). All four legs of that table were computed via the same
chunked pipeline, so the whole table is provisional, not just the rows
that looked surprising. Marked provisional in `CURRENT_STATE.md`/
`NEXT_STEPS.md` pending a rerun once a continuous backtest engine
exists (`FX-29`, next).

**Root cause, framed honestly**: `run_backtest`'s own documented O(n²)
scaling (full-history reslice plus full EMA/ADX recompute every step)
was known and accepted at FX-21's ~1,500-candle scale. Chunking was a
workaround adopted for FX-28's ~62,000-candle scale without adequately
reasoning through what it silently changes about the economics being
simulated — an error in judgment on this story's own performance
mitigation, not a subtle edge case. `FX-29` (next) replaces the
workaround with a real fix: an incremental backtest engine that
processes the full history continuously, with parity-tested guarantees
against the existing slow engine on small data.

## 2026-09-19 — FX-29: scalable continuous backtest engine

Replaces FX-28's withdrawn chunking workaround with a real fix, per the
same external review that caught it: an incremental backtest path that
processes a full H1 series continuously — no artificial boundaries, no
position/indicator-state resets — validated trade-for-trade against the
existing engine, then used to rerun FX-28's comparison for real.

**Scope, confirmed empirically before building anything**: `simulate_
trades` is already O(n) (one indexed pass) and needed no change — it
already force-closes only at the true end of whatever candle list it's
given; the problem was always that FX-28 gave it artificially-truncated
lists. The O(n²) cost is entirely `run_backtest`'s full-history reslice
plus each strategy's own from-scratch EMA/ADX recompute every call.
`segment_trades_by_regime` (attribution) is *not* O(n²) over candles —
its cost scales with trade-count × average history length, confirmed
directly (below) to be tolerable as-is, no incremental treatment needed.

**New, additive-only infrastructure** — nothing existing touched:
- `domain/incremental_ema.py` (`IncrementalSmaSeededEma`) and `domain/
  incremental_adx.py` (`IncrementalAdx`): O(1)-per-update primitives
  replicating `_sma_seeded_ema`'s and `_compute_adx`'s exact math (same
  Decimal operations, same order) one bar at a time. Deliberately
  shared/reusable rather than per-strategy-duplicated (a departure from
  this codebase's usual convention) — performance/correctness-critical
  shared infrastructure benefits from one well-tested implementation,
  not several near-duplicates.
- `domain/incremental_strategy.py`: `IncrementalStrategy` protocol
  (`on_candle(candle) -> TradeHypothesis | None`, stateful) and
  `run_backtest_incremental` — same validation guards as `run_backtest`,
  one O(n) forward pass, no reslicing, no candle ever re-shown.
- `IncrementalEmaCrossoverStrategy` and `IncrementalEmaCrossoverTrend
  RegimeGatedStrategy` — same `strategy_key`/parameters as their
  existing counterparts (same strategy, faster implementation, not a
  new identity). `EmaCrossoverStrategy`/`EmaCrossoverTrendRegimeGated
  Strategy` themselves are completely unmodified and remain the
  permanent ground-truth reference.

**Verification, exact parity at every level, not just aggregates**:
- `IncrementalSmaSeededEma`/`IncrementalAdx` checked step-by-step
  against `_sma_seeded_ema`/`_compute_adx` on synthetic series, then
  stress-tested against 1,500 real H1 candles (`IncrementalAdx`): 0
  mismatches across 1,473 steps.
- `IncrementalEmaCrossoverStrategy`/`IncrementalEmaCrossoverTrendRegime
  GatedStrategy` checked hypothesis-for-hypothesis against the slow
  engine over a 400-candle synthetic series exercising both confirmed
  and gated-FLAT outcomes — exact equality on the first attempt for the
  EMA strategy; the gated strategy needed one real bug fix first (an
  inverted `regime is TrendRegime.RANGING` gate condition, caught by
  mypy's Optional-narrowing complaints during cleanup, not by a test
  failure — fixed before any test ran against it).
- Golden parity tests at the exact acceptance-criterion granularity
  (side, entry time/price, exit time/price, P&L) added explicitly, not
  left as an implication of hypothesis-level parity.

**Performance, measured**: 62,194 real H1 candles (EUR/USD), full
continuous run: `IncrementalEmaCrossoverStrategy` 0.19s,
`IncrementalEmaCrossoverTrendRegimeGatedStrategy` 0.47s — down from an
extrapolated 35-40 minutes each with the old O(n²) engine at this scale.
`segment_trades_by_regime` (unmodified): ~200-225s per instrument
(~3.5 minutes) — confirmed, not just estimated, and treated as
acceptable for a one-off analysis run; not optimized further in this
story.

**FX-28's comparison rerun, continuously, all 5 instruments, full
10-year H1 history** (replaces the withdrawn table):

| Instrument | Leg | n | win rate | expectancy | profit factor | Sharpe |
|---|---|---|---|---|---|---|
| EUR_USD | Unconditional | 1165 | 0.317 | -0.00015 USD | 0.938 | -0.021 |
| EUR_USD | TRENDING-only | 296 | 0.311 | -0.00070 USD | 0.746 | -0.106 |
| EUR_USD | RANGING-only | 869 | 0.319 | 0.00004 USD | 1.017 | 0.006 |
| EUR_USD | Gated (actual) | 296 | 0.311 | -0.00070 USD | 0.746 | -0.106 |
| GBP_USD | Unconditional | 1181 | 0.292 | -0.00024 USD | 0.928 | -0.024 |
| GBP_USD | TRENDING-only | 307 | 0.326 | 0.00029 USD | 1.081 | 0.023 |
| GBP_USD | RANGING-only | 874 | 0.280 | -0.00042 USD | 0.866 | -0.048 |
| GBP_USD | Gated (actual) | 307 | 0.326 | 0.00029 USD | 1.081 | 0.023 |
| USD_JPY | Unconditional | 1119 | 0.312 | 0.02636 JPY | 1.085 | 0.025 |
| USD_JPY | TRENDING-only | 293 | 0.317 | 0.03225 JPY | 1.090 | 0.026 |
| USD_JPY | RANGING-only | 826 | 0.310 | 0.02427 JPY | 1.083 | 0.025 |
| USD_JPY | Gated (actual) | 293 | 0.317 | 0.03225 JPY | 1.090 | 0.026 |
| USD_CAD | Unconditional | 1205 | 0.269 | -0.00047 CAD | 0.831 | -0.061 |
| USD_CAD | TRENDING-only | 289 | 0.304 | -0.00046 CAD | 0.841 | -0.060 |
| USD_CAD | RANGING-only | 916 | 0.258 | -0.00047 CAD | 0.827 | -0.062 |
| USD_CAD | Gated (actual) | 289 | 0.304 | -0.00046 CAD | 0.841 | -0.060 |
| XAU_USD | Unconditional | 1132 | 0.293 | 1.24596 USD | 1.129 | 0.030 |
| XAU_USD | TRENDING-only | 313 | 0.304 | 2.67158 USD | 1.224 | 0.046 |
| XAU_USD | RANGING-only | 819 | 0.289 | 0.70112 USD | 1.080 | 0.020 |
| XAU_USD | Gated (actual) | 313 | 0.304 | 2.67158 USD | 1.224 | 0.046 |

Gated rows equal their instrument's TRENDING-only row exactly, again —
the proven structural equivalence holds identically under continuous
processing (expected: it's a property of the strategy pairing at each
decision bar, independent of how the backtest is executed).

Trade counts shifted modestly from the withdrawn chunked table (e.g.
EUR_USD unconditional: 1165 continuous vs. 1157 chunked) — confirming
the chunking bug was real and did distort results, exactly as the
external review predicted, though the shift is modest here rather than
dramatic. **Qualitative conclusions are unchanged**: TRENDING-
conditioning helps GBP_USD, USD_JPY, and XAU_USD (higher win rate,
expectancy, profit factor, and Sharpe than unconditional) and hurts
EUR_USD; USD_CAD is essentially a wash (win rate improves 0.269→0.304,
expectancy is flat within rounding). No single instrument-independent
answer to "should EMA crossover be regime-gated" — this table is now
trustworthy evidence for that conclusion, not an exploratory
approximation.

**Verification**: 32 new tests across the incremental primitives,
strategies, and golden parity checks. Full-suite tally (including
FX-30/FX-31, below) recorded at the end of that entry rather than
duplicated here.

## 2026-09-19 — FX-30: ingestion watermark boundary semantics

The first of two smaller hardening items the same external review
flagged, explicitly said to not affect the research data already
loaded. `FX-27H.1`'s fix was a symptom: `DetectDataGaps` got a false-
positive gap because a watermark's `earliest_ingested` was a literal
wall-clock query time (`2016-09-19T19:14:34Z`, from `build_research_
dataset.py`'s own `datetime.now()`), not a genuine candle boundary.
That story fixed the *consumer*; this closes it at the *source* instead
of leaving every future consumer to defend against it individually.

**Traced precisely before changing anything**: `split_into_pages`
already snaps its own cursor via `candle_start_boundary`, so every
page's `.start` is always boundary-aligned, and non-final pages' `.end`
too (`_advance`'s closed-form/exact-walk construction). The ONLY leak
is the *final* page's `.end`, clamped directly to a caller's raw,
possibly mid-candle `range_end` — and `BackfillCandles.__call__`'s
`floor_earliest=start` on a series' very first backfill, using the
caller's raw `start` unmodified. Both are `BackfillCandles`' own
bookkeeping, not `split_into_pages`' fault.

**Decision: floor both bounds, never round up** — considered and
rejected rounding `latest` up to "the nearest boundary" as the more
obviously-symmetric fix. It's wrong: a requested `end` is very often
"now", almost always mid-candle, and the candle containing it may
still be forming. Rounding up would claim a candle that might not
exist yet as covered. Flooring both bounds means the watermark only
ever claims candles that are already fully behind the requested `end`
— conservative, never overstates coverage. (Built and tested a
`round_up_to_candle_boundary` helper before this reasoning, then
deleted it and its tests once the flooring analysis showed rounding up
was actively the wrong choice, not just unnecessary — caught before
shipping, not after.)

**No change to what's fetched**: `split_into_pages` calls inside
`_extend_forward`/`_extend_backward` still receive the exact same raw
`range_start`/`range_end` as before — only what gets recorded via
`set_watermark` changes (the final page's `.end` and the first-ever
`floor_earliest`, both floored via `candle_boundary.candle_start_
boundary`). Existing FX-26 tests (all already boundary-aligned
fixtures) passed unmodified, confirming no behavior change for the
common case.

**Verification**: two new regression tests reproducing the exact
production scenario (a `start`/`end` a few seconds past a minute
boundary) and the specific risk a naive round-up fix would reintroduce
(a mid-candle `end` must never claim the next, possibly-forming candle
as covered). Regression-proof discipline applied: reverted both fixes,
confirmed both new tests fail, restored, confirmed they pass. Existing
FX-26 unit and live-Postgres integration suites unaffected.

## 2026-09-19 — FX-31: ingestion watermark concurrency protection

The second smaller hardening item, also explicitly forward-looking —
"irrelevant to the sequential one-off dataset load, but matters later
when the scheduler exists." Two concurrent `BackfillCandles` calls for
the same `(instrument, granularity)` could previously read the same
starting watermark, independently compute conflicting page plans, and
their interleaved `set_watermark` calls could clobber each other.

**Decision: a Postgres session-level advisory lock
(`pg_advisory_lock`/`pg_advisory_unlock`), held for the whole
`BackfillCandles.__call__`, not just one `set_watermark`** — new
`acquire_lock`/`release_lock` methods on the `IngestionWatermarkRepository`
port, implemented in the SQL adapter via a stable key (SHA-256 of
`"{instrument}:{granularity}"`, truncated to a signed 64-bit int —
not Python's own `hash()`, which is process-salted and not stable
across runs/processes). Session-level (not transaction-scoped)
specifically because `BackfillCandles` commits once per page, many
times per call — a transaction-scoped row lock would be released at
the first commit, long before the call actually finishes. The `Fake`
double uses one real `asyncio.Lock` per key, so concurrent-caller tests
get the same genuine serialization guarantee, not a no-op stand-in.

**Considered and rejected**: `SELECT ... FOR UPDATE` on the watermark
row itself — released at each of `BackfillCandles`' own per-page
commits, defeating the purpose; would need restructuring the existing
crash-safety design (durable per-page progress) to hold one long
transaction instead, a much bigger, riskier change for a
still-forward-looking concern.

**Verification, and an honest note on the discipline used**: a live-
Postgres test runs two genuinely concurrent `BackfillCandles` calls
(separate sessions/connections, `asyncio.gather`, small pages to
maximize real await-point interleaving) for the same series with
overlapping ranges, asserting the final watermark and stored candles
exactly match what a sequential run of both would produce. Async
interleaving timing isn't fully deterministic, so a single failing run
pre-fix wouldn't be a fully reliable demonstration on its own — ran the
un-fixed version 8 times before restoring the fix: **8/8 failed**,
confirming the race is reliably reproducible at this contention level,
not a rare fluke. Ran the fixed version 5 times after restoring: 5/5
passed.

**Full suite, both stories**: 597 passed, the same 6 pre-existing
weekend-related live-OANDA failures as FX-26/27/28 plus FX-29's own
unrelated live-smoke test (same "0 candles in the last 4 hours"
signature, today is still Saturday) — confirmed not a regression.
Lint/format/mypy/pre-commit clean.

## 2026-09-19 — FX-29H: incremental strategy lifecycle hardening

Second-round external review of FX-29, both claims independently
reproduced before fixing, not taken on trust.

**Bug 1: `IncrementalStrategy` is stateful, and nothing reset it.**
Reproduced directly: `run_backtest_incremental(strategy, candles)`
called twice on the SAME instance gave a different result the second
time (EMA state carried over from the first run) — 4 hypotheses first
call, 6 the second, on identical input. `run_backtest`/the slow
`Strategy` path has no equivalent hazard (each call gets the full
candle list fresh and computes everything from scratch), so this was a
genuinely new failure mode this story's own statefulness introduced.

**Bug 2: a failed validation left the strategy partially mutated.**
Also reproduced directly: 30 finalized candles followed by one
non-finalized "poison" candle raised as expected, but `on_candle` had
already been called (and had already mutated internal EMA state) for
all 30 preceding candles before the raise. A later, fully-valid call on
that SAME instance then diverged from a fresh instance's output —
finalized-status validation happened bar-by-bar, interleaved with
mutation, rather than up front.

**Fix**: `IncrementalStrategy` gained `reset()`, called unconditionally
by `run_backtest_incremental` before any replay begins. `candles` is
now validated IN FULL — including every candle's finalized status —
before `reset()` or `on_candle` is called at all, so a rejected series
never gets the chance to mutate anything.

**Decision: `reset()` on the strategy, not a factory that always
constructs a fresh instance internally** — the alternative the review
also offered. `reset()` keeps the door open for the same
`IncrementalStrategy` object to be used directly in a future live/paper
streaming mode (no "replay" to reset before there); only the historical
replay driver needs to reset one before use. `IncrementalEmaCrossoverStrategy`/
`IncrementalEmaCrossoverTrendRegimeGatedStrategy` both refactored so
`__init__` simply calls `self.reset()` — one code path, not two ways to
end up in the same initial state.

**Verification**: four new regression tests (`tests/unit/domain/
test_incremental_strategy.py`) reproducing both scenarios exactly,
plus a structural check reaching into the strategy's own seed-buffer
state to prove zero mutation happened before a rejected series raises
(not just that a later `reset()` papers over whatever did). Regression-
proof discipline applied: reverted both fixes, confirmed all four fail,
restored, confirmed all four pass. All existing golden parity tests
(hypothesis-level and trade-level) re-run and still pass unmodified —
`reset()` in `__init__` doesn't change first-construction behavior at
all, only re-use behavior. Full suite: 604 passed (cumulative with
FX-31H below), same 7 pre-existing/unrelated live-OANDA failures.
Lint/format/mypy/pre-commit clean.

## 2026-09-19 — FX-31 reopened, FX-31H: connection-pinned advisory lock

External review reopened FX-31 with a specific, well-reasoned
correctness concern about the advisory-lock implementation, verified
directly before accepting or rejecting it — not taken on trust either
way, and not dismissed because the original concurrency test had
already passed 5/5.

**The claim**: FX-31's advisory lock was acquired/released through the
same `AsyncSession` `BackfillCandles` uses for its `candles`/
`watermarks` work. SQLAlchemy's `Session.commit()` checks its
underlying DBAPI connection back in to the connection pool; the next
operation checks a connection back OUT, which is not guaranteed to be
the SAME physical connection. A Postgres session-level advisory lock is
tied to the physical backend connection, not to any SQLAlchemy object —
if a later page's `upsert_many`/`set_watermark` commit happens to hand
the lock-holding connection to someone else, the lock silently stops
protecting anything.

**Confirmed directly, in three steps, before touching any code:**
1. Attached SQLAlchemy pool `checkout`/`checkin` event listeners and
   watched a single session run five `execute()` + `commit()` cycles:
   confirmed `commit()` genuinely does check the connection back in,
   and the next `execute()` does a fresh checkout (empirically it kept
   getting the same connection back with no contention — expected, not
   yet proof of safety on its own).
2. Forced real contention: two concurrent sessions sharing a
   `pool_size=2` engine, alternating commits with a `pg_sleep` between
   each — over 6 iterations, each worker consistently got its own
   connection back (no crossover observed), showing the danger is real
   but not automatic.
3. Directly caused the actual failure: reverted to the exact original
   (session-sharing) lock design and ran the live concurrency scenario
   repeatedly under `pool_size=2` with maximally aggressive per-page
   commit frequency (`max_candles_per_page=1`) — it failed (`RESULT
   OK: False`, watermark/stored-candle mismatch) at least once across
   scattered runs, and also passed clean in many others. This confirmed
   the race is real, not merely theoretical, but is genuinely
   timing-dependent — not reliably reproducible on every single
   attempt, which is itself worth stating plainly rather than
   overclaiming a clean revert-and-confirm-fails cycle.

**Fix: a dedicated `BackfillLock` port** (`application/ports/
backfill_lock.py`), deliberately separate from `IngestionWatermarkRepository`
rather than folding physical-connection lifetime back into a repository
whose job is persisting state, not owning a connection's lifetime.
`PostgresBackfillLock` (`infrastructure/db/backfill_lock.py`) acquires
its OWN dedicated `AsyncConnection` directly from the engine
(`engine.connect()`, not an ORM `Session`) with `AUTOCOMMIT` isolation
(avoids holding an idle transaction open for a potentially long
backfill's whole duration — the lock itself needs no transaction),
pinned for the lock's entire held duration via one `async with` block —
structurally immune to the connection churn that broke the original
design, not just empirically lucky. `pg_advisory_unlock`'s return value
is now checked and raises if it ever reports `false` (a stranded lock),
rather than being silently discarded as before.

**Verification**: the original `test_concurrent_backfills_for_the_same_
series_do_not_race` kept (now using the fixed lock); a new
`test_concurrent_backfills_do_not_race_even_under_forced_pool_churn`
adds a severely constrained, heavily-churning pool (`pool_size=2`,
one-candle pages) for the two workers' OWN sessions specifically, while
the lock uses a separate, unconstrained engine — proving the fix holds
by construction regardless of how much the other sessions' pool
churns, run across 5 trials per test invocation. A fast, in-memory
complement (`test_shared_fake_lock_serializes_concurrent_backfills`,
`FakeBackfillLock` backed by a real `asyncio.Lock`) covers the same
property without needing Postgres. Full suite: 604 passed, same 7
pre-existing/unrelated live-OANDA failures. Lint/format/mypy/
pre-commit clean.

## 2026-09-19 — Third-round review: two small FX-29H/FX-31H follow-ups

**FX-29H — `reset()` wasn't truly unconditional.** Caught by external
review: `run_backtest_incremental`'s empty-`candles` early return
happened BEFORE `strategy.reset()`, despite the docstring already
claiming "called unconditionally." Confirmed directly (not assumed): a
strategy warmed by a real call, then called again with `[]`, still had
its prior EMA state intact immediately afterward. Fixed by moving
`reset()` to the literal first line of the function, before even that
early return — not by softening the documented claim to match the
looser behavior. New regression test checks the strategy's internal
state directly after the empty call (not via a later call, which would
reset it anyway and mask the bug). Regression-proof discipline applied:
reverted, confirmed the new test fails, restored, confirmed it passes.

**FX-31H — a pool-starvation deadlock the connection-pinning fix
didn't address.** External review identified a specific, well-reasoned
scenario: `pg_advisory_lock` blocks while holding a checked-out
connection. If the lock and the `candles`/`watermarks` sessions share
one pool, two concurrent backfills for the same series can deadlock —
A holds the lock on connection 1; B blocks on connection 2 waiting for
it; A now needs a connection for its own `get_watermark`/`upsert_many`
work (to finish and release the lock) but the pool has none left; B
can't release connection 2 until A releases the lock; neither can
proceed. Real for a small enough pool, and the review correctly noted
this project's own strongest test (`test_concurrent_backfills_do_not_
race_even_under_forced_pool_churn`) already used separate engines for
the lock and the workers — proving the SAFE pattern works, while the
actual composition root (`scripts/build_research_dataset.py`) used
`get_engine()` for both, the UNSAFE pattern. Confirmed directly before
fixing: read through the exact composition and verified it does share
one engine.

Not currently triggered — `build_research_dataset.py` runs its
backfills sequentially, so at most one `BackfillCandles` call is ever
active, needing at most 2 connections (one for its lock, one for its
worker session) against the default pool's much larger capacity. The
review's own point stands: this is a latent structural risk for
whatever future scheduler FX-31 was meant to make safe, not a bug in
current behavior.

**Fix**: new `get_lock_engine()` (`infrastructure/db/session.py`) — a
SEPARATE, dedicated engine (own connection pool) specifically for
`PostgresBackfillLock`, never shared with `get_engine()`. Its own
docstring spells out the deadlock scenario explicitly, at the exact
point future composition code would look, matching this project's
practice of documenting a requirement where someone would actually
encounter it, not just in a commit message. `build_research_dataset.py`
and every test constructing `PostgresBackfillLock` updated to use it —
`get_engine()` is no longer used for lock construction anywhere in the
codebase, establishing one unambiguous convention rather than two
interchangeable-looking options. `BackfillLock`'s port docstring and
`PostgresBackfillLock`'s own docstring both updated to state the
separate-pool requirement as a MUST, not a suggestion.

**Considered and not built**: a non-blocking `pg_try_advisory_lock`
polling loop (releasing the connection between attempts) as
defense-in-depth even if a future caller ignores the separate-engine
requirement. Decided against for now — the dedicated-engine fix
already eliminates the specific deadlock class structurally, and a
polling loop is real added complexity to the tested, working blocking-
lock semantics for a risk that's already closed. Flagged, not built,
matching this project's practice of naming a real future option rather
than silently deciding for the user.

**Verification**: full suite (unit + integration, live Postgres)
green — 605 passed, same 7 pre-existing/unrelated live-OANDA failures.
The concurrency tests (including the forced-pool-churn one) all still
pass using the new `get_lock_engine()` throughout. Lint/format/mypy/
pre-commit clean.

## 2026-09-19 — Research dataset run 1/6: FX-32, control strategies

First of six planned runs of the existing concrete strategies across
the full 10-year, 5-instrument research dataset, per the same external
review's own closing recommendation: pause infrastructure hardening,
use the now-trustworthy capability to find real economic questions
faster than more platform work would. Ordered cheapest-and-most-
foundational first: controls establish the no-skill baseline every
later strategy's numbers get read against.

**Scope check, timed not assumed**: all four control strategies are
O(1) per `evaluate()` call (only ever look at the last 1-2 candles);
`run_backtest`'s own O(n) reslicing is the only cost, and empirically
that's cheap (~30s for a full 62,000-candle series) — no incremental
engine needed, ran directly on the existing slow path.
`NoTradeStrategy` trivially produces zero trades everywhere by
definition (`compute_metrics` can't even be called on an empty list) —
not run, its "result" is definitionally unconditional.

**Results, full 10-year H1, all 5 instruments:**

| Strategy | Instrument | n | win rate | expectancy | profit factor | Sharpe |
|---|---|---|---|---|---|---|
| AlwaysLong | EUR_USD | 1 | 1.000 | +0.03129 USD | n/a | n/a |
| AlwaysLong | GBP_USD | 1 | 1.000 | +0.03557 USD | n/a | n/a |
| AlwaysLong | USD_JPY | 1 | 1.000 | +54.988 JPY | n/a | n/a |
| AlwaysLong | USD_CAD | 1 | 1.000 | +0.07744 CAD | n/a | n/a |
| AlwaysLong | XAU_USD | 1 | 1.000 | +3062.62 USD | n/a | n/a |
| AlwaysShort | (all 5) | 1 | 0.000 | exact negative of AlwaysLong | 0.000 | n/a |
| PreviousBarDirection | EUR_USD | 32070 | 0.275 | -0.00020 USD | 0.639 | -0.141 |
| PreviousBarDirection | GBP_USD | 32081 | 0.271 | -0.00029 USD | 0.626 | -0.148 |
| PreviousBarDirection | USD_JPY | 31953 | 0.288 | -0.02015 JPY | 0.712 | -0.098 |
| PreviousBarDirection | USD_CAD | 32147 | 0.265 | -0.00028 CAD | 0.577 | -0.174 |
| PreviousBarDirection | XAU_USD | 30452 | 0.296 | -0.50228 USD | 0.776 | -0.058 |

**Findings**: `AlwaysLong`/`AlwaysShort` are exactly one buy-and-hold/
sell-and-hold trade each, as designed — every instrument in this
10-year window ended up net favorable to being long (matches real
macro history: broad USD strength/JPY weakness over the period, and a
substantial gold rally), confirming these behave as intended, not a
finding about skill.

`PreviousBarDirectionStrategy` is the first genuinely decisive result
this whole project has produced: **consistently unprofitable across
every single instrument**, with profit factor well below 1.0 (0.58-0.78)
and negative Sharpe throughout, at `n` = 30,000-32,000 trades per
instrument — several orders of magnitude past FX-21/23's own `n=26`/
`n=57` samples that were explicitly flagged as too small to draw
conclusions from. This sample size, on this data, supports an actual
conclusion: naively chasing the previous H1 bar's direction is not a
free edge, and the effect is large and consistent enough that it's very
unlikely to be sampling noise. Plausible mechanism (not verified
further here): H1 bar-to-bar direction is closer to noise than trend,
and 30,000+ round-trip trades each paying the bid/ask spread compounds
into a large, structural drag — exactly the kind of "looks like
momentum, is actually noise plus transaction costs" trap control
strategies exist to catch.

**Verification**: existing `run_backtest`/`simulate_trades`/
`compute_metrics` pipeline, completely unmodified — this story is pure
empirical analysis, no new production code. Timed: ~30s/instrument,
~10 minutes total for all three non-trivial control strategies across
all 5 instruments.

## 2026-09-19 — Research dataset run 2/6: FX-33, TimeSeriesMomentumStrategy

`TimeSeriesMomentumStrategy` (FX-16), default parameters
(`lookback=20`, `threshold=0`): O(1) per call (direct indexing —
`candles[-1]`/`candles[-(lookback+1)]`, no full-list rescans), timed
directly at ~30s/instrument, same profile as the controls — no
incremental engine needed.

**Results, full 10-year H1, all 5 instruments:**

| Instrument | n | win rate | expectancy | profit factor | Sharpe |
|---|---|---|---|---|---|
| EUR_USD | 6056 | 0.295 | -0.00015 USD | 0.854 | -0.047 |
| GBP_USD | 6166 | 0.285 | -0.00026 USD | 0.817 | -0.057 |
| USD_JPY | 6148 | 0.292 | -0.00328 JPY | 0.974 | -0.007 |
| USD_CAD | 6482 | 0.267 | -0.00031 CAD | 0.734 | -0.090 |
| XAU_USD | 5895 | 0.303 | +0.22268 USD | 1.057 | +0.012 |

**Findings**: unprofitable on 4 of 5 instruments (profit factor
0.73-0.97, negative Sharpe, negative expectancy) at a large sample
size (n=6,000-6,500 per instrument — comparable in scale to FX-32's
own decisive result). `XAU_USD` is the one exception: marginally
profitable (profit factor 1.057, Sharpe +0.012), though the margin is
thin enough that "marginally positive" is a fair characterization, not
"a real edge" — worth noting rather than either dismissing or
overselling. Directionally consistent with FX-32's `PreviousBarDirection`
finding: simple H1 momentum, in either its 1-bar (control) or 20-bar
(this story) form, does not clear transaction costs on FX pairs in
this dataset; gold is the one instrument where trend-following
patterns come closer to (or, here, just past) breaking even.

**Verification**: existing pipeline unmodified, pure empirical
analysis. ~30s/instrument, ~3 minutes total.

## 2026-09-19 — Research dataset run 3/6: FX-34, CloseChannelBreakoutStrategy

`CloseChannelBreakoutStrategy` (FX-15), default `lookback=20`: O(n) per
call (builds a full closes list every call even though only the last
`lookback` values are used) — actual timing came in at ~640s/instrument
(~10.7 min), somewhat higher than the ~7.6 min extrapolated from the
4,000-candle sample, but still a tolerable one-off run (~53 minutes
total for all 5 instruments) without needing an incremental engine.

**Results, full 10-year H1, all 5 instruments:**

| Instrument | n | win rate | expectancy | profit factor | Sharpe |
|---|---|---|---|---|---|
| EUR_USD | 2065 | 0.343 | -0.00024 USD | 0.883 | -0.045 |
| GBP_USD | 2127 | 0.349 | -0.00035 USD | 0.877 | -0.045 |
| USD_JPY | 1948 | 0.367 | +0.01965 JPY | 1.077 | +0.024 |
| USD_CAD | 2102 | 0.328 | -0.00038 CAD | 0.836 | -0.064 |
| XAU_USD | 1894 | 0.356 | +1.55841 USD | 1.200 | +0.049 |

**Findings**: genuinely mixed, not uniform like FX-32/33's results —
unprofitable on 3 of 5 (`EUR_USD`/`GBP_USD`/`USD_CAD`, profit factor
0.84-0.88) and profitable on 2 of 5 (`USD_JPY`/`XAU_USD`, profit
factor 1.08/1.20), at n=1,900-2,100 trades per instrument — a smaller
sample than FX-32/33's but still ~35-80x FX-21/23's own flagged-
as-too-small samples. No obvious pattern separates the winning pair
from the losing three (not "majors vs. minors," not "USD-base vs.
USD-quote") — worth naming as an open question rather than reaching
for a story. This is the first strategy in this batch where "does it
work" genuinely depends on which instrument you ask, rather than a
clean project-wide answer.

**Verification**: existing pipeline unmodified, pure empirical
analysis. ~10.7 min/instrument, ~53 minutes total.

## 2026-09-19 — Research dataset run 4/6: FX-35, MeanReversionStrategy

`MeanReversionStrategy` (FX-19), default `period=20`,
`entry_threshold=2.0`: O(n) per call (same full-closes-list-per-call
pattern as FX-34), ~600-645s/instrument actual — consistent with
FX-34's own timing, no incremental engine needed.

**Results, full 10-year H1, all 5 instruments:**

| Instrument | n | win rate | expectancy | profit factor | Sharpe |
|---|---|---|---|---|---|
| EUR_USD | 2555 | 0.616 | -0.00003 USD | 0.977 | -0.008 |
| GBP_USD | 2537 | 0.614 | -0.00017 USD | 0.912 | -0.031 |
| USD_JPY | 2274 | 0.602 | -0.05535 JPY | 0.739 | -0.092 |
| USD_CAD | 2514 | 0.627 | -0.00005 CAD | 0.968 | -0.011 |
| XAU_USD | 2236 | 0.618 | -1.47744 USD | 0.782 | -0.062 |

**Findings**: unprofitable on **every single instrument** (profit
factor 0.74-0.98, all below breakeven) at n=2,200-2,555 trades each —
as decisive and consistent as FX-32's `PreviousBarDirection` result.
Notably, this happens **despite a consistently high win rate**
(0.60-0.63 across all five) — the classic mean-reversion signature of
many small wins offset by a smaller number of larger losses, where the
strategy is "usually right" bar-by-bar but structurally loses money
overall. This is a genuinely informative failure mode, distinct from
FX-32/33's "loses because win rate is low": a strategy can look
statistically appealing on win rate alone and still be a net loser —
exactly the kind of thing `compute_metrics`' full field set (not just
win rate) exists to catch.

**Verification**: existing pipeline unmodified, pure empirical
analysis. ~10.5 min/instrument, ~53 minutes total.

## 2026-09-19 — Research dataset run 5/6: FX-36, VolatilityExpansionBreakoutStrategy

`VolatilityExpansionBreakoutStrategy` (FX-20), default parameters
(`short_period=14`, `long_period=50`, `breakout_lookback=20`,
`expansion_threshold=1.5`), run via the new
`IncrementalVolatilityExpansionBreakoutStrategy` (this story's own
first part) — measured 2.3-2.6s/instrument, down from an extrapolated
92 minutes each.

**Results, full 10-year H1, all 5 instruments:**

| Instrument | n | win rate | expectancy | profit factor | Sharpe |
|---|---|---|---|---|---|
| EUR_USD | 14 | 0.286 | -0.00293 USD | 0.189 | -0.471 |
| GBP_USD | 11 | 0.364 | -0.00256 USD | 0.452 | -0.222 |
| USD_JPY | 27 | 0.519 | +0.00111 JPY | 1.003 | +0.001 |
| USD_CAD | 11 | 0.182 | -0.00230 CAD | 0.056 | -0.871 |
| XAU_USD | 19 | 0.316 | -17.04568 USD | 0.116 | -0.500 |

**Findings, read with real caution — unlike FX-32/33/35's samples**:
the double condition (fresh Donchian breakout AND simultaneous ATR
expansion above 1.5x) is rare at H1 with these default parameters —
n=11-27 trades per instrument over 10 years, closer to FX-21/23's own
flagged-as-too-small samples than to this batch's other, much larger
runs. Where a pattern IS visible, it's negative: 4 of 5 instruments
show poor profit factors (0.06-0.45), and `USD_JPY` is the only one
near breakeven (profit factor 1.003) — but at n=27, "near breakeven"
isn't a finding either way. Unlike FX-32/34/35, this result does not
support a confident conclusion about the strategy itself; it does
confirm the *engine* works correctly (verified separately, in depth,
via golden parity tests including a hand-constructed exact-threshold
boundary case — see the incremental-engine commit). A meaningfully
looser parameterization (lower `expansion_threshold` or shorter
`breakout_lookback`) would likely be needed before this strategy's
real performance question could be answered with a large enough
sample — not attempted here, flagged as a possible follow-up rather
than pursued in this story.

**Verification**: golden-parity-tested incremental engine (own commit).
This run: 2.3-2.6s/instrument, under 15 seconds total for all 5.

## 2026-09-19 — Research dataset run 6/6: FX-37, MultiTimeframeTrendStrategy (engine)

The sixth and final strategy in the user-authorized batch, and the only
one of the six genuinely requiring a new incremental engine solely
because of its shape (two candle series), not its cost — `Multi
TimeframeTrendStrategy`'s per-call work is dominated by refiltering and
recomputing the whole H4 EMA from scratch every H1 bar, an O(n) cost
per call the other five strategies mostly don't share.

`IncrementalStrategy.on_candle` (FX-29) only ever receives one candle
stream. `MultiTimeframeTrendStrategy` itself already solves the
two-series problem by taking the full H4 series as a constructor
argument (legitimate for backtesting) and filtering it by visibility on
every call — `IncrementalMultiTimeframeTrendStrategy` keeps that exact
same shape, but replaces the per-call refilter with an internal cursor
that advances into the pre-supplied H4 series as H1 time progresses,
feeding each newly-visible H4 candle into a reused `IncrementalSma
SeededEma` pair exactly once, in order, the moment it becomes visible.
Visibility still uses the shared, canonical `candle_boundary.
candle_end_time` (FX-25H) — not duplicated.

Two subtleties, both worked through by hand before writing any code,
not discovered by trial and error:

1. The slow strategy's own `len(candles) < h1_slow_period + 1: return
   None` guard looks like a separate gate from EMA readiness, but
   turns out to be *exactly* equivalent to "the H1 EMA doesn't have a
   second diff value to compare yet" — confirmed by working through
   `_sma_seeded_ema`'s own list-length arithmetic. That means
   granularity/instrument validation is unreachable during H1 warm-up
   in the slow strategy, and the incremental version reproduces that
   for free just by placing its own equivalent checks in the same
   relative position, rather than needing a separate counter.
2. The slow strategy's own `_h4_bias` requires `slow_period + 1`
   *visible* H4 candles before computing anything — one more than
   `_sma_seeded_ema` itself needs to produce a value. An incremental H4
   EMA tracker naturally becomes "ready" one candle earlier than that,
   so the incremental engine needed an explicit extra counter
   (`_h4_consumed_count`) gating bias reads at `slow_period + 1`, not
   just EMA non-None-ness. This is a real, not hypothetical, gap:
   confirmed via the same regression-proof discipline as FX-36's own
   exact-threshold case — temporarily removed the counter, watched a
   dedicated new test fail (a bias got computed one candle early) while
   every other parity test still passed, then restored it.

Golden-parity-tested against the unmodified slow strategy (which
remains the permanent reference): the exact hand-derived FX-25 series
(known trace: LONG/FLAT/LONG/SHORT), an independent longer sine-based
series exercising both confirmed and unconfirmed paths at default
periods, the FX-25H DST fall-back regression reused verbatim, and the
`_h4_consumed_count` edge case above — plus a trade-level fingerprint
check in `test_incremental_backtest_golden_parity.py`.

**Verification**: `pytest` (unit — including the deliberate
revert-and-confirm-failure step above), `ruff`, `mypy --strict`,
`pre-commit run --all-files`, full suite against live Postgres.

## 2026-09-19 — Research dataset run 6/6: FX-37, MultiTimeframeTrendStrategy (results)

`MultiTimeframeTrendStrategy` (FX-25), default parameters
(`h1_fast_period=20`, `h1_slow_period=50`, `h4_fast_period=20`,
`h4_slow_period=50`), run via `IncrementalMultiTimeframeTrendStrategy`
(this story's own first part) — ~3s/instrument for the full 10-year
H1+H4 pair, down from ~41 minutes extrapolated.

**Results, full 10-year H1 (confirmed by H4), all 5 instruments:**

| Instrument | n | win rate | expectancy | profit factor | Sharpe |
|---|---|---|---|---|---|
| EUR_USD | 426 | 0.317 | -0.00022 USD | 0.906 | -0.034 |
| GBP_USD | 457 | 0.304 | -0.00033 USD | 0.896 | -0.037 |
| USD_JPY | 425 | 0.339 | +0.08939 JPY | 1.306 | +0.084 |
| USD_CAD | 462 | 0.279 | -0.00022 CAD | 0.917 | -0.027 |
| XAU_USD | 431 | 0.316 | +2.27467 USD | 1.253 | +0.054 |

**Findings**: n=425-462 trades per instrument over 10 years — a solid
sample, same order of magnitude as FX-34's (not FX-36's too-small one).
Genuinely mixed, like FX-34: unprofitable on `EUR_USD`/`GBP_USD`/
`USD_CAD` (profit factor 0.90-0.92), profitable on `USD_JPY`/`XAU_USD`
(profit factor 1.25-1.31). No obvious shared property separates the
two winners from the three losers (same open question FX-34 left).
Notable, consistent across all 5 regardless of profitability: a LOW
win rate (0.28-0.34) — the classic trend/breakout-confirmation
signature (few larger wins carrying many small losses), the mirror
image of FX-35's mean-reversion strategy (high win rate, net loss
anyway).

**Correction (FX-38 Part G)**: this entry originally claimed H4
confirmation produces "a meaningfully higher trade count than a bare H1
EMA crossover would produce unfiltered" — that is backwards, and the
direct head-to-head this entry called a follow-up already existed at
the time: FX-29's own continuous rerun of `EmaCrossoverStrategy`
("Unconditional" leg) shows **1,106-1,205** trades per instrument over
the same 10-year window (EUR_USD 1165, GBP_USD 1181, USD_JPY 1119,
USD_CAD 1205, XAU_USD 1132), against this strategy's own 425-462. H4
confirmation materially **reduces** the number of EMA crossover trades
(to roughly a third), not increases it — every H1 crossover event still
fires, but most get closed straight back to FLAT by H4 disagreement
rather than opening/reversing a position. On USD_JPY and XAU_USD
specifically, the 2016-2026 results show that this smaller, reduced
trade set had a better profit factor/expectancy than the corresponding
bare H1 `EmaCrossoverStrategy` (FX-29's own continuous, non-withdrawn
table: USD_JPY 1.306 vs. 1.085; XAU_USD 1.253 vs. 1.129) — stated here
as what the 2016-2026 development data shows, not as a proven, durable,
or future improvement; see FX-38 for the pre-development historical
holdout evaluation of exactly this question.

**This closes the user-authorized batch** (external review's closing
recommendation, agreed 2026-09-19): every remaining concrete strategy
now has a real empirical run across the full 10-year, 5-instrument
research dataset. Summary across all six: two decisive/consistent
findings (FX-32's `PreviousBarDirectionStrategy`, unprofitable
everywhere; FX-35's `MeanReversionStrategy`, unprofitable everywhere);
two genuinely instrument-dependent findings with no identified
separating property (FX-34's `CloseChannelBreakoutStrategy`, FX-37's
`MultiTimeframeTrendStrategy`); one too-small-to-trust sample
(FX-36's `VolatilityExpansionBreakoutStrategy`, n=11-27); one thin/
marginal result (FX-33's `TimeSeriesMomentumStrategy`, breakeven-ish
on `XAU_USD` only). No strategy in this batch shows a strong, broad,
trustworthy edge across all 5 instruments.

**Verification**: golden-parity-tested incremental engine (previous
commit). This run: ~3s/instrument, ~15 seconds total for all 5.

## 2026-09-19 — FX-38 Parts A-C: historical coverage discovery, dataset extension, locked pre-development holdout protocol

**Context**: FX-32 through FX-37's results have already been inspected
and used to pick interesting strategy/instrument combinations (USD_JPY
and XAU_USD with `CloseChannelBreakoutStrategy`/`MultiTimeframeTrend
Strategy`). That makes 2016-2026 development/exploratory data, not an
untouched validation set — this story extends the dataset further back
and evaluates the SAME unchanged strategies on the newly-available
pre-2016 history as a genuine previously-unseen historical holdout.

### Part A — actual earliest OANDA availability, discovered not assumed

`scripts/discover_historical_coverage.py` (new): bounded, deterministic
binary search per `(instrument, granularity)` between a hardcoded,
deliberately absurd 1990-01-01 lower bound (confirmed empty for
EUR/USD H1 before writing the search) and each series' own currently
recorded earliest ingestion watermark (reused as the known-good upper
bound, not "2016-09-19" hardcoded). Each probe is an ordinary
`OandaMarketDataAdapter.get_candles(start, end)` call over a 60-day
window — no adapter changes, no new query mode. After convergence, a
wider extraction query pins down the exact earliest candle and, from
the same response, a density read on the opening ~90 days. A
monotonicity spot-check (a full year before the discovered boundary
must still be empty) ran for every series and held for all 10.

| Instrument | Granularity | Earliest candle (UTC) | Opening-era density (~90d) |
|---|---|---|---|
| EUR_USD | H1 | 2002-05-06T20:00:00 | 5.3% |
| EUR_USD | H4 | 2002-05-07T17:00:00 | 21.0% |
| GBP_USD | H1 | 2002-05-06T20:00:00 | 5.1% |
| GBP_USD | H4 | 2002-05-07T17:00:00 | 20.2% |
| USD_JPY | H1 | 2002-05-06T20:00:00 | 5.3% |
| USD_JPY | H4 | 2002-05-07T17:00:00 | 21.0% |
| USD_CAD | H1 | 2002-05-07T20:00:00 | 5.1% |
| USD_CAD | H4 | 2002-05-08T17:00:00 | 18.8% |
| XAU_USD | H1 | 2006-03-19T20:00:00 | 99.6% |
| XAU_USD | H4 | 2006-03-19T22:00:00 | 104.2% |

H1 vs. H4 start dates are NOT materially different for any instrument
(0-1 day apart) — H4 simply needs its own first bar to have closed.
The four FX pairs all technically begin within a two-day window of each
other (2002-05-06/07); XAU/USD begins nearly 4 years later
(2006-03-19), a real, not manufactured, difference — accepted as fact,
not forced onto a common start date.

**The opening-era density numbers above are the "obvious provider gap
near the beginning" Part A asks for.** A supplementary year-by-year
density probe (90-day Jan-Mar windows, same live adapter, not
committed as reusable infrastructure — a one-off characterization) found
where each series' density actually stabilizes:

- EUR_USD H1 (representative of all 4 FX pairs, confirmed structurally
  identical start dates and same order-of-magnitude opening density):
  2002 0.0% → 2003 5.5% → 2004 5.1% → **2005 103.4%** → stable ~100-105%
  every year through 2010. A real ~2.5-year thin/ramp-up era, then dense.
- XAU_USD: 2006 15.4% → **2007 98.8%** → stable ~97-101% through 2009. A
  shorter ~10-month thin era.

  **Correction (FX-38H)**: the XAU_USD row above is WRONG — a
  measurement artifact of this probe's own fixed Jan 1 - Mar 31
  calendar window, not XAU/USD's real behavior. XAU/USD's data doesn't
  begin until 2006-03-19; roughly 77 of that "2006" window's 90 days
  had zero candles because the data didn't exist yet, not because of a
  provider gap, dragging the reported average density down to ~15%
  even though the data that DOES exist from 2006-03-19 onward is
  already near-full density. FX-38H's own properly-anchored, objective
  algorithm (`scripts/determine_usable_history_start.py`) confirms
  this directly: XAU/USD needs NO ramp-up exclusion at all — its
  usable start equals its earliest available candle. See FX-38H's own
  entry below for the full correction; this row is left as originally
  written, not silently edited, with the correction linked from here.

This is a genuine OANDA provider characteristic (electronic FX/gold
feed maturity in the early-to-mid 2000s) for the four FX pairs — not a
backfill defect, and not (per the correction above) something that
applies to XAU_USD the way originally described here.

### Part B — dataset extended backward; existing 2016-2026 data untouched

`scripts/extend_research_dataset_pre2016.py` (new): calls the existing,
unmodified `BackfillCandles` (FX-26) with each series' Part-A-discovered
earliest boundary as `start` — `BackfillCandles` already has backward
extension as a first-class case (`_extend_backward`, FX-26), so this is
pure reuse, not new backfill logic. Same OANDA Practice, bid+ask,
`CandleSource.NATIVE`, canonical H4 NY/DST alignment, pagination,
idempotent upsert, watermark, and separate backfill-lock (FX-31H)
machinery as every prior backfill in this project — nothing new needed.
Ran cleanly in one pass, no interruption:

| Instrument | New H1 candles | New H4 candles | Now covers (H1) |
|---|---|---|---|
| EUR_USD | 76,421 | 20,325 | 2002-05-06 → 2026-09-20 |
| GBP_USD | 76,208 | 20,217 | 2002-05-06 → 2026-09-20 |
| USD_JPY | 76,305 | 20,251 | 2002-05-06 → 2026-09-20 |
| USD_CAD | 76,096 | 20,163 | 2002-05-07 → 2026-09-20 |
| XAU_USD | 65,673 | 17,063 | 2006-03-19 → 2026-09-20 |

(Counts include a small forward top-up to "now" too, same as any
`BackfillCandles` call with `end=now` — the pre-existing 2016-2026
portion itself was never re-fetched or altered, per FX-26's own
watermark-driven idempotency.)

**Gap-check** (`scripts/check_research_dataset_gaps.py`, unmodified,
run over each series' full new range): 438,494 raw missing candle
slots, 86,911 unexplained after weekly-closure filtering. Every prior
research-dataset gap-check (FX-27H.1) already established this script's
own known, named limitation — no holiday calendar, so a holiday closure
always shows up as "unexplained" — and that limitation, not a defect,
explains the bulk of this too. A year-by-year breakdown (EUR_USD and
XAU_USD shown, representative) confirms the SAME pattern found in
Part A independently, from a completely different angle (gap counts,
not density sampling):

- EUR_USD: 2002 (3,938) / 2003 (6,003) / 2004 (6,025) unexplained gaps —
  the thin ramp-up era, then **2005: 0** — a perfectly clean year — then
  a steady ~20-60/year baseline (holiday closures, FX-27H.1's own
  already-understood signature) all the way through 2026, INCLUDING the
  already-trusted 2016-2026 range unchanged from before this story.
- XAU_USD: elevated but declining 2006-2011 (122→42), the same
  thin-ramp-up signature; 2012 onward stabilizes near ~350/year — this
  is FX-27H.1's own already-documented daily-settlement-gap signature
  (gold doesn't continue trading through OANDA's NY 17:00 rollover the
  way FX pairs do), confirmed there as a real provider characteristic,
  not new here.

**Conclusion, consistent with Part A**: the newly-added history is
genuinely usable from ~2005 (FX pairs) / ~2007 (XAU/USD) onward, with a
real, disclosed thin/unreliable stretch before that — not silently
smoothed over. No gaps were discovered outside the two already-
recognized categories (thin-era sparsity, holiday/settlement closures);
the already-existing 2016-2026 data shows an unchanged gap signature,
confirming this extension didn't disturb it.

### Part C — protocol, locked BEFORE any holdout strategy result is computed

**Development period**: `2016-09-19T00:00:00Z` through
`2026-09-19T00:00:00Z` (the already-backfilled, already-inspected
range FX-32 through FX-37 ran against). This data directly influenced
which strategy/instrument combinations this story treats as
candidates — it is NOT untouched validation and must never be
presented as such.

**Pre-development historical holdout**: for each instrument, its own
Part-A-discovered earliest available H1 candle through
`2016-09-18T23:00:00Z` (the last H1 candle strictly before the
development cutoff — a non-overlapping, candle-boundary-consistent
split; every candle is used in exactly one of the two periods).
Explicitly named **pre-development historical holdout**, not
"prospective" or "future" out-of-sample data — it is chronologically
EARLIER than the development period, but genuinely unseen by the
process that picked the current candidates. Its opening stretch
(pre-2005 for the four FX pairs, pre-2007 for XAU/USD) is real but
sparse data, disclosed above, not excluded — excluding it would be
indistinguishable from choosing a start date to make results look
better, which this story's own safeguards rule out. Where it matters,
results are read with that caveat, not hidden from it.

**Locked strategy parameters**: every strategy below runs with its
existing, already-shipped default constructor parameters, exactly as
they exist in `src/forex_agent/domain/strategies/` today. No
optimization, threshold search, lookback search, per-instrument
parameter change, or post-result adjustment occurs anywhere in this
story — locked before Part D's first holdout number is computed, not
after.

**Execution methodology, locked**: one continuous backtest per
`(strategy, instrument)`, from that instrument's Part-A earliest
candle through the present, using `run_backtest`/`run_backtest_
incremental` (whichever already has golden-parity-tested exactness for
that strategy) + unmodified `simulate_trades` — same N+1 execution,
executable bid/ask pricing with spread, current fill semantics, no-
look-ahead rules, and final-bar handling as every prior story. Trades
are then split into development/holdout buckets by `entry_time`, and
further into calendar-year and 2-year buckets for Part F. This is
DELIBERATELY continuous-then-sliced, not two independent truncated
runs, for `EmaCrossoverStrategy`, `EmaCrossoverTrendRegimeGatedStrategy`,
and `MultiTimeframeTrendStrategy` (all three already have golden-
parity-tested `IncrementalStrategy` engines, so this costs seconds):
warm-up state (EMA/ADX/H4 bias) carries continuously across the 2016
boundary exactly as a real continuously-running strategy would
experience it, rather than artificially reseeding at the boundary.

**One disclosed, deliberate deviation**: `CloseChannelBreakoutStrategy`
has no incremental engine (FX-34 didn't need one at 10-year scale; this
story's ~2.4x larger full-history range makes its O(n²) slow-engine cost
non-trivial). For `USD_JPY` and `XAU_USD` specifically — the two
instruments Part F's time-stability analysis needs fine-grained,
genuinely continuous slicing for — it still runs as one continuous
full-history call. For `EUR_USD`, `GBP_USD`, and `USD_CAD` (Part D/E
only, no Part F requirement for this strategy on those three), it runs
as two independent slow-engine calls — one over the development range,
one over the holdout range — to avoid paying full-history O(n²) cost
three times over for no analytical benefit. This introduces a small,
disclosed discontinuity at exactly the 2016 boundary for those three
(the strategy's own `lookback` warm-up reseeds there instead of
carrying over) — negligible against this dataset's scale, not a change
to strategy semantics, and named here explicitly rather than left
implicit. If `CloseChannelBreakoutStrategy`'s continuous full-history
run for `USD_JPY`/`XAU_USD` turns out impractical once measured, that
will be documented as a stopped experiment, not worked around by
changing what's being measured.

**No parameter tuning, no start-date adjustment, and no unfavorable-
year discarding will occur past this point in the story.** If any
locked strategy cannot be run unchanged for some instrument, that
specific experiment stops and is documented as such — nothing is
modified to improve its result.

## 2026-09-20 — FX-38 Parts D-F: pre-development historical holdout results

Executed exactly per the Part C protocol above, locked before any of
these numbers existed. All four strategies ran with their existing
default constructor parameters, unmodified. No parameter was changed
after seeing any result below.

**Shared H1 candle coverage** (same series every strategy in this story
runs against; not repeated per strategy/table below):

| Instrument | Holdout n | Holdout range | Dev n | Dev range |
|---|---|---|---|---|
| EUR_USD | 76,401 | 2002-05-06 .. 2016-09-18 | 62,218 | 2016-09-19 .. 2026-09-18 |
| GBP_USD | 76,188 | 2002-05-06 .. 2016-09-18 | 62,221 | 2016-09-19 .. 2026-09-18 |
| USD_JPY | 76,285 | 2002-05-06 .. 2016-09-18 | 62,235 | 2016-09-19 .. 2026-09-18 |
| USD_CAD | 76,076 | 2002-05-07 .. 2016-09-18 | 62,244 | 2016-09-19 .. 2026-09-18 |
| XAU_USD | 65,653 | 2006-03-19 .. 2016-09-18 | 59,131 | 2016-09-19 .. 2026-09-18 |

**A small, expected, disclosed numerical note before the tables**: every
trade count below differs by a handful of trades (never more than 3)
from this same strategy/instrument's own previously-published
2016-2026-only table (FX-29's continuous EMA/gated-EMA rerun, FX-37's
MultiTimeframeTrendStrategy table). This is the continuous-warm-up
effect named in Part C's protocol, not a discrepancy: EMA/ADX/H4-bias
state entering 2016-09-19 is now already "hot" from running
continuously since 2002/2006, instead of cold-starting at 2016-09-19
in isolation — a handful of trades right at the boundary that a
truncated run couldn't have produced become possible. Expected, and a
genuine fidelity improvement (a real continuously-running strategy
would also enter 2016 already warmed up), not an inconsistency between
stories.

### EmaCrossoverStrategy (ema_crossover_v1, defaults)

**Development 2016-2026**

| Instrument | n | L/S | Win% | AvgWin | AvgLoss | Expectancy | PF | TotalP&L | MaxDD | Sharpe | Sortino |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EUR_USD | 1166 | 583/583 | 0.317 | 0.00707 USD | -0.00351 USD | -0.00015 USD | 0.938 | -0.17170 USD | 0.25455 USD | -0.0211 | -0.0409 |
| GBP_USD | 1182 | 591/591 | 0.292 | 0.01044 USD | -0.00464 USD | -0.00024 USD | 0.927 | -0.28547 USD | 0.58531 USD | -0.0242 | -0.0505 |
| USD_JPY | 1121 | 561/560 | 0.312 | 1.07845 JPY | -0.45220 JPY | 0.02610 JPY | 1.084 | 29.26200 JPY | 27.28600 JPY | 0.0247 | 0.0500 |
| USD_CAD | 1208 | 604/604 | 0.269 | 0.00856 CAD | -0.00380 CAD | -0.00047 CAD | 0.830 | -0.56920 CAD | 0.79457 CAD | -0.0617 | -0.1188 |
| XAU_USD | 1137 | 569/568 | 0.293 | 37.08925 USD | -13.62037 USD | 1.23126 USD | 1.128 | 1399.93800 USD | 1188.55000 USD | 0.0292 | 0.0688 |

**Pre-development historical holdout**

| Instrument | n | L/S | Win% | AvgWin | AvgLoss | Expectancy | PF | TotalP&L | MaxDD | Sharpe | Sortino |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EUR_USD | 1443 | 721/722 | 0.278 | 0.01380 USD | -0.00583 USD | -0.00037 USD | 0.911 | -0.53931 USD | 0.72350 USD | -0.0289 | -0.0607 |
| GBP_USD | 1409 | 704/705 | 0.307 | 0.01510 USD | -0.00689 USD | -0.00015 USD | 0.969 | -0.20663 USD | 0.75885 USD | -0.0099 | -0.0201 |
| USD_JPY | 1448 | 724/724 | 0.286 | 1.03081 JPY | -0.45123 JPY | -0.02719 JPY | 0.916 | -39.36600 JPY | 61.57400 JPY | -0.0276 | -0.0508 |
| USD_CAD | 1453 | 727/726 | 0.281 | 0.01134 CAD | -0.00467 CAD | -0.00017 CAD | 0.950 | -0.24479 CAD | 0.60546 CAD | -0.0147 | -0.0333 |
| XAU_USD | 1170 | 585/585 | 0.303 | 21.35966 USD | -8.98312 USD | 0.19751 USD | 1.032 | 231.08800 USD | 632.90400 USD | 0.0099 | 0.0206 |

Plain EMA crossover: unprofitable in BOTH periods on EUR_USD/GBP_USD/
USD_CAD (PF < 1 throughout, consistent). USD_JPY **sign-flips**:
positive in development (PF 1.084) but negative in historical holdout
(PF 0.916, expectancy -0.02719 JPY). XAU_USD is positive in both
periods but materially weaker in holdout (expectancy +1.23126 USD dev
→ +0.19751 USD holdout, an 84% drop; PF 1.128 → 1.032, near breakeven).

### EmaCrossoverTrendRegimeGatedStrategy (ema_crossover_trend_regime_gated_v1, defaults)

**Development 2016-2026**

| Instrument | n | L/S | Win% | AvgWin | AvgLoss | Expectancy | PF | TotalP&L | MaxDD | Sharpe | Sortino |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EUR_USD | 296 | 148/148 | 0.311 | 0.00664 USD | -0.00401 USD | -0.00070 USD | 0.746 | -0.20756 USD | 0.20763 USD | -0.1058 | -0.1680 |
| GBP_USD | 307 | 152/155 | 0.326 | 0.01207 USD | -0.00539 USD | 0.00030 USD | 1.081 | 0.09068 USD | 0.12546 USD | 0.0231 | 0.0545 |
| USD_JPY | 293 | 119/174 | 0.317 | 1.23330 JPY | -0.52624 JPY | 0.03225 JPY | 1.090 | 9.44800 JPY | 19.51200 JPY | 0.0257 | 0.0522 |
| USD_CAD | 290 | 148/142 | 0.303 | 0.00806 CAD | -0.00420 CAD | -0.00048 CAD | 0.836 | -0.13936 CAD | 0.18406 CAD | -0.0623 | -0.1104 |
| XAU_USD | 313 | 142/171 | 0.304 | 48.08456 USD | -17.11848 USD | 2.67158 USD | 1.224 | 836.20400 USD | 627.31000 USD | 0.0464 | 0.1235 |

**Pre-development historical holdout**

| Instrument | n | L/S | Win% | AvgWin | AvgLoss | Expectancy | PF | TotalP&L | MaxDD | Sharpe | Sortino |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EUR_USD | 427 | 203/224 | 0.337 | 0.01195 USD | -0.00596 USD | 0.00008 USD | 1.020 | 0.03389 USD | 0.23118 USD | 0.0069 | 0.0137 |
| GBP_USD | 397 | 202/195 | 0.373 | 0.01346 USD | -0.00754 USD | 0.00029 USD | 1.062 | 0.11594 USD | 0.25537 USD | 0.0203 | 0.0411 |
| USD_JPY | 361 | 157/204 | 0.319 | 1.14065 JPY | -0.51848 JPY | 0.01005 JPY | 1.028 | 3.62800 JPY | 25.90500 JPY | 0.0091 | 0.0171 |
| USD_CAD | 348 | 179/169 | 0.273 | 0.00948 CAD | -0.00528 CAD | -0.00123 CAD | 0.677 | -0.42906 CAD | 0.42965 CAD | -0.1343 | -0.2251 |
| XAU_USD | 364 | 175/189 | 0.297 | 21.86471 USD | -10.38884 USD | -0.81910 USD | 0.888 | -298.15400 USD | 619.67300 USD | -0.0379 | -0.0768 |

ADX-gated EMA: EUR_USD flips the OTHER way (negative dev, PF 0.746 →
marginally positive holdout, PF 1.020 — a weak reversal, not read as a
finding either way). GBP_USD positive in both periods (PF 1.081 →
1.062), directionally consistent. USD_JPY positive in both, weaker in
holdout (PF 1.090 → 1.028, close to breakeven). USD_CAD negative in
both periods (PF 0.836 → 0.677). XAU_USD **sign-flips**: positive in
development (PF 1.224, one of this whole batch's stronger dev results)
but clearly negative in historical holdout (PF 0.888, expectancy
-0.81910 USD) — the same instrument FX-28's own development-only
table called out as ADX-gating's best case; that does not hold before
2016.

### MultiTimeframeTrendStrategy (multi_timeframe_trend_v1, defaults)

**Development 2016-2026**

| Instrument | n | L/S | Win% | AvgWin | AvgLoss | Expectancy | PF | TotalP&L | MaxDD | Sharpe | Sortino |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EUR_USD | 427 | 217/210 | 0.316 | 0.00665 USD | -0.00341 USD | -0.00022 USD | 0.904 | -0.09583 USD | 0.12253 USD | -0.0344 | -0.0620 |
| GBP_USD | 459 | 228/231 | 0.305 | 0.00979 USD | -0.00455 USD | -0.00018 USD | 0.944 | -0.08100 USD | 0.20419 USD | -0.0188 | -0.0389 |
| USD_JPY | 426 | 248/178 | 0.340 | 1.12477 JPY | -0.44236 JPY | 0.09105 JPY | 1.312 | 38.78800 JPY | 13.98000 JPY | 0.0853 | 0.1840 |
| USD_CAD | 464 | 246/218 | 0.278 | 0.00878 CAD | -0.00371 CAD | -0.00024 CAD | 0.912 | -0.10964 CAD | 0.20527 CAD | -0.0290 | -0.0618 |
| XAU_USD | 433 | 268/165 | 0.314 | 35.64818 USD | -13.05820 USD | 2.23988 USD | 1.250 | 969.86800 USD | 761.32000 USD | 0.0536 | 0.1306 |

**Pre-development historical holdout**

| Instrument | n | L/S | Win% | AvgWin | AvgLoss | Expectancy | PF | TotalP&L | MaxDD | Sharpe | Sortino |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EUR_USD | 545 | 246/299 | 0.277 | 0.01327 USD | -0.00571 USD | -0.00044 USD | 0.893 | -0.24061 USD | 0.45559 USD | -0.0369 | -0.0743 |
| GBP_USD | 527 | 260/267 | 0.309 | 0.01707 USD | -0.00654 USD | 0.00077 USD | 1.172 | 0.40730 USD | 0.20411 USD | 0.0485 | 0.1193 |
| USD_JPY | 539 | 284/255 | 0.308 | 1.08105 JPY | -0.42306 JPY | 0.04017 JPY | 1.137 | 21.65100 JPY | 19.91700 JPY | 0.0413 | 0.0899 |
| USD_CAD | 539 | 267/272 | 0.269 | 0.00976 CAD | -0.00437 CAD | -0.00056 CAD | 0.824 | -0.30149 CAD | 0.46224 CAD | -0.0606 | -0.1244 |
| XAU_USD | 452 | 230/222 | 0.325 | 21.94284 USD | -8.97188 USD | 1.08224 USD | 1.179 | 489.17300 USD | 224.51500 USD | 0.0504 | 0.1124 |

MultiTimeframeTrendStrategy: EUR_USD/USD_CAD negative in both periods
(consistent with development). GBP_USD **sign-flips** the favorable
way: negative development (PF 0.944) but positive historical holdout
(PF 1.172) — the one case in this whole story where holdout looks
BETTER than development. Read the same way as any other sign-flip in
this report: a genuine change of sign between periods, not evidence
this combination is now trustworthy — it was never a candidate this
story selected for. USD_JPY and XAU_USD (this story's own two MTT
candidates) are positive in both periods, directionally consistent,
materially weaker in holdout — see the candidate comparison below.

### CloseChannelBreakoutStrategy (close_channel_breakout_v1, defaults)

Per Part C's disclosed deviation: EUR_USD/GBP_USD/USD_CAD ran as two
independent slow-engine calls (development-only, holdout-only);
USD_JPY/XAU_USD ran as one continuous full-history call, trades then
split by `entry_time` (needed for Part F below).

**Development 2016-2026**

| Instrument | n | L/S | Win% | AvgWin | AvgLoss | Expectancy | PF | TotalP&L | MaxDD | Sharpe | Sortino |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EUR_USD | 2066 | 1033/1033 | 0.343 | 0.00537 USD | -0.00318 USD | -0.00025 USD | 0.883 | -0.50672 USD | 0.52286 USD | -0.0447 | -0.0779 |
| GBP_USD | 2128 | 1064/1064 | 0.349 | 0.00710 USD | -0.00435 USD | -0.00035 USD | 0.877 | -0.73961 USD | 0.84922 USD | -0.0448 | -0.0802 |
| USD_JPY | 1948 | 974/974 | 0.367 | 0.75107 JPY | -0.40361 JPY | 0.01982 JPY | 1.078 | 38.61300 JPY | 25.88800 JPY | 0.0246 | 0.0459 |
| USD_CAD | 2103 | 1052/1051 | 0.328 | 0.00589 CAD | -0.00344 CAD | -0.00038 CAD | 0.836 | -0.79698 CAD | 0.87862 CAD | -0.0645 | -0.1099 |
| XAU_USD | 1895 | 948/947 | 0.356 | 26.25799 USD | -12.08133 USD | 1.55492 USD | 1.200 | 2946.58000 USD | 536.38000 USD | 0.0486 | 0.1078 |

**Pre-development historical holdout**

| Instrument | n | L/S | Win% | AvgWin | AvgLoss | Expectancy | PF | TotalP&L | MaxDD | Sharpe | Sortino |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EUR_USD | 2564 | 1282/1282 | 0.350 | 0.00902 USD | -0.00496 USD | -0.00007 USD | 0.978 | -0.18267 USD | 0.53425 USD | -0.0072 | -0.0138 |
| GBP_USD | 2552 | 1276/1276 | 0.348 | 0.01091 USD | -0.00591 USD | -0.00005 USD | 0.988 | -0.12203 USD | 0.76036 USD | -0.0040 | -0.0080 |
| USD_JPY | 2358 | 1179/1179 | 0.358 | 0.71630 JPY | -0.38067 JPY | 0.01243 JPY | 1.051 | 29.31500 JPY | 28.30800 JPY | 0.0162 | 0.0307 |
| USD_CAD | 2560 | 1280/1280 | 0.336 | 0.00736 CAD | -0.00417 CAD | -0.00029 CAD | 0.895 | -0.74515 CAD | 1.02774 CAD | -0.0361 | -0.0673 |
| XAU_USD | 2157 | 1078/1079 | 0.363 | 14.29764 USD | -7.72250 USD | 0.28111 USD | 1.057 | 606.35400 USD | 500.99900 USD | 0.0187 | 0.0368 |

CloseChannelBreakoutStrategy: EUR_USD/GBP_USD/USD_CAD negative in both
periods, directionally consistent (PF stays < 1 throughout, though all
three creep closer to breakeven in holdout). USD_JPY and XAU_USD (this
story's own two CCB candidates) are positive in both periods — see the
candidate comparison below.

### The four candidate combinations, explicitly

| Combination | Dev n | Holdout n | Dev PF | Holdout PF | Dev Expectancy | Holdout Expectancy | Sign persisted? | Profitable both? | Read |
|---|---|---|---|---|---|---|---|---|---|
| USD_JPY + CloseChannelBreakoutStrategy | 1948 | 2358 | 1.078 | 1.051 | +0.01982 JPY | +0.01243 JPY | Yes | Yes | Positive in both periods, directionally consistent, modestly weaker in holdout |
| USD_JPY + MultiTimeframeTrendStrategy | 426 | 539 | 1.312 | 1.137 | +0.09105 JPY | +0.04017 JPY | Yes | Yes | Positive in both periods, directionally consistent but materially weaker in holdout (expectancy roughly halved) |
| XAU_USD + CloseChannelBreakoutStrategy | 1895 | 2157 | 1.200 | 1.057 | +1.55492 USD | +0.28111 USD | Yes | Yes | Positive in both periods but materially weaker in holdout (expectancy down ~82%), holdout close to breakeven |
| XAU_USD + MultiTimeframeTrendStrategy | 433 | 452 | 1.250 | 1.179 | +2.23988 USD | +1.08224 USD | Yes | Yes | Positive in both periods, directionally consistent but materially weaker in holdout (expectancy roughly halved) |

**None of the four candidate combinations flip sign, and all four have
solid holdout sample sizes (n=452-2358) — sufficient to assess, not
"insufficient holdout trades."** But none is "validated" either: every
one is measurably, sometimes substantially, weaker in the
pre-development holdout than in the development window that got it
selected as a candidate in the first place — exactly the regression-
to-the-mean pattern that picking "interesting" combinations from
already-inspected data should be expected to produce. By contrast, two
of the two comparison strategies (`EmaCrossoverStrategy` on USD_JPY,
`EmaCrossoverTrendRegimeGatedStrategy` on XAU_USD — the SAME two
instruments) outright sign-flip between periods. That the four
selected candidates merely weakened rather than flipped is a
meaningfully better outcome than the comparison strategies show on the
same instruments, but "weaker than development, still positive" is the
most this data supports — not evidence of a durable, tradeable edge.

### Part F: time-stability analysis (USD_JPY, XAU_USD)

Full available history (each instrument's own Part-A earliest candle
through the present), sliced into fixed, non-overlapping calendar
buckets from the SAME trade sets computed above — no separate reruns,
no per-period parameter changes. 2-year buckets primary; individual
years secondary. `n/a`/`-` cells are buckets with zero or one trade
(insufficient for Sharpe's sample-variance denominator). Every
`2026-2027`/`2026` row is a PARTIAL period — data runs through
2026-09-20, not a full 2027 — smaller `n` there is expected, not a
finding.

#### USD_JPY / EmaCrossoverStrategy (2-year buckets)

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2002-2003 | 12 | -1.62750 JPY | 0.322 | -0.4571 | 28.08000 JPY |
| 2004-2005 | 119 | -0.06445 JPY | 0.833 | -0.0602 | 14.46000 JPY |
| 2006-2007 | 227 | 0.04941 JPY | 1.164 | 0.0507 | 12.93700 JPY |
| 2008-2009 | 281 | -0.07543 JPY | 0.810 | -0.0752 | 40.88900 JPY |
| 2010-2011 | 267 | -0.07890 JPY | 0.698 | -0.1189 | 22.23200 JPY |
| 2012-2013 | 233 | 0.03423 JPY | 1.145 | 0.0418 | 8.57300 JPY |
| 2014-2015 | 231 | 0.01458 JPY | 1.059 | 0.0169 | 15.35800 JPY |
| 2016-2017 | 224 | 0.03078 JPY | 1.090 | 0.0263 | 15.03500 JPY |
| 2018-2019 | 230 | -0.00146 JPY | 0.993 | -0.0026 | 10.13500 JPY |
| 2020-2021 | 219 | 0.04061 JPY | 1.199 | 0.0497 | 13.23800 JPY |
| 2022-2023 | 211 | 0.03018 JPY | 1.069 | 0.0216 | 27.28600 JPY |
| 2024-2025 | 225 | 0.05910 JPY | 1.154 | 0.0488 | 12.35100 JPY |
| 2026-2027 | 90 | 0.01867 JPY | 1.051 | 0.0148 | 16.84300 JPY |

Oscillates on both sides of breakeven throughout the full 24-year
span — 6 of 13 buckets below PF 1.0, spread across early (2002-2005),
middle (2008-2011), and late (2018-2019) history, not concentrated in
one era. No single exceptional episode drives this strategy's result
on USD_JPY either way.

<details><summary>Individual years</summary>

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2002 | 4 | -2.57000 JPY | 0.065 | -1.0581 | 10.99000 JPY |
| 2003 | 8 | -1.15625 JPY | 0.480 | -0.2835 | 17.80000 JPY |
| 2004 | 10 | -0.95300 JPY | 0.363 | -0.3882 | 14.46000 JPY |
| 2005 | 109 | 0.01706 JPY | 1.060 | 0.0208 | 5.89900 JPY |
| 2006 | 112 | -0.01841 JPY | 0.947 | -0.0194 | 12.93700 JPY |
| 2007 | 115 | 0.11545 JPY | 1.457 | 0.1160 | 5.11200 JPY |
| 2008 | 165 | -0.18894 JPY | 0.592 | -0.1807 | 40.88900 JPY |
| 2009 | 116 | 0.08603 JPY | 1.283 | 0.0936 | 6.94500 JPY |
| 2010 | 127 | -0.08451 JPY | 0.714 | -0.1168 | 13.32500 JPY |
| 2011 | 140 | -0.07380 JPY | 0.679 | -0.1217 | 12.57500 JPY |
| 2012 | 119 | 0.01477 JPY | 1.084 | 0.0232 | 8.57300 JPY |
| 2013 | 114 | 0.05454 JPY | 1.183 | 0.0560 | 7.83800 JPY |
| 2014 | 95 | 0.14246 JPY | 1.704 | 0.1496 | 5.06300 JPY |
| 2015 | 136 | -0.07475 JPY | 0.732 | -0.0955 | 14.83700 JPY |
| 2016 | 116 | -0.00772 JPY | 0.982 | -0.0054 | 10.72100 JPY |
| 2017 | 108 | 0.07212 JPY | 1.299 | 0.0885 | 4.43700 JPY |
| 2018 | 112 | 0.05774 JPY | 1.302 | 0.0907 | 3.34700 JPY |
| 2019 | 118 | -0.05764 JPY | 0.717 | -0.1234 | 10.13500 JPY |
| 2020 | 124 | 0.01629 JPY | 1.074 | 0.0178 | 12.04800 JPY |
| 2021 | 95 | 0.07235 JPY | 1.400 | 0.1078 | 4.22800 JPY |
| 2022 | 97 | 0.07800 JPY | 1.160 | 0.0470 | 16.21700 JPY |
| 2023 | 114 | -0.01050 JPY | 0.973 | -0.0093 | 13.48200 JPY |
| 2024 | 112 | 0.07336 JPY | 1.163 | 0.0514 | 12.35100 JPY |
| 2025 | 113 | 0.04496 JPY | 1.140 | 0.0471 | 6.51300 JPY |
| 2026 | 90 | 0.01867 JPY | 1.051 | 0.0148 | 16.84300 JPY |

</details>

#### USD_JPY / EmaCrossoverTrendRegimeGatedStrategy (2-year buckets)

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2002-2003 | 1 | -5.04000 JPY | 0.000 | n/a | 5.04000 JPY |
| 2004-2005 | 34 | -0.41918 JPY | 0.277 | -0.4379 | 14.25200 JPY |
| 2006-2007 | 57 | 0.10423 JPY | 1.346 | 0.0982 | 4.92600 JPY |
| 2008-2009 | 59 | -0.07663 JPY | 0.833 | -0.0699 | 9.99500 JPY |
| 2010-2011 | 72 | -0.10822 JPY | 0.595 | -0.1979 | 8.61200 JPY |
| 2012-2013 | 59 | 0.25173 JPY | 2.008 | 0.2202 | 2.81500 JPY |
| 2014-2015 | 52 | -0.00021 JPY | 0.999 | -0.0003 | 9.74900 JPY |
| 2016-2017 | 67 | 0.21728 JPY | 1.545 | 0.1276 | 10.70600 JPY |
| 2018-2019 | 55 | 0.00864 JPY | 1.048 | 0.0162 | 3.46000 JPY |
| 2020-2021 | 40 | 0.18300 JPY | 1.982 | 0.1657 | 2.66700 JPY |
| 2022-2023 | 65 | -0.14202 JPY | 0.706 | -0.1123 | 19.36600 JPY |
| 2024-2025 | 59 | 0.19795 JPY | 1.487 | 0.1309 | 5.31600 JPY |
| 2026-2027 | 34 | -0.02653 JPY | 0.940 | -0.0182 | 13.22400 JPY |

More volatile than plain EMA (smaller per-bucket n), but still no
single dominant episode — strong and weak 2-year windows alternate
across the whole span, including well before 2016 (2012-2013's PF
2.008 predates development by 3-4 years).

<details><summary>Individual years</summary>

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2002 | 1 | -5.04000 JPY | 0.000 | n/a | 5.04000 JPY |
| 2003 | 0 | - | - | - | - |
| 2004 | 2 | -3.34500 JPY | 0.000 | -12.7853 | 6.69000 JPY |
| 2005 | 32 | -0.23631 JPY | 0.419 | -0.3803 | 7.56200 JPY |
| 2006 | 28 | -0.00004 JPY | 1.000 | -0.0000 | 2.51800 JPY |
| 2007 | 29 | 0.20490 JPY | 1.767 | 0.1716 | 2.50900 JPY |
| 2008 | 21 | -0.28833 JPY | 0.531 | -0.2493 | 9.99500 JPY |
| 2009 | 38 | 0.04037 JPY | 1.109 | 0.0382 | 6.30200 JPY |
| 2010 | 34 | -0.05976 JPY | 0.762 | -0.1088 | 2.85200 JPY |
| 2011 | 38 | -0.15158 JPY | 0.461 | -0.2764 | 6.90400 JPY |
| 2012 | 29 | 0.12097 JPY | 1.547 | 0.1302 | 2.79500 JPY |
| 2013 | 30 | 0.37813 JPY | 2.363 | 0.2861 | 2.00100 JPY |
| 2014 | 23 | 0.33570 JPY | 2.651 | 0.3278 | 2.06700 JPY |
| 2015 | 29 | -0.26662 JPY | 0.268 | -0.5483 | 8.89700 JPY |
| 2016 | 39 | 0.20228 JPY | 1.348 | 0.0942 | 10.70600 JPY |
| 2017 | 28 | 0.23818 JPY | 2.654 | 0.3078 | 1.54700 JPY |
| 2018 | 27 | -0.05407 JPY | 0.765 | -0.0888 | 2.43900 JPY |
| 2019 | 28 | 0.06911 JPY | 1.519 | 0.1531 | 1.12900 JPY |
| 2020 | 22 | 0.26555 JPY | 2.279 | 0.1868 | 2.66700 JPY |
| 2021 | 18 | 0.08211 JPY | 1.512 | 0.1546 | 1.25700 JPY |
| 2022 | 34 | -0.18962 JPY | 0.679 | -0.1185 | 16.78300 JPY |
| 2023 | 31 | -0.08981 JPY | 0.755 | -0.1168 | 4.50100 JPY |
| 2024 | 27 | 0.50807 JPY | 2.223 | 0.2614 | 5.31600 JPY |
| 2025 | 32 | -0.06372 JPY | 0.840 | -0.0651 | 4.09100 JPY |
| 2026 | 34 | -0.02653 JPY | 0.940 | -0.0182 | 13.22400 JPY |

</details>

#### USD_JPY / MultiTimeframeTrendStrategy (2-year buckets)

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2002-2003 | 0 | - | - | - | - |
| 2004-2005 | 41 | 0.04705 JPY | 1.163 | 0.0558 | 2.32200 JPY |
| 2006-2007 | 80 | -0.00961 JPY | 0.968 | -0.0105 | 13.15500 JPY |
| 2008-2009 | 115 | 0.06498 JPY | 1.180 | 0.0561 | 16.30700 JPY |
| 2010-2011 | 103 | -0.06567 JPY | 0.757 | -0.0901 | 10.94400 JPY |
| 2012-2013 | 90 | 0.15377 JPY | 1.736 | 0.1681 | 6.91000 JPY |
| 2014-2015 | 80 | 0.14239 JPY | 1.545 | 0.1222 | 5.95700 JPY |
| 2016-2017 | 88 | 0.01728 JPY | 1.060 | 0.0184 | 6.09200 JPY |
| 2018-2019 | 85 | 0.00805 JPY | 1.038 | 0.0126 | 6.31500 JPY |
| 2020-2021 | 76 | -0.05247 JPY | 0.777 | -0.0780 | 8.34900 JPY |
| 2022-2023 | 85 | 0.25706 JPY | 1.710 | 0.1909 | 4.34000 JPY |
| 2024-2025 | 87 | 0.22684 JPY | 1.631 | 0.1581 | 5.83500 JPY |
| 2026-2027 | 35 | -0.18463 JPY | 0.524 | -0.2215 | 8.71000 JPY |

**Notable**: this strategy's strongest 2-year windows are 2012-2013
(PF 1.736), 2022-2023 (1.710), and 2024-2025 (1.631) — the two most
recent buckets are among the best in the whole 22-year span, and both
fall inside the already-inspected development window. Pre-2016 history
does show comparably strong stretches too (2012-2015), so this is not
*purely* a 2016-2026 artifact, but the development period's own
apparent edge is measurably concentrated in a genuinely strong recent
run, not spread evenly — a real caveat on top of Part E's already-
weaker holdout numbers, not a contradiction of them.

<details><summary>Individual years</summary>

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2002 | 0 | - | - | - | - |
| 2003 | 0 | - | - | - | - |
| 2004 | 0 | - | - | - | - |
| 2005 | 41 | 0.04705 JPY | 1.163 | 0.0558 | 2.32200 JPY |
| 2006 | 39 | -0.13564 JPY | 0.643 | -0.1549 | 9.39500 JPY |
| 2007 | 41 | 0.11027 JPY | 1.491 | 0.1174 | 3.76000 JPY |
| 2008 | 69 | -0.03390 JPY | 0.920 | -0.0267 | 16.30700 JPY |
| 2009 | 46 | 0.21330 JPY | 1.803 | 0.2221 | 4.20800 JPY |
| 2010 | 51 | -0.00539 JPY | 0.981 | -0.0061 | 4.45000 JPY |
| 2011 | 52 | -0.12479 JPY | 0.508 | -0.2290 | 7.36100 JPY |
| 2012 | 45 | 0.08611 JPY | 1.566 | 0.1301 | 2.61800 JPY |
| 2013 | 45 | 0.22142 JPY | 1.834 | 0.1985 | 6.91000 JPY |
| 2014 | 29 | 0.38707 JPY | 2.820 | 0.2630 | 3.20400 JPY |
| 2015 | 51 | 0.00325 JPY | 1.011 | 0.0035 | 5.95700 JPY |
| 2016 | 47 | 0.00109 JPY | 1.003 | 0.0009 | 6.09200 JPY |
| 2017 | 41 | 0.03585 JPY | 1.163 | 0.0565 | 3.13700 JPY |
| 2018 | 43 | 0.16277 JPY | 1.963 | 0.2247 | 1.84800 JPY |
| 2019 | 42 | -0.15036 JPY | 0.423 | -0.3046 | 6.31500 JPY |
| 2020 | 46 | -0.14717 JPY | 0.422 | -0.2916 | 7.45400 JPY |
| 2021 | 30 | 0.09273 JPY | 1.453 | 0.1078 | 2.68500 JPY |
| 2022 | 41 | 0.40166 JPY | 2.009 | 0.2506 | 4.34000 JPY |
| 2023 | 44 | 0.12232 JPY | 1.373 | 0.1159 | 3.94400 JPY |
| 2024 | 46 | 0.27843 JPY | 1.631 | 0.1587 | 5.83500 JPY |
| 2025 | 41 | 0.16895 JPY | 1.630 | 0.1727 | 2.78100 JPY |
| 2026 | 35 | -0.18463 JPY | 0.524 | -0.2215 | 8.71000 JPY |

</details>

#### USD_JPY / CloseChannelBreakoutStrategy (2-year buckets)

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2002-2003 | 19 | -0.50474 JPY | 0.581 | -0.1894 | 17.78000 JPY |
| 2004-2005 | 208 | 0.03059 JPY | 1.123 | 0.0405 | 7.57700 JPY |
| 2006-2007 | 408 | -0.02284 JPY | 0.915 | -0.0313 | 20.56200 JPY |
| 2008-2009 | 367 | 0.10444 JPY | 1.380 | 0.1093 | 10.04800 JPY |
| 2010-2011 | 453 | -0.04503 JPY | 0.772 | -0.0924 | 23.58800 JPY |
| 2012-2013 | 383 | 0.05088 JPY | 1.274 | 0.0803 | 7.23200 JPY |
| 2014-2015 | 385 | 0.00013 JPY | 1.001 | 0.0002 | 21.36700 JPY |
| 2016-2017 | 380 | -0.00302 JPY | 0.989 | -0.0038 | 15.87700 JPY |
| 2018-2019 | 414 | -0.02932 JPY | 0.830 | -0.0666 | 16.84200 JPY |
| 2020-2021 | 396 | 0.00288 JPY | 1.016 | 0.0052 | 6.43900 JPY |
| 2022-2023 | 382 | 0.04119 JPY | 1.119 | 0.0394 | 25.88800 JPY |
| 2024-2025 | 379 | 0.06547 JPY | 1.192 | 0.0628 | 21.17200 JPY |
| 2026-2027 | 132 | 0.11061 JPY | 1.453 | 0.1099 | 4.42100 JPY |

Reasonably well distributed — the strongest 2-year window is the
partial, most-recent one (2026, n=132), and 2008-2009 (PF 1.380) is
the strongest full window; several negative windows (2002-2003,
2006-2007, 2010-2011, 2018-2019) are spread across early, middle, and
late history. No single episode dominates.

<details><summary>Individual years</summary>

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2002 | 9 | -1.04556 JPY | 0.255 | -0.5256 | 10.12000 JPY |
| 2003 | 10 | -0.01800 JPY | 0.982 | -0.0057 | 8.37000 JPY |
| 2004 | 9 | 0.11444 JPY | 1.132 | 0.0508 | 2.91000 JPY |
| 2005 | 199 | 0.02680 JPY | 1.121 | 0.0428 | 6.80600 JPY |
| 2006 | 213 | -0.09192 JPY | 0.690 | -0.1405 | 19.67800 JPY |
| 2007 | 195 | 0.05262 JPY | 1.220 | 0.0658 | 10.01500 JPY |
| 2008 | 189 | 0.11168 JPY | 1.399 | 0.1100 | 8.24500 JPY |
| 2009 | 178 | 0.09675 JPY | 1.359 | 0.1086 | 10.04800 JPY |
| 2010 | 195 | -0.00900 JPY | 0.958 | -0.0160 | 6.13700 JPY |
| 2011 | 258 | -0.07226 JPY | 0.608 | -0.1712 | 22.29700 JPY |
| 2012 | 203 | -0.00379 JPY | 0.976 | -0.0089 | 7.23200 JPY |
| 2013 | 180 | 0.11254 JPY | 1.511 | 0.1403 | 4.64000 JPY |
| 2014 | 182 | 0.07987 JPY | 1.461 | 0.1151 | 4.29600 JPY |
| 2015 | 203 | -0.07135 JPY | 0.732 | -0.1108 | 21.36700 JPY |
| 2016 | 189 | 0.01912 JPY | 1.060 | 0.0197 | 15.00400 JPY |
| 2017 | 191 | -0.02493 JPY | 0.897 | -0.0435 | 9.58600 JPY |
| 2018 | 194 | 0.01779 JPY | 1.106 | 0.0354 | 5.44500 JPY |
| 2019 | 220 | -0.07087 JPY | 0.598 | -0.1901 | 16.84200 JPY |
| 2020 | 203 | 0.01011 JPY | 1.052 | 0.0156 | 5.85000 JPY |
| 2021 | 193 | -0.00472 JPY | 0.971 | -0.0106 | 5.40600 JPY |
| 2022 | 176 | 0.11491 JPY | 1.324 | 0.1010 | 12.10800 JPY |
| 2023 | 206 | -0.02180 JPY | 0.936 | -0.0227 | 25.88800 JPY |
| 2024 | 197 | 0.04519 JPY | 1.129 | 0.0421 | 15.09700 JPY |
| 2025 | 182 | 0.08743 JPY | 1.265 | 0.0865 | 13.13700 JPY |
| 2026 | 132 | 0.11061 JPY | 1.453 | 0.1099 | 4.42100 JPY |

</details>

#### XAU_USD / EmaCrossoverStrategy (2-year buckets)

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2006-2007 | 201 | 0.27453 USD | 1.067 | 0.0208 | 107.10000 USD |
| 2008-2009 | 204 | 1.39765 USD | 1.220 | 0.0634 | 181.10000 USD |
| 2010-2011 | 224 | 1.96057 USD | 1.280 | 0.0846 | 178.84200 USD |
| 2012-2013 | 235 | -0.67845 USD | 0.911 | -0.0287 | 303.98600 USD |
| 2014-2015 | 226 | -0.91354 USD | 0.831 | -0.0603 | 349.65000 USD |
| 2016-2017 | 213 | -0.69004 USD | 0.889 | -0.0395 | 378.86900 USD |
| 2018-2019 | 236 | -1.13358 USD | 0.760 | -0.0896 | 368.08700 USD |
| 2020-2021 | 240 | 1.92753 USD | 1.299 | 0.0714 | 185.20900 USD |
| 2022-2023 | 227 | 0.28978 USD | 1.039 | 0.0122 | 488.74700 USD |
| 2024-2025 | 212 | 5.62613 USD | 1.470 | 0.1174 | 313.46000 USD |
| 2026-2027 | 89 | -1.00191 USD | 0.973 | -0.0088 | 1188.55000 USD |

A genuine "bad stretch" 2012-2019 (4 consecutive negative 2-year
windows) bracketed by positive windows on both sides (2006-2011 and
2020-2025) — not one exceptional episode, but a real multi-year regime
change mid-history worth naming plainly.

<details><summary>Individual years</summary>

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2006 | 85 | -0.26118 USD | 0.950 | -0.0178 | 106.70000 USD |
| 2007 | 116 | 0.66707 USD | 1.204 | 0.0553 | 83.80000 USD |
| 2008 | 88 | 3.93977 USD | 1.551 | 0.1410 | 174.50000 USD |
| 2009 | 116 | -0.53086 USD | 0.907 | -0.0331 | 164.71000 USD |
| 2010 | 112 | 0.84946 USD | 1.151 | 0.0549 | 164.77000 USD |
| 2011 | 112 | 3.07168 USD | 1.366 | 0.1061 | 178.84200 USD |
| 2012 | 118 | -2.50105 USD | 0.672 | -0.1416 | 295.12400 USD |
| 2013 | 117 | 1.15974 USD | 1.151 | 0.0409 | 221.86400 USD |
| 2014 | 107 | -0.74340 USD | 0.866 | -0.0461 | 201.11400 USD |
| 2015 | 119 | -1.06652 USD | 0.798 | -0.0748 | 188.19000 USD |
| 2016 | 115 | -1.49786 USD | 0.800 | -0.0739 | 378.86900 USD |
| 2017 | 98 | 0.25792 USD | 1.055 | 0.0191 | 135.80400 USD |
| 2018 | 118 | -0.97542 USD | 0.766 | -0.0976 | 151.54300 USD |
| 2019 | 118 | -1.29175 USD | 0.754 | -0.0867 | 262.66700 USD |
| 2020 | 112 | 4.00808 USD | 1.609 | 0.1194 | 185.20900 USD |
| 2021 | 128 | 0.10705 USD | 1.017 | 0.0055 | 171.23300 USD |
| 2022 | 122 | 0.34077 USD | 1.048 | 0.0151 | 239.05200 USD |
| 2023 | 105 | 0.23053 USD | 1.029 | 0.0091 | 440.51300 USD |
| 2024 | 115 | 1.26791 USD | 1.126 | 0.0380 | 313.46000 USD |
| 2025 | 97 | 10.79309 USD | 1.758 | 0.1780 | 259.93000 USD |
| 2026 | 89 | -1.00191 USD | 0.973 | -0.0088 | 1188.55000 USD |

</details>

#### XAU_USD / EmaCrossoverTrendRegimeGatedStrategy (2-year buckets)

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2006-2007 | 50 | -0.19580 USD | 0.960 | -0.0163 | 79.76000 USD |
| 2008-2009 | 68 | 1.82368 USD | 1.244 | 0.0693 | 119.15000 USD |
| 2010-2011 | 73 | 0.17356 USD | 1.022 | 0.0080 | 159.42000 USD |
| 2012-2013 | 79 | -0.99729 USD | 0.878 | -0.0362 | 251.95700 USD |
| 2014-2015 | 72 | -2.87260 USD | 0.570 | -0.1833 | 216.35400 USD |
| 2016-2017 | 59 | -4.46092 USD | 0.436 | -0.2901 | 344.30800 USD |
| 2018-2019 | 54 | -1.21628 USD | 0.792 | -0.0795 | 131.18000 USD |
| 2020-2021 | 61 | 9.49280 USD | 2.763 | 0.2403 | 69.93000 USD |
| 2022-2023 | 67 | 0.03664 USD | 1.004 | 0.0013 | 211.06400 USD |
| 2024-2025 | 60 | 0.45050 USD | 1.031 | 0.0098 | 244.87000 USD |
| 2026-2027 | 34 | 12.26765 USD | 1.301 | 0.0823 | 627.31000 USD |

**This is exactly the failure mode Part F was built to catch.** The
2020-2021 bucket (PF 2.763) is dramatically above every other window —
roughly double the next-best (2008-2009's 1.244) — and the individual-
year table below shows it concentrated specifically in 2020 (PF
3.797). FX-28's own development-only table already flagged XAU_USD as
ADX-gating's single strongest case; this full-history view shows that
result leans heavily on one exceptional 1-2 year episode (COVID-era
gold volatility), not a broadly distributed edge — consistent with,
and a concrete mechanism behind, this same combination's sign-flip
already shown in Part E above.

<details><summary>Individual years</summary>

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2006 | 17 | -3.57647 USD | 0.488 | -0.2962 | 71.70000 USD |
| 2007 | 33 | 1.54576 USD | 1.403 | 0.1312 | 35.06000 USD |
| 2008 | 34 | 4.05647 USD | 1.522 | 0.1274 | 71.19000 USD |
| 2009 | 34 | -0.40912 USD | 0.943 | -0.0210 | 68.11000 USD |
| 2010 | 34 | -2.28324 USD | 0.680 | -0.1644 | 159.42000 USD |
| 2011 | 39 | 2.31538 USD | 1.278 | 0.0861 | 108.04000 USD |
| 2012 | 43 | -0.64670 USD | 0.903 | -0.0337 | 154.02700 USD |
| 2013 | 36 | -1.41606 USD | 0.858 | -0.0401 | 251.95700 USD |
| 2014 | 37 | -3.74465 USD | 0.504 | -0.2251 | 146.67100 USD |
| 2015 | 35 | -1.95071 USD | 0.660 | -0.1321 | 70.95600 USD |
| 2016 | 28 | -8.68750 USD | 0.267 | -0.5102 | 274.02500 USD |
| 2017 | 31 | -0.64335 USD | 0.852 | -0.0502 | 78.46000 USD |
| 2018 | 29 | 0.52534 USD | 1.147 | 0.0470 | 50.26600 USD |
| 2019 | 25 | -3.23656 USD | 0.620 | -0.1699 | 127.82300 USD |
| 2020 | 29 | 14.45328 USD | 3.797 | 0.2809 | 69.93000 USD |
| 2021 | 32 | 4.99738 USD | 1.895 | 0.2064 | 66.55400 USD |
| 2022 | 39 | -0.89497 USD | 0.887 | -0.0353 | 211.06400 USD |
| 2023 | 28 | 1.33425 USD | 1.145 | 0.0413 | 181.47200 USD |
| 2024 | 32 | -1.08219 USD | 0.901 | -0.0316 | 244.87000 USD |
| 2025 | 28 | 2.20214 USD | 1.117 | 0.0387 | 236.58000 USD |
| 2026 | 34 | 12.26765 USD | 1.301 | 0.0823 | 627.31000 USD |

</details>

#### XAU_USD / MultiTimeframeTrendStrategy (2-year buckets)

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2006-2007 | 79 | 0.64658 USD | 1.171 | 0.0493 | 117.16000 USD |
| 2008-2009 | 76 | 1.17789 USD | 1.182 | 0.0563 | 133.44000 USD |
| 2010-2011 | 87 | 2.24254 USD | 1.329 | 0.0936 | 102.55000 USD |
| 2012-2013 | 93 | 1.06643 USD | 1.138 | 0.0373 | 223.19400 USD |
| 2014-2015 | 89 | 1.69562 USD | 1.380 | 0.1021 | 100.65700 USD |
| 2016-2017 | 85 | -1.17362 USD | 0.800 | -0.0718 | 276.47400 USD |
| 2018-2019 | 87 | -1.31511 USD | 0.733 | -0.0937 | 209.45200 USD |
| 2020-2021 | 91 | 3.18659 USD | 1.500 | 0.1033 | 119.33900 USD |
| 2022-2023 | 88 | 0.61347 USD | 1.094 | 0.0311 | 216.72900 USD |
| 2024-2025 | 77 | 9.22065 USD | 1.881 | 0.2036 | 160.60000 USD |
| 2026-2027 | 33 | 1.01424 USD | 1.027 | 0.0086 | 761.32000 USD |

Positive from 2006 through 2015 (5 consecutive windows), a genuine
negative stretch 2016-2019 (echoing plain EMA's own 2016-2019 weak
stretch above — the same instrument, same rough era, different
strategy), then positive again from 2020 on. The strongest window by
far is the most recent full one, 2024-2025 (PF 1.881, expectancy
+9.22 USD) — this strategy's development-period result leans on a
genuinely strong, genuinely recent stretch, similar to the USD_JPY/MTT
observation above.

<details><summary>Individual years</summary>

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2006 | 34 | -0.80000 USD | 0.849 | -0.0495 | 93.50000 USD |
| 2007 | 45 | 1.73956 USD | 1.664 | 0.1696 | 37.46000 USD |
| 2008 | 31 | 1.91419 USD | 1.211 | 0.0684 | 133.44000 USD |
| 2009 | 45 | 0.67067 USD | 1.142 | 0.0461 | 52.47000 USD |
| 2010 | 43 | -0.48791 USD | 0.916 | -0.0333 | 102.55000 USD |
| 2011 | 44 | 4.91093 USD | 1.628 | 0.1616 | 81.27600 USD |
| 2012 | 44 | -3.66202 USD | 0.539 | -0.2207 | 223.19400 USD |
| 2013 | 49 | 5.31239 USD | 1.701 | 0.1483 | 119.20100 USD |
| 2014 | 42 | 0.38969 USD | 1.089 | 0.0293 | 70.98500 USD |
| 2015 | 47 | 2.86262 USD | 1.633 | 0.1495 | 100.65700 USD |
| 2016 | 43 | -3.29970 USD | 0.571 | -0.1685 | 274.13600 USD |
| 2017 | 42 | 1.00307 USD | 1.251 | 0.0834 | 52.85100 USD |
| 2018 | 42 | -0.88588 USD | 0.799 | -0.0843 | 90.20600 USD |
| 2019 | 45 | -1.71573 USD | 0.684 | -0.1023 | 158.50300 USD |
| 2020 | 41 | 7.38900 USD | 2.161 | 0.1817 | 110.24500 USD |
| 2021 | 50 | -0.25938 USD | 0.959 | -0.0135 | 119.33900 USD |
| 2022 | 48 | 0.89671 USD | 1.142 | 0.0419 | 135.99200 USD |
| 2023 | 40 | 0.27358 USD | 1.041 | 0.0154 | 146.76400 USD |
| 2024 | 41 | 4.57561 USD | 1.483 | 0.1149 | 120.09000 USD |
| 2025 | 36 | 14.51083 USD | 2.253 | 0.2855 | 160.60000 USD |
| 2026 | 33 | 1.01424 USD | 1.027 | 0.0086 | 761.32000 USD |

</details>

#### XAU_USD / CloseChannelBreakoutStrategy (2-year buckets)

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2006-2007 | 353 | 0.47059 USD | 1.159 | 0.0516 | 122.60000 USD |
| 2008-2009 | 419 | -0.38413 USD | 0.936 | -0.0248 | 452.79000 USD |
| 2010-2011 | 434 | 0.89034 USD | 1.170 | 0.0513 | 234.82900 USD |
| 2012-2013 | 422 | 0.68062 USD | 1.116 | 0.0350 | 231.74600 USD |
| 2014-2015 | 379 | 0.21861 USD | 1.054 | 0.0193 | 189.24900 USD |
| 2016-2017 | 397 | -0.37052 USD | 0.914 | -0.0340 | 345.25800 USD |
| 2018-2019 | 390 | -0.36354 USD | 0.903 | -0.0343 | 255.70100 USD |
| 2020-2021 | 374 | 1.13145 USD | 1.166 | 0.0512 | 309.52000 USD |
| 2022-2023 | 387 | -0.12254 USD | 0.981 | -0.0071 | 423.71700 USD |
| 2024-2025 | 366 | 3.35519 USD | 1.295 | 0.0854 | 377.91000 USD |
| 2026-2027 | 131 | 11.27038 USD | 1.470 | 0.1293 | 536.38000 USD |

Positive/negative windows alternate throughout with no single episode
dominating; like the other three XAU_USD strategies, the two most
recent full windows (2024-2025, and the partial 2026) are the
strongest in the series — a consistent pattern across ALL FOUR
strategies on XAU_USD, worth naming as a single observation rather
than four separate coincidences (see below).

<details><summary>Individual years</summary>

| Period | n | Expectancy | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 2006 | 154 | 0.41169 USD | 1.118 | 0.0405 | 118.20000 USD |
| 2007 | 199 | 0.51618 USD | 1.202 | 0.0625 | 59.50000 USD |
| 2008 | 193 | 0.29979 USD | 1.044 | 0.0160 | 232.76000 USD |
| 2009 | 226 | -0.96819 USD | 0.814 | -0.0801 | 283.88000 USD |
| 2010 | 204 | -0.11902 USD | 0.975 | -0.0101 | 174.78000 USD |
| 2011 | 230 | 1.78559 USD | 1.315 | 0.0846 | 171.86600 USD |
| 2012 | 212 | 0.28545 USD | 1.051 | 0.0176 | 153.20300 USD |
| 2013 | 210 | 1.07956 USD | 1.175 | 0.0485 | 231.74600 USD |
| 2014 | 195 | 0.62836 USD | 1.170 | 0.0565 | 98.58100 USD |
| 2015 | 184 | -0.21563 USD | 0.950 | -0.0186 | 137.11000 USD |
| 2016 | 208 | -1.02928 USD | 0.800 | -0.0848 | 266.17000 USD |
| 2017 | 189 | 0.35447 USD | 1.106 | 0.0381 | 148.44200 USD |
| 2018 | 196 | -0.76361 USD | 0.780 | -0.0959 | 185.64400 USD |
| 2019 | 194 | 0.04064 USD | 1.010 | 0.0032 | 141.15100 USD |
| 2020 | 182 | 2.27394 USD | 1.309 | 0.0882 | 148.81000 USD |
| 2021 | 192 | 0.04846 USD | 1.008 | 0.0027 | 309.52000 USD |
| 2022 | 204 | -1.17701 USD | 0.832 | -0.0707 | 423.71700 USD |
| 2023 | 183 | 1.05295 USD | 1.179 | 0.0585 | 265.38000 USD |
| 2024 | 191 | 2.01361 USD | 1.266 | 0.0818 | 163.02000 USD |
| 2025 | 175 | 4.81943 USD | 1.311 | 0.0950 | 377.91000 USD |
| 2026 | 131 | 11.27038 USD | 1.470 | 0.1293 | 536.38000 USD |

</details>

### Part F conclusion — does the USD_JPY/XAU_USD trend/breakout behavior predate 2016?

**Yes — it is not purely a feature of the 2016-2026 macro environment.**
Every one of the 8 (instrument × strategy) time-series above shows
comparably strong 2-year windows well before 2016 (USD_JPY MTT and
gated-EMA both peak in 2012-2015; XAU_USD's four strategies all show
real positive stretches in 2006-2011) — this is not a pattern that
simply switched on in 2016.

**Correction (FX-38H, external review)**: this entry originally also
claimed "the two most recent full 2-year windows (2022-2025) are at or
near each series' own best... across ALL EIGHT series." That overstates
what the data actually shows — checked by ranking, not re-eyeballed:

| Series | 2022-2023 rank (of its own full 2-year buckets) | 2024-2025 rank |
|---|---|---|
| USD_JPY/EmaCrossoverStrategy | mid (6th of 12) | top-3 |
| USD_JPY/EmaCrossoverTrendRegimeGatedStrategy | low (11th of 13) | top-4 |
| USD_JPY/MultiTimeframeTrendStrategy | top-2 | top-3 |
| USD_JPY/CloseChannelBreakoutStrategy | mid (4th-5th of 12) | top-3 |
| XAU_USD/EmaCrossoverStrategy | mid (6th-7th of 10) | **best** |
| XAU_USD/EmaCrossoverTrendRegimeGatedStrategy | mid-low (4th-5th of 10) | mid-low (4th-5th) |
| XAU_USD/MultiTimeframeTrendStrategy | mid (6th-7th of 10) | **best** |
| XAU_USD/CloseChannelBreakoutStrategy | low (9th of 10) | **best** (excl. partial 2026-2027) |

**2024-2025 is genuinely near-best (top 4) in 7 of 8 series — the one
exception is XAU_USD/EmaCrossoverTrendRegimeGatedStrategy, where it is
merely mediocre.** But **2022-2023 is NOT** — it's mid-pack-to-weak in
7 of 8 series, genuinely strong in exactly one
(USD_JPY/MultiTimeframeTrendStrategy). Treating "2022-2025" as one
uniformly-strong recent stretch across all eight series, as originally
written, conflated a real pattern in ONE of its two 2-year buckets with
the other. The accurate statement: **the single 2024-2025 bucket
specifically (not the 2022-2025 pair of buckets) is commonly, though
not universally, one of each series' strongest windows** — real
corroborating evidence that the development period partly overlaps a
genuinely strong recent stretch, consistent with (not a replacement
for) Part E's own finding that holdout results come back weaker than
development without flipping sign — but a narrower, single-bucket
claim, not the two-bucket one this entry originally made.

XAU_USD/`EmaCrossoverTrendRegimeGatedStrategy` remains the one clear
exception to "no single episode dominates" either way: its apparent
edge is disproportionately one 2020-2021 episode (this table's own
2022-2023 AND 2024-2025 ranks for it are both mediocre, reinforcing
that its real driver is neither of the two originally-claimed recent
windows) — and that is also the one candidate-adjacent combination
that outright sign-flips in Part E.

## 2026-09-20 — FX-38H (part 1): objective usable-history threshold + sealed evaluation windows

External review of FX-38 (methodologically sound overall — accepted
Parts A/B, the Part G correction, and the strategy-parameter
discipline outright) raised two real gaps: FX-38's holdout period
started at the raw technical `earliest_available_candle` (including a
real but sparse ramp-up era, disclosed but not excluded by any
objective rule), and its dev/holdout split was a single continuous run
sliced by `entry_time` alone, which can let a trade whose entry and
exit straddle the boundary leak an out-of-period price into the
"wrong" period's metrics. FX-38H addresses both, with FX-38's own raw
history and findings preserved, not discarded — the external review's
own framing: "the outcome remains interesting... this is exactly where
methodological cleanliness matters most."

### Distinguishing `earliest_available_candle` from `earliest_usable_research_candle`

`scripts/determine_usable_history_start.py` (new, committed): an
OBJECTIVE, data-quality-driven rule, locked before running rather than
tuned to produce a particular answer — a 90-day window is "clean" if,
after excluding the standard forex weekly closure and (for XAU/USD's
H1 series specifically) its own documented daily settlement gap
(FX-27H.1), (a) coverage >= 95% and (b) no single run of consecutive
missing expected slots exceeds 72 hours. `earliest_usable_research_
candle` is the start of the first such window that stays clean for the
following 7 windows too (8 * 90 days ~= 2 years — "sustained", not one
lucky window). Runs entirely against the already-backfilled Postgres
dataset (FX-38 Part B) — no OANDA calls, and FX-38's raw 2002-2006
history is read, never deleted or modified.

| Instrument | Granularity | earliest_available_candle | earliest_usable_research_candle |
|---|---|---|---|
| EUR_USD | H1 | 2002-05-06 | 2005-01-20 |
| EUR_USD | H4 | 2002-05-07 | 2005-01-21 |
| GBP_USD | H1 | 2002-05-06 | 2005-01-20 |
| GBP_USD | H4 | 2002-05-07 | 2005-01-21 |
| USD_JPY | H1 | 2002-05-06 | 2005-01-20 |
| USD_JPY | H4 | 2002-05-07 | 2005-01-21 |
| USD_CAD | H1 | 2002-05-07 | 2005-01-21 |
| USD_CAD | H4 | 2002-05-08 | 2005-01-22 |
| XAU_USD | H1 | 2006-03-19 | 2006-03-19 |
| XAU_USD | H4 | 2006-03-19 | 2006-03-19 |

`MultiTimeframeTrendStrategy` usable start = the LATER of its own H1/H4
boundaries (per instrument, both already equal or one day apart, so
this changes nothing beyond the H1 figure above except USD_CAD, which
uses its own H4 date 2005-01-22).

**A genuine correction to FX-38's own Part A/B, caught by building this
properly rather than reusing the earlier informal probe**: XAU/USD's
usable start comes back as its OWN earliest available candle —
2006-03-19, no ramp-up exclusion at all. This directly contradicts
FX-38's own reported "XAU/USD opening-era density ~15.4% in 2006,
~98.8% from 2007" — and that earlier number was wrong, not XAU/USD's
real behavior: FX-38's informal probe sampled a fixed Jan 1 - Mar 31
calendar window for "2006," but XAU/USD's data didn't exist before
2006-03-19 — roughly 77 of that window's 90 days had zero candles
BECAUSE THE DATA DIDN'T EXIST YET, not because of any provider gap.
(85.6% zero-density days at ~0% density blended with ~13.5 days of
already-dense trading averages out to almost exactly the reported
15.4% — confirmed by direct arithmetic, not just plausible.) This
script's own first window is anchored to `earliest_ingested` itself,
not a calendar boundary, so it doesn't inherit that flaw. The four FX
pairs' ramp-up era (2002 through early 2005) IS real and reproduced
here consistently with FX-38's own finding — only XAU/USD's reported
ramp-up was a measurement artifact. `docs/CURRENT_STATE.md`/FX-38's
own entries are corrected accordingly; FX-38's raw data and every OTHER
finding stand unchanged.

### Sealed evaluation windows

`domain/sealed_window_backtest.py` (new): `run_sealed_window_backtest`
runs a strategy continuously across `warmup_candles + window_candles`
(so indicators are genuinely warmed up, not cold-started at the window
boundary — legitimate, since a real continuously-running strategy
would also enter any given day already warmed up), then returns only
the hypotheses generated at or after the window's own first candle —
discarding whatever position warm-up-only hypotheses would have
implied, so the portfolio provably starts flat at the window boundary.
Callers then pass those hypotheses to the existing, UNMODIFIED
`simulate_trades` alongside ONLY `window_candles` (never
`warmup_candles`) — `simulate_trades` already force-closes any open
position at the end of whatever `candles` it receives and already
refuses to execute a hypothesis generated on the final candle (no
next-bar price to use), so window-edge sealing falls out of composition
with existing, already-tested behavior rather than needing new
execution logic. A generic callable (`run_backtest`/`run_backtest_
incremental`) keeps this working for both engine types.

8 new tests (`tests/unit/domain/test_sealed_window_backtest.py`),
including two built on values confirmed by direct computation before
writing the assertion, matching this project's established practice
for boundary-sensitive tests: `test_warmup_actually_matters_not_a_
no_op` (cold-start vs. warmed-up hypothesis lists provably differ, not
just "should" differ) and `test_force_closes_at_the_windows_own_last_
candle_not_beyond` (a real trade confirmed to straddle a chosen window
boundary in a continuous run — entry inside, exit outside — then shown
to force-close at a different time AND price once sealed). Regression-
proof discipline applied: temporarily removed the hypothesis filter
(sealing became a no-op), confirmed 5 of 8 tests fail, restored,
confirmed all 8 pass again.

**Verification**: `pytest` (604 passed, unit/contract/replay), `ruff`,
`mypy --strict`, `pre-commit run --all-files`.

## 2026-09-20 — FX-38H (part 2): results — rerun from usable history, sealed windows

`scripts/run_fx38h_analysis.py` (new, committed — this IS the
reproducible source of every number below, not a markdown-only claim;
also writes `research_results/fx38h/results.json`, a machine-readable
artifact with full experiment config/metadata alongside every metric).
Same locked default strategy parameters as FX-38 throughout — nothing
tuned. Holdout windows now start at each series' own `earliest_usable_
research_candle` (FX-38H part 1) instead of the raw technical start;
every window (both holdout AND development, per the external review's
own criterion 8) is economically sealed (`domain.sealed_window_
backtest`): a 60-day explicit warm-up buffer before the window (>> the
longest locked period, 50), portfolio starts flat at the window's own
first candle, and force-close happens at the window's own last candle
— no trade's entry or exit price can come from outside its window.

### Development vs. holdout, by strategy (sealed windows, usable-history holdout start)

**EmaCrossoverStrategy**

| Instrument | Period | n | L/S | Win% | Expectancy | PF |
|---|---|---|---|---|---|---|
| EUR_USD | holdout | 1424 | 712/712 | 0.277 | -0.00044 USD | 0.893 |
| EUR_USD | development | 1166 | 583/583 | 0.317 | -0.00015 USD | 0.938 |
| GBP_USD | holdout | 1391 | 695/696 | 0.308 | -0.00012 USD | 0.975 |
| GBP_USD | development | 1182 | 591/591 | 0.292 | -0.00024 USD | 0.927 |
| USD_JPY | holdout | 1421 | 710/711 | 0.286 | -0.00812 JPY | 0.973 |
| USD_JPY | development | 1121 | 561/560 | 0.312 | +0.02610 JPY | 1.084 |
| USD_CAD | holdout | 1436 | 718/718 | 0.280 | -0.00026 CAD | 0.920 |
| USD_CAD | development | 1208 | 604/604 | 0.269 | -0.00047 CAD | 0.830 |
| XAU_USD | holdout | 1170 | 585/585 | 0.303 | +0.20195 USD | 1.032 |
| XAU_USD | development | 1137 | 569/568 | 0.293 | +1.23126 USD | 1.128 |

**EmaCrossoverTrendRegimeGatedStrategy**

| Instrument | Period | n | L/S | Win% | Expectancy | PF |
|---|---|---|---|---|---|---|
| EUR_USD | holdout | 424 | 203/221 | 0.335 | +0.00011 USD | 1.029 |
| EUR_USD | development | 296 | 148/148 | 0.311 | -0.00070 USD | 0.746 |
| GBP_USD | holdout | 395 | 202/193 | 0.372 | +0.00034 USD | 1.073 |
| GBP_USD | development | 307 | 152/155 | 0.326 | +0.00030 USD | 1.081 |
| USD_JPY | holdout | 357 | 155/202 | 0.322 | +0.04389 JPY | 1.136 |
| USD_JPY | development | 293 | 119/174 | 0.317 | +0.03225 JPY | 1.090 |
| USD_CAD | holdout | 346 | 177/169 | 0.275 | -0.00117 CAD | 0.688 |
| USD_CAD | development | 290 | 148/142 | 0.303 | -0.00048 CAD | 0.836 |
| XAU_USD | holdout | 364 | 175/189 | 0.297 | -0.80484 USD | 0.890 |
| XAU_USD | development | 313 | 142/171 | 0.304 | +2.67158 USD | 1.224 |

**MultiTimeframeTrendStrategy**

| Instrument | Period | n | L/S | Win% | Expectancy | PF |
|---|---|---|---|---|---|---|
| EUR_USD | holdout | 543 | 246/297 | 0.276 | -0.00043 USD | 0.895 |
| EUR_USD | development | 427 | 217/210 | 0.316 | -0.00022 USD | 0.904 |
| GBP_USD | holdout | 524 | 260/264 | 0.309 | +0.00081 USD | 1.181 |
| GBP_USD | development | 459 | 228/231 | 0.305 | -0.00018 USD | 0.944 |
| USD_JPY | holdout | 537 | 284/253 | 0.309 | +0.04227 JPY | 1.145 |
| USD_JPY | development | 426 | 248/178 | 0.340 | +0.09105 JPY | 1.312 |
| USD_CAD | holdout | 539 | 267/272 | 0.271 | -0.00055 CAD | 0.827 |
| USD_CAD | development | 464 | 246/218 | 0.278 | -0.00024 CAD | 0.912 |
| XAU_USD | holdout | 452 | 230/222 | 0.325 | +1.08224 USD | 1.179 |
| XAU_USD | development | 433 | 268/165 | 0.314 | +2.23988 USD | 1.250 |

**CloseChannelBreakoutStrategy**

| Instrument | Period | n | L/S | Win% | Expectancy | PF |
|---|---|---|---|---|---|---|
| EUR_USD | holdout | 2527 | 1263/1264 | 0.350 | -0.00007 USD | 0.977 |
| EUR_USD | development | 2066 | 1033/1033 | 0.343 | -0.00024 USD | 0.883 |
| GBP_USD | holdout | 2517 | 1258/1259 | 0.347 | -0.00012 USD | 0.969 |
| GBP_USD | development | 2129 | 1065/1064 | 0.349 | -0.00035 USD | 0.876 |
| USD_JPY | holdout | 2319 | 1160/1159 | 0.359 | +0.01650 JPY | 1.071 |
| USD_JPY | development | 1948 | 974/974 | 0.367 | +0.01982 JPY | 1.078 |
| USD_CAD | holdout | 2523 | 1262/1261 | 0.336 | -0.00033 CAD | 0.877 |
| USD_CAD | development | 2104 | 1052/1052 | 0.328 | -0.00038 CAD | 0.835 |
| XAU_USD | holdout | 2157 | 1078/1079 | 0.363 | +0.28350 USD | 1.058 |
| XAU_USD | development | 1895 | 948/947 | 0.356 | +1.55492 USD | 1.200 |

### The four candidate combinations: FX-38 vs. FX-38H, exactly what changed and why

| Combination | Period | FX-38 n / PF / Exp | FX-38H n / PF / Exp | What changed | Why |
|---|---|---|---|---|---|
| USD_JPY + CloseChannelBreakoutStrategy | Development | 1948 / 1.078 / +0.01982 JPY | 1948 / 1.078 / +0.01982 JPY | Nothing | Dev window already fully "usable"; both methodologies enter it equally warmed up |
| USD_JPY + CloseChannelBreakoutStrategy | Holdout | 2358 / 1.051 / +0.01243 JPY | 2319 / 1.071 / +0.01650 JPY | n ↓39, PF ↑0.020, Exp ↑33% | Usable-history threshold drops USD_JPY's 2002-2004 ramp-up-era trades; audit found 1 boundary-straddling trade removed too. Net: slightly BETTER |
| USD_JPY + MultiTimeframeTrendStrategy | Development | 426 / 1.312 / +0.09105 JPY | 426 / 1.312 / +0.09105 JPY | Nothing | Same as above |
| USD_JPY + MultiTimeframeTrendStrategy | Holdout | 539 / 1.137 / +0.04017 JPY | 537 / 1.145 / +0.04227 JPY | n ↓2, PF ↑0.008, Exp ↑5% | Usable-history threshold only (audit found 0 straddling trades for this combo) — small effect since MTT's own H4 warm-up requirement already limited exposure to the sparse era |
| XAU_USD + CloseChannelBreakoutStrategy | Development | 1895 / 1.200 / +1.55492 USD | 1895 / 1.200 / +1.55492 USD | Nothing | Same as above |
| XAU_USD + CloseChannelBreakoutStrategy | Holdout | 2157 / 1.057 / +0.28111 USD | 2157 / 1.058 / +0.28350 USD | PF ↑0.001, Exp ↑0.9% | XAU/USD's usable start EQUALS its earliest available candle (FX-38H part 1's own correction) — no ramp-up era to exclude; audit found exactly 1 straddling trade, explaining the tiny residual shift |
| XAU_USD + MultiTimeframeTrendStrategy | Development | 433 / 1.250 / +2.23988 USD | 433 / 1.250 / +2.23988 USD | Nothing | Same as above |
| XAU_USD + MultiTimeframeTrendStrategy | Holdout | 452 / 1.179 / +1.08224 USD | 452 / 1.179 / +1.08224 USD | **Nothing measurable** | XAU usable start = earliest available AND the audit found ZERO straddling trades for this specific combination — FX-38's original number was already exactly right here |

**None of the four candidates flip sign under the more rigorous
methodology — if anything, two (both USD_JPY combinations) look
slightly BETTER, and the other two (both XAU_USD combinations) are
essentially unchanged, confirming FX-38's original XAU_USD numbers
were already sound.** This directly answers the external review's own
framing: "all four selected candidates survived the first historical
challenge without sign-flipping" — FX-38H's more careful methodology
CONFIRMS that finding rather than undermining it, and the two holdout
PFs the review specifically flagged as "only around 1.05" (USD_JPY/CCB
and XAU_USD/CCB) come back at 1.071 and 1.058 respectively — still
modest, still not "validated," but not weaker either.

**The two comparison-strategy sign-flips FX-38 found also persist,
unchanged**: `EmaCrossoverStrategy` on USD_JPY (development PF 1.084,
positive; holdout PF 0.973, still negative — was 0.916, so the flip is
real but less dramatic under the cleaner methodology) and
`EmaCrossoverTrendRegimeGatedStrategy` on XAU_USD (development PF
1.224; holdout PF 0.890, was 0.888 — essentially identical). Applying
more rigorous methodology did not manufacture or erase a single sign
flip anywhere in this story — a real, if modest, piece of evidence
that FX-38's qualitative conclusions were not artifacts of its
methodological gaps.

### Boundary-straddling audit of FX-38's original methodology

Per external review's criterion 9: audited FX-38's ORIGINAL continuous-
run-sliced-by-`entry_time` methodology directly (not assumed), over a
±400-day window around the 2016-09-19 boundary (comfortably wider than
any holding period observed anywhere in this project's trade tables —
at most a few weeks) for all 4 strategies × 5 instruments:

| Strategy | Instrument | Straddling trades | Local PF | PF excl. straddlers |
|---|---|---|---|---|
| ema_crossover_v1 | EUR_USD | 1 | 0.688 | 0.685 |
| ema_crossover_trend_regime_gated_v1 | EUR_USD | 0 | 0.695 | 0.695 |
| multi_timeframe_trend_v1 | EUR_USD | 0 | 0.569 | 0.569 |
| close_channel_breakout_v1 | EUR_USD | 1 | 0.917 | 0.913 |
| ema_crossover_v1 | GBP_USD | 1 | 1.170 | 1.153 |
| ema_crossover_trend_regime_gated_v1 | GBP_USD | 0 | 1.483 | 1.483 |
| multi_timeframe_trend_v1 | GBP_USD | 1 | 1.233 | 1.185 |
| close_channel_breakout_v1 | GBP_USD | 1 | 1.021 | 1.015 |
| ema_crossover_v1 | USD_JPY | 1 | 1.001 | 1.005 |
| ema_crossover_trend_regime_gated_v1 | USD_JPY | 0 | 1.418 | 1.418 |
| multi_timeframe_trend_v1 | USD_JPY | 0 | 1.026 | 1.026 |
| close_channel_breakout_v1 | USD_JPY | 1 | 1.015 | 1.019 |
| ema_crossover_v1 | USD_CAD | 1 | 1.033 | 1.037 |
| ema_crossover_trend_regime_gated_v1 | USD_CAD | 1 | 0.741 | 0.750 |
| multi_timeframe_trend_v1 | USD_CAD | 1 | 1.151 | 1.161 |
| close_channel_breakout_v1 | USD_CAD | 1 | 0.883 | 0.886 |
| ema_crossover_v1 | XAU_USD | 1 | 0.897 | 0.882 |
| ema_crossover_trend_regime_gated_v1 | XAU_USD | 1 | 0.431 | 0.391 |
| multi_timeframe_trend_v1 | XAU_USD | 0 | 0.977 | 0.977 |
| close_channel_breakout_v1 | XAU_USD | 1 | 0.934 | 0.931 |

**At most ONE straddling trade per (strategy, instrument) combination,
never more, across all 20 combinations** — the boundary-straddling
leak was real (confirmed directly, not assumed) but numerically tiny:
even within this narrow ±400-day AUDIT window alone (not the full
multi-year holdout, where its share is smaller still), removing the
single straddling trade shifts PF by at most ~0.05 (`multi_timeframe_
trend_v1`/GBP_USD: 1.233 → 1.185) and typically much less. Against
FX-38's full holdout sample sizes (hundreds to thousands of trades),
this is immaterial — consistent with, not contradicted by, the small
holdout-vs-FX-38H deltas the four-candidate table above already shows.
The methodological fix (sealed windows) was worth making on principle
— a real trade should never be able to use a price from outside its
own evaluation period — but it was not hiding a result-changing bug.

### Overall FX-38H conclusion

Every criterion in the external review is addressed: an objective,
locked-before-running usable-history threshold (not 2002/2006, not an
assumed 2005/2007 either — computed); sealed evaluation windows applied
to BOTH development and holdout; a direct audit of FX-38's original
boundary-straddling exposure, quantified and shown to be immaterial;
the Part-F 2022-2025 overstatement corrected with a ranked re-
derivation; and the actual analysis program committed
(`scripts/determine_usable_history_start.py`,
`scripts/run_fx38h_analysis.py`) alongside a machine-readable artifact
(`research_results/fx38h/results.json`) — nothing here is a markdown-
only claim. No strategy parameter was changed, no year was added or
dropped based on performance, and no result was known before the
protocol (usable-history rule, sealed-window design, warm-up size,
audit margin) was locked.

**The finding stands, now on firmer ground**: all four candidate
combinations remain positive and sign-stable across development and
historical holdout; two comparison strategies on the same instruments
do not. Two of the four candidates' holdout profit factors are still
modest (USD_JPY/CloseChannelBreakoutStrategy 1.071, XAU_USD/
CloseChannelBreakoutStrategy 1.058) — not evidence of a durable edge,
and not described as validated. The external review's own suggested
next question — whether PF in the 1.05-1.18 range is statistically
distinguishable from noise once trade dependence and regime clustering
are accounted for — remains open and is the natural next step, not
pursued in this story.

**Verification**: `pytest` (604 passed — no production strategy code
changed in this part, only the analysis script), `ruff`, `mypy
--strict`, `pre-commit run --all-files`. Total runtime: ~2 hours
(`CloseChannelBreakoutStrategy`'s slow engine across 10 sealed windows
dominates; the other three strategies' incremental engines completed
in seconds).

## 2026-09-21 — FX-38H.1: holdout provenance & warm-up hardening

External review of FX-38H itself (accepted the usable-history
methodology, sealed windows, reproducibility, and the XAU density
correction outright) found one real remaining inconsistency and one
fragility, packaged as this small follow-up story.

**Issue 1 — the holdout warm-up still used data just declared
unusable.** `_window_candles`'s warm-up start was an unconditional
`window_start - WARMUP_DAYS`, with no lower bound. For USD_JPY's
holdout window (`window_start` = 2005-01-20), that reached back to
~2004-11-21 — squarely inside the 2002-2004 stretch FX-38H's own
usable-history algorithm had just excluded as not research-grade. A
recursively-smoothed indicator (EMA/ADX) seeded partly from that data
could carry a trace of it into the first real holdout decisions —
small, but a genuine inconsistency between what the story concluded
about that data and how it was actually used.

**Fix (external review's own preferred option)**: `warmup_start =
max(window_start - WARMUP_DAYS, earliest_usable_for_this_series)`.
For the FIRST holdout window, `window_start` already equals that
series' own `earliest_usable_research_candle` (by construction — see
FX-38H part 1), so this now correctly collapses to ZERO pre-window
warm-up: the strategy warms up naturally on its own first bars,
sacrificing only its first handful of possible trades, with every
piece of state provably derived from research-grade data only. The
development window (2016-09-19) is unaffected — 60 days earlier is
itself deep inside usable history for every series, so the bound is
never binding there. Applied independently to
`MultiTimeframeTrendStrategy`'s own H1 and H4 boundaries, not its
combined (later) usable start — H1 data between its own usable start
and the later H4-driven combined boundary is still legitimately usable
H1 data, just not yet part of the combined window.

**Issue 2 — `source=None` means "any provenance," not "native."**
Every candle fetch across `determine_usable_history_start.py` and
`run_fx38h_analysis.py` used `source=None`, which FX-27 defines as "no
provenance filter" — not "native OANDA history," which is what this
research protocol actually specifies and currently happens to hold.
Harmless today (the research dataset has no overlapping NATIVE/
AGGREGATED pairs to collide), but fragile: a future H4 aggregation
alongside native H4 data would let this exact code path see duplicate
timestamps, fail series validation, or (in the usable-history script's
own present-times set) silently collapse two different-provenance
observations into one. **Fix**: every fetch now explicitly passes
`source=CandleSource.NATIVE` — an explicit provenance invariant
instead of an implicit, currently-harmless default.

**Rerun, otherwise unchanged (same locked parameters, same protocol)**:

| Combination | Period | FX-38H n / PF / Exp | FX-38H.1 n / PF / Exp | Changed? |
|---|---|---|---|---|
| USD_JPY + CloseChannelBreakoutStrategy | Development | 1948 / 1.078 / +0.01982 JPY | 1948 / 1.078 / +0.01982 JPY | No |
| USD_JPY + CloseChannelBreakoutStrategy | Holdout | 2319 / 1.071 / +0.01650 JPY | 2319 / 1.070 / +0.01629 JPY | Negligible (PF −0.001) |
| USD_JPY + MultiTimeframeTrendStrategy | Development | 426 / 1.312 / +0.09105 JPY | 426 / 1.312 / +0.09105 JPY | No |
| USD_JPY + MultiTimeframeTrendStrategy | Holdout | 537 / 1.145 / +0.04227 JPY | 536 / 1.146 / +0.04254 JPY | Negligible (n −1, PF +0.001) |
| XAU_USD + CloseChannelBreakoutStrategy | Development | 1895 / 1.200 / +1.55492 USD | 1895 / 1.200 / +1.55492 USD | No |
| XAU_USD + CloseChannelBreakoutStrategy | Holdout | 2157 / 1.058 / +0.28350 USD | 2157 / 1.058 / +0.28350 USD | **None — bit-for-bit identical** |
| XAU_USD + MultiTimeframeTrendStrategy | Development | 433 / 1.250 / +2.23988 USD | 433 / 1.250 / +2.23988 USD | No |
| XAU_USD + MultiTimeframeTrendStrategy | Holdout | 452 / 1.179 / +1.08224 USD | 452 / 1.179 / +1.08224 USD | **None — bit-for-bit identical** |

**XAU_USD's two candidates are bit-for-bit identical, not just close —
explained, not coincidental**: XAU/USD's `earliest_usable_research_
candle` already equals its `earliest_available_candle` (FX-38H part
1's own correction). Even the OLD, unbounded warm-up fetch
(`window_start - 60 days`) reached back to a date BEFORE any XAU/USD
data exists at all, so it already returned zero candles before the
fix — there was never any actual not-research-grade data available to
accidentally include for XAU/USD in the first place. The fix only
changes behavior for the four FX pairs, where real (if sparse)
2002-2004 data does exist and could previously leak in.

**The two comparison-strategy sign-flips persist, essentially
unchanged**: `EmaCrossoverStrategy` on USD_JPY (holdout PF 0.973 →
0.974) and `EmaCrossoverTrendRegimeGatedStrategy` on XAU_USD (holdout
PF 0.890 → 0.890, identical, same "no prior data existed" reasoning as
above).

**Conclusion, exactly as the external review predicted**: removing the
pre-usable-history warm-up changes at most a handful of early holdout
trades and moves profit factor by ~0.001 for the affected instruments,
literally nothing for XAU_USD's two candidates. No candidate result
changes materially; no sign flips anywhere are created or removed.
This closes the last methodological inconsistency in FX-38/FX-38H's
holdout protocol — the finding was already sound; it now also has no
remaining gap between what the story concluded about pre-2005 data and
how that data was used.

Also fixed per external review's minor note: FX-38H's own Part-F
correction (above) said "narrower, one-year claim" — `2024-2025` is
itself a 2-year bucket, so the accurate phrasing is "narrower, single-
bucket claim" (vs. the original two-bucket "2022-2025" one) — corrected
in place, not a substantive change.

**Verification**: `pytest` (full suite, no production `src/` code
changed beyond the previously-added `domain/sealed_window_backtest.py`
— only the two analysis scripts changed), `ruff`, `mypy --strict`,
`pre-commit run --all-files`. Rerun total: ~2 hours (same profile as
FX-38H part 2 — `CloseChannelBreakoutStrategy` dominates).

## 2026-09-21 — FX-39 (part 1): block-bootstrap significance testing primitive

The natural next question FX-38H's own external review named: two of
the four holdout candidates have profit factors only ~1.05-1.07 —
close enough to breakeven that the real question is whether they're
statistically distinguishable from a strategy with no real edge, once
TRADE DEPENDENCE (a strategy's own state carries from one trade to the
next — consecutive trades are not independent draws) and REGIME
CLUSTERING (FX-38's own Part F found real multi-year strong/weak
stretches) are accounted for, rather than an ordinary independence-
assuming confidence interval that would understate the true
uncertainty.

**Method, locked before computing any result on real data**:

1. **Moving-block bootstrap** (Künsch 1989) — the standard fix for
   testing a sample mean's significance under autocorrelation: resample
   OVERLAPPING CONSECUTIVE blocks (not individual points) with
   replacement, preserving local dependence within each block. Block
   length is chosen OBJECTIVELY from the series' own sample
   autocorrelation function (`select_block_length`) — the first lag
   from which the ACF stays inside the approximate white-noise 95% band
   (`±1.96/sqrt(n)`) for 3 consecutive lags, not guessed or tuned to
   produce a particular answer. Falls back to `round(sqrt(n))` (a
   standard rule of thumb) if no such run is found, with that fallback
   explicitly flagged to the caller rather than silently trusted.
2. **Segment (regime) block bootstrap** — resamples WHOLE pre-defined
   segments (e.g. the SAME 2-year calendar buckets already computed in
   FX-38's own Part F) with replacement, directly addressing "regime
   clustering" by construction — pooling by trade count (matching this
   project's own `expectancy` convention: total P&L / total trade
   count), not a naive average of segment-level means.

Both produce 90%/95% percentile confidence intervals on expectancy
(mean per-trade P&L). A CI excluding zero is evidence the population
mean is likely non-zero even after accounting for the relevant
dependence structure — explicitly NOT proof of a durable, tradeable
edge, and not evidence about any period other than the one tested.

**Implementation**: `domain/block_bootstrap.py` — pure functions over
`Decimal` P&L sequences, no infrastructure/strategy/candle dependency
(reusable for any strategy's trade list, not tied to this story). 29
tests (`tests/unit/domain/test_block_bootstrap.py`), several built on
values confirmed by direct computation before writing the assertion
(this project's established practice for boundary-sensitive tests):
the perfect-alternating-series ACF is `-0.95` exactly, not `-1` (hand-
verified via direct computation — the standard biased estimator's
numerator sums `n-lag` terms against a denominator summed over all
`n`, so even perfect anti-correlation doesn't reach exactly -1); a
"paired-repeat" series (each white-noise value repeated twice
consecutively) gives a strong, verified lag-1 ACF with decay from lag 2
onward, confirming `select_block_length` finds a run starting after
lag 1, not at it; a 5-point series with one outlier at position 5 and
`block_length=4` has, confirmed by hand-enumeration, only two possible
truncated-resample means (0 or 20) — a real gap this test closes:
regression-proof discipline caught that no other test would have
noticed a missing truncation step (which allows an unrelated third
value, 40, to leak in from beyond the original sample size). Two
deliberately-injected bugs (segment bootstrap using naive mean-of-
segment-means instead of pooled-by-count; missing post-concatenation
truncation in the moving-block bootstrap) were each confirmed to make
the relevant test fail before being reverted.

**Not yet done in this part**: no real strategy data has been touched
yet — this commit is the tested primitive only. Applying it to the
four holdout candidates (plus the two known-negative comparison
strategies as a validation check on the method itself) is FX-39 part
2, next.

**Verification**: `pytest` (635 passed, unit/contract/replay — full
suite including integration not required for a pure-domain addition
with no infrastructure/candle dependency), `ruff`, `mypy --strict`,
`pre-commit run --all-files`.

## 2026-09-21 — FX-39 (part 1, continued): multiple-comparison correction, before any real result

Review of FX-39's design itself (caught mid-turn, before the driver
script had been run against real data — nothing to walk back) found
the design was missing three things needed to interpret the eventual
result honestly: multiple-comparison control across the four
candidates, an explicit preregistered directional hypothesis with
interpretation tiers, and clarity that the regime-block bootstrap is a
robustness check, not an equally-precise significance test given only
~5-6 available 2-year blocks. Incorporated into the primitive and its
protocol before part 2 runs anything:

- **`holm_bonferroni_adjusted_p_values`** (new): standard Holm step-
  down family-wise-error-rate correction, valid under arbitrary
  dependence between tests (no independence assumption needed, unlike
  some alternatives) and uniformly at least as powerful as plain
  Bonferroni. Will be applied across the FOUR candidates' one-sided
  p-values (`BootstrapResult.fraction_le_zero`, which already doubles
  as an approximate bootstrap one-sided p-value for `H0: expectancy <=
  0` — documented explicitly now) — NOT the two negative controls,
  which stay outside that family since they aren't part of the
  "selected by prior research" multiplicity problem.
- **`select_block_length`** now also returns `acf_by_lag` (every lag's
  own autocorrelation, not just the selected one) and `band`, for full
  per-series auditability in the eventual artifact — and accepts an
  optional `max_block_length` hard cap (never below `min_block_length`)
  so pathological ACF behavior can't select an absurd block. Noted
  explicitly in its own docstring: zero linear autocorrelation does not
  prove independence — volatility/regime-level dependence can persist
  even with a flat ACF, which is precisely why the regime-block
  bootstrap is a useful complement, not a redundant check.
- **Preregistered interpretation tiers** (to be applied mechanically in
  part 2, not decided after seeing results): 95% lower bound > 0 →
  "evidence of positive expectancy"; 90% lower bound > 0 but 95% lower
  bound <= 0 → "suggestive, not strong evidence"; 90% lower bound <= 0
  → "cannot distinguish from noise." Applied per-candidate BEFORE
  looking at the Holm-adjusted family result, so there's no later
  temptation to pick whichever of 90%/95% "counts."
- **Regime-block bootstrap reframed explicitly as a robustness check,
  not a peer significance test**: the holdout windows span roughly
  10.5-11.7 years, giving only ~5-6 independent 2-year blocks to draw
  from. 10,000 resamples drawn from 5-6 source blocks does not create
  10,000 independent historical regimes — part 2's own report states
  the raw block count next to every regime-bootstrap CI, not just the
  resample count, so a narrow-looking CI is never read as more precise
  than the underlying evidence actually supports.
- **Explicitly forbidden, stated here so it can be pointed back to
  later**: no parameter optimization, strategy modification, instrument
  substitution, period substitution, exclusion of unfavorable regimes,
  or post-result change of bootstrap method, triggered by any FX-39
  result. If a candidate's result doesn't survive, that is the answer,
  not a prompt to try a different breakout lookback or add a filter.

12 new tests (regression-proof discipline applied to the Holm
implementation specifically: a naive per-rank formula without the
running-max monotonization step was confirmed, via a hand-verified
example — `[0.01, 0.011, 0.012]` → candidates `[0.03, 0.022, 0.012]`,
strictly decreasing — to produce an invalid non-monotonic result;
restored, confirmed valid).

**Verification**: `pytest` (644 passed), `ruff`, `mypy --strict`,
`pre-commit run --all-files`.

## 2026-09-21 — FX-39 (part 2): results — none of the four candidates survive

`scripts/run_fx39_significance_testing.py` (new, committed — the
reproducible source of every number below, alongside `research_results/
fx39/results.json`, which also carries every series' full ACF
diagnostics). Reran FX-38H.1's own sealed-window methodology exactly
(same warm-up bound, `CandleSource.NATIVE` filtering, locked default
strategy parameters — nothing changed) to regenerate the six holdout
trade lists, then applied the locked protocol above unchanged.

**Results, all four candidates (holdout)**:

| Combination | n | Observed expectancy | Observed PF | MBB block length | MBB 90% CI | MBB 95% CI | MBB tier | Regime blocks | Regime 95% CI | Regime tier |
|---|---|---|---|---|---|---|---|---|---|---|
| USD_JPY + CloseChannelBreakoutStrategy | 2319 | +0.01629 JPY | 1.070 | 1 | [-0.0074, 0.0415] | [-0.0119, 0.0463] | cannot distinguish from noise | 6 | [-0.0255, 0.0640] | cannot distinguish from noise |
| USD_JPY + MultiTimeframeTrendStrategy | 536 | +0.04254 JPY | 1.146 | 3 | [-0.0271, 0.1156] | [-0.0394, 0.1288] | cannot distinguish from noise | 6 | [-0.0295, 0.1382] | cannot distinguish from noise |
| XAU_USD + CloseChannelBreakoutStrategy | 2157 | +0.28350 USD | 1.058 | 1 | [-0.2473, 0.8186] | [-0.3451, 0.9102] | cannot distinguish from noise | 6 | [-0.1996, 0.6531] | cannot distinguish from noise |
| XAU_USD + MultiTimeframeTrendStrategy | 452 | +1.08224 USD | 1.179 | 1 | [-0.5250, 2.7507] | [-0.8245, 3.0801] | cannot distinguish from noise | 6 | **[0.0328, 1.7195]** | **evidence of positive expectancy** |

**Multiple-comparison correction (Holm, across the four candidates only, not the controls)**.
`p` here is the approximate percentile-bootstrap one-sided p-value —
the fraction of moving-block-bootstrap resamples at or below zero
(`BootstrapResult.fraction_le_zero`), not a p-value from a closed-form
test — and "Holm-adjusted" is the Holm-Bonferroni step-down adjustment
of that same approximate quantity across the family of four:

| Combination | Approx. one-sided p (bootstrap) | Holm-adjusted p |
|---|---|---|
| USD_JPY + CloseChannelBreakoutStrategy | 0.1324 | 0.5296 |
| USD_JPY + MultiTimeframeTrendStrategy | 0.1545 | 0.5296 |
| XAU_USD + CloseChannelBreakoutStrategy | 0.1933 | 0.5296 |
| XAU_USD + MultiTimeframeTrendStrategy | 0.1383 | 0.5296 |

**Classification matrix**:

| Candidate | MBB evidence | Regime robustness |
|---|---|---|
| USD_JPY + CloseChannelBreakoutStrategy | no | no |
| USD_JPY + MultiTimeframeTrendStrategy | no | no |
| XAU_USD + CloseChannelBreakoutStrategy | no | no |
| XAU_USD + MultiTimeframeTrendStrategy | no | **yes** (regime robustness only) |

**The honest answer: none of the four candidates are statistically
distinguishable from noise under the primary test (moving-block
bootstrap), and none survive Holm correction (adjusted p = 0.53 for
all four — nowhere near any conventional significance threshold).**
Every approximate percentile-bootstrap one-sided p-value (the fraction
of bootstrap resamples at or below zero, `BootstrapResult.fraction_le_
zero`) sits at 0.13-0.19 even before Holm-adjusting that same
approximate p-value across the family of four — this was never close
for any of the four, not just after adjusting for multiplicity.

**Correction**: this entry originally attributed the wide CIs to
"trade dependence... accounted for via the objectively-selected block
length" for all four candidates. That overstates what the block-length
selection actually found: three of the four candidates (USD_JPY +
CloseChannelBreakoutStrategy, XAU_USD + CloseChannelBreakoutStrategy,
XAU_USD + MultiTimeframeTrendStrategy) selected `block_length=1` — no
detectable lag-1+ linear autocorrelation, so the moving-block bootstrap
degenerated to an ordinary individual-trade bootstrap for those three;
their wide CIs reflect genuine sampling variability given the observed
effect size relative to per-trade variance, not a dependence
correction inflating them. Only USD_JPY + `MultiTimeframeTrendStrategy`
selected a larger block (`block_length=3`), where a real, if modest,
dependence adjustment was actually in effect. The correct, general
statement: given the observed effect sizes, variability, and available
holdout samples, neither the positive candidates nor the negative
controls are distinguishable from zero — for three of the four
candidates that conclusion holds even under an ordinary (non-block)
bootstrap, not because of any dependence correction.

**The one nuance, reported exactly as the locked protocol requires —
not overclaimed**: XAU_USD + `MultiTimeframeTrendStrategy`'s regime-
block bootstrap 95% CI barely excludes zero (lower bound +0.033, out
of an observed expectancy of +1.08). Per the protocol locked before
this result existed, this is a SECONDARY ROBUSTNESS CHECK, not a peer
significance test: with only 6 available 2-year regime blocks, 10,000
resamples do not create 10,000 independent historical regimes, and a
95% CI computed from 6 source blocks is not as precise as the same
nominal CI computed from thousands of individual trades. This is
directionally interesting — worth naming — but is not being read as
"XAU_USD/MTT is validated" or as overriding its own "cannot
distinguish from noise" result under the PRIMARY test.

**A finding about the whole research program, not just this story**:
the two negative controls (`EmaCrossoverStrategy`/USD_JPY, expectancy
-0.00762 JPY; `EmaCrossoverTrendRegimeGatedStrategy`/XAU_USD, expectancy
-0.80484 USD — both already known to sign-flip from FX-38's own
development-vs-holdout comparison) ALSO come back "cannot distinguish
from noise" under this same test, in the negative direction. This is
NOT a failure of the bootstrap method itself — `domain/block_
bootstrap.py`'s own test suite already confirms directly (on synthetic
data with a known, low-variance non-zero mean) that the method
correctly excludes zero when a real effect with adequate power is
present. It means something more general: given the observed effect
sizes, variability, and available holdout samples, neither the
positive candidates nor the negative controls are distinguishable from
zero. The positive PFs (1.06-1.18) and the negative ones (0.89-0.97)
are both consistent with a population expectancy at or near zero,
given the samples actually available — not something FX-39 could have
designed around.

**What this does NOT mean**: it does not mean the four candidates are
"disproven" or that development-period profit factors were fabricated
or wrong — FX-38/FX-38H's own findings (no sign flips, directionally
consistent between development and holdout) stand as reported. What
FX-39 adds is a calibration on CONFIDENCE: given the observed effect
sizes, variability, and available holdout samples, profit factors of
1.06-1.18 do not yet constitute statistically confident evidence of a
durable edge.
"Positive and stable across two periods" and "statistically
distinguishable from noise" are different, both true-or-false-
independently claims — FX-38/FX-38H established the first for all
four candidates; FX-39 shows the second does not yet hold for any of
them.

**Per this story's own locked, unconditional prohibition**: no
parameter was changed, no strategy was modified, no instrument or
period was substituted, and no unfavorable regime was excluded in
response to this result. The result is the result.

This closes the pure-technical-signal research phase FX-14 through
FX-39 opened. The next architectural step is not a different EMA
variant, breakout parameter, or filter — per the project's own roadmap,
technical signals are one evidence layer among several (regime,
fundamentals, event risk, news/intelligence, and eventually decision/
risk machinery), not a phase to keep optimizing in isolation.

**Verification**: `pytest` (full suite, no production `src/` code
changed beyond `domain/block_bootstrap.py` — only the driver script is
new), `ruff`, `mypy --strict`, `pre-commit run --all-files`. Runtime
~28 minutes (the two `CloseChannelBreakoutStrategy` holdout reruns
dominate; everything else — `MultiTimeframeTrendStrategy` and both
negative controls, all incremental engines — completed in seconds).

## 2026-09-21 — FX-40: backtest run report export + static HTML results viewer

Observability/reporting only, requested to close out the pure-
technical-strategy research phase FX-39 ended: a human should be able
to inspect a real backtest run visually (metrics, an equity curve,
individual trades) without reading terminal output or Markdown tables.
No strategy behavior changed; `domain/backtest.py`, `trade_simulation.
py`, and `backtest_metrics.py` are all untouched, and no new third-
party dependency (Python or JavaScript) was introduced.

**`domain/backtest_report.py`** (new): a pure serializer, not a use
case or port — no file/DB/network I/O, no metric recomputation, no
backtesting, no trade simulation. `to_report_dict(...)` turns an
already-computed `list[SimulatedTrade]` + `BacktestMetrics | None`
(plus caller-supplied metadata: strategy key/version/parameters,
instrument, granularity, source, requested window, git commit,
generated-at) into the canonical JSON-serializable report dict.
`git_commit` and `generated_at` are supplied by the CALLER rather than
read internally (a `subprocess`/`datetime.now()` call inside this
function would make it impure and impossible to test against an exact
expected value). Every `Decimal`-derived value — prices, `Money`
amounts (serialized as just their `.amount` string; the report's own
`instrument` field already fixes the currency, so nothing is lost),
ratios (win_rate/profit_factor/Sharpe/Sortino), and any `Decimal`-typed
strategy parameter — serializes as a JSON string; plain integers
(counts, `int`-typed parameters) stay JSON integers; a mathematically
undefined metric (e.g. `profit_factor` with zero gross loss, or every
metric when there are zero trades — `metrics=None`, not a fabricated
placeholder `BacktestMetrics`) serializes as JSON `null`, never `"None"`
or an invented `0`. Also provides `config_identifier` (sha256 of a
canonical sorted-keys JSON encoding of a parameter set, truncated to 8
hex characters — deliberately NOT Python's own randomized-per-process
`hash()`) and `report_filename` (deterministic, readable filenames;
non-default parameter configurations get an 8-character suffix so two
genuinely different configurations for the same strategy/instrument/
granularity/date-range can never collide).

24 tests (`tests/unit/domain/test_backtest_report.py`), including an
exact-shape assertion against the real `compute_metrics` output (not
hand-faked numbers), a dedicated "serializer performs no
recalculation" test (passes METRICS that deliberately don't match the
given trades and confirms the report reflects exactly what was passed
in), and a filename-collision test. Regression-proof discipline
applied twice: a `float()`-instead-of-`str()` bug in metric
serialization, and a disabled filename-suffix branch, were each
confirmed to fail the relevant tests before being reverted.

**`scripts/export_backtest_report.py`** (new): composes this project's
own already-trusted, unmodified pipeline — `SqlAlchemyCandleRepository.
get_range(..., source=CandleSource.NATIVE)` (never `source=None`,
matching FX-38H.1's own provenance hardening) → `run_backtest`/
`run_backtest_incremental` → `simulate_trades` → `compute_metrics` →
`to_report_dict` → write report + update `reports/index.json` +
regenerate `reports/dashboard_data.js`. An explicit, small mapping (not
a general strategy-plugin architecture) supports the 7 concrete
strategies with real research findings — `EmaCrossoverStrategy`,
`EmaCrossoverTrendRegimeGatedStrategy`, `CloseChannelBreakoutStrategy`,
`VolatilityExpansionBreakoutStrategy`, `MeanReversionStrategy`,
`TimeSeriesMomentumStrategy`, `MultiTimeframeTrendStrategy` — using
each strategy's existing recommended engine (incremental where one
exists and is golden-parity-tested; the slow reference otherwise, e.g.
`CloseChannelBreakoutStrategy`, `MeanReversionStrategy`,
`TimeSeriesMomentumStrategy`, which have none).
`MultiTimeframeTrendStrategy` is handled as its own explicit special
case (needs an H4 series too) rather than forced into the other
strategies' uniform shape. Index updates are idempotent (re-exporting
the same report never duplicates its filename) and use an atomic
write-temp-then-replace pattern so an interruption can't leave a
malformed `index.json`.

**`fta_dashboard_sketch.html`** (new, repo root): a single static HTML
file — no ES modules, no npm, no build step, no server. Loads
`reports/dashboard_data.js` via an ordinary classic `<script src=...>`
tag (browsers commonly block `fetch()` of local files under `file://`,
so this is the load-bearing mechanism, not an enhancement) and reads
`const RUNS = window.FTA_BACKTEST_RUNS || [];`. Shows strategy/
instrument/parameters/granularity/source/date range/git commit,
all eight metric cards (trade count, win rate, profit factor,
expectancy, total P&L, max drawdown, Sharpe, Sortino — each rendering
"N/A" rather than a fabricated value when the underlying JSON field is
`null`), a cumulative-P&L equity curve drawn with a plain `<canvas>` 2D
context (a native browser API, not a dependency), and a sortable-by-
time trade table. A `<select>` run-picker (plain HTML/JS, no framework)
appears whenever more than one report exists. Empty/error states are
explicit rather than crashes: no reports at all shows install/usage
instructions instead of a blank page; a report with zero trades shows
"This run has zero trades" and an explicit "No trades to chart"
message instead of an empty or broken chart.

**Verified against three real exported runs** (`ema_crossover_v1`/
EUR_USD, `close_channel_breakout_v1`/EUR_USD with a non-default
`lookback=30` override — confirming the filename-suffix collision
protection works live, not just in unit tests — and
`multi_timeframe_trend_v1`/USD_JPY, exercising the H4-dependent path),
plus a deliberate zero-trade export (very short date range) to confirm
the empty-trades path end-to-end before being removed from the final
demonstration set. `reports/` (the three JSON reports, `index.json`,
`dashboard_data.js`) is committed alongside the code, matching this
project's own `research_results/` precedent, so the demonstration is
reviewable from git history directly, not just reproducible by rerunning
the script.

**Verification**: `pytest` (713 passed, full suite — no changes to
`domain/backtest.py`/`trade_simulation.py`/`backtest_metrics.py`),
`ruff`, `mypy --strict`, `pre-commit run --all-files`. JavaScript
syntax verified directly (`node --check`) since this project has no
JS test tooling and none was added. No new Python or JavaScript
dependency of any kind.

Per this story's own explicit stop instruction: no broader dashboard,
database-backed report storage, live monitoring, paper-trading UI,
strategy-editing UI, or API work follows this story.

## 2026-09-21 — FX-41: point-in-time fundamental data model

**Numbering note**: the story spec supplied for this work called
itself "FX-40" and its Definition of Done named the following story
"FX-41". This codebase already has a committed, shipped FX-40 (the
backtest report export/viewer, previous entry). To avoid colliding
with that established numbering, this story is recorded as **FX-41**
throughout — commits, code comments, and this entry — and the next
story (the spec's own "FX-41") will be FX-42 when picked up. Flagged
explicitly here rather than silently overwriting or ignoring the
discrepancy.

**Scope**: architecture/foundation only. At historical time T, the
system may only see fundamental information that was actually
available to the market at or before T — this story builds the domain
model and repository contract that makes that statement checkable, and
nothing else. No external provider, no ingestion pipeline, no
economic calendar, no carry/rate-differential strategy, no fundamental
score, no BUY/SELL decision logic, no LLM/news/sentiment analysis. No
existing strategy, backtest, or candle-data code path is touched.

**`MacroSeriesDefinition`** (`domain/macro_series_definition.py`):
canonical, provider-independent series identity — `key`, `economy`,
`currency`, `category` (`MacroCategory`), `unit`, `frequency`
(`MacroFrequency`), `point_in_time_safety` (`PointInTimeSafety`,
defaulting to `UNKNOWN`). Deliberately holds no FRED series ID, no
central-bank API code, no vendor ticker — a future infrastructure
adapter maps a specific provider's identifiers onto this identity, not
the other way around, so the domain model supports an official
central-bank source, a FRED/ALFRED-style source, or a commercial
provider without changing shape. **Not persisted in its own database
table** — a deliberate choice to keep it a pure in-memory value object.
Reasoning: this story is explicitly told not to "design a giant
generic economic-data warehouse," and a `macro_series_definitions`
table would be exactly that ahead of any real second consumer needing
one (no ingestion adapter exists yet to populate it, and the one
existing consumer — `require_point_in_time_safe` — only needs the
object in hand, not a lookup by key). If a future story needs to look
up series metadata by key without the caller holding the object
already, that is the trigger to add persistence for this type — not
before.

**`MacroObservationVintage`** (`domain/macro_observation_vintage.py`):
a single class represents both a first release and every later
revision — there is deliberately no separate "MacroObservation"
wrapper type despite the story's own "MacroObservation /
MacroObservationVintage" naming. A first release is not conceptually
different from a revision: it is simply the vintage with
`revision_sequence == 0`. Modelling them as two classes would invent a
distinction with no distinct behaviour — again, the "giant generic
warehouse" shape this story is told not to build. Three timestamps
kept explicitly distinct per the story's own requirement:
`observation_period` (which reference period — a calendar fact),
`released_at` (when this vintage first became publicly knowable — the
field every point-in-time query filters on), and optional
`effective_at` (when a value takes legal/economic effect, only set
when materially later than `released_at`; `None` for the large
majority of series). `value` is `Decimal`-only. No `ingested_at`
domain field — mirrors the existing precedent that `Candle` (domain)
carries no such field while `CandleRow` (infrastructure) gets
`created_at` for free from `TimestampMixin`; inventing a redundant
domain-level ingestion timestamp would duplicate what the persistence
layer's existing convention already covers.

**Point-in-time safety classification** (`domain/
point_in_time_safety.py`): `PointInTimeSafety` is `POINT_IN_TIME_SAFE`
/ `LATEST_ONLY` / `UNKNOWN`. `require_point_in_time_safe` (in
`macro_series_definition.py`, not `point_in_time_safety.py` — keeping
the enum itself dependency-free avoided a circular import with the
dataclass it classifies) fails closed: it raises for anything that
isn't explicitly `POINT_IN_TIME_SAFE`, including `UNKNOWN`.
`MacroSeriesDefinition.point_in_time_safety` defaults to `UNKNOWN`, not
`POINT_IN_TIME_SAFE` — an unverified source must never silently pass
as research-safe. Enforcement lives as a small standalone guard rather
than inside the repository: the repository only ever sees a bare
`series_key: str` and has no independent way to know a series' safety
classification, so a future research/strategy consumer (none exists
yet — this story is not one) must call this guard against the series'
own definition before trusting an as-of query result for historical
research.

**`MacroObservationRepository`** (`application/ports/
macro_observation_repository.py`, a `Protocol`): `add_vintage` (write,
never overwrites), `latest_available_as_of(series_key, as_of)` ("what's
the newest data point the market could have known about at all, by
this instant, in its most up-to-date known form" — orders by
`observation_period` then `released_at`, both descending), and
`observation_as_known_at(series_key, observation_period, as_of)`
("for this specific period, what was the most recently-revised value
known by this instant" — orders by `released_at` descending within
that fixed period). Neither method takes an `effective_at` cutoff —
`effective_at` describes when a value takes effect, not when it became
knowable, so it plays no part in what a point-in-time query is allowed
to see. The shared invariant, stated once in the port's docstring: "a
query at timestamp T must never return a vintage whose `released_at`
is after T."

**Persistence** (`infrastructure/db/models/
macro_observation_vintage.py`, `infrastructure/db/
macro_observation_repository.py`, migration `7f04ea660a34`): one table,
`macro_observation_vintages`, following `CandleRow`'s established
mixin pattern (`UUIDPrimaryKeyMixin`, `TimestampMixin`). Every write in
`SqlAlchemyMacroObservationRepository` is `INSERT ... ON CONFLICT DO
NOTHING` — there is no UPDATE anywhere in the class, so a historical
vintage row can never be mutated once stored, satisfying "must not
overwrite historical observations destructively" at the SQL level, not
just by convention. Unique constraint on `(series_key,
observation_period, revision_sequence)` — a vintage's natural identity,
making a duplicate insert idempotent rather than something callers
must deduplicate by hand. Index on `(series_key, released_at)`
supports both query methods' shared `released_at <= as_of` filter.
Explicitly not a generic economic-data warehouse: one table, no
provider/source table, no metadata table — `source` is a plain string
column for provenance, not a foreign key into anything.

**Tests**: the story's own worked examples reproduced exactly, against
both `FakeMacroObservationRepository` (`tests/unit/application/
test_fake_macro_observation_repository.py`) and live Postgres
(`tests/integration/test_macro_observation_repository.py`) — release
timing (February observation released March 12 13:30 UTC: NOT
AVAILABLE the day before, AVAILABLE from the release instant),
revision (2.1 available July 1, revised to 2.4 available August 1: a
July 15 query returns 2.1, an August 15 query returns 2.4), an
explicit no-future-leakage test, Decimal fidelity (`2.123456789`
round-trips exactly, including through Postgres `Numeric`), and
naive-timestamp rejection (delegated to — and re-verified against —
the existing `UtcTimestamp` guard). Domain validation tests for both
dataclasses, including a structural test that
`MacroSeriesDefinition`'s field set contains no provider-ID-shaped
field. Regression-proof discipline applied to the point-in-time query
logic specifically: the `released_at <= as_of` filter was deliberately
removed from both `SqlAlchemyMacroObservationRepository` and
`FakeMacroObservationRepository` in turn, confirmed each time that the
no-future-leakage and revision tests failed as expected, then
restored.

**Verification**: `pytest` (767 passed, full suite — zero changes to
any existing strategy, backtest, or candle-data code), `ruff`,
`mypy --strict`, `pre-commit run --all-files`. `alembic upgrade head`
applied clean against a fresh `docker compose up -d db`.

Per this story's own explicit stop instruction: no ingestion adapter,
no economic calendar, no carry or rate-differential strategy, no
fundamental score, and no decision-engine work follows this story.

## 2026-09-21 — FX-41H: macro vintage integrity hardening

**Scope**: harden `add_vintage`'s idempotency contract and the
determinism of both point-in-time queries before real macro-data
ingestion begins. No point-in-time semantics changed -- `released_at
<= as_of` remains the entire safety guarantee for both read methods,
untouched by this story. No external provider, no rate data, no
strategy, no scoring, no decision logic.

**Conflict detection** (`application/ports/
macro_observation_repository.py`, new `MacroVintageConflictError`):
FX-41's `add_vintage` silently no-opped on ANY insert conflict, whether
the incoming vintage was an exact duplicate or a different payload
wrongly reusing an already-taken `(series_key, observation_period,
revision_sequence)` identity -- the latter case is a data-integrity bug
that FX-41 let through unnoticed. `add_vintage` now distinguishes the
two: an exact duplicate (every field equal) is still a no-op, matching
FX-41's own idempotency requirement; a same-identity vintage with a
different `value`, `released_at`, `effective_at`, or `source` now
raises `MacroVintageConflictError`, carrying both the `existing` and
`incoming` vintages for the caller to inspect. The already-stored
vintage is left completely unchanged in both cases -- FX-41's "no
UPDATE anywhere in this class" property is preserved exactly;
`MacroVintageConflictError` is raised from a comparison against what
was already committed, never from a partially-applied write.

`SqlAlchemyMacroObservationRepository.add_vintage` detects the
conflict by attempting `INSERT ... ON CONFLICT DO NOTHING RETURNING
id`: if a row comes back, the insert happened and the vintage is new;
if not, the identity already existed, so the existing row is fetched
and compared field-by-field against the incoming vintage before
deciding no-op vs. raise. `FakeMacroObservationRepository.add_vintage`
does the equivalent dict-based comparison. Both implementations are
exercised by the same scenario set (exact duplicate; conflicting
value, `released_at`, `effective_at`, and `source`; the stored row's
survival after a conflict; the exception's `existing`/`incoming`
payload) in `tests/unit/application/
test_fake_macro_observation_repository.py` and `tests/integration/
test_macro_observation_repository.py`.

**Deterministic tie-breaking**: `latest_available_as_of` (order by
`observation_period DESC, released_at DESC`) and
`observation_as_known_at` (order by `released_at DESC`) each now
append `revision_sequence DESC` as a final tie-breaker. Without it, two
vintages of the same period sharing an identical `released_at` (a
legitimate case -- nothing in the domain model forbids a provider
publishing two revisions at the same instant) resolved to whichever row
the database happened to scan first, which is not guaranteed stable
across queries or across a table's physical layout. A dedicated test
(`test_tie_break_by_revision_sequence_when_released_at_matches`, both
fake and Postgres) inserts the lower revision first and the higher
revision second and asserts the higher one is returned regardless --
proving the result depends on `revision_sequence`, not insertion or
scan order.

**Provider/source-specific point-in-time safety is explicitly deferred,
not addressed here**: this story hardens the STORAGE-level integrity
invariant (one immutable fact per natural identity, deterministic
retrieval) for vintages that are already in the repository. It says
nothing about how a specific provider's own revision numbering, release
timing, or historical-vintage availability maps onto this repository's
`(series_key, observation_period, revision_sequence)` identity -- that
mapping, and the decision of which `PointInTimeSafety` classification a
given provider integration deserves, belongs to the provider mapping
layer the future policy-rate registry/ingestion stories will introduce.
This story deliberately does not sketch or partially implement that
layer.

**Regression-proof discipline applied**: conflict detection was
deliberately removed from both `SqlAlchemyMacroObservationRepository`
and `FakeMacroObservationRepository` in turn (reverting `add_vintage` to
FX-41's original ON-CONFLICT-DO-NOTHING/no-op behavior), confirmed each
time that all five new conflict tests failed as expected, then restored.
The `revision_sequence DESC` tie-breaker was separately removed from
both `latest_available_as_of` and `observation_as_known_at` in both
implementations, confirmed the tie-break test failed with the
lower-revision vintage returned instead of the higher one, then restored.

**Verification**: `pytest` (781 passed, full suite -- 14 new tests, zero
changes to any existing strategy, backtest, or candle-data code), `ruff`,
`mypy --strict`, `pre-commit run --all-files`.

Per this story's own explicit stop instruction: no external provider, no
rate data, no strategy, no scoring, and no decision logic follows this
story.

## 2026-09-21 — FX-42: canonical central-bank policy-rate registry

**Scope**: define semantics and provider mappings for the policy-rate
concept of USD, EUR, GBP, JPY, and CAD -- the five currencies in the
research universe. No historical ingestion, no pair differential, no
carry strategy, no rate-expectations logic, no trading. Builds directly
on FX-41/FX-41H's foundation and, per this story's own instruction,
introduces the explicit separation between canonical economic series
identity and provider/source mapping + point-in-time safety that FX-41
deferred.

**Four new domain types, no persistence** (matching FX-41's own choice
not to persist `MacroSeriesDefinition`: this story is semantics/metadata,
not observations, so there is nothing to store in Postgres, no Alembic
migration, and no `MacroObservationRepository` involvement):

- **`RateTransformation`** (`domain/rate_transformation.py`): a
  `RateTransformationKind` (`IDENTITY` | `TARGET_RANGE_MIDPOINT`) paired
  with an explicit `version` string and a real `apply(*raw_values) ->
  Decimal` method -- not just descriptive metadata. `version` exists
  separately from `kind` so the deterministic rule itself is pinned and
  auditable, per the story's "make that transformation explicit and
  versioned" requirement: if `TARGET_RANGE_MIDPOINT`'s arithmetic mean is
  ever replaced by a different rule, that is a new version, not a silent
  behavior change under the same name.
- **`ProviderSeriesMapping`** (`domain/provider_series_mapping.py`): maps
  one provider's own identifier(s) onto a canonical definition --
  `provider`, `provider_series_ids` (a tuple, since some canonical
  scalars are derived from more than one raw series, e.g. a target
  range's upper/lower bound), its own `point_in_time_safety`, a
  `verified: bool`, and free-text `notes`. This is the explicit split
  this story was asked to introduce: `point_in_time_safety` lives HERE,
  not on `MacroSeriesDefinition`, because point-in-time trustworthiness
  is a property of a SOURCE, not of the abstract economic concept -- the
  same canonical "USD policy rate" concept could in principle be sourced
  from a vintage-preserving archive (potentially `POINT_IN_TIME_SAFE`) or
  a scraped current-value-only page (`LATEST_ONLY`). Every mapping this
  registry adds is `PointInTimeSafety.UNKNOWN` and `verified=False` --
  fail closed, matching FX-41's own principle: this story researched
  candidate providers and identifiers in good faith, it did not call a
  live provider API to confirm any of them. A new guard,
  `require_point_in_time_safe_mapping`, mirrors FX-41's
  `require_point_in_time_safe` at the mapping level.
- **`PolicyRateDefinition`** (`domain/policy_rate_definition.py`): one
  effective-dated definition -- `series` (a `MacroSeriesDefinition`,
  whose `category` this class enforces must be `MacroCategory.
  POLICY_RATE`), `institution`, `instrument_name`, `transformation`,
  `valid_from`/`valid_to` (a half-open window; `covers(as_of)` answers
  membership), and `provider_mappings` (always at least one -- an entry
  naming zero providers is not "ready for FX-43 ingestion" per this
  story's Definition of Done). `summary()` renders this definition's
  answers to the six audit questions the spec requires a canonical
  definition be able to answer (economic concept, currency/economy,
  unit, transformation, provider mapping, valid period) as plain
  strings, tested directly.
- **`policy_rate_registry`** (`domain/policy_rate_registry.py`): the
  actual registry -- `POLICY_RATE_DEFINITIONS`, a module-level tuple of
  six `PolicyRateDefinition`s (five currencies, USD split into two
  effective-dated eras -- see below), plus `definitions_for_currency`,
  `definition_as_of` (the point-in-time definition lookup: which
  definition applied at a given instant), and `canonical_series_for_
  currency`. `validate_registry` checks registry-wide invariants no
  single definition can check alone (all definitions for one currency
  share exactly one `series.key`; validity windows for one currency
  neither overlap nor leave a gap; all five required currencies are
  present) and runs at import time, failing fast on a malformed
  registry -- also called directly in tests against deliberately broken
  fixtures.

**USD is the story's required effective-dated example** ("do not
silently splice unlike concepts... represent effective-dated
definitions"): the Federal Open Market Committee announced a single
numeric target rate until December 16, 2008, when it switched to
announcing a target range instead -- a genuine instrument change, not a
cosmetic one. Represented as two `PolicyRateDefinition`s sharing one
`USD_POLICY_RATE` series key: `valid_from=1954-07-01` / `valid_to=
2008-12-16` with `IDENTITY` (FRED's `DFEDTAR`), and `valid_from=
2008-12-16` / `valid_to=None` with `TARGET_RANGE_MIDPOINT` (FRED's
`DFEDTARU`/`DFEDTARL`, averaged). Tests prove `definition_as_of` selects
the correct era on both sides of the switch date (including the switch
date itself, since `valid_to` is an exclusive bound), and that the
range-era transformation computes a numerically correct midpoint.

**EUR/GBP/JPY/CAD are each one continuous definition**, not because
those institutions' practices never changed, but because this registry
judges none of their changes to be a genuine semantic splice of the
canonical concept itself:

- **EUR**: the ECB Deposit Facility Rate (DFR), continuously defined
  since the euro's January 1, 1999 launch, chosen over the more
  commonly-cited pre-2008 Main Refinancing Operations (MRO) rate because
  the DFR (not MRO) has been the effective floor for euro area overnight
  money markets under the ECB's post-2014 structural liquidity surplus
  framework -- documented as a shift in relative importance, not a
  definition change. Notes record the DFR's negative-rate period (June
  11, 2014 to July 27, 2022).
- **GBP**: Bank of England Bank Rate, `valid_from=1997-06-01` (the
  Monetary Policy Committee's establishment). Notes record the 2006
  rename from "Repo Rate" to "Bank Rate" as a label change to the same
  instrument, not a splice.
- **JPY**: a single continuous concept ("the short-term interest rate the
  BoJ sets as its primary policy instrument"), `valid_from=1998-04-01`
  (the new Bank of Japan Act taking effect), despite substantial
  operational-mechanism change over time (uncollateralized overnight
  call rate target pre-2016; a negative rate on a tier of current-account
  balances under QQE+YCC January 2016-March 2024; overnight call rate
  target again from March 2024). Notes explicitly flag that if FX-43
  ingestion finds this mechanism change requires different derivation
  logic (not just a different rate level), this definition should be
  split into effective-dated definitions following the USD precedent --
  deliberately not pre-emptively built here.
- **CAD**: Bank of Canada Overnight Rate Target, `valid_from=1991-02-01`
  (the Bank of Canada/Government of Canada's joint inflation-control
  target announcement).

**Every historical date above is this story's good-faith research, not a
value confirmed against a primary source** -- each is documented with
its own reasoning in `policy_rate_registry.py`'s notes and module
docstring, but none were checked against a live provider API in this
session. Likewise, `ECB_SDW`'s and `BOE_DATABASE`'s provider series IDs
are best-effort based on commonly-documented naming conventions
(`verified=False`); `BOJ_TIME_SERIES_DATA_SEARCH`'s and `BOC_VALET`'s are
explicit placeholders (`VERIFY_BOJ_SHORT_TERM_POLICY_RATE`,
`VERIFY_BOC_OVERNIGHT_RATE_TARGET`) where this story did not have enough
confidence to assert a specific code. FX-43 must confirm all of the
above against each provider's live API/database before ingesting
anything -- this is the explicit intent of `verified=False` throughout,
not an oversight.

**Provider identifiers are not scattered through research code**: the
only place any FRED/ECB/BoE/BoJ/BoC series identifier appears in this
codebase is inside a `ProviderSeriesMapping` within this registry --
there is no ingestion code yet to scatter them into.

**Provider/source-specific point-in-time safety belongs to this
registry's provider mappings, not to a future multi-provider ingestion
system** -- per FX-41H's own explicit deferral note, this story is that
promised follow-up, but it stops at defining WHERE that classification
lives (`ProviderSeriesMapping.point_in_time_safety`) and HOW a consumer
must fail closed against it (`require_point_in_time_safe_mapping`); it
does not implement a multi-provider ingestion system, per this story's
own non-goals.

**Regression-proof discipline applied**: `PolicyRateDefinition.covers`'s
half-open boundary was deliberately made fully-closed, confirmed the
boundary test and the USD switch-date test both failed as expected, then
restored. `RateTransformation.apply`'s `TARGET_RANGE_MIDPOINT` arithmetic
was deliberately replaced with a wrong (non-averaging) return value,
confirmed both the unit test and the USD-registry integration-style test
failed with the exact wrong numeric result, then restored.
`validate_registry`'s overlap/gap checks were deliberately removed,
confirmed all four overlap/gap/non-terminal-open-ended tests failed
(each for the right underlying reason -- the checks were simply gone),
then restored.

**Verification**: `pytest` (851 passed, full suite -- 70 new tests, zero
changes to any existing strategy, backtest, candle-data, or FX-41/FX-41H
macro-observation code), `ruff`, `mypy --strict`, `pre-commit run
--all-files`.

Per this story's own explicit stop instruction: no rate-history download,
no pair differential calculation, no carry strategy, no assumption that
policy rate equals actual tradable carry, no CPI/GDP/employment, no rate
expectations, and no trading follows this story.

## 2026-09-21 — FX-42H: policy-rate registry semantic hardening

**Scope**: correct FX-42's factual/semantic weaknesses before real
ingestion (FX-43) begins, without changing FX-42's domain architecture
(`RateTransformation`, `PolicyRateDefinition`, `ProviderSeriesMapping`,
the registry/validation shape) or performing any ingestion, differential
calculation, carry strategy, parameter research, or trading.

**1. Point-in-time safety is now tracked solely on `ProviderSeriesMapping`.**
FX-41 gave `MacroSeriesDefinition` its own `point_in_time_safety` field
(defaulting to `UNKNOWN`) alongside `require_point_in_time_safe`. FX-42H
removes both: a canonical economic CONCEPT is provider-independent by
construction and has no source of its own to be trustworthy or not about
-- only a specific `(provider, provider_series_ids)` mapping has a real
source. `domain/macro_series_definition.py` no longer has a
`point_in_time_safety` field at all (asserted structurally by
`test_no_point_in_time_safety_field_exists`); `PointInTimeSafety` itself
(the enum) is unchanged and still lives in `domain/point_in_time_safety.py`,
now used only by `ProviderSeriesMapping`.

**2. One combined, fail-closed guard replaces the narrower FX-42 one.**
FX-42's `require_point_in_time_safe_mapping` checked only
`point_in_time_safety`. FX-42H replaces it with
`require_research_usable_mapping`, which requires BOTH `verified is True`
AND `point_in_time_safety is POINT_IN_TIME_SAFE` -- neither condition
alone is sufficient: a mapping believed point-in-time-safe in the
abstract but never confirmed against the live provider is not
research-usable, and a mapping confirmed to exist but not established as
point-in-time-safe is not research-usable either. The function reports
every failing condition, not just the first (`"not verified;
point_in_time_safety is UNKNOWN"`, for a mapping failing both). No
mapping in the registry currently passes this guard -- every entry
remains `UNKNOWN`/`verified=False`, matching FX-42's original posture
and this story's explicit instruction: do not mark any mapping
`POINT_IN_TIME_SAFE` merely because the value series exists. FX-43 must
independently verify how exact `released_at` timestamps are obtained;
daily effective-date observations alone are not sufficient for H1
no-lookahead research.

**3. USD's target-point era corrected: 1994-02-04, not 1954.** FX-42
claimed the concept effectively started with FRED's `DFEDTAR` series
availability (1954), hedged only in prose. FX-42H moves `valid_from` to
February 4, 1994 -- the first FOMC meeting after which policy changes
were announced immediately and explicitly, the point at which an
explicit numeric target became a contemporaneously PUBLISHED fact rather
than something inferred after the fact. The 1982-1993 portion of FRED's
`DFEDTAR` history is documented in the definition's own `notes` as a
retrospective reconstruction by the data provider, not contemporaneously
published data, and therefore unsuitable as pristine point-in-time
historical information -- no canonical definition in this registry
claims to cover it. `DFEDTARU`/`DFEDTARL`/`DFEDTAR` remain the confirmed
candidate FRED IDs (unchanged from FX-42).

**4. EUR's canonical scalar corrected: MRO, not DFR continuously.**
FX-42 chose the ECB Deposit Facility Rate (DFR) as the single continuous
EUR definition, reasoning from its post-2014 structural-liquidity-surplus
relevance. FX-42H reverses this for the INITIAL cross-currency
policy-rate-differential feature: under the ECB's pre-2008 "corridor
system", the Main Refinancing Operations (MRO) minimum-bid/fixed rate was
the actively-managed, headline-cited policy signal, with DFR a
rarely-binding floor far below it -- DFR only became the effective
binding rate under the post-2014 "floor system", a genuine regime
difference, not just an emphasis shift. MRO is therefore the historically
comparable scalar across the ECB's FULL history (1999 onward), matching
this story's explicit instruction: use the ECB MRO minimum-bid/fixed-rate
canonical series (`FM.D.U2.EUR.4F.KR.MRR_RT.LEV`) unless primary-source
verification shows a better continuous choice. DFR is retained in the
definition's `notes` as a documented CANDIDATE for a later, explicitly
regime-aware feature (e.g. applicable only from the floor-system era
onward) -- not discarded, and explicitly NOT to be silently substituted
back in merely because doing so would improve some later research
result; any such switch requires its own explicit, documented registry
change.

**5. JPY no longer claims one continuous definition.** This is FX-42H's
largest structural change. FX-42 claimed a single continuous "short-term
policy interest rate" concept from 1998 onward, hedging only that the
underlying MECHANISM changed. That claim does not survive scrutiny: the
BoJ's operating TARGET itself changed instrument type, not just
mechanism -- during its quantitative-easing eras the operating target was
a quantity (the outstanding balance of current accounts, or later the
monetary base; both denominated in yen, not percent), which is not a
"policy rate" in this registry's sense at all. Representing those eras
with a borrowed or nearby rate value would misrepresent what was actually
being targeted. FX-42H instead represents five distinct rate-target eras
sharing one `JPY_POLICY_RATE` canonical series, with INTENTIONAL GAPS
during the two quantitative-target eras:

  - 1998-04-01 .. 2001-03-19 — overnight call rate target (including
    ZIRP, 1999-2000)
  - *(gap)* 2001-03-19 .. 2006-03-09 — Quantitative Easing Policy
    (current-account-balance target; no rate-scalar definition)
  - 2006-03-09 .. 2013-04-04 — overnight call rate target resumed
    (including the 2010 "Comprehensive Monetary Easing" 0-0.1% range,
    not separately modeled in this pass)
  - *(gap)* 2013-04-04 .. 2016-01-29 — Quantitative and Qualitative
    Monetary Easing (monetary-base target; no rate-scalar definition)
  - 2016-01-29 .. 2024-03-19 — interest rate on policy-rate balances
    (Negative Interest Rate Policy + Yield Curve Control)
  - 2024-03-19 .. 2024-07-31 — overnight call rate target RANGE (0% to
    0.1%; `TARGET_RANGE_MIDPOINT`, mirroring USD's post-2008 pattern)
  - 2024-07-31 onward — overnight call rate target (single point again)

`definition_as_of("JPY", ...)` correctly returns `None` for any instant
in either gap -- proven directly by
`test_jpy_returns_none_during_quantitative_easing_gap_2001_2006` and
`test_jpy_returns_none_during_qqe_gap_2013_2016`. Every JPY boundary date
is held to a LOWER confidence bar than the other four currencies given
the operational complexity involved (the module docstring and each
definition's own `notes` say so explicitly), and BoJ provider identifiers
remain entirely unresolved -- every JPY `ProviderSeriesMapping` uses an
explicit `VERIFY_BOJ_...` placeholder, per this story's own instruction
that BoJ mapping stays unresolved until primary-source mapping is
established. FX-43 must confirm every JPY boundary against BoJ primary
sources before ingesting anything across it.

**6. Registry validation now allows gaps and checks full series
semantics, not just the key string.** `validate_registry`'s gap-rejection
check (inherited from FX-42) is removed entirely -- gaps are now a
legitimate, expected registry state (see JPY above), and
`definition_as_of`'s existing logic already returns `None` correctly for
an instant in one without any other code change. The overlap-rejection
check is unchanged. Separately, FX-42's "same `series.key` string" check
is replaced with a full `MacroSeriesDefinition` EQUALITY check (`{d.series
for d in currency_definitions}`, relying on the dataclass's own
auto-generated `__eq__`): two definitions could previously share a key
string while silently disagreeing on economy, unit, category, or
frequency, and FX-42's check would not have caught it --
`test_validate_registry_rejects_same_key_but_different_semantics` proves
the stricter check does.

**7. CAD's overnight-target boundary corrected: 1999-02-01, not
1991-02-01.** FX-42's `valid_from` (the Bank of Canada/Government of
Canada's joint inflation-control target announcement) reached back to a
period whose OPERATING FRAMEWORK was never confirmed to match this
definition's single-point-target instrument. FX-42H moves `valid_from`
to February 1999, per this story's explicit instruction, as the verified
modern overnight-target framework boundary giving a clean,
internationally comparable target definition; the pre-1999 era is
removed rather than retained as an unconfirmed earlier definition -- if a
future story confirms its exact instrument via BoC primary sources, it
should be added as its own explicitly distinct definition, not backdated
into this one. The provider mapping's placeholder ID is replaced with
`V39079` (this story's supplied candidate), still `verified=False`,
subject to FX-43's live API verification.

**8. Confirmed candidate IDs, unchanged from FX-42**: FRED
`DFEDTAR`/`DFEDTARU`/`DFEDTARL` (USD), BoE `IUDBEDR` (GBP). **New in
FX-42H**: ECB MRO `FM.D.U2.EUR.4F.KR.MRR_RT.LEV` (EUR, replacing FX-42's
DFR key), BoC `V39079` (CAD, replacing FX-42's placeholder). **Still
unresolved**: every BoJ (JPY) mapping, per this story's own instruction
that BoJ provider mapping stays unresolved until primary-source mapping
is established -- five `VERIFY_BOJ_...` placeholders, one per era.

**Regression-proof discipline applied**: `require_research_usable_mapping`
was deliberately reduced to check only `point_in_time_safety` (dropping
the `verified` check), confirmed the two tests exercising the `verified`
failure path both failed as expected, then restored.
`validate_registry`'s series-equality check was deliberately reverted to
a key-string-only check, confirmed
`test_validate_registry_rejects_same_key_but_different_semantics` failed
(masked by the unrelated `missing required currencies` error, itself
proof the weaker check let a semantically-broken registry through),
then restored. `validate_registry`'s gap-rejection check was deliberately
reintroduced, which made the real registry itself fail to IMPORT (not
just fail a test) because JPY's own intentional gaps tripped it --
concrete proof the real registry now depends on gap-tolerance, not just
a synthetic test fixture -- then restored.

**Verification**: `pytest` (875 passed, full suite -- 24 net new/changed
tests, zero changes to any existing strategy, backtest, candle-data, or
FX-41/FX-41H macro-observation code), `ruff`, `mypy --strict`,
`pre-commit run --all-files`.

Per this story's own explicit stop instruction: no ingestion, differential
calculation, carry strategy, parameter research, or trading follows this
story.

## 2026-09-21 — FX-42H.1: policy-rate gap and JPY boundary hardening

**Scope**: replace FX-42H's blanket gap tolerance with explicitly
declared, auditable gaps, and correct two more JPY factual weaknesses
(the 2010-10-05 target-range switch, the announcement-vs-effective-date
distinction for the 2016 negative-rate transition) identified on further
review. Preserves all accepted FX-42/FX-42H architecture. No provider
verification, ingestion, rate differential, strategy, parameter research,
or trading.

**Declared gaps replace blanket tolerance.** FX-42H's `validate_registry`
accepted ANY gap between two consecutive definitions for a currency,
reasoning that some currencies genuinely have periods with no comparable
canonical scalar (the Bank of Japan's quantity-target eras). That
tolerance was too permissive: it could not tell an intentional gap from
an accidental one (a boundary typo, a forgotten definition) -- both
passed silently. `domain/declared_policy_rate_gap.py` (new):
`DeclaredPolicyRateGap` -- `currency`, half-open `start`/`end`
(`UtcTimestamp`), and a required non-empty `reason`. `validate_registry`
(`domain/policy_rate_registry.py`) now, per currency:
  - rejects any declared gap that overlaps an actual policy-rate
    definition of that currency;
  - for every gap between two consecutive definitions, requires EXACTLY
    one declared gap whose `start`/`end` exactly match the definitions'
    `valid_to`/`valid_from` boundaries -- anything else is an
    "undeclared gap" validation error, including a deliberately
    constructed one-day gap in tests;
  - rejects declared gaps for the same currency that overlap each other.

`DECLARED_GAPS` (new, `policy_rate_registry.py`) holds the registry's two
real declared gaps, both for JPY (see below); `validate_registry` is now
called at import time as `validate_registry(POLICY_RATE_DEFINITIONS,
DECLARED_GAPS)`.

**JPY's 2006-2013 overnight-call-rate era is split at October 5, 2010.**
The BoJ explicitly changed its target from a single point (around 0.1%)
to an explicit range (around 0% to 0.1%) under "Comprehensive Monetary
Easing" on this date -- a genuine instrument-SHAPE change (point vs.
range), not merely a level change, and the registry already represents
published target ranges via `TARGET_RANGE_MIDPOINT` for USD and JPY's
2024 transitional range. FX-42H's single 2006-2013 definition is
replaced by two: `_JPY_CALL_RATE_ERA_2A` (2006-03-09 to 2010-10-05,
`IDENTITY`) and `_JPY_CALL_RATE_ERA_2B` (2010-10-05 to 2013-04-04,
`TARGET_RANGE_MIDPOINT`). `test_jpy_2010_10_04_uses_identity_
transformation`/`test_jpy_2010_10_05_uses_target_range_midpoint_
transformation` prove the boundary lands correctly on each side;
`test_jpy_2010_2013_range_midpoint_of_zero_and_tenth_percent` proves the
arithmetic (midpoint of 0 and 0.1 is `Decimal("0.05")`).

**JPY's Policy-Rate Balance era now starts February 16, 2016 (effective
date), not January 29, 2016 (announcement/release date).** The BoJ
ANNOUNCED "Quantitative and Qualitative Monetary Easing with a Negative
Interest Rate" on January 29, 2016, but the -0.10% rate did not take
EFFECT until February 16, 2016. FX-42H's `valid_from=2016-01-29`
conflated the two. This is exactly the distinction FX-41's own
`MacroObservationVintage` already models with two separate fields
(`released_at` vs. optional `effective_at`) -- the Policy-Rate Balance
definition's `notes` now say so explicitly, so FX-43 knows to expect,
for the observation marking this transition, `released_at` around
January 29 and `effective_at` around February 16, and must not collapse
the two into one timestamp. The preceding QQE declared gap is extended
to end at February 16, 2016 (not January 29) -- the prior monetary-base-
target framework arguably still governed policy until the new rate
actually took effect, so the gap, not a rate definition, should cover
the announcement-to-effect window. `test_jpy_2016_02_15_returns_no_
canonical_policy_rate_definition`/`test_jpy_2016_02_16_returns_policy_
rate_balance_definition` prove the exact boundary.

**Stale documentation corrected.** `domain/policy_rate_definition.py`'s
class docstring still described "EUR/GBP/JPY/CAD" together as this
story's choice for a single continuous, open-ended definition -- true
for EUR/GBP/CAD, but wrong for JPY since FX-42H itself split JPY into
multiple effective-dated definitions with gaps. Corrected to list
EUR/GBP/CAD only, with an explicit note that USD and JPY instead need
multiple effective-dated definitions (USD for its 2008 switch, JPY for
several genuine operating-target changes including declared gaps) and a
pointer to `DeclaredPolicyRateGap` for periods with no comparable scalar
at all.

**Regression-proof discipline applied**: the undeclared-gap check, the
gap-overlaps-definition check, and the gap-overlaps-gap check were each
deliberately disabled in turn, confirmed the relevant tests failed
(including, for the undeclared-gap check, three failures at once:
the one-day-gap test, the mismatched-boundary test, and the
per-real-gap-removal test), then restored. The real registry's own
2010-10-05 split was regression-tested by temporarily corrupting era
2A's `RateTransformationKind` to `TARGET_RANGE_MIDPOINT`, confirming
`test_jpy_2010_10_04_uses_identity_transformation` failed with the wrong
kind reported, then restored. The 2016-02-16 boundary was
regression-tested by temporarily reverting both the Policy-Rate Balance
definition's `valid_from` and the preceding declared gap's `end` back to
2016-01-29, confirming `test_jpy_2016_02_15_returns_no_canonical_policy_
rate_definition` failed (a definition was wrongly returned one day
early), then restored.

**Verification**: `pytest` (899 passed, full suite -- 24 net new/changed
tests, zero changes to any existing strategy, backtest, candle-data, or
FX-41/FX-41H macro-observation code), `ruff`, `mypy --strict`,
`pre-commit run --all-files`.

Per this story's own explicit stop instruction: no provider verification,
ingestion, rate differential, strategy, parameter research, or trading
follows this story.

## 2026-09-22 — FX-43: first real external fundamental data (policy-rate
backfill)

**Numbering note**: this story's own request referred to "the FX-40
point-in-time model + FX-41 registry" -- the requester's own original
pre-renumbering shorthand from the very first story in this arc. This
codebase's actual numbering (established at that time and used
consistently since) is FX-41 (point-in-time model) and FX-42/FX-42H/
FX-42H.1 (registry). This story is recorded as **FX-43**, matching what
every prior entry in this arc already committed to calling the
ingestion story that follows the registry (`docs/DECISIONS.md`'s FX-42/
FX-42H/FX-42H.1 entries and `docs/NEXT_STEPS.md` all already say
"FX-43 ingestion").

**Scope**: the first use case and infrastructure in this codebase that
ingest real, external fundamental data -- backfilling policy-rate
history for USD, EUR, GBP, and CAD from real public provider APIs into
`MacroObservationVintage` rows via the existing, unmodified FX-41/
FX-41H `MacroObservationRepository`. JPY is not attempted (its provider
mapping remains unresolved, per FX-42H.1's own explicit scope
boundary). No pair differential, no carry framing (this data is never
called "carry" anywhere in this story, per its own explicit
instruction), no strategy, no decision logic, no parameter research.

**Architecture**: `domain/policy_rate_change_extraction.py`
(`extract_change_points`, pure, no I/O) + `application/ports/
policy_rate_history_provider.py` (`PolicyRateHistoryProvider`, a
minimal fetch-only port) + `application/use_cases/
backfill_policy_rate_history.py` (`BackfillPolicyRateHistory`,
orchestration) + four infrastructure adapters under `infrastructure/
policy_rate_providers/` (FRED, ECB Data Portal, Bank of England, Bank
of Canada) + `scripts/backfill_policy_rate_history.py` (the one-off
operational script that actually runs it). See `docs/ARCHITECTURE.md`'s
FX-43 section for the full pipeline diagram.

**No synthetic interpolation, concretely enforced**: `extract_change_
points` is the one place this guarantee lives. A provider's raw daily
series (all four confirmed to publish this way) repeats the same value
every day it stayed in effect; this function reduces that to one
observation per date the canonical value genuinely changed, and for a
`TARGET_RANGE_MIDPOINT` era, a date present in the upper-bound series
but missing from the lower-bound series (or vice versa) is recorded as
`skipped_dates`, never paired with a guessed counterpart. 8 dedicated
unit tests, plus a regression check: the "date must be present in
every raw series" guard was deliberately replaced with a forward-fill
(exactly the synthetic interpolation this function must never do),
confirmed two tests failed with fabricated values, then restored.

**Idempotent backfill, confirmed live, not just in a fake**: every
vintage goes through `MacroObservationRepository.add_vintage`, relying
entirely on FX-41H's existing conflict handling -- this story adds no
new idempotency mechanism. `scripts/backfill_policy_rate_history.py`
was run twice in sequence against the real APIs and a real Postgres:
identical change-point counts, identical vintages-ingested counts,
zero conflicts, both times. A direct SQL query after both runs
confirmed zero duplicate `(series_key, observation_period,
revision_sequence)` rows.

**Live provider verification -- real findings, not assumptions**:

- **USD (FRED)**: `DFEDTAR`/`DFEDTARU`/`DFEDTARL` confirmed correct via
  FRED's public `fredgraph.csv` endpoint (no API key). Marked
  `verified=True` in the registry.
- **EUR (ECB Data Portal)**: FX-42H's documented host
  (`sdw-wsrest.ecb.europa.eu`) is unreachable -- superseded by
  `data-api.ecb.europa.eu`. The series KEY itself, `MRR_RT`, is
  confirmed CORRECT (FX-42H's original choice, not a guess that needed
  correcting): it tracks the ECB's headline MRO rate continuously
  across the 2000-2008 variable-rate-tender period (confirmed via a
  live value change from 2.00% to 2.25% on 2005-12-06, matching the
  well-documented first hike after the ECB's 2003-2005 pause), unlike
  `MRR_FR` ("...fixed rate" only), which has NO rows at all during
  that period. Marked `verified=True`.
- **GBP (Bank of England)**: `IUDBEDR` confirmed correct. A genuine bug
  was found and fixed along the way: the BoE's WAF returns HTTP 403 for
  httpx's own default `User-Agent` string, even though an otherwise-
  identical request succeeds with any other string (reproduced by
  changing only that header) -- `BoePolicyRateHistoryProvider` now
  sends a descriptive, honest `User-Agent`
  (`forex-agent-research/1.0 (+github URL)`), not a spoofed browser
  string. Marked `verified=True`.
- **CAD (Bank of Canada)**: `V39079` confirmed correct but with a
  genuine coverage gap: its own live data only starts 2009-04-21,
  materially later than the registry's documented 1999-02-01
  `valid_from`. Checked four other candidate series
  (`V122514` "Overnight rate" -- a market/achieved rate, not the
  announced target; `STATIC_ATABLE_V39079`; `BR.CDN`; `B114039`) --
  all either measure the wrong concept or also only start 2009-04-21.
  Per this story's own instruction to stop and document rather than
  invent, **1999-02-01 through 2009-04-20 is NOT backfilled** and is
  explicitly listed in the data-quality report's `known_gaps`. Marked
  `verified=True` for the 2009-04-21-onward portion its live data
  actually covers.

**A real infrastructure bug was found and fixed via the live run,
not code review**: the ECB client originally built its request path as
`/service/data/FM/{provider_series_id}`, but the registry stores the
FULL key including the "FM." dataflow prefix (as ECB itself cites it,
and as the response's own `KEY` column echoes it back) --
`FM.D.U2.EUR.4F.KR.MRR_RT.LEV`. Passed through unmodified, this
produced `/service/data/FM/FM.D.U2...`, which the live API correctly
rejects with HTTP 400 (a doubled dataflow segment). The bug did not
surface in the mocked-transport unit test, because that test's own
canned `provider_series_id` input didn't reflect the registry's real
(prefixed) value -- fixed both the client (`removeprefix("FM.")`
before building the path) and the test (now passes the real prefixed
key and asserts the resulting path has the prefix stripped exactly
once). A reminder that a unit test's fidelity to real input shapes
matters as much as the code under test; caught only because this story
insisted on running the real pipeline end-to-end rather than trusting
mocked coverage alone.

**Coverage reporting reflects actual data, not the requested window --
a second bug found via the live run**: `CurrencyBackfillReport.
coverage_start`/`coverage_end` originally reported the WINDOW A
BACKFILL ASKED a provider for, not what it actually got back. Running
the real CAD backfill exposed this concretely: the report claimed
coverage starting 1999-02-01 (the requested/registry `valid_from`)
while the actual earliest ingested vintage was 2009-04-21 -- exactly
the gap `known_gaps` was supposed to be flagging, silently
contradicted by the summary field sitting right next to it.
`EraBackfillReport` now carries `earliest_change_point`/
`latest_change_point` (the true span of change points actually found),
and `CurrencyBackfillReport.coverage_start`/`coverage_end` aggregate
from those instead of the requested window.
`test_coverage_reflects_actual_data_not_the_requested_window`
reproduces the exact scenario (a provider whose real data starts later
than the requested window) and was confirmed to fail against the
original (reverted) implementation before being restored.

**Real data now in Postgres**: 258 `MacroObservationVintage` rows
across USD (92: 59 target-point + 33 target-range change points), EUR
(62), GBP (71), CAD (33). Spot-checked against well-known historical
facts: USD's 2008-12-16 vintage is exactly `0.125` (the midpoint of the
FOMC's newly announced 0%-0.25% target range, computed by
`TARGET_RANGE_MIDPOINT` on real FRED data); a `latest_available_as_of`
query at 2008-12-15 correctly returns `1.0000` (the prior level, in
effect since October 29, 2008) while the same query at 2008-12-16
returns `0.125` -- an as-of query working correctly across a genuine
historical policy transition, on real ingested data, through the
unmodified FX-41 repository. GBP's earliest vintage (1997-06-06,
`6.5`) matches the Monetary Policy Committee's first-ever rate decision
after gaining operational independence.

**The point-in-time-safety gap this story does NOT close, by design**:
`released_at` is set equal to `observation_period` (the date a
provider's raw series shows a value change) for every ingested
vintage -- an EFFECTIVE-DATE proxy. This is knowably NOT the same as
when the market actually learned of a decision: central banks
routinely announce a rate decision (e.g. an FOMC statement release,
conventionally around 2:00 p.m. ET) some time before it takes effect.
Establishing genuine announcement/publication timestamps, distinct
from effective dates, was explicitly out of scope for this story and
is exactly the "next review gate" its own instructions named. No
`ProviderSeriesMapping.point_in_time_safety` is changed by this story
-- every mapping remains `UNKNOWN`, and `require_research_usable_
mapping` continues to reject every mapping in the registry
unconditionally, including the ones just marked `verified=True`.
Daily effective-date observations are explicitly NOT sufficient
grounds for `POINT_IN_TIME_SAFE`, matching FX-42H's own stated
principle -- this story's real ingestion changes nothing about that
invariant.

**Verification**: `pytest` (945 passed, full suite -- new tests for the
change-extraction algorithm, the use case (using the REAL registry
with fake provider data, matching how `AggregateCandles` et al. call
domain functions directly), and all four provider clients via
`httpx.MockTransport`, matching the existing OANDA adapter precedent),
`ruff`, `mypy --strict`, `pre-commit run --all-files`. The real
backfill script was additionally run twice, live, against the real
APIs and a real Postgres, with results spot-checked against known
historical facts as described above.

Per this story's own explicit instruction: this data is not called
"carry" anywhere in this codebase. No rate differential is computed.
No strategy, scoring, or decision logic follows this story.

## 2026-09-22 — FX-43H: policy-rate backfill hardening

**Scope**: harden FX-43 before any rate-differential research reads
this data. Seven required items, all addressed; no ingestion of new
currencies/series, no rate differential, no carry strategy, no
parameter research, no JPY provider work, no invented release
timestamps, no decision logic.

**1. Half-open policy-rate eras now genuinely enforced.** Registry
validity is `[valid_from, valid_to)`, but `PolicyRateHistoryProvider`'s
own contract queries providers by INCLUSIVE calendar-date range.
FX-43's original window computation could, for an era with a defined
`valid_to`, request the provider for `end=valid_to` itself -- wrongly,
since `valid_to`'s date belongs to the NEXT era. This never surfaced
in practice only because FRED's `DFEDTAR` happens to stop publishing
the day before USD's target-point-to-target-range boundary (2008-12-16)
-- a fact about FRED, not a guarantee. `BackfillPolicyRateHistory.
_fetch_end` now clamps the requested end to `valid_to - 1 day`
whenever the window would otherwise reach or pass `valid_to`.
`test_half_open_era_boundary_is_enforced_against_the_provider_fetch`
reproduces the story's own exact required scenario: era A's `valid_to`
and era B's `valid_from` are the same date D (USD's real 2008-12-16
boundary), a FAKE provider is given a row on D for BOTH eras
(deliberately contrary to real FRED behavior), and the test proves D
belongs only to era B, with era A's own `requested_end` never reaching
D at all. Regression-tested by reverting the clamp and confirming the
test fails with `requested_end == D` instead of `< D`.

**2. Raw provider coverage separated from change-point span.**
`EraBackfillReport` gained `earliest_raw_observation`/`latest_raw_
observation` (the true span of raw data a provider returned, computed
from every raw `(date, value)` pair fetched, regardless of whether any
of it represented a rate change) alongside the existing `earliest_
change_point`/`latest_change_point` (the narrower span of genuine
changes). `CurrencyBackfillReport.coverage_start`/`coverage_end` now
aggregate from the RAW fields, not the change-point fields --
correcting FX-43's own choice, which (ironically, given FX-43's own
`docs/DECISIONS.md` entry already documents catching a SIMILAR
requested-vs-actual conflation for CAD) still conflated "the newest
data received" with "the newest rate change", understating coverage
for any currency whose rate has been stable for a stretch before the
report's `as_of`.
`test_coverage_end_reflects_raw_data_not_last_change_point`
constructs exactly this scenario (a change on 2010-02-01, then stable,
still-published data through 2010-06-01) and proves `coverage_end` is
2010-06-01, not 2010-02-01. Regression-tested by reverting `coverage_
start`/`coverage_end` to aggregate from the change-point fields and
confirming the test fails.

**3. `add_vintage` reports INSERTED vs ALREADY_PRESENT accurately.**
`VintageWriteOutcome` (`application/ports/
macro_observation_repository.py`) -- `INSERTED`/`ALREADY_PRESENT` --
replaces `add_vintage`'s previous `None` return across the Protocol,
`SqlAlchemyMacroObservationRepository`, and `FakeMacroObservationRepository`.
`MacroVintageConflictError` is unchanged for genuine same-identity/
different-payload conflicts. `BackfillPolicyRateHistory` now reports
`vintages_inserted`/`vintages_already_present` per era (and
`total_vintages_inserted`/`total_vintages_already_present` per
currency) instead of one undifferentiated `vintages_ingested` count.
Confirmed against the real pipeline: the real Postgres data was
cleared and the hardened backfill script run twice -- first run
`inserted=258` total across USD/EUR/GBP/CAD, `already_present=0`;
second run `inserted=0`, `already_present=258`; a direct SQL query
confirmed zero duplicate `(series_key, observation_period,
revision_sequence)` rows both times.

**4. The release/effective distinction is now explicit in the data
model, not just in prose.** `MacroObservationVintage` gained
`released_at_is_verified: bool = True` (defaulting to the ordinary
case -- unaffected for every pre-existing caller).
`BackfillPolicyRateHistory` now explicitly constructs every vintage
with `released_at_is_verified=False`, making FX-43's effective-date-
proxy limitation part of the stored fact, not something a reader has
to already know from documentation. `MacroObservationRepository`
gained `replace_provisional_release_timing(series_key,
observation_period, revision_sequence, verified_released_at,
verified_effective_at)` -- the explicit, safe replacement path this
story was asked to design and implement (not use): it corrects an
existing PROVISIONAL row's `released_at`/`effective_at` in place,
marking it verified, WITHOUT a `value` parameter at all (structurally
impossible to also change the economic value through this method --
`test_replace_provisional_release_timing_has_no_value_parameter`
asserts this directly via `inspect.signature`) and WITHOUT touching
`revision_sequence` -- a release-timing correction is never
represented as a revision, per this story's own explicit instruction.
Fails closed: raises if no vintage exists at the identity, and raises
if the existing row is already `released_at_is_verified=True` (only a
still-provisional row may be replaced this way, so this method can
never be used to silently rewrite an already-verified timestamp).
Implemented as the ONE deliberate, narrowly-scoped UPDATE in
`SqlAlchemyMacroObservationRepository` -- every other write remains
`INSERT ... ON CONFLICT DO NOTHING`, and this one UPDATE only ever
touches `released_at`/`effective_at`/`released_at_is_verified`,
guaranteeing "a corrected release timestamp must not coexist with an
earlier proxy row a historical as-of query could accidentally see":
there is only ever one row at that identity, so a query at any as-of
time sees either the old proxy (before correction) or the new verified
timestamp (after) -- never both. No caller of this method exists yet;
this story's job was to make replacement possible and safe, not to
perform it -- no verified announcement timestamp exists yet to replace
anything with, and none is invented here. New Alembic migration
(`5707ecb39242`) adds the backing column, `server_default='true'`
(unaffected for any pre-existing row's default). The 258 rows FX-43
had already written were cleared and the hardened backfill script
re-run so every row correctly carries `released_at_is_verified=False`
-- confirmed via direct SQL query (`SUM(CASE WHEN released_at_is_
verified THEN 1 ELSE 0 END) = 0` for every series).

**5. Duplicate raw observations: identical values collapse, conflicting
values fail -- never "last value wins".** `extract_change_points`
(`domain/policy_rate_change_extraction.py`) now raises the new
`ConflictingRawObservationError` when one raw series reports two
DIFFERENT values for the same date; an identical repeat still
collapses harmlessly (unchanged). `BackfillPolicyRateHistory` catches
this and reports it as an explicit `data_integrity_error` on the era,
writing zero vintages for that era rather than guessing. The existing
no-forward-fill rule (a date missing from one series in a multi-series
transformation is skipped and reported, never paired with a fabricated
counterpart) is unchanged.
`test_conflicting_duplicate_raw_values_on_one_date_raises` and
`test_conflicting_raw_values_are_reported_as_data_integrity_error`
cover the domain and use-case levels respectively.

**6. FRED documentation corrected: DFEDTAR does not cover
"1954-present".** `infrastructure.policy_rate_providers.fred_client`'s
module docstring and the registry's own USD provider-mapping note both
previously said DFEDTAR "covers 1954-07-01 through the present" (or
"onward") -- wrong. DFEDTAR is FRED's DISCONTINUED single-target-rate
series; its raw data ends 2008-12-15, the day before the FOMC switched
to a target range. Both docstrings now say so explicitly, and
cross-reference FX-42H's already-established finding that the
pre-1994 portion is a retrospective reconstruction, not
contemporaneously published data -- this registry's own `valid_from`
(1994-02-04), not DFEDTAR's raw availability, is what actually bounds
the usable history. `DFEDTARU`/`DFEDTARL` are correctly documented as
the LIVE series covering the target-range era from 2008-12-16 onward.

**Regression-proof discipline applied**: the half-open boundary clamp
and the raw-vs-change-point coverage aggregation were each deliberately
reverted in turn, confirmed to fail their respective dedicated tests
(the boundary test failing with `requested_end == boundary` instead of
`< boundary`; the coverage test failing with `coverage_end` equal to
the change-point date instead of the later raw-observation date), then
restored. `extract_change_points`'s duplicate-conflict detection and
`add_vintage`'s INSERTED/ALREADY_PRESENT/conflict paths were exercised
directly by their own new dedicated tests (unit, integration, and a
live double-run against real Postgres) rather than by breaking and
restoring the passing implementation a second time, since the FX-43H
live re-run itself already served as an end-to-end confirmation
(cleared real data, re-ran the hardened script twice, confirmed
`inserted`/`already_present` counts and zero duplicate rows directly
via SQL).

**Verification**: `pytest` (962 passed, full suite -- net new/changed
tests across `domain.policy_rate_change_extraction`,
`domain.macro_observation_vintage`,
`application.ports.macro_observation_repository`'s two concrete
implementations, and `BackfillPolicyRateHistory`; zero changes to any
existing strategy, backtest, or unrelated candle-data code), `ruff`,
`mypy --strict`, `pre-commit run --all-files`. Three transient live-
OANDA-practice-API test failures were observed across repeated runs
(Cloudflare 504 gateway timeouts, a different live-candle test each
time) -- confirmed unrelated to this story (no policy-rate/macro code
touches that path) and transient (each passed on immediate retry; a
fully clean 962-passed run was also obtained). The real Postgres
policy-rate data was cleared and the hardened backfill script re-run
twice live against the real FRED/ECB/BoE/BoC APIs, confirming: (a)
zero duplicate rows, (b) every row `released_at_is_verified=False`,
(c) the real USD boundary date (2008-12-16) has exactly one row,
owned by the target-range era, at the correct midpoint value (0.125).

Per this story's own explicit stop instruction: no rate differential,
no carry strategy, no parameter research, no JPY provider work, no
invented release timestamps, and no decision logic follows this
story.

## 2026-09-22 — FX-43H.1: provisional timestamp fail-closed hardening

FX-43H introduced `released_at_is_verified` and
`replace_provisional_release_timing` but left two gaps: the field
DEFAULTED to `True` (verified) rather than failing closed, and the
replacement method was a SELECT-then-conditional-UPDATE with a real
race window between the two statements. This story closes both,
touching only those two mechanisms -- no new provider, no verified
announcement timestamp, no rate/carry/JPY work.

**1. `MacroObservationVintage.released_at_is_verified` now defaults to
`False`.** A caller that does not explicitly pass
`released_at_is_verified=True` gets a provisional vintage, not a
silently-assumed-verified one. Blast-radius check before flipping it:
`grep -rn released_at_is_verified` across the whole codebase found
exactly one test relying on the old default (renamed/inverted in
place) and no non-test construction site that omits the field while
depending on it being `True`.

**2. The SQLAlchemy column's `server_default` now matches (`'false'`,
was `'true'`).**

**3. Migration `80c0ae20257b` conservatively reclassifies every
pre-existing row, unconditionally.** It does not merely change the
schema default for future inserts -- that alone would leave every row
written under the old `server_default='true'` looking "verified" when
it never actually was. The migration's `upgrade()` issues an
unconditional `UPDATE macro_observation_vintages SET
released_at_is_verified = false` (no `WHERE` clause narrowing which
rows) BEFORE changing the schema default, so a database applying this
migration ends up correct without an operator manually clearing or
reloading data -- the story's own explicit constraint.
`downgrade()` reverts only the schema-level default back to `'true'`;
it deliberately does NOT attempt to restore per-row values, since we
have no way to know which rows (if any) were ever genuinely verified
versus merely defaulted -- inventing that certainty on downgrade would
be worse than not reverting the data at all.

**4. `replace_provisional_release_timing` is now one atomic
conditional `UPDATE ... WHERE ... AND released_at_is_verified = false
... RETURNING id`**, replacing the old SELECT-then-UPDATE. The
provisional-row check and the write are the same statement; `RETURNING
id` is how the caller learns whether it applied, with no second query
deciding anything. Under Postgres's default READ COMMITTED isolation
this is race-safe: a second concurrent UPDATE against the same
identity blocks on the first's row lock, then -- once the first
commits -- re-evaluates its own `WHERE` clause against the
now-verified row and correctly matches zero rows. When the UPDATE
matches nothing, a subsequent `SELECT` (reusing the existing
`_select_one` helper) is purely diagnostic, distinguishing "no such
vintage" from "already verified" for the raised error -- it never
influences whether anything was written. The port's docstring
(`application.ports.macro_observation_repository`) now states this
atomicity as part of the contract itself, not just as an
implementation detail of one adapter.

**`FakeMacroObservationRepository`** needed no logic change: its
check-then-set has no `await` between the two steps, so nothing can
interleave under Python's single-threaded cooperative asyncio
scheduling -- a comment now says so explicitly, to head off a future
"make the fake atomic too" misunderstanding.

**Regression-proof discipline applied to all three new guarantees,
each deliberately broken and confirmed to fail for the right reason,
then restored:**
- domain default flipped back to `True` -- confirmed
  `test_released_at_is_verified_defaults_to_false` fails;
- the atomic UPDATE reverted to SELECT-then-UPDATE -- confirmed the
  new concurrency test fails, and it failed by both racers reporting
  success (`outcomes=[None, None]`) rather than an error, i.e. the
  test caught exactly the double-write race it exists to catch;
- the migration's reclassification narrowed with a `WHERE
  released_at_is_verified IS NULL` escape hatch -- confirmed the new
  migration unit test fails, correctly reporting the injected `WHERE`
  clause.

**New tests**: `test_released_at_is_verified_defaults_to_false` /
`test_released_at_is_verified_can_be_explicitly_true` (domain);
`test_migration_released_at_is_verified_fail_closed.py` (new file --
loads migration `80c0ae20257b` directly via `importlib.util` rather
than a dotted import, since `alembic/` collides in name with the
installed `alembic` package and `alembic/versions/` has no
`__init__.py`; patches `alembic.op.execute`/`alter_column` to assert
the exact DDL/DML without touching a real database);
`test_concurrent_replace_provisional_release_timing_only_one_wins`
(integration -- two independent sessions/connections race
`replace_provisional_release_timing` against the identical identity
via `asyncio.gather`; asserts exactly one success and one
already-verified failure). Existing `replace_provisional_release_
timing` tests (fake and integration) needed no behavioural changes --
same error-message text, same success/failure shape -- only the
concurrency case was new.

**Verification**: `pytest` (967 passed, full suite), `ruff`, `ruff
format`, `mypy --strict`, `pre-commit run --all-files`. Applied
migration `80c0ae20257b` against the real dev Postgres and confirmed
directly via SQL: all 258 existing policy-rate rows read
`released_at_is_verified = false` (they already did, from FX-43H's own
explicit sets -- this migration's reclassification was a structural
safety net here, not a correction of a known-wrong value) and the
column's `information_schema` default is now `false`.

Per this story's own explicit stop instruction: no providers, no
verified announcement timestamps, no rate differential, no carry
research, no JPY work, no release-time sourcing, no strategy changes
follow this story.

## 2026-09-22 — FX-44: point-in-time policy-rate release verification

FX-43/FX-43H established real policy-rate change points with
provisional, effective-date-proxy timing; FX-43H.1 made the
replacement mechanism fail-closed and atomic. This story is the first
to actually USE that mechanism: real primary-source research into
USD/EUR/GBP/CAD central-bank release-timing conventions, applied only
where genuinely defensible, leaving everything else provisional. JPY
stays out of scope throughout, per the story's own instruction.

**Research method.** Federal Reserve, ECB, Bank of England, and Bank
of Canada release-timing conventions were researched live (WebSearch/
WebFetch against each institution's own site plus corroborating
secondary sources), then checked for self-consistency against the 258
real change-point dates already in Postgres (e.g. computing the
weekday of every stored EUR/GBP/CAD date to confirm or refute an
assumed institutional pattern before relying on it -- see
`domain.policy_rate_release_timing_registry`'s own per-currency
research notes and citations for the full reasoning). This caught a
real mistake before it shipped: an initial assumption that the Fed's
"2:15pm ET" figure was a stable pre-2013 convention turned out, on
closer reading of the same sources, to describe only the 2011-2012
press-conference-meeting schedule specifically (non-press-conference
statements in that window were released at 12:30pm ET instead) --
i.e. the exact minute is genuinely evidenced as UNSTABLE pre-2013, not
merely unconfirmed. That finding is why USD's pre-2013 era uses a
conservative bound rather than an exact claim (below).

**1. `ReleaseTimingRule`/`ReleaseTimingConfidence`
(`domain.release_timing_rule`, new).** A pure, cited data type: an
institution, a local time-of-day, an IANA timezone, a validity window,
and a citation, with `confidence` distinguishing `EXACT` (a
specific, documented institutional convention -- from a primary
source or multiple mutually-consistent secondary sources) from
`CONSERVATIVE_SAFE_BOUND` (the exact minute is not confidently
citable, but a same-day/business-hours convention is confirmed, so a
deliberately late bound -- e.g. end of the announcement day, local
time -- is used instead; guaranteed no earlier than the true release,
never claimed as the exact moment). `resolve()` uses `zoneinfo` (the
stdlib's own historical IANA database) to convert a local date/rule
into an exact UTC instant with the CORRECT historical DST offset for
that specific date -- this module hand-codes zero DST transition
dates itself.

**2. `domain.policy_rate_release_timing_registry` (new)** -- the
hand-researched, cited rule set itself, one resolver per currency:
  - **USD (Federal Reserve)**: `EXACT`, 14:00 America/New_York, for
    regularly scheduled meetings from 2013-03-19 onward (the Fed's own
    March 13, 2013 press release) -- 30 of USD's 92 change points (all
    fall in the 2015-12-16-onward stretch, since the 2008-2015 ZIRP
    period has no change points to disambiguate against the rule
    change). `CONSERVATIVE_SAFE_BOUND`, end-of-day America/New_York,
    for 1994-02-04 through 2013-03-19 -- 54 change points; the exact
    minute is same-day/afternoon but not confidently citable as stable
    across this span (see the research-method note above). 8 known
    inter-meeting/emergency dates (1998-10-15, 2001-01-03, 2001-04-18,
    2001-09-17, 2008-01-22, 2008-10-08, 2020-03-04, 2020-03-16) are
    explicitly excluded and remain provisional.
  - **GBP (Bank of England)**: `EXACT`, 12:00 Europe/London, for every
    regular Thursday MPC decision (65 of 71) -- every source found
    describes this consistently, with no contradicting evidence across
    the MPC's history, unlike the Fed case. 6 known irregular dates
    (the pre-MPC 1997-06-02 transition, the MPC's own first, Friday,
    decision on 1997-06-06, a stray 1999-09-08 Wednesday, and the
    2001-09-18/2008-10-08/2020-03-11 coordinated/emergency actions)
    remain provisional.
  - **CAD (Bank of Canada)**: `CONSERVATIVE_SAFE_BOUND`, end-of-day
    America/Toronto, for 30 of 33 change points -- the exact
    9:00am-vs-9:45am ET transition date within our 2009-2025 data
    range was not established, and it is not established whether the
    raw provider's stored date is the announcement date itself or a
    next-business-day proxy; end-of-day is safe under either
    uncertainty. The 3 March 2020 COVID emergency dates remain
    provisional.
  - **EUR (European Central Bank)**: `EXACT`, 13:45 Europe/Brussels
    (pre-2022-07-21) or 14:15 Europe/Brussels (from 2022-07-21, the
    ECB's own announced change), for 44 of 62 change points. This is
    also the one currency with a genuine, DOCUMENTED
    announcement-before-effective-date split (FX-44 section 4): the
    stored proxy date is confirmed (every single one from 2006-03-08
    onward is a Wednesday -- checked computationally against all 45
    real dates, not assumed) to be the EFFECTIVE date -- "the first
    main refinancing operation following the Governing Council
    decision" per the ECB's own published methodology -- six days
    after the Thursday decision. `released_at` is therefore set to the
    Thursday decision date/time, STRICTLY BEFORE the unchanged
    `effective_at` (the original stored proxy). 18 change points
    remain provisional: the 1999-01-01 Euro-launch inception rate (no
    ordinary announcement event), the pre-2006-03-08 era (a genuinely
    different, less-established operational regime the ECB's own page
    describes separately), and two pattern-breaking anomalies
    (2005-12-06, 2006-06-15) plus the 2001-09-18 coordinated action,
    none independently investigated further in this story.

**3. `MacroObservationVintage.released_at_is_conservative_bound: bool
= False` (new field, mirroring `released_at_is_verified`'s own
fail-closed default from FX-43H.1)** -- distinguishes a deliberately
conservative timestamp from an exactly verified one, so
`released_at_is_verified=True` is never overloaded to mean "we guessed
a safely late time" (the story's own explicit prohibition). New
migration `aee1fa641be6` adds the column, defaulting `False` for every
existing and future row.

**4. `replace_provisional_release_timing` extended, not replaced**
(`confidence: ReleaseTimingConfidence` parameter added; `verified_
released_at`/`verified_effective_at` renamed to `released_at`/
`effective_at` since they are no longer necessarily "verified"). The
atomic UPDATE's WHERE predicate now requires BOTH `released_at_is_
verified = false` AND `released_at_is_conservative_bound = false` --
a still-fully-provisional row -- before either outcome can be written;
a row already classified either way is protected from a second write,
confirmed for both outcomes by dedicated tests (see below) and by
regression-proof discipline (the conservative-bound predicate clause
was deliberately dropped, confirmed the new symmetric test failed by
silently overwriting an already-conservative row, then restored).
`list_all_for_series` (new port method) enumerates every stored
vintage for a series -- an administrative/batch read, deliberately NOT
point-in-time filtered, that the new use case needs and no existing
method provided.

**5. `VerifyPolicyRateReleaseTiming`
(`application.use_cases.verify_policy_rate_release_timing`, new)** --
the first real caller of `replace_provisional_release_timing`. For
each stored change point: resolves via the registry; if unresolved,
reports it and leaves the row untouched; if resolved and the row is
still fully provisional, replaces through the repository; if resolved
and the row is ALREADY classified, compares against what the registry
resolves to NOW -- identical timing is reported as a no-op
(`newly_applied=False`, not an error, satisfying the story's
idempotency requirement), a genuine mismatch is reported as
`CONFLICTING` and left untouched (this can only arise if the registry
itself changes between runs). `scripts/verify_policy_rate_release_
timing.py` runs this for USD/EUR/GBP/CAD against real Postgres and
writes `research_results/fx44/policy_rate_release_verification.json`.

**6. `domain.research_readiness` (new)** -- FX-44 section 8's critical
invariant as code: `require_research_ready_interval` raises
`ResearchIntervalNotReadyError` if ANY vintage in the caller's
selected `[start, end)` interval is neither `released_at_is_verified`
nor `released_at_is_conservative_bound` -- a single provisional
observation fails the WHOLE interval, no partial pass, no percentage
threshold. This is the mandatory pre-flight check a future FX-45 must
call before running against any selected interval.

**7. Provider-mapping promotion: deliberately NOT touched.** No
`ProviderSeriesMapping.point_in_time_safety`/`verified` field is
flipped for any currency -- every currency still has unresolved
change points across its full stored history, and FX-44 section 7 is
explicit that promotion requires the ENTIRE research interval to
qualify, not merely some observations within it. Interval-specific
safety is represented explicitly instead: the JSON report's
`provider_mapping_promotion` block states this reasoning directly and
machine-readably, and a future research use case is expected to call
`require_research_ready_interval` against its own specific selected
interval rather than rely on a blanket mapping-level flag.

**Live run against real Postgres** (258 existing change points, all
from FX-43's real backfill): USD 30 exact / 54 conservative / 8
unresolved; EUR 44 exact / 0 conservative / 18 unresolved; GBP 65
exact / 0 conservative / 6 unresolved; CAD 0 exact / 30 conservative /
3 unresolved. Zero conflicts. A second run reproduced identical
figures with 0 newly-classified (full idempotency confirmed live, not
just in tests). Spot-checked directly via SQL: the EUR 2022-07-27 row
now reads `released_at=2022-07-21T12:15:00Z`,
`effective_at=2022-07-27T00:00:00Z` (announcement strictly before
effective, both correctly converted for DST -- CEST in July);
known-irregular USD 2008-01-22 remains fully untouched
(`released_at_is_verified=false`, `released_at_is_conservative_bound=
false`, original proxy `released_at` unchanged).

**Regression-proof discipline applied to every new safety-relevant
mechanism**, each deliberately broken, confirmed to fail its dedicated
test for the right reason, then restored: the domain-default fail-
closed test (new field), the DST-sensitive UTC conversion (both
`ReleaseTimingRule.resolve()` tests failed correctly when DST handling
was stubbed out to a bare UTC reinterpretation), the research-
readiness fail-closed gate (all three relevant tests failed correctly
when the offender-detection list was hardcoded empty), the new
conservative-bound atomic-UPDATE predicate (the new symmetric
already-conservative test failed correctly, and specifically by
silently succeeding at an overwrite it should have refused), and the
use case's idempotency match-check (both the unit and integration
rerun tests failed correctly, reporting `CONFLICTING` instead of a
clean no-op, when the match check was stubbed to always report a
mismatch).

**Tests**: `test_release_timing_rule.py` (exact intraday UTC
conversion, DST sensitivity for two different institutions/timezones,
validity-window half-open semantics, validation); `test_policy_rate_
release_timing_registry.py` (per-currency exact/conservative/
unresolved cases, the EUR announcement-before-effective-date case, JPY
and unsupported currencies raise); `test_macro_observation_vintage.py`
(new field default/explicit/type-validation, extending FX-43H.1's
pattern); `test_research_readiness.py` (all-safe passes, mixed range
rejected, a single provisional observation fails closed even alone,
provisional vintages OUTSIDE the interval don't block it, the
half-open interval boundary); `test_verify_policy_rate_release_
timing.py` (unit, fake-repository-based, and integration, live-
Postgres-based, covering: newly-exact classification, newly-
conservative classification, unresolved stays provisional, rerun
idempotency, the EUR announcement-before-effective case end-to-end
through the repository, mixed-outcome report aggregation, and a
future timestamp never visible before its corrected release time);
two new symmetric `replace_provisional_release_timing` tests (fake and
integration) proving an already-CONSERVATIVE row is protected from
overwriting, not just an already-VERIFIED one.

**Verification**: `pytest` (1023 passed, full suite, up from 967),
`ruff`, `ruff format`, `mypy --strict`, `pre-commit run --all-files`.
Live-verified against real Postgres as described above, including a
second idempotent run.

Per this story's own explicit stop instruction: no pair-rate
differential, no carry strategy, no technical-signal filtering, no
performance research, no JPY provider ingestion, no COT, no
macro-event surprises, no news, no decision logic follows this story
-- and the differential experiment (FX-45) does not start
automatically.

## 2026-09-22 — FX-44H: release-timing semantic hardening

A review of FX-44 found a real, demonstrable bug in its USD
resolution, plus four related gaps in the mechanisms around it. This
story fixes all five, using the SAME live-Postgres-verification
discipline as every prior story in this epic.

**1. USD announcement/effective semantics were backwards for the
modern (2013+) EXACT tier.** FX-44 treated FRED's stored change-point
date as the FOMC announcement date and set `effective_at=None`. This
is wrong: that stored date is the target range's OPERATIONAL EFFECTIVE
date, and the FOMC's own "Implementation Note" (a document accompanying
the main statement, e.g. "Effective January 29, 2026, the Federal Open
Market Committee directs the Desk to...",
https://www.federalreserve.gov/newsevents/pressreleases/
monetary20260128a1.htm) states an explicit effective date that is
LATER than the decision itself -- one day later, in every case this
story checked. Per the story's own explicit instruction not to assume
a blind `-1 day` offset, every one of the 30 currently EXACT-classified
USD change points was individually cross-referenced against the Fed's
own published FOMC meeting calendars (fomccalendars.htm for 2021-2027,
fomchistorical2015.htm through fomchistorical2019.htm for the rest).
This paid off directly: 2015-12-16 ("liftoff", the first hike since
2006) and 2016-12-14 (the second hike) both have a same-day (0-day)
gap, predating the now-standard next-day mechanism -- a blind `-1 day`
formula would have gotten these two specific, real historical dates
wrong. `USD_EFFECTIVE_TO_DECISION_DATE` (`domain.policy_rate_
release_timing_registry`) is therefore an explicit, individually-cited
`dict[date, date]`, not a formula -- the EXACT tier now has NO
fallback transformation at all: a USD date not present as a mapping
key is unresolved, even a future one that "looks like" it fits the
usual pattern. `effective_at` is now populated (the original stored
proxy, kept as-is) for all 30, mirroring the same announcement-before-
effective pattern already established for EUR.

**2. Remediating the 30 already-written rows required a genuinely new
mechanism, not a bigger hammer.** FX-44 had already written the WRONG
timing into Postgres for these 30 rows, and `replace_provisional_
release_timing`'s whole safety contract is refusing to touch an
already-classified row -- exactly the rows needing a fix. Rather than
weakening that guarantee, `MacroObservationRepository.correct_
verified_release_timing` (new port method) is a SEPARATE, deliberately
different atomic conditional UPDATE: it requires the row to ALREADY be
`released_at_is_verified=True` (the opposite precondition), plus an
exact match on the caller's `expected_current_released_at`/
`expected_current_effective_at` -- an optimistic-concurrency guard that
makes a second, accidental correction attempt fail closed (the
expected value is now stale) rather than silently reapplying, and a
concurrent double-correction race structurally impossible (proven by a
new `asyncio.gather` concurrency regression test, mirroring FX-43H.1's
own). `application.use_cases.remediate_release_timing.
RemediateReleaseTiming` is the use case that drives this: for every
currently-EXACT vintage of a currency, it compares stored timing
against what the (now-fixed) registry resolves NOW, corrects a
mismatch, and reports (without writing) a row that's already correct
-- idempotent by construction. `scripts/remediate_usd_release_
timing.py` ran this live against the real 30 rows: all 30 corrected
on the first run, all 30 reported `ALREADY_CORRECT` (zero writes) on
an immediate second run. This is a genuinely different operation from
routine verification, run deliberately, not automatically -- see
`docs/ARCHITECTURE.md`'s own framing of the split.

**3. Research readiness didn't account for carry-in state.**
`require_research_ready_interval` originally judged only vintages
whose `observation_period` fell literally inside the selected
interval -- insufficient, because a query anywhere in an interval with
zero in-interval changes still returns whatever vintage was CARRIED IN
from before it (`latest_available_as_of`/`observation_as_known_at`'s
own semantics). An interval with no changes of its own is not
vacuously safe: if the observation that actually governs the whole
interval is provisional, the interval is unsafe even though nothing
"inside" it looks wrong. New `domain.research_readiness.select_
research_candidates` derives BOTH the carry-in state (the latest
`observation_period` at or before `interval_start`) and the
in-interval observations from a series' COMPLETE stored history, so a
caller cannot get this wrong by hand-selecting the wrong candidate set
-- `require_research_ready_interval`'s own signature changed to take
that complete history directly, not a pre-filtered list. An interval
with an EMPTY derived candidate set (no carry-in and nothing in-
interval either) now fails closed too, via a new `no_baseline` flag on
`ResearchIntervalNotReadyError` -- "no evidence" is not the same as
"nothing wrong found", and must not silently pass.

**4. Exact/conservative mutual exclusivity is now structurally
enforced, at both layers the story named.** Nothing previously stopped
`MacroObservationVintage(released_at_is_verified=True, released_at_
is_conservative_bound=True)` from being constructed -- the two
FX-44H.1/FX-44 docstrings only asserted this was true "in practice".
`__post_init__` now rejects it explicitly. Migration `f350d505412b`
adds `ck_macro_observation_vintages_exclusive_timing_confidence`, a
Postgres CHECK constraint mirroring the same rule -- applying this
migration is itself the existing-data verification (Postgres refuses
to add a CHECK constraint over data that already violates it; this
migration applied cleanly, and a direct query confirmed zero violating
rows before it ran). Live-verified twice: a raw `UPDATE` attempting to
set both flags on a real row was rejected with `IntegrityError` and
rolled back cleanly (confirmed via direct SQL that zero rows ended up
violating the invariant), and a dedicated integration test reproduces
this exact scenario formally.

**5. ECB provenance hardened.** The EUR timing rules' citations were
secondary sources (investinglive.com, an ECB tweet) even though a
primary one exists: the ECB's own official 27 June 2022 press release,
"New times for ECB's monetary policy decisions and press conference"
(https://www.ecb.europa.eu/press/pr/date/2022/html/
ecb.pr220627~73acedf868.en.html), which explicitly states "Starting
from 21 July, monetary policy decisions will be published at 14:15 CET
(instead of 13:45)" -- one document, authoritative for BOTH the old
and new times, replacing both prior citations. Separately, `_resolve_
eur` previously relied ENTIRELY on a hand-curated exclusion list
(`EUR_IRREGULAR_DATES`) to keep the six-day transformation away from
non-Wednesday dates -- safe only as long as every past anomaly had
already been found and listed by hand. It now REQUIRES `stored_date.
weekday() == Wednesday` structurally before ever applying the
transformation, with `EUR_EXPLICIT_DECISION_DATE_OVERRIDES` (new,
empty today) as the only sanctioned way a genuinely-researched
non-Wednesday date may still resolve -- never a generic fallback. This
means a future anomalous EUR date a later backfill run ingests fails
closed automatically, not only the two anomalies already known today.

**Regression-proof discipline applied to every new safety-relevant
mechanism**, each deliberately broken, confirmed to fail its dedicated
test for the right reason, then restored: the USD explicit mapping
(reverted to FX-44's original per-date-formula bug -- all 4 relevant
tests failed correctly, including one proving a random future date
would wrongly resolve); the EUR Wednesday structural check (disabled
-- the new non-Wednesday test failed correctly); the carry-in
derivation (`select_research_candidates` reverted to excluding
carry-in -- 5 tests failed correctly, including both new `Test
SelectResearchCandidates` cases); `correct_verified_release_timing`'s
optimistic-concurrency guard (expected-value predicate clauses
dropped -- the idempotency, stale-value, AND concurrency tests all
failed correctly, the concurrency test specifically by showing
`outcomes=[None, None]`, both racers wrongly succeeding). The CHECK
constraint's own drop/recreate cycle was not attempted: the sandbox's
permission system correctly blocked a direct `ALTER TABLE ... DROP
CONSTRAINT` against the live dev database as a destructive schema
action, and that block was respected rather than routed around --
this mechanism's protection instead rests on the live `IntegrityError`
demonstration and passing integration test described in point 4 above,
plus the migration's own clean-apply verification.

**Tests**: `test_usd_2026_09_17_worked_example` (this story's own
worked example, verbatim); `test_usd_regular_post_2013_meeting_is_
exact` (2018-06-14, a second historical post-2015 case, corrected in
place); `test_usd_liftoff_2015_has_same_day_gap_not_minus_one`;
`test_usd_exact_date_not_in_explicit_mapping_is_unresolved`; new
`correct_verified_release_timing` tests (fake and integration:
corrects a stale row, rejects missing identity, rejects a non-verified
row, rejects a stale expected value, has no `value` parameter, and a
new `asyncio.gather` concurrency regression); new `Remediate
ReleaseTiming` tests (fake and integration: corrects a stale row,
idempotent rerun, an already-correct row is reported without writing,
a provisional row is not remediated at all, a conservative-bound row
is not remediated, an EXACT row for a now-unresolved date is reported
`NOT_APPLICABLE` and left untouched); `test_provisional_carry_in_
blocks_an_otherwise_empty_interval` (this story's own required
regression -- a 2008-01-22-like unresolved observation with a February
interval containing no changes of its own); `test_verified_carry_in_
permits_an_otherwise_empty_interval` (the safe counterpart);
`test_empty_candidate_set_fails_closed` / `test_no_baseline_interval_
fails_closed_even_with_unrelated_history`; `TestSelectResearch
Candidates` (direct tests of the new derivation helper);
`test_rejects_exact_and_conservative_simultaneously` (domain) and
`test_database_rejects_exact_and_conservative_simultaneously`
(integration, a raw UPDATE against the real CHECK constraint);
`test_eur_non_wednesday_effective_date_is_unresolved_unless_
explicitly_mapped` and `test_eur_non_wednesday_date_resolves_when_
explicitly_overridden` (the override mechanism itself, via
`monkeypatch.setitem`, proven to work, not just proven empty).

**Live run against real Postgres**: all 30 USD EXACT rows corrected on
the first remediation run, `ALREADY_CORRECT` (zero writes) on the
second; the story's own worked example verified directly via SQL --
`2026-09-17` now reads `released_at=2026-09-16T18:00:00Z` (14:00 EDT),
`effective_at=2026-09-17T00:00:00Z`; zero duplicate rows anywhere (an
UPDATE, not an INSERT -- total row count unchanged at 258); a full
re-run of `scripts/verify_policy_rate_release_timing.py` afterward
shows zero `CONFLICTING` change points across all four currencies
(previously 30, all USD, immediately after the resolver fix and before
remediation); final aggregate counts across all 258 rows: 139 exact,
84 conservative-safe, 35 unresolved, zero rows violating the new
mutual-exclusivity invariant.

**Verification**: `pytest` (1058 passed, full suite, up from 1023),
`ruff`, `ruff format`, `mypy --strict`, `pre-commit run --all-files`.

Per this story's own explicit stop instruction: no pair differential,
no carry strategy, no JPY provider, no news/event-surprise work, no
technical filtering follows this story.

## 2026-09-22 — FX-44H.1: USD effective-date correction

A narrow factual correction to FX-44H's own USD registry, found by
the same live primary-source scrutiny this whole epic has applied
throughout: FX-44H correctly separated the FOMC decision date from the
provider-stored change-point date, but it ALSO silently assumed the
stored date always equals the genuine operational EFFECTIVE date --
an assumption never stated, never tested, and wrong for the exact
same two rows FX-44H had already flagged as needing special handling
for a different reason.

**The bug.** FX-44H's `USD_EFFECTIVE_TO_DECISION_DATE: dict[date,
date]` mapped a stored date directly to a decision date, and
`_resolve_usd` set `effective_at=observation_period` (the stored
proxy) unconditionally -- correct for 28 of 30 entries, where the
stored date genuinely does equal the effective date, but wrong for
2015-12-16 ("liftoff") and 2016-12-14 (the second post-crisis hike).
The Federal Reserve's own Implementation Notes -- confirmed to exist
in exactly this document form as early as December 2015, contradicting
FX-44H's own guess that they began "since ~2019"
(https://www.federalreserve.gov/newsevents/pressreleases/
20151216a1.htm, "Implementation Note issued December 16, 2015":
"Effective December 17, 2015, the Federal Open Market Committee
directs the Desk to undertake open market operations..."; https://
www.federalreserve.gov/newsevents/pressreleases/20161214a1.htm,
"Implementation Note issued December 14, 2016": "Effective December
15, 2016, the Federal Open Market Committee directs the Desk to
undertake open market operations...") -- establish the TRUE effective
date is one day AFTER the decision date for BOTH, exactly the same gap
every other mapped USD meeting has. FX-44H had instead modeled a
same-day (0-day) stored/effective gap for these two specifically,
because nothing in its data model distinguished "the provider's stored
date" from "the genuine effective date" as independently-verifiable
facts -- it only ever questioned whether the DECISION date could
differ, never the effective date.

**The fix.** `USD_EFFECTIVE_TO_DECISION_DATE: dict[date, date]` is
replaced by `USD_POLICY_TIMINGS: dict[date, UsdPolicyTiming]` (new
domain type, `domain.policy_rate_release_timing_registry`) --
`stored_date`, `decision_date`, and `effective_date` as three
genuinely independent fields, each populated from an individual
record, never assumed equal to one another by any formula. This is
deliberately NOT a two-column mapping with a third column bolted on:
the type exists specifically so a future discrepancy between the
provider's date and the true effective date (for ANY USD meeting, not
only these two) cannot silently reintroduce this exact class of bug.
All 30 entries were re-expressed as full records -- the 28 unaffected
ones carry forward FX-44H's already-verified decision/effective
relationship unchanged (per this story's own instruction not to
re-litigate what wasn't found to be wrong), sharing one citation
pointing to the same FOMC-calendar cross-referencing evidence FX-44H
used, now confirmed to ALSO be backed by the Implementation Note
mechanism at least as far back as 2015; the 2 corrected ones carry
their own freshly-verified, individually fetched primary citations.
`_resolve_usd` now reads `effective_at` from `timing.effective_date`
(via a new `_date_only_as_utc_midnight` normalization helper),
never from `observation_period` directly.

**Effective-date precision (this story's own explicit concern).**
`_date_only_as_utc_midnight` and `MacroObservationVintage.effective_at`
now both carry an explicit docstring warning: representing a date-only
effective fact as a `UtcTimestamp` at `00:00:00 UTC` is a
REPRESENTATION CONVENTION for fitting the fact into this field's type,
never a claim that 00:00 UTC is itself a source-verified operational
instant. No source this registry cites documents an intraday effective
TIME for any USD or EUR entry; none is claimed.

**Remediation, through the existing FX-44H mechanism, unmodified.**
`RemediateReleaseTiming`/`MacroObservationRepository.correct_verified_
release_timing` needed no code changes at all -- exactly the point of
building them as a genuinely reusable mechanism in FX-44H rather than
a one-off script. Running `scripts/remediate_usd_release_timing.py`
against the corrected registry found precisely the 2 affected rows (28
already matched and were left untouched) and corrected only
`effective_at` for each (`released_at` was already correct for both --
FX-44H's decision-date recovery was right, only the effective-date
assumption was wrong): `2015-12-16` now reads `effective_at=
2015-12-17T00:00:00Z`; `2016-12-14` now reads `effective_at=
2016-12-15T00:00:00Z`. A second run reported both `ALREADY_CORRECT`
with zero writes. `value`, `revision_sequence`, `series_key`, and
`observation_period` were confirmed unchanged for both directly via
SQL and via dedicated tests. Total row count unchanged at 258; zero
duplicate rows; a full re-run of `scripts/verify_policy_rate_release_
timing.py` shows zero `CONFLICTING` change points across all four
currencies both before AND after remediation (`VerifyPolicyRateRelease
Timing` correctly detected the 2 as `CONFLICTING` -- left untouched --
the moment the registry changed, precisely the safety property that
use case exists to provide, and precisely why remediation needed its
own separate, deliberately-invoked mechanism rather than a relaxed
`replace_provisional_release_timing`).

**Future-safety note, recorded but explicitly NOT solved here (this
story's own point 7).** If an observation currently classified EXACT
later becomes UNRESOLVED because further source research invalidates
its timing entirely (not merely corrects a value within the tier, as
this story did), this codebase will eventually need a safe way to
REVOKE research-ready status -- today, `correct_verified_release_
timing` can only correct an EXACT row's timestamps WITHIN the EXACT
tier; nothing can move a row from EXACT back to provisional (or to
CONSERVATIVE_SAFE_BOUND) once classified. No declassification
mechanism is built in this story -- neither of the two corrections
here needed one (both stayed EXACT throughout) -- but a future story
should not assume today's fail-closed guarantees also cover
"un-verifying" a previously-verified row; they do not yet. Tracked in
`docs/NEXT_STEPS.md`.

**Regression-proof discipline applied to both new safety-relevant
mechanisms**, each deliberately broken, confirmed to fail its
dedicated test for the right reason, then restored: `UsdPolicyTiming`'s
`effective_date >= decision_date` ordering check (dropped -- the new
dedicated test failed correctly); `_resolve_usd`'s `effective_at`
sourcing (reverted to reading `observation_period` again -- both new
2015-12-16/2016-12-14 domain tests failed correctly, AND both
remediation-level tests (unit and integration) failed correctly too,
confirming the fix is genuinely load-bearing through the full
resolve-then-remediate pipeline, not just at the point where it was
introduced).

**Tests**: `test_usd_2015_12_16_liftoff_decision_and_effective_dates`
/ `test_usd_2016_12_14_second_hike_decision_and_effective_dates`
(replacing FX-44H's own now-incorrect
`test_usd_liftoff_2015_has_same_day_gap_not_minus_one`);
`test_usd_regular_post_2013_meeting_is_exact` (2018-06-14, unchanged
regression) and `test_usd_2026_09_17_worked_example` (2026-09-17,
unchanged regression) both re-confirmed still correct;
`test_usd_exact_date_not_in_explicit_mapping_is_unresolved` (unmapped
future date, unchanged); `TestUsdPolicyTiming` (the new type's own
validation: valid construction, `effective_date == decision_date`
permitted, `effective_date < decision_date` rejected, empty citation
rejected, immutability); `test_usd_policy_timings_has_no_formulaic_
relationship_assumed` (structural: all 30 entries independently
populated); new remediation tests reproducing the exact historical bug
for both 2015-12-16 and 2016-12-14 (unit, fake-repository-based, and
integration, live-Postgres-based) proving correction, idempotent
rerun, and preserved `value`/`revision_sequence`/`series_key`/
`observation_period`; a dedicated point-in-time visibility test for
the corrected `released_at` boundary using 2015-12-16 specifically.

**Verification**: `pytest` (1068 passed, full suite, up from 1058),
`ruff`, `ruff format`, `mypy --strict`, `pre-commit run --all-files`.
Live-verified against real Postgres as described above, including a
second idempotent remediation run and a full verification re-run
showing zero conflicts.

Per this story's own explicit stop instruction: no pair-rate
differential, no carry strategy, no JPY provider work, no technical
filtering, no news/event-surprise logic, no expected-rate differential,
no decision engine changes follow this story -- and FX-45 does not
start automatically.

## 2026-09-23 — FX-45: pair-relative policy-rate differential

A deterministic, fully-auditable monetary-policy feature built on top
of FX-44H/FX-44H.1's release-timing model: `policy_rate_differential =
base_currency_rate - quote_currency_rate`, `Decimal` only, never
called "carry" anywhere in this codebase -- not a tradeable financing
return, not an interest-rate strategy, not a rate-arbitrage signal.
EUR/USD, GBP/USD, USD/CAD as the first pairs; XAU/USD explicitly out
of scope (not a canonical-policy-rate currency); USD/JPY must fail
closed (JPY has a registry definition, per FX-42H, but zero ingested
rows, per FX-43/FX-43H).

**Two rate-state notions, kept structurally separate.** New `domain.
policy_rate_state` answers "which decision governs a currency's policy
rate at instant T" two ways that must never substitute for one
another: `announced_state_as_of` (market-known, gated on `released_at
<= T`) and `effective_state_as_of` (operationally in force, gated on a
POPULATED `effective_at <= T`). A future-effective-but-already-
announced rate IS the announced rate under ANNOUNCED semantics --
deliberate, per this story's own section 5. `effective_state_as_of`
strictly excludes any vintage whose `effective_at` is `None` from
consideration; it never falls back to `released_at` or
`observation_period` for such a vintage. This is why these are two
distinctly-named functions rather than one function taking a mode
flag: a caller cannot accidentally pass the wrong mode and silently
receive the other semantics. `previous_announced_state`/`previous_
effective_state` answer the matching "what came immediately before
this state" question, each within its own semantics only. Neither
function consults `domain.research_readiness` itself -- this module
answers "what does the stored history say," not "is it safe to
trust"; every caller must run the readiness gate separately.

**`domain.policy_rate_differential`** is pure domain logic: `RateSemantics`
(`ANNOUNCED`/`EFFECTIVE`), `DifferentialDirection`
(`WIDENING`/`NARROWING`/`UNCHANGED`), `CurrencyRateState` (one leg's
full auditable provenance -- currency, rate, series key, observation
period, revision sequence, `released_at`, `effective_at`, both
timing-confidence flags), `PolicyRateDifferentialSnapshot` (pair,
`as_of`, semantics, both legs, differential), `PolicyRateDifferential
Feature` (a snapshot plus three independently-computed changes and
directions), and `DifferentialUnavailable` (pair, `as_of`, semantics,
reason). `rate_differential(base, quote) = base - quote`, requiring
`Decimal` for both arguments; reversing the arguments reverses the
sign by construction, proven directly by `test_pair_orientation_is_
antisymmetric` at the point a snapshot is actually built (base/quote
assignment), not merely at the arithmetic. `classify_direction` is
purely mathematical -- positive is `WIDENING`, negative is `NARROWING`,
exactly zero is `UNCHANGED`, `None` in producing `None` out -- no
fuzzy "neutral" band, no tuned threshold, and an unavailable change is
never coerced into `UNCHANGED`.

**"Change since previous policy observation" for a PAIR: last-mover
reversion.** A single currency's "previous state" is well-defined, but
a PAIR has two legs that do not necessarily change together.
`pair_differential_change_since_previous` determines which leg's
CURRENT state began more recently (comparing `released_at` under
ANNOUNCED, `effective_at` under EFFECTIVE) and reverts ONLY that leg
to its own previous state, keeping the other leg's current rate
unchanged since it did not move at that instant; on an exact tie, both
legs are reverted. Returns `None` (never a guess) if the mover's own
previous state is unavailable. Hand-verified by dedicated domain tests
computing the expected value by hand for both a base-leg-moved and a
quote-leg-moved scenario.

**Orchestration: `application.use_cases.compute_policy_rate_
differential.ComputePolicyRateDifferential`.** A single use case,
`(instrument, as_of, rate_semantics) -> PolicyRateDifferentialFeature |
DifferentialUnavailable`. Fetches each currency's COMPLETE stored
history via `MacroObservationRepository.list_all_for_series` and lets
the readiness gate examine it, rather than hand-selecting which rows
"should" matter -- a single provisional observation anywhere in the
window this feature actually needs (current state, previous policy
observation, and both lookbacks, all at once) fails the WHOLE request;
there is no partial result.

**Raise vs. return, deliberately not conflated.** Two distinct kinds
of "no answer": unsafe or insufficient DATA -- `domain.research_
readiness.ResearchIntervalNotReadyError` is RAISED, the existing
FX-44H mechanism completely unmodified, propagated to the caller
uncaught; a structurally unsupported REQUEST -- `DifferentialUnavailable`
is RETURNED, covering (a) a currency with no canonical policy rate at
all (`canonical_series_for_currency` returns `None` -- XAU) and (b) a
currency whose readiness-proven-safe history still lacks a governing
CURRENT state under the requested semantics (only possible for
EFFECTIVE: every currently-relevant vintage is exact/conservative on
`released_at` but has no `effective_at` at all). JPY needs no special
case at all: `list_all_for_series` returns an empty tuple, and
`require_research_ready_interval` raises with `no_baseline=True`
naturally, exactly like any other currency with zero rows would.

**Axis-safety margin -- the key new structural risk this story found
and closed.** `require_research_ready_interval`/`select_research_
candidates` (FX-44H) window on `observation_period`; this story's
state selection windows on `released_at`/`effective_at` -- different
axes that are usually close (per FX-44H.1's own research, at most a
few days apart for any currency in this registry, EUR's six-day gap
being the largest ever found) but never assumed identical. Without
accounting for this, a state-selection query could return a vintage
whose actual safety was validated by a naively-computed window that
did not truly cover it. `_AXIS_SAFETY_MARGIN` (14 days -- comfortably
more than double the largest known offset) pads every bound of
`_readiness_window`'s computed `[start, end)`, so the vintage a
state-selection query actually returns is always PROVABLY inside the
window that was actually validated for it, not merely "usually"
inside it.

**No scoring, no thresholds, no trading labels.** Every result type
carries full per-leg provenance instead (currency, rate, source series
key, `observation_period`, `revision_sequence`, `released_at`,
`effective_at`, both timing-confidence flags) -- a reviewer can trace
any `differential` back to the exact stored vintage on both legs
without re-querying anything.

**Real, live findings (this story's own point 14 diagnostic,
`scripts/report_policy_rate_differential_coverage.py`, every candidate
`as_of` a REAL stored change point's own `released_at` across both
legs and every confidence tier, each queried once per semantics
through the same `ComputePolicyRateDifferential` the real feature
uses -- no bespoke coverage logic).** Written live to `research_
results/fx45/policy_rate_differential_coverage.json`:
- EUR/USD: 49 usable / 105 blocked ANNOUNCED (earliest research-ready
  2007-03-08); 43 usable / 111 blocked EFFECTIVE (earliest
  2016-03-10).
- GBP/USD: 78 usable / 84 blocked ANNOUNCED (earliest 1998-06-04); 0
  usable / 162 blocked EFFECTIVE, NEVER research-ready. Confirmed
  directly via SQL before any code was written: GBP's exact tier (65
  rows) has never had `effective_at` populated by FX-44's original
  resolver. A genuine, expected data-quality finding, not a bug.
- USD/CAD: 44 usable / 79 blocked ANNOUNCED (earliest 2015-12-16); 0
  usable / 123 blocked EFFECTIVE, NEVER research-ready. Confirmed
  directly via SQL: CAD is 100% conservative-tier (zero exact rows),
  so `effective_at` coverage is 0% by construction. Also genuine and
  expected.

One blocked ANNOUNCED entry was individually spot-checked as due
diligence: USD/CAD at `as_of=2022-09-21T18:00:00Z` is blocked citing
USD's own `2020-03-16` (COVID emergency cut, known-irregular) as the
offending observation, despite the query instant being roughly two and
a half years later. Verified this is CORRECT, not a bug: the Fed held
its target rate at the zero lower bound with no intervening change
from March 2020 until its first post-COVID hike on 2022-03-17; this
query's ~6-month-plus-margin window starts on 2022-03-09, eight days
BEFORE that hike, so the only vintage on record at-or-before the
window's start is genuinely the 2020-03-16 cut -- exactly the carry-in
mechanism FX-44H built working as designed, now exercised for real by
FX-45. A useful illustration of why some blocked windows late in a
long rate-hold period are correctly, not spuriously, blocked.

**Mandatory three-state regression, against the real, FX-44H.1-
verified USD observation (decision 2026-09-16 18:00 UTC, effective
2026-09-17), both unit (fake-repository) and integration (live
Postgres).** Just before release: ANNOUNCED and EFFECTIVE both read
the OLD rate (3.625%). Just after release, before the effective date:
ANNOUNCED already reads the NEW rate (3.875%); EFFECTIVE still reads
the OLD rate (3.625%) -- the two semantics visibly diverge for exactly
the window this story exists to make safe. Once effective: both read
the NEW rate. EUR (stable throughout this window) is used as the
quote leg so the observed movement is provably attributable to USD
alone.

**Regression-proof discipline applied to three new safety-relevant
mechanisms**, each deliberately broken, confirmed to fail its
dedicated tests for the right reason, then restored: (1) `effective_
state_as_of`'s fail-closed exclusion of `effective_at is None` --
removing the filter broke 4 tests across domain/application/
integration layers; (2) the axis-safety-margin readiness-gate
integration -- removing the margin (or the readiness call entirely)
broke 6 tests across unit and integration layers; (3) orientation/
subtraction order in `rate_differential` -- swapping the operands
broke 4 absolute-value/real-data tests (while confirming, separately,
that relative sign-flip-style tests correctly did NOT catch this class
of bug, validating the need for both test styles in this story's own
test list). All three restored cleanly; full suite (1131 passing)
reconfirmed after each restore.

**Architecture**: pure domain functions for rate-state selection
(`domain.policy_rate_state`), pair subtraction/differential-changes/
direction classification (`domain.policy_rate_differential`);
repository orchestration entirely in the application layer
(`application.use_cases.compute_policy_rate_differential`); no
SQLAlchemy in the domain layer; no new FastAPI endpoints (none
genuinely required -- this story's own explicit allowance). No
"carry"/"interest-rate strategy"/"rate-arbitrage signal" language
anywhere in the new modules, checked directly.

**Tests**: `tests/unit/domain/test_policy_rate_state.py` (14 tests,
including `test_announced_and_effective_diverge_around_a_real_
verified_observation` using the real 2026-09-16/17 USD case);
`tests/unit/domain/test_policy_rate_differential.py` (17 tests,
including `test_pair_orientation_is_antisymmetric` and hand-verified
last-mover-reversion arithmetic); `tests/unit/application/test_
compute_policy_rate_differential.py` (19 tests, including the
mandatory three-state regression, JPY raising, XAU/GBP/CAD-EFFECTIVE
returning `DifferentialUnavailable`, and a crisis-crossing rejection);
`tests/integration/test_compute_policy_rate_differential.py` (8 tests
against live Postgres: real EUR/USD and USD/CAD orientation with exact
verified rate values, real GBP/USD and USD/CAD EFFECTIVE-unavailable,
real USD/JPY raise, real 2008-01-22 crisis-crossing rejection, the
real three-state regression, deterministic output for identical
inputs).

**Verification**: `pytest` (1131 passed, full suite, up from 1068),
`ruff`, `ruff format`, `mypy --strict`, `pre-commit run --all-files`,
all clean. Diagnostic script run live against real Postgres, output
committed at `research_results/fx45/policy_rate_differential_coverage.
json`, regenerated once more immediately before commit to confirm
byte-for-byte determinism against the unchanged code.

Per this story's own explicit stop instruction: no automatic
resolution of the blocked crisis dates, no historical rate-
differential experiment, no trading rules, no backtest performance
research, no optimized thresholds, no technical-signal gating, no JPY
ingestion work, no actual broker financing/roll/forward-points/OIS-or-
futures-expectations logic, no event-surprise logic, no news
intelligence, no decision engine changes follow this story -- and
FX-46 (the historical rate-differential experiment) does not start
automatically. The usable/blocked evidence above is reported so the
next story can be decided from it.

## 2026-09-24 — FX-45H: policy-rate differential point-in-time & coverage hardening

Three real point-in-time gaps in FX-45's own state-selection and
readiness logic, found by the same kind of direct scrutiny this whole
epic applies throughout, fixed WITHOUT touching any accepted FX-45
architecture or terminology (this story's own explicit constraint).

**Bug 1: EFFECTIVE state was not point-in-time safe.** `effective_
state_as_of` selected the vintage with the greatest `effective_at <=
T` among those with a populated `effective_at` -- but never checked
`released_at <= T` at all. A REVISION can carry an OLD, PIT-safe-
looking `effective_at` while its own `released_at` is still in the
future relative to `T` (a retroactively-disclosed or corrected
effective date, published later than the date it claims to describe)
-- such a revision must stay invisible before its own `released_at`,
exactly like ANNOUNCED semantics already required, and did not.

**The fix.** New `domain.policy_rate_state.known_as_of(vintages,
as_of)` is the single shared point-in-time filter (`released_at <=
as_of`) every function in the module now applies FIRST, before doing
anything else with a vintage. `announced_state_as_of` was refactored
to use it too (no behavior change -- it already filtered correctly);
`effective_state_as_of` now filters through it before selecting a
candidate. A fact not yet released by `T` cannot affect ANY point-in-
time query evaluated at `T`, no matter how favorably its other dates
happen to line up.

**Bug 2: no fail-closed handling for an intervening decision with
unknown effective timing.** Even after fixing bug 1, a second gap
remained: if an OLD decision has a populated, PIT-safe `effective_at`,
but a NEWER decision has ALREADY been released (`released_at <= T`)
and its own `effective_at` is not yet established, `effective_state_
as_of` still silently returned the OLD decision's rate -- effectively
assuming the newer decision had not yet taken effect, something this
code has no way to verify either way. The true effective state at `T`
is genuinely UNRESOLVED until whichever decision actually governs `T`
gets a defensibly-established `effective_at` of its own.

**The fix.** New private `_has_unresolved_later_decision` checks,
among the PIT-filtered (`known_as_of`) history, whether any vintage
represents a genuinely LATER policy decision than the candidate --
ordered by `observation_period`, the only axis available for a
vintage that has no `effective_at` to order by at all -- whose own
`effective_at` is unpopulated. If one exists, `effective_state_as_of`
returns `None` instead of the old decision's rate. `previous_
effective_state` needed the identical treatment, applied symmetrically:
it now takes an explicit `as_of` parameter (a genuine signature change,
unlike `previous_announced_state`, which needs none -- see below) and
runs the same PIT filter and the same unresolved-later-decision check,
bounded to decisions strictly between the found predecessor and
`current` itself.

**Why `previous_effective_state` needed `as_of` but `previous_
announced_state` did not.** ANNOUNCED orders entirely on one axis
(`released_at`); since `current` (passed in by the caller) was itself
already selected via `released_at <= as_of`, any candidate this
function finds with `released_at < current.released_at` transitively
satisfies `released_at <= as_of` too, automatically -- no separate
filter is needed. EFFECTIVE has TWO axes that do not stand in the same
transitive relationship: a vintage with an early `effective_at` can
still have a late `released_at` (the exact shape of bug 1). "Previous"
must therefore apply the SAME `known_as_of(vintages, as_of)` filter
`effective_state_as_of` applies for `current`, using the SAME `as_of`
-- not one derived from `current.effective_at`, which would answer a
different question entirely (point-in-time safety is about what
`as_of` could know, not about `current`'s own timeline).

**Bug 3: a not-yet-released observation could still block a historical
query.** `_readiness_window`'s baseline padded `end` forward by
`_AXIS_SAFETY_MARGIN` (14 days) from `as_of` UNCONDITIONALLY, before
ever considering what `current`/`previous` actually needed. This swept
any vintage whose `observation_period` fell in that 14-day padding
zone into `require_research_ready_interval`'s candidate set --
including vintages not yet released as of `as_of` -- and blocked the
whole query if such a vintage happened to be provisional. Confirmed on
a REAL, already-committed row: USD's 1998-10-15 change point has
`released_at_is_verified=false` AND `released_at_is_conservative_
bound=false` (genuinely provisional) with `released_at == observation_
period == 1998-10-15` itself -- i.e. not yet released as of
1998-10-08. Before this fix, a GBP/USD query at 1998-10-08T11:00:00Z
(GBP's own real, verified 1998-10-08 decision) was wrongly blocked by
this not-yet-released USD row, a 7-day reach forward the margin made
possible but which had nothing to do with what the query actually
needed.

**The fix, and why it is safe for FX-44H's carry-in mechanism.**
`ComputePolicyRateDifferential` now narrows each currency's full
stored history to `known_as_of(history, as_of)` BEFORE either state
selection or `require_research_ready_interval` ever runs -- both now
operate on the same PIT-filtered view. `domain.research_readiness`'s
own docstring warns against handing `require_research_ready_interval`
an "already-interval-filtered" list (it would silently drop the
carry-in state) -- `known_as_of` filters on a DIFFERENT axis
(`released_at`, not `observation_period`), so this was verified
directly against the real dataset BEFORE writing any code: the
largest `released_at`-vs-`observation_period` gap, in EITHER
direction, across all four currencies, is under six days (EUR's known
announcement/effective skew) -- for GBP, USD, and CAD, `released_at`
never exceeds `observation_period` by more than about 1 day 5 hours
(CAD/USD's conservative-bound safety margin), and GBP's own exact tier
shows only a same-day, intraday-time artifact (`observation_period` is
midnight, `released_at` carries the real announcement time). Both gaps
are trivially smaller than the 6-month lookback and the margin itself,
so a genuine carry-in candidate (by construction always well before
`as_of`, given the lookback) is never excluded by this filter in
practice -- only a vintage that truly was not yet known. `_readiness_
window`'s baseline `end` no longer pads forward from `as_of`
unconditionally either: `end = as_of.value`, extended past that only
as far as `current`'s own `observation_period` (+ margin) actually
requires. With `known_as_of` already guaranteeing no not-yet-released
vintage can ever appear in what gets checked, this tightened baseline
is a precision improvement, not a second correctness mechanism the fix
depends on.

**Bug 4 (the story's own point 4): the margin was documented as more
than it is.** `_AXIS_SAFETY_MARGIN`'s own comment and `compute_policy_
rate_differential`'s module docstring previously described 14 days as
making a state-selection result "always provably covered" because the
largest offset ever found is six days -- reasoning that does not
generalize to a future currency or regime. Both are rewritten: the
PRIMARY correctness mechanism is now `known_as_of`'s exact `released_
at <= as_of` filter, which holds regardless of how large a future
axis offset becomes; the margin is explicitly documented as defensive
padding layered on top, for the narrower, still-real need of covering
`current`/`previous`'s own `observation_period` skew -- and flagged
for re-examination whenever a new currency or timing regime is added.

**Terminology (the story's own point 7).** Every occurrence of "GBP
and CAD's EFFECTIVE semantics is ... permanently unavailable" (`docs/
CURRENT_STATE.md`, `docs/NEXT_STEPS.md`) is replaced with "currently
unavailable with present effective-date coverage" -- the underlying
fact (0% `effective_at` coverage for both, confirmed via SQL) has not
changed and is not being softened; the correction is that "permanently"
overclaimed a guarantee about the future that this codebase cannot
make, when what was actually established is a fact about the PRESENT
data. Related "never ready" wording describing the coverage
diagnostic's scan results was softened to "not ready in this scan" for
the same reason.

**`DifferentialUnavailable.reason` wording for EFFECTIVE**, updated to
cover both of the two distinct causes that now collapse to the same
`None` at the domain layer: "no {semantics} policy-rate state is
defensibly established for {missing} as of {as_of} (either effective_
at has not been populated for the governing vintage, or a newer
decision has already been released whose own effective_at is not yet
established)".

**Live diagnostic re-run (point 5: semantics-aware candidate axes).**
`scripts/report_policy_rate_differential_coverage.py`'s candidate
instants were previously drawn from `released_at` for BOTH semantics
-- wrong for EFFECTIVE, which does not change on `released_at`
transitions at all. Candidates are now drawn from the axis the
requested semantics actually governs itself on: ANNOUNCED samples
every real vintage's own `released_at` (unchanged); EFFECTIVE samples
every real vintage's own POPULATED `effective_at` instead. Each
semantics now reports its own `candidate_axis` and `candidate_
instants_scanned` in the written JSON (previously one shared count per
pair). Regenerated at the same path (`research_results/fx45/policy_
rate_differential_coverage.json`), same real Postgres:

| Pair | Semantics | Before (FX-45) | After (FX-45H) |
|---|---|---|---|
| EUR/USD | ANNOUNCED | 49 usable/105 blocked, ready 2007-03-08 | unchanged |
| EUR/USD | EFFECTIVE | 43 usable/111 blocked, ready 2016-03-10 | 44 usable/30 blocked, ready 2015-12-17 |
| GBP/USD | ANNOUNCED | 78 usable/84 blocked, ready 1998-06-04 | 80 usable/82 blocked, ready 1998-06-04 |
| GBP/USD | EFFECTIVE | 0 usable/162 blocked, not ready | 0 usable/30 blocked, not ready |
| USD/CAD | ANNOUNCED | 44 usable/79 blocked, ready 2015-12-16 | unchanged |
| USD/CAD | EFFECTIVE | 0 usable/123 blocked, not ready | 0 usable/30 blocked, not ready |

Every change is individually explainable: EUR/USD and USD/CAD
ANNOUNCED are byte-for-byte unchanged (neither pair's ANNOUNCED
candidates were ever affected by bugs 1-3 in practice -- confirming
the fixes are surgical, not a wholesale behavior change). GBP/USD
ANNOUNCED gained exactly 2 previously-wrong blocks lifted -- diffed
directly: `1998-10-08T11:00:00Z` (this story's own worked example) and
`1999-08-25T03:59:59Z` (the same bug class, a GBP row blocked by
GBP's own not-yet-released future row), both confirmed via a before/
after diff of the written JSON's `blocked` lists. All three EFFECTIVE
scans now sample far fewer, far more relevant candidates (154→74,
162→30, 123→30) since `released_at` transitions are no longer wastefully
sampled for a semantics they do not govern; EUR/USD EFFECTIVE's
earliest-ready date moved from 2016-03-10 to 2015-12-17, which is
FX-44H.1's own real, individually-verified "liftoff" effective date --
not a coincidence, but the first point at which both legs have clean,
PIT-safe, populated `effective_at` coverage once measured on the
correct axis. GBP/USD and USD/CAD EFFECTIVE remain at 0 usable, now
established over a much smaller and more honest candidate set (30
instead of 162/123) -- still a genuine, present data-coverage fact
(point 7), not a bug.

**Regression-proof discipline applied to all three new mechanisms**,
each deliberately broken, confirmed to fail its dedicated tests for
the right reason, then restored:
- Bug 1's PIT filter (`known = known_as_of(...)` reverted to `known =
  vintages`): `test_effective_state_as_of_excludes_a_revision_not_yet_
  released` failed correctly.
- Bug 2's blocking check, broken and verified as TWO SEPARATE,
  independently load-bearing mechanisms (matching the two distinct
  call sites): `effective_state_as_of`'s own check broke `test_
  effective_state_as_of_unavailable_when_newer_decision_has_no_
  effective_at` at the domain layer AND `test_effective_unavailable_
  when_newer_decision_has_no_effective_at` at the application layer;
  `previous_effective_state`'s own check (a differently-shaped call
  site, verified in a separate pass) broke `test_previous_effective_
  state_unavailable_with_unresolved_intervening_decision`.
- Bug 3's fix, broken by reverting BOTH the PIT pre-filter (`base_
  known = base_history`) and the readiness window's tightened baseline
  (`end = as_of.value + _AXIS_SAFETY_MARGIN` restored) at once: broke
  `test_future_unreleased_provisional_observation_does_not_block` (unit)
  AND `test_future_unreleased_provisional_observation_does_not_block_
  real` (integration, live Postgres) -- the latter reproducing the
  EXACT real `ResearchIntervalNotReadyError` citing `USD_POLICY_
  RATE@1998-10-15` that this story's own worked example describes,
  directly against the real database.

All breaks restored; full suite (1145 passing) reconfirmed after each
restore.

**Tests**: 10 new domain tests (`known_as_of` direct coverage; bug 1
for both `effective_state_as_of` and, symmetrically, `previous_
effective_state`; bug 2 for both functions, including an "unblocked
once resolved" companion; the point-3 preservation case -- a released,
future-observation_period decision stays visible under ANNOUNCED); 3
new application-layer tests (future unreleased provisional does not
block; released future-effective observation remains visible; EFFECTIVE
unavailable with the new two-cause reason wording); 1 new integration
test against real Postgres reproducing the exact 1998-10-08/1998-10-15
scenario with real GBP (7.25%) and USD (5.25%) rates. Every pre-
existing FX-45 test (three-state regression, orientation, crisis-
crossing rejection, carry-in, GBP/CAD-EFFECTIVE-unavailable, JPY-raises,
determinism) re-confirmed passing unchanged -- this story's own point 6
("preserve fail-closed behavior") and the story's own required
confirmation that the mandatory 2026 USD three-state regression and
the real 2008-01-22 crisis-crossing rejection both stay green.

**Verification**: `pytest` (1145 passed, full suite, up from 1131),
`ruff`, `ruff format`, `mypy --strict`, `pre-commit run --all-files`,
all clean. Diagnostic re-run live against real Postgres as tabulated
above.

Per this story's own explicit stop instruction: no FX-return research,
no strategy/backtest, no carry, no JPY ingestion, no news, no event-
surprise work, no technical gating follow this story -- and FX-46 (the
historical rate-differential experiment) does not start automatically.

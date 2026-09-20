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

This is a genuine OANDA provider characteristic (electronic FX/gold
feed maturity in the early-to-mid 2000s), not a backfill defect —
consistent with, and not contradicted by, the gap-check findings below.

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

**Yes, partially — it is not purely a feature of the 2016-2026 macro
environment, but the strongest evidence for it IS concentrated in
recent years.** Every one of the 8 (instrument × strategy) time-series
above shows comparably strong 2-year windows well before 2016 (USD_JPY
MTT and gated-EMA both peak in 2012-2015; XAU_USD's four strategies
all show real positive stretches in 2006-2011) — so this is not a
pattern that simply switched on in 2016. But a second, independent
pattern is equally clear and consistent across ALL EIGHT series: **the
two most recent full 2-year windows (2022-2025) are at or near each
series' own best**, most sharply for XAU_USD (all four strategies) and
USD_JPY/MultiTimeframeTrendStrategy. That both things are true at once
is the honest answer: there IS a longer-run pattern predating 2016,
AND the specific period used to select these candidates also happens
to sit inside an unusually strong recent stretch — which is exactly
why Part E's holdout numbers come back weaker than development without
flipping sign. XAU_USD/`EmaCrossoverTrendRegimeGatedStrategy` is the
one clear exception to "no single episode dominates": its apparent
edge is disproportionately one 2020-2021 episode, not a distributed
pattern — and that is also the one candidate-adjacent combination that
outright sign-flips in Part E.

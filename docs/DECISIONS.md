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

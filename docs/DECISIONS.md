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

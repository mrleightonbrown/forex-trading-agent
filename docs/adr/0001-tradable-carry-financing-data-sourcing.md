# ADR 0001: Tradable Carry / Financing Data Sourcing (FX-48)

## Status

Decided. One candidate (short-term funding-rate differential) is viable
and a minimal ingestion design is proposed below — **not implemented**
in this story, pending a separate explicit go-ahead. The other two
candidates (market-quoted forward/swap points; OANDA's own historical
financing) are **not viable** for this project and are closed avenues
unless the underlying constraint changes (a paid data subscription; this
practice account genuinely accruing years of real financing history).

## Context

`policy_rate_differential` (FX-42–FX-46H) is a central-bank *policy*-rate
differential. It has never been called "carry" in this codebase, and for
good reason: the economic financing actually available to a spot FX
position is determined by either (a) the market-quoted FX forward/swap
points (covered interest parity plus cross-currency basis), or (b) the
specific broker's own financing/rollover rate charged on an open
position — neither of which this project has ever ingested. FX-47/FX-47H
found (at most) a weak, inconsistent interaction between the policy-rate
differential and existing technical strategies' trades, which raised the
natural follow-up question this story investigates: is there a
historically-reliable, point-in-time-safe source for something closer to
genuine tradable carry?

Three candidates were investigated independently, per the story's own
explicit acceptance criteria (source, historical depth, point-in-time
safety, instrument coverage, licensing/cost, calculation method,
long/short asymmetry, triple-roll/day conventions). **No historical
financing was fabricated from today's broker table at any point in this
investigation** — every claim below about depth or freshness was verified
directly (against the real OANDA practice API, or against the named
provider's own documentation), never assumed.

## Candidate A: market-quoted FX forward/swap points

**Not viable — no free, legal, continuously-updated historical source
found.** Genuine FX forward/swap point quotes (the most direct
market-observed measure of implied carry) are a commercial data product
in practice — Bloomberg, Refinitiv, and ICE were the sources actually
used in the academic literature checked (BIS Working Paper 590 and
related BIS/ECB/Boston Fed research on covered-interest-parity
breakdown), not a public feed. The BIS and CME Group publish *analysis*
of the phenomenon (cross-currency basis charts, working papers) but not a
general-purpose, redistributable historical time series usable as an
ingestion feed. Separately confirmed: **OANDA itself does not offer FX
forward outright contracts at all** — it is a spot/CFD broker only — so
there is no forward-outright quoting channel through this project's
existing broker relationship either. Closed unless a paid commercial
subscription becomes available.

## Candidate C: OANDA's own historical financing/rollover rate

**Not viable for historical/backtesting use.** Verified directly against
the real OANDA practice API (not assumed):

- `GET /v3/accounts/{id}/instruments` exposes financing fields, but only
  as a **current snapshot** — e.g. (checked live) EUR/USD:
  `longRate=-0.0247`, `shortRate=+0.0045`; USD/CAD: `longRate=+0.0064`,
  `shortRate=-0.0284`. Long and short are **not symmetric or sign-mirror
  images of each other** — OANDA applies its own markup on top of the
  underlying rate differential, confirming the "does long/short carry
  differ" question in the affirmative, but only as of *today*.
- `financingDaysOfWeek` (also per-instrument, also current-only) confirms
  the triple-roll day genuinely **varies by instrument** — checked live:
  EUR/USD charges triple on **Wednesday**, USD/CAD charges triple on
  **Thursday** (consistent with USD/CAD's own T+1, not T+2, spot
  settlement convention). OANDA's own general help documentation states
  "Wednesday" as if it were universal — the real per-instrument API data
  contradicts that generalization. This is exactly the caution the
  story's own acceptance criteria named ("confirm per-instrument, do not
  assume it's always Wednesday") and it is a real, not hypothetical,
  discrepancy.
- Calculation method (per OANDA's own published formula): `daily
  financing = position_size × annual_rate × (days_held / 365) ×
  fx_conversion_to_account_currency` — a simple annualized-rate-to-daily
  accrual, no compounding.
- `GET /v3/accounts/{id}/transactions` (`DAILY_FINANCING` type) returned
  **zero records** for this project's own practice account — verified
  live. The account was created 2026-09-13, has `openTradeCount=0`, and
  has never held a real position; there is no financing history to read
  because none has ever accrued. OANDA's V20 API has no separate
  historical financing-rate time-series endpoint independent of an
  account's own transaction history (consistent with independent
  reporting: "the OANDA V20 API does not return rollover rates" as a
  general time series). No downloadable historical financing archive was
  found on OANDA's public site either — only current-rate displays and
  links back to the same API.

Using today's live snapshot to backfill history would be **exactly** the
fabrication this story's own directive forbade. This channel could
support a *future, forward-looking* feature (recording each day's actual
rate as a real position is held, prospectively, in paper trading) — a
different feature from "historical financing data for backtesting,"
which is what this story asked about, and out of scope here.

## Candidate B: short-term wholesale funding-rate differential

**Viable.** All four series this project needs map onto the exact same
four providers already integrated for policy-rate ingestion (FX-43) —
confirmed by checking each provider directly, not assumed from the
policy-rate precedent alone:

| Currency | Series | Provider (already integrated) | Real depth | License/cost |
|---|---|---|---|---|
| USD | SOFR | FRED (Federal Reserve Bank of NY) | Daily from 2018-04-03 | Free, no key |
| EUR | €STR | ECB Data Portal (successor to SDW) | Daily from 2019-10-02 (first published, reflecting 2019-10-01 trading) | Free, public |
| GBP | SONIA | Bank of England Interactive Statistical Database (series `IUDSOIA`) | Daily from 1997 | Free, Open Government Licence |
| CAD | CORRA | Bank of Canada Valet API | Daily, but **reformed methodology only from 2020-06-15** (Bank of Canada took over administration from Refinitiv Benchmark Services on that date; legacy pre-2020-06-15 CORRA used a different administrator/methodology) | Free, no key, no registration |

**Point-in-time safety**: each is a daily-published benchmark rate
(same-day or next-business-day publication), a materially *better* PIT
profile than policy decisions (occasional, announcement-driven) — but
this must still be verified per series with the same rigor FX-43H/FX-44
applied to policy rates before being trusted: is the recorded
publication instant itself verified, or a same-day proxy? Not yet
checked in this story (that is implementation work, not sourcing work).

**Instrument coverage**: full — EUR/USD, GBP/USD, USD/CAD map directly
onto (EUR vs. USD), (GBP vs. USD), (USD vs. CAD) funding-rate
differentials. This is in fact **better** coverage than the existing
policy-rate differential, which has no EFFECTIVE-semantics data at all
for GBP/CAD (FX-45H/FX-46) — a daily published rate has no
ANNOUNCED-vs-EFFECTIVE split to begin with.

**CORRA's methodology break is a real caveat, not a formality**: it is
the same class of issue this project already handles for
provisional-vs-verified release timing (FX-43H) — a pre-2020-06-15 CAD
series value and a post-2020-06-15 value are not necessarily computed
the same way, and any research spanning that boundary must treat it
explicitly, not silently splice two administrators' output together.

**Long/short asymmetry**: does **not** apply to this candidate's own
data — a market-quoted funding-rate differential is symmetric by
construction (the higher-yielding side benefits by exactly the same
differential the lower-yielding side pays). Asymmetry only enters once a
broker's own markup is layered on top (Candidate C) — which is exactly
why this candidate, even if built, is **still not literal tradable
carry**: it has no cross-currency basis term and no broker spread/markup,
the same fundamental gap `policy_rate_differential` already has, just
measured against the market's actual short-term wholesale rate instead
of the central bank's target/policy rate. It would need its own honest
name (e.g. `short_term_funding_differential`), distinct from both
`policy_rate_differential` and any use of the word "carry."

**Triple-roll/day conventions**: not applicable — this candidate is a
rate series, not a position-carrying cost; that concept remains specific
to Candidate C (a broker's own accounting), not to a market benchmark
rate.

## Decision

- **Candidates A and C: do not pursue.** No further work in this
  direction unless the underlying constraint changes (A: a paid
  commercial data subscription becomes available; C: this practice
  account genuinely accrues years of real financing history through
  actual trading, at which point it could support a paper-trading
  financing-awareness feature — not a backtesting one).
- **Candidate B: viable, proposed design below, not implemented in this
  story.** Per this story's own explicit constraint, no ingestion code
  is written here — the proposal below is for a future story's separate
  sign-off.

### Proposed design for Candidate B (if authorized as a future story)

Reuse `domain/macro_series_definition.py::MacroSeriesDefinition`,
`domain/macro_observation_vintage.py::MacroObservationVintage`, and
`domain/provider_series_mapping.py::ProviderSeriesMapping` unchanged —
all three are provider-independent by design already and were confirmed
reusable for a non-policy-rate series (their own docstrings explicitly
anticipate "a FRED/ALFRED-style source... without changing shape").
`PolicyRateDefinition` and `policy_rate_release_timing_registry.py` are
**not** reusable — both are built for discrete-decision semantics
(target-point/target-range transforms, meeting-date-keyed release-timing
rules) that don't fit a continuously-published daily rate. A new,
parallel definition concept (e.g. `DailyBenchmarkRateDefinition`) would
be needed, analogous in spirit to `PolicyRateDefinition` but shaped for
"one value per calendar day, no announced/effective split, no revision
semantics beyond ordinary data correction." The four provider adapters
under `infrastructure/policy_rate_providers/` would each need a new
series mapping (SOFR/€STR/SONIA/CORRA) added to their existing FRED/ECB/
BoE/BoC clients — not new adapters.

## Consequences

- `policy_rate_differential` continues to be described honestly as a
  fundamental/macro feature, never "carry" — this decision changes
  nothing about that labeling.
- If Candidate B is ever built, it must also never be labeled "carry" —
  it is a better proxy for funding costs than the policy rate, not a
  measure of actual realized carry (no cross-currency basis, no broker
  markup).
- This ADR, and the accompanying `docs/DECISIONS.md` entry, are the
  complete output of FX-48 per its own explicit instruction that the
  output "may be an implementation or a documented feasibility result" —
  no code was written toward Candidates A or C, and Candidate B's design
  is a proposal only.

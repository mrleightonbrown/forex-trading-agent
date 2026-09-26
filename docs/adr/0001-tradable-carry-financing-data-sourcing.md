# ADR 0001: Tradable Carry / Financing Data Sourcing (FX-48)

## Status

Decided. One candidate (overnight benchmark rate differential) is
viable and a minimal ingestion design is proposed below — **not
implemented** in this story, pending a separate explicit go-ahead. The
other two candidates (market-quoted forward/swap points; OANDA's own
historical financing) are **not viable** for this project and are
closed avenues unless the underlying constraint changes (a paid data
subscription; this practice account genuinely accruing years of real
financing history).

**2026-09-25 correction, before archival closure**: a follow-up review
found this ADR's first draft (a) omitted SONIA's own 2018-04-23
methodology reform (present for CORRA, missing for SONIA), (b)
conflated CORRA's publication-regime date with its first
new-methodology observation date, (c) didn't flag that the four
candidate series mix secured (repo) and unsecured (wholesale) overnight
benchmarks — a real economic heterogeneity, not just a naming
nicety — and (d) used wording stronger than the investigation actually
established in two places (Candidate A's "no source exists"; Candidate
C's OANDA-documentation "contradiction"). All four verified and fixed
below; none of them change the decision itself.

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
  EUR/USD charges triple on **Wednesday** (the usual FX-market
  convention, and the one example OANDA's own general help
  documentation walks through), while USD/CAD charges triple on
  **Thursday** (consistent with USD/CAD's own T+1, not T+2, spot
  settlement convention) — a concrete, instrument-specific exception to
  the usual Wednesday convention, not a claim that OANDA's own
  documentation is wrong (it illustrates one example, not a universal
  rule, and the API's own `financingDaysOfWeek` field exists precisely
  because this varies). This is exactly the caution the story's own
  acceptance criteria named ("confirm per-instrument, do not assume it's
  always Wednesday") and it is a real, not hypothetical, exception.
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

## Candidate B: overnight benchmark rate differential

**Viable.** All four series this project needs map onto the exact same
four providers already integrated for policy-rate ingestion (FX-43) —
confirmed by checking each provider directly, not assumed from the
policy-rate precedent alone. Deliberately named "overnight benchmark
rate differential" here, not "short-term wholesale funding-rate
differential" — see the heterogeneity caveat below for why that
stronger name would overclaim.

| Currency | Series | Provider (already integrated) | Real depth | License/cost |
|---|---|---|---|---|
| USD | SOFR | FRED (Federal Reserve Bank of NY) | Daily from 2018-04-03 | Free, no key |
| EUR | €STR | ECB Data Portal (successor to SDW) | Daily from 2019-10-02 (first published, reflecting 2019-10-01 trading) | Free, public |
| GBP | SONIA | Bank of England Interactive Statistical Database (series `IUDSOIA`) | Daily from 1997, but **reformed methodology only from 2018-04-23** (see below) | Free, Open Government Licence |
| CAD | CORRA | Bank of Canada Valet API | Daily, but **reformed methodology only from 2020-06-15** (see below) | Free, no key, no registration |

**Point-in-time safety**: each is a daily-published benchmark rate
(same-day or next-business-day publication), a materially *better* PIT
profile than policy decisions (occasional, announcement-driven) — but
this must still be verified per series with the same rigor FX-43H/FX-44
applied to policy rates before being trusted: is the recorded
publication instant itself verified, or a same-day proxy? Not yet
checked in this story (that is implementation work, not sourcing work).

**Instrument coverage**: full — EUR/USD, GBP/USD, USD/CAD map directly
onto (EUR vs. USD), (GBP vs. USD), (USD vs. CAD) benchmark-rate
differentials. This is in fact **better** coverage than the existing
policy-rate differential, which has no EFFECTIVE-semantics data at all
for GBP/CAD (FX-45H/FX-46) — a daily published rate has no
ANNOUNCED-vs-EFFECTIVE split to begin with.

**Two real methodology breaks, not formalities — both the same class of
issue this project already handles for provisional-vs-verified release
timing (FX-43H): a value from before a reform and a value from after it
are not necessarily computed the same way, and any research spanning
either boundary must treat it explicitly, never silently splice two
methodologies' output together.**

- **SONIA (GBP), reformed 2018-04-23**: the Bank of England took over
  end-to-end administration, broadened underlying market coverage
  (bilaterally-negotiated overnight unsecured transactions were added,
  not just broker-arranged ones), changed the averaging method to a
  volume-weighted trimmed mean, and moved publication to 09:00 on the
  following business day. Friday 2018-04-20 was the last observation
  under the old (WMBA) methodology; the first reformed-methodology
  observation was for Monday 2018-04-23, published Tuesday 2018-04-24
  (no data was published for Monday itself). A future
  `DailyBenchmarkRateDefinition` needs an effective-dated methodology
  regime for SONIA, not a single homogeneous 1997-present series.
- **CORRA (CAD), reformed 2020-06-15 — with a real observation/
  publication distinction, not one date for both concepts**: the Bank
  of Canada took over administration from Refinitiv Benchmark Services
  and began publishing under the new methodology on 2020-06-15 — but
  CORRA is published one business day after its own observation date,
  and that first new-methodology publication was itself FOR Friday
  2020-06-12, not for 2020-06-15. Given this project's own careful
  `observation_period`/`released_at` split (`MacroObservationVintage`),
  the correct future representation is two separate facts, not one
  boundary date: the new methodology/publication regime is effective
  `released_at >= 2020-06-15`, and the first observation actually
  produced under that regime has `observation_period = 2020-06-12`
  (published `released_at = 2020-06-15`) — legacy pre-reform CORRA
  observations (`observation_period < 2020-06-12`) belong to the old
  Refinitiv-administered regime instead.

**A real economic heterogeneity across the four legs, not just a naming
nicety**: the four benchmarks are not homogeneous. SOFR and CORRA are
both **secured** overnight repo rates (collateralized borrowing —
"Secured Overnight Financing Rate" and "Canadian Overnight *Repo* Rate
Average" respectively, by their own official names); €STR and SONIA are
both **unsecured** overnight wholesale borrowing benchmarks. This means
the three pairs' own contrasts are economically mixed, not a uniform
"funding cost" comparison: EUR/USD and GBP/USD would each contrast an
unsecured leg against a secured one, while USD/CAD would contrast two
secured legs against each other. This does **not** invalidate the
candidate — these remain the canonical overnight/RFR benchmark for each
currency, and are useful market-rate proxies — but it means any future
implementation must document explicitly that the differential is a
**cross-currency benchmark-rate proxy**, not a homogeneous measure of
wholesale funding cost, and that this heterogeneity may matter when
comparing effects across the three pairs later. This is also why
"overnight benchmark rate differential" is used as this candidate's own
name throughout this ADR, rather than "short-term wholesale funding-rate
differential" — the latter would overclaim a homogeneity the four legs
don't actually share.

**Long/short asymmetry**: does **not** apply to this candidate's own
data — a market-quoted benchmark-rate differential is symmetric by
construction (the higher-yielding side benefits by exactly the same
differential the lower-yielding side pays). Asymmetry only enters once a
broker's own markup is layered on top (Candidate C) — which is exactly
why this candidate, even if built, is **still not literal tradable
carry**: it has no cross-currency basis term and no broker spread/markup,
the same fundamental gap `policy_rate_differential` already has, just
measured against the market's actual overnight benchmark rate instead
of the central bank's target/policy rate. It would need its own honest
name (`overnight_benchmark_rate_differential`), distinct from both
`policy_rate_differential` and any use of the word "carry" — and its own
documentation must state the secured-vs-unsecured heterogeneity above
explicitly, not imply a single homogeneous "funding cost."

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
- **Candidate B (overnight benchmark rate differential): viable,
  proposed design below, not implemented in this story.** Per this
  story's own explicit constraint, no ingestion code is written here —
  the proposal below is for a future story's separate sign-off.

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
semantics beyond ordinary data correction" — **and**, per the SONIA/
CORRA methodology breaks documented above, it must support
effective-dated methodology regimes per series (an administrator/
calculation-method change at a specific `released_at` boundary, with
its own first `observation_period` under the new regime, distinct
concepts per the `observation_period`/`released_at` split
`MacroObservationVintage` already enforces) rather than treating an
entire series' history as one homogeneous definition. This is new
design surface `PolicyRateDefinition` never needed (policy decisions
don't have "administrator changes" the way benchmark-rate
methodologies do) — the closest existing precedent is FX-43H's
provisional-vs-verified release-timing distinction, reused as
inspiration, not as code. The four provider adapters under
`infrastructure/policy_rate_providers/` would each need a new series
mapping (SOFR/€STR/SONIA/CORRA) added to their existing FRED/ECB/BoE/
BoC clients — not new adapters.

## Consequences

- `policy_rate_differential` continues to be described honestly as a
  fundamental/macro feature, never "carry" — this decision changes
  nothing about that labeling.
- If Candidate B is ever built, it must also never be labeled "carry" —
  it is a closer market-rate proxy than the policy rate, not a measure
  of actual realized carry (no cross-currency basis, no broker markup)
  — nor should it be called a homogeneous "funding-rate differential"
  without the secured-vs-unsecured caveat above; its own eventual name
  should be `overnight_benchmark_rate_differential`.
- This ADR, and the accompanying `docs/DECISIONS.md` entry, are the
  complete output of FX-48 per its own explicit instruction that the
  output "may be an implementation or a documented feasibility result" —
  no code was written toward Candidates A or C, and Candidate B's design
  is a proposal only.

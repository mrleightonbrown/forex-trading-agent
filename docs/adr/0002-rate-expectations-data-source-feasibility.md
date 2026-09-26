# ADR 0002: Rate-Expectations Data-Source Feasibility (FX-49)

## Status

**DEFER.** A defensible method to construct market-implied policy-rate
expectations exists in principle for every currency this project needs
(EUR, GBP, USD, CAD) — real, liquid, long-established exchange-traded
short-term-interest-rate futures exist for each, and a futures
settlement price is genuinely point-in-time-safe (it was a real,
observable market price on the day it settled). But responsible
implementation is blocked by an external dependency this story has no
authority to resolve: **every single instrument's real historical
depth is gated behind a paid commercial data subscription** (CME
DataMine for USD, ICE Data Services for GBP/EUR, TMX Datalinx for
CAD), each with licensing terms that at minimum restrict
redistribution and, in one case (TMX), leave even internal automated
research use unclear without a separate data agreement. This is
exactly DEFER's own definition: "the concept may be viable, but a
material unresolved dependency prevents responsible implementation
now" — a commercial licensing/cost decision is required, which this
story is explicitly forbidden from making unilaterally (FX-49 scope
exclusions: "adding a commercial data subscription without approval").
A second, independent complication (EUR's cross-currency comparability
tension — see below) would need resolving even if licensing were
approved.

This is not a NO-GO: nothing found makes the underlying concept
unworkable, and no currency is a dead end the way FX-48's Candidates A
and C were. It is not a GO: three real, unresolved dependencies (cost/
licensing approval; the EUR instrument-choice tension; several
technical unknowns listed below) prevent writing a responsible FX-50
implementation contract today.

## Context

This project already has (FX-42–FX-46H) a working *current/observed*
central-bank policy-rate differential, and (FX-48) a documented
feasibility finding that genuine tradable carry (forward points;
broker financing history) is not obtainable, with a *viable but
unbuilt* proposal for an overnight-benchmark-rate differential (also
current/observed, just measured against the market's overnight rate
instead of the policy rate). None of this tells the project what the
market, at some past date, *expected* future policy rates to be. FX-49
investigates whether that is obtainable at all, without look-ahead,
for the four currencies this project's fundamental-analysis research
already covers (EUR, GBP, USD, CAD — confirmed from
`scripts/run_fx46_policy_rate_differential_research.py` and
`scripts/run_fx47_rate_differential_attribution.py`'s own `PAIRS`
tuples: EUR/USD, GBP/USD, USD/CAD).

**Non-negotiable principle applied throughout**: for every candidate,
the question was "could the system, standing at historical timestamp
T, have known this value using information actually available at or
before T?" No candidate below was accepted on the strength of a
current webpage, today's curve, or a value that could have been
back-calculated using knowledge of what actually happened after T.

**Research method**: three parallel research passes (one per currency
group: USD; GBP+EUR; CAD) were run against primary sources — exchange
contract-specification pages, benchmark-administrator announcements,
and central-bank publications — with instructions to flag anything
not independently confirmed as `UNRESOLVED` rather than guess. No
production code was written, no live authenticated or paid API was
called, no schema was touched, and no FX-50 feature was implemented.
Every factual claim below carries its primary source; where a claim
could only be confirmed via a secondary source (a search engine's own
summarization, not a direct primary-source page read), that is stated
explicitly rather than presented as verified.

## Required currency coverage (Section 6)

**Required for FX-50**: EUR, GBP, USD, CAD — exactly the four
currencies behind this project's three existing fundamental-analysis
pairs (EUR/USD, GBP/USD, USD/CAD). This is the full currency set
already used by every FX-42 through FX-48H story; nothing has been
added or removed here. USD/JPY and XAU/USD remain out of scope
(unchanged from FX-46/FX-47/FX-48: JPY has zero ingested policy-rate
data, XAU has no canonical policy rate at all) — **optional/future
coverage only**, not evaluated in this story.

## Target semantic (Section 7)

Before any source was judged "good enough," the target concept was
defined precisely, per currency, and checked against what each
candidate instrument actually measures:

> `expected_policy_rate(currency, as_of_time, horizon)` — the
> market-implied value, as of `as_of_time`, of some short-term
> reference rate averaged or fixed over a period ending approximately
> `horizon` (3/6/12 months) after `as_of_time`.

**This is not literally "the market's statistical expectation of the
central bank's future policy decision."** Every instrument
investigated prices a *risk-neutral, futures-market-implied* value of
an actual overnight benchmark (SOFR, SONIA, €STR, CORRA) or a term
interbank rate (Euribor) — not the policy rate itself, and not a
literal probability-weighted survey of decision-makers. The value
embeds whatever term premium, liquidity premium, and (for Euribor)
bank-credit premium the market prices in, on top of pure rate
expectations (Section 18). None of the four currencies' most liquid,
longest-history instrument is a direct read of "the policy rate the
market expects" — it is always one step removed, and that step is
economically different across the four candidates (see Cross-currency
comparability below). **If this story had reached GO, the eventual
feature name would need to say what the instrument actually measures
(e.g. `implied_overnight_rate_differential` or
`policy_expectations_proxy_differential`), not `expected_rate_
differential` as originally imagined in FX-49's own framing** — this
is flagged per Section 18's own explicit instruction, independent of
the DEFER verdict.

## Candidate sources investigated

Best-established, longest-history candidate per currency, plus every
alternative actually investigated. All facts below are cited to their
own primary source; secondary-source-only claims are marked as such.

### USD

**30-Day Federal Funds futures (`ZQ`, CBOT/CME)** — the closest thing
any currency here has to a genuine central-bank-meeting-oriented
product (Section 5C): settlement is the arithmetic average of the
daily Effective Federal Funds Rate (EFFR) over the entire delivery
month, and CME's own public "FedWatch" methodology is built on exactly
this contract to infer FOMC-meeting-level probabilities. Source: CBOT
Rulebook Chapter 22, §22101 (https://www.cmegroup.com/rulebook/CBOT/III/22.pdf).
Monthly contract months, reported (secondary-source-mediated, not
independently confirmed against CME's own contractSpecs page — CME's
domain could not be fetched directly in this research, every attempt
timed out) to list ~36 months forward — if confirmed, 3/6/12-month
horizons are directly obtainable without interpolation. Launch date
reported as October 1988 (also secondary-source-mediated,
**UNRESOLVED** against CME's own historical-first-trade-dates page).

**SOFR futures, 1-Month (`SR1`) and 3-Month (`SR3`) (CME)** — launched
**7 May 2018, first trades 8 May 2018** (CME's own press releases:
https://www.cmegroup.com/media-room/press-releases/2018/5/08/cme_group_announcesfirsttradesofnewsofrfutures.html).
SR3 settles on business-day-compounded SOFR over an IMM-dated
"Reference Quarter"; SR3 lists **39 quarterly expiries plus 6 serial
monthly contracts (45 months total)** — the richest listing depth of
any candidate found in this research, giving genuine monthly
granularity near-term and quarterly granularity out to ~10 years.

**CME Term SOFR Reference Rates** — a *derived daily benchmark*
(administered by CME Group Benchmark Administration Limited, an
FCA-supervised, IOSCO-aligned benchmark administrator), calculated
FROM SOFR futures prices, **not raw futures data**. **A critical
PIT-safety finding**: CME's own press release
(https://www.cmegroup.com/media-room/press-releases/2021/4/21/cme_group_announceslaunchofcmetermsofrreferencerates.html)
confirms this benchmark's real public launch was **21 April 2021**
(1M/3M/6M tenors only); the 12-month tenor was not ARRC-endorsed until
**19 May 2022**. Some catalog metadata suggests "historical" data back
to September 2020 or "2021" is available via CME DataMine — **since
actual first publication was April 2021, any purported value dated
before that (and any 12-month value dated before May 2022) cannot be
a genuine point-in-time observation and must be a back-calculated
reconstruction — exactly the fabrication Section 4 forbids.** This
finding alone disqualifies the *derived benchmark* as a PIT-safe
source before its own real launch date, though it does not disqualify
the *raw futures prices* it's built from (those are genuinely
contemporaneous market prices from 2018 onward). Term SOFR is also
explicitly **revisable**: CME's own FAQ and methodology PDF document a
republication policy for same-day errors exceeding 1bp (before 2:00pm
CT) and a materiality-based restatement policy (2bp threshold cited)
for retrospective errors — a real revision-vintage risk this project's
own PIT discipline would need to handle explicitly if this benchmark
were ever used, per the same principle FX-43H already established for
policy-rate revisions.

**FRED coverage — confirmed absent.** Direct site-scoped verification
of fred.stlouisfed.org confirms FRED carries only the *realized* SOFR
(from 2018-04-03), SOFR Averages/Index, and EFFR/Fed Funds Target Range
— all sourced from the New York Fed, not CME. **No FRED series exists
for Fed Funds futures, SOFR futures, or CME Term SOFR** — confirming
directly (not assuming) that this project's own already-integrated FRED
adapter cannot be reused for this candidate the way it was for FX-48's
Candidate B.

**Free vs paid**: same-day settlement is free (delayed to midnight CT)
on CME's own site; genuine multi-day historical settlement data
requires **CME DataMine**, a paid product — no free bulk historical
download was found. The free "CHRIS" continuous-contract datasets on
Nasdaq Data Link (formerly Quandl), once a candidate free route,
were **directly confirmed dead** in this research: a live query of
Nasdaq's own v3 API for a CME CHRIS dataset returned a `refreshed_at`
of `2021-06-30` — the dataset stopped updating mid-2021 and is not a
viable current source.

### GBP

**Three-Month SONIA futures (`SO3`, ICE Futures Europe)** — cash-settled
against a compounded average of daily SONIA over the contract's accrual
quarter (Act/365 Fixed). **25 delivery months** listed (quarterly IMM
cycle, ~6+ years forward) — 3/6/12-month horizons directly available.
**Launched 1 June 2018** (confirmed via ICE's own press release:
https://ir.theice.com/press/news-details/2018/Intercontinental-Exchange-Announces-June-1-Launch-of-ICE-Three-Month-SONIA-Futures/default.aspx)
— real usable history is therefore only ~7 years deep, all of it.

**Short Sterling futures (legacy, LIBOR-based, ICE)** — discontinued:
all open interest was converted 2:1 into SONIA-future equivalents at
close of business **17 December 2021**, coincident with GBP LIBOR's
own panel-bank cessation on 31 December 2021 (FIA's own "SONIA First"
FAQ: https://www.fia.org/fia/articles/faqs-switch-sonia-first-gbp-exchange-traded-derivatives-17-june).
Short Sterling priced LIBOR, a *different, non-fungible benchmark*
(LIBOR carried bank credit risk; SONIA is risk-free) — its own decades
of pre-2018 history cannot be spliced onto SONIA futures as a simple
rebasing; using it would mean pricing a materially different economic
quantity for the pre-2018 period.

**Bank of England's own OIS-derived forward curve** — the BoE does
publish a daily "UK instantaneous nominal forward curve (OIS)"
alongside its gilt curves (https://www.bankofengland.co.uk/statistics/yield-curves),
aimed at noon the following business day, bulk-downloadable as a zip
file, **explicitly not available over an API**. Its own documentation
states re-estimation occurs on methodology changes ("This replaces
earlier models: all data have been re-estimated") — meaning **historical
curve values can and do change retroactively**, a PIT-safety concern
distinct from (and, because it is unbounded/methodology-driven rather
than a bounded-materiality correction, arguably worse than) CME Term
SOFR's own documented revision policy. The curve's own true historical
starting date could not be confirmed from the BoE's own published
pages in this research (a secondary source suggested ~2009) —
**UNRESOLVED**.

### EUR

**Three-Month Euribor futures (ICE Futures Europe)** — settles on the
3-month Euribor rate as published by EMMI (the European Money Markets
Institute); **28 delivery months** listed (quarterly plus four serial
months, nearest six consecutive) — the deepest month-listing of any
candidate found, comfortably covering every needed horizon. Contract
existence/pricing reported (secondary-source) from as early as
December 1998; genuine ICE-primary free historical accessibility back
that far is **UNRESOLVED**. **Important semantic caveat**: Euribor is
a *term-quoted, panel-bank-estimated* offered rate, not an overnight
transaction-based benchmark — it embeds interbank credit/liquidity
premium on top of pure rate expectations, a materially different
economic character from every other currency's leading candidate
below.

**€STR futures** — listed on **both** Eurex (ticker `FST3`, launched
23 January 2023) and ICE Futures Europe (launched 1 November 2023).
Settles on compounded daily €STR (an overnight, risk-free benchmark —
economically comparable in *character* to SONIA/SOFR/CORRA, unlike
Euribor). Eurex also separately launched **"ECB Dated €STR Futures"
(`FEMP`)** on 15 December 2025, whose delivery months are tied
directly to individual ECB reserve-maintenance periods rather than
calendar IMM quarters — architecturally the closest thing to a
genuine meeting-dated product outside the US, but with essentially no
history yet (launched within the last year). Real usable €STR-futures
history overall: **under 3 years** (since Jan/Nov 2023) as of this
research — by far the shortest of any candidate across all four
currencies.

**ECB's own derived curves** — the ECB's flagship "euro area yield
curves" are built from **government bonds**, not money-market/OIS
instruments — not a policy-expectations proxy in the sense this story
needs. A genuine OIS-market data category exists on the ECB Data
Portal (transaction-derived MMSR reporting, including forward-rate
buckets) but the specific page returned an HTTP 503 during this
research and its exact series composition/depth is **UNRESOLVED**,
pending a retry.

**The EUR-specific tension driving part of the DEFER verdict**: the
two real EUR candidates trade off exactly the two properties this
story cares about most. Euribor futures have deep, multi-decade
history but price a structurally different, credit/liquidity-premium-
bearing quantity than every other currency's leading candidate. €STR
futures are economically comparable to the other three currencies'
instruments but have under three years of history — far too short to
support a multi-year backtest alongside USD/GBP/CAD's 7+ years. There
is no currently-available EUR instrument that is simultaneously deep
and economically comparable; picking one means either accepting a
comparability gap or accepting a severely truncated common backtest
window.

### CAD

**Three-Month CORRA futures (`CRA`, Montreal Exchange/TMX)** —
compounded daily CORRA over an IMM-dated reference quarter; **12
quarterly months listed** (~3 years forward, 3/6/12-month horizons
directly obtainable). **Launched 12 June 2020** — verified via TMX's
own launch release
(https://investors.tmx.com/English/News--Events/news/news-details/2020/Montral-Exchange-Launches-CORRA-Futures-2020-6-15/default.aspx)
and the Bank of Canada/CARR's own welcome notice
(https://www.bankofcanada.ca/2020/06/carr-welcomes-mxs-listing-new-three-month-corra-futures/)
— **three days before**, and deliberately timed to coincide with, the
2020-06-15 CORRA-administration handover this project already
documented in FX-48. Because it launched already CORRA-based, `CRA`
has a genuinely clean, single-methodology history of just over 5
years — longer than initially assumed and methodologically consistent
throughout its own life, but still the second-shortest of the four
currencies' leading candidates (only €STR futures are shorter).

**One-Month CORRA futures (`COA`, Montreal Exchange)** — launched **23
January 2023** (TMX Advisory Notice A22-018), only ~4 months listed —
useful for isolating individual BoC decisions, not standalone
6m/12m-horizon construction.

**BAX/CDOR legacy** — the pre-CORRA instrument (Bankers' Acceptance
futures on CDOR, since 1988) was **not simply discontinued on a clean
date**: outstanding BAX contracts expiring after June 2024 were
force-converted into CRA contracts on **26 April 2024** (using an
ISDA fallback spread adjustment of 32.138bp), with CDOR itself
permanently ceasing publication after **28 June 2024** per its
administrator's own cessation notice (Refinitiv/LSEG:
https://www.lseg.com/content/dam/ftse-russell/en_us/documents/announcement/cdor-cessation-notice.pdf).
BAX and CRA **coexisted for four years** (June 2020–June 2024) as two
different benchmarks priced side by side — CAD's own history is
therefore fragmented into three non-equivalent regimes (pre-2020
CDOR-only; 2020–2024 coexistence; post-2024 CORRA-only), a more
fragmented picture than any other currency, though `CRA` itself
remains internally consistent throughout its own life.

**Bank of Canada's own derived curve — confirmed absent.** The BoC
does not publish an OIS-implied or forward-CORRA policy-expectations
curve; its CARR working group has itself been wound down having
completed its CDOR-transition mandate. The only comparable tool is the
Montreal Exchange's own **"Canadian Interest Rate Expectations
Tool"** (https://www.m-x.ca/en/trading/tools/canadian-interest-rate-expectations)
— a live analytical display derived from CRA/COA prices, not a
Bank-of-Canada primary source, and with **no historical-data download
capability found**.

## Point-in-time assessment (Section 8)

Every leading candidate (Fed Funds futures, SOFR futures, SONIA
futures, Euribor futures, €STR futures, CORRA futures) is a genuinely
**PIT-safe raw observation**: a futures settlement price on date T was
a real, tradeable market price on T, and — unlike the CME Term SOFR
finding above — carries no reconstruction risk, provided the actual
data obtained is the contemporaneous settlement, not a benchmark
derived from it after the fact.

The **derived-curve candidates are meaningfully less safe**: CME Term
SOFR's specific pre-launch-date reconstruction trap is documented
above; the BoE's OIS curve's own methodology-driven re-estimation
policy means "the value the BoE currently shows for date T" is not
guaranteed to equal "the value the BoE would have shown for date T on
date T" — a fundamentally different, weaker PIT guarantee than a raw
settlement price.

**A subtle finding applies regardless of which raw-futures candidate
is eventually chosen**: the *observation timestamp* (when a contract's
settlement price is actually fixed — e.g. CME STIR settlements are
fixed from Globex trading activity in a ~60-second window around
2:00pm Chicago time) is **different from, and earlier than, the
*availability timestamp* of whatever specific access tier the project
would actually be licensed for** (CME's own free public display of
that same settlement is delayed until midnight Central Time the same
day; ICE and TMX's paid data-feed delivery timing for GBP/EUR/CAD was
not independently confirmed in this research — **UNRESOLVED**). Any
future PIT cutoff rule must use the *availability* timestamp of the
project's actual licensed access channel, never the earlier fixing
time — the same class of "which timestamp is actually knowable"
question FX-43H/FX-44 already resolved for policy-rate release timing,
applied here to a new data class.

Settlement-price **revision policy** could not be confirmed for the
raw futures themselves in any of the three research passes (CME, ICE,
and MX/TMX all lack a located, product-specific statement on whether
STIR futures settlement prices are ever restated) — **UNRESOLVED**,
and would need confirming before implementation, though the general
presumption in derivatives markets is that a published settlement
price is not later revised (unlike vintage-revisable macro data).

## Historical coverage (Section 9)

Verified earliest date a genuinely comparable instrument existed,
per currency (not "since when the underlying benchmark existed" —
since when the specific *futures contract* existed and was
methodologically consistent with itself):

| Currency | Instrument | Verified start | Real usable depth (as of 2026-09) |
|---|---|---|---|
| USD | Fed Funds futures (`ZQ`) | Oct 1988 (secondary-source; unverified against CME primary) | ~38 years, if confirmed |
| USD | SOFR futures (`SR1`/`SR3`) | 7–8 May 2018 (CME primary) | ~8.5 years |
| GBP | SONIA futures (`SO3`) | 1 June 2018 (ICE primary) | ~8.5 years |
| EUR | Euribor futures | ~Dec 1998 (secondary-source; unverified against ICE primary) | ~28 years, if confirmed |
| EUR | €STR futures | 23 Jan 2023 (Eurex) / 1 Nov 2023 (ICE) (both primary) | <3 years |
| CAD | CORRA futures (`CRA`) | 12 June 2020 (TMX/BoC primary) | ~5.3 years |

None of this depth is **free** beyond a short rolling window on the
exchange's own site (CME: today only, delayed to midnight CT; ICE: no
free historical tier found; MX: 6 months rolling, explicitly
disclaimed as "not the official source"). Genuine multi-year depth for
every single currency requires a paid subscription (Section 10).

## Cross-currency comparability (Section 19)

Restricting to each currency's longest-history, most liquid candidate
(`ZQ` for USD, `SO3` for GBP, Euribor futures for EUR, `CRA` for CAD)
produces a genuinely mixed set: USD and GBP price **unsecured
overnight** benchmarks (EFFR, SONIA) as period averages; CAD prices a
**secured overnight repo** benchmark (CORRA) the same way (matching
FX-48's own already-documented SOFR/CORRA-are-secured finding); EUR's
Euribor futures price a **term, panel-bank-quoted, credit/liquidity-
premium-bearing** rate structurally unlike any of the other three.
Switching EUR to €STR futures (unsecured overnight, economically
comparable to the other three) fixes that mismatch but collapses EUR's
own usable history to under three years — which would then cap any
multi-currency comparison to that same short window regardless of how
deep USD/GBP/CAD's own data goes. **There is no currently-available
combination that is simultaneously economically homogeneous and
historically deep across all four currencies.**

## Access / cost / licensing (Section 10)

| Currency | Provider | Free tier | Paid product | Redistribution |
|---|---|---|---|---|
| USD | CME Group | Same-day only (delayed to midnight CT) | CME DataMine (license required; exact current pricing unconfirmed) | Restricted under CME's Market Data License Agreement |
| GBP/EUR | ICE | No free historical tier found | ICE Data Services / EOD subscription (annual) | Restricted under ICE Futures Europe Market Data Policy; redistribution needs a separate license fee |
| CAD | TMX/Montreal Exchange | 6 months rolling, explicitly "not official" | TMX Datalinx ("MX Futures Trading Summary"; exact pricing unconfirmed) | TMX's own base terms-of-use grant only "non-commercial or personal use," explicitly prohibiting redistribution/derivative works without written permission — **even internal automated research use is not clearly covered without a separate Datalinx agreement** |

No currency offers a free, legally clear, automation-suitable
historical channel. This mirrors — and is a materially harder version
of — the exact cost/licensing gate FX-48 already hit for tradable
carry (Candidates A and C there); the difference here is that FX-48
had one free, already-integrated alternative (the overnight-benchmark
differential); FX-49 has **no free alternative for any of the four
currencies**.

## Important methodology / benchmark breaks (Section 11 evidence, consolidated)

- **GBP**: LIBOR → SONIA, hard break, Short Sterling discontinued
  2021-12-17; no continuous SONIA-consistent history before 2018-06-01.
- **EUR**: EONIA → €STR (already documented in FX-48's own ADR 0001);
  Euribor itself never discontinued, so EUR is the only currency where
  the *legacy* instrument (Euribor futures) is still live today rather
  than converted/discontinued — but it prices a different rate than
  the reformed benchmark, unlike the other currencies' clean
  legacy→reformed handoffs.
- **CAD**: CORRA reform 2020-06-15 (FX-48's own finding) plus the
  *separate*, four-years-later CDOR cessation 2024-06-28 with BAX's
  forced conversion into CRA on 2024-04-26 — two distinct
  regime-change events, not one, uniquely among the four currencies.
- **USD**: no benchmark-administration break in the underlying rates
  used here (EFFR/SOFR have not been re-administered the way
  SONIA/CORRA/€STR/EONIA were) — but CME Term SOFR's own launch
  (2021-04-21, 12-month tenor 2022-05-19) creates the derived-benchmark
  reconstruction trap documented above, a different kind of break.

## Exact proposed semantics, if this were ever built (Section 7/18, informational only — no GO)

Were licensing ever resolved, the defensible semantic per instrument
would be: *the market-implied, compounded (or averaged) [SOFR/SONIA/
€STR/CORRA] rate over the delivery period ending closest to the
requested horizon, as priced by the nearest listed futures contract at
the observation instant* — **not** "the policy rate the market
expects," and the eventual feature name should say so (e.g.
`implied_overnight_rate_at_horizon`, not `expected_policy_rate`). For
EUR specifically, whichever instrument is chosen (Euribor futures or
€STR futures) must be named and documented distinctly, since — per the
comparability section above — they are not economically
interchangeable stand-ins for each other.

## Decision

**DEFER.** Reopening conditions, per Section 16:

1. **A commercial data-licensing/cost decision** — CME DataMine, ICE
   Data Services, and TMX Datalinx subscription terms and pricing
   would need to be obtained and explicitly approved (this story
   cannot and does not approve any spend). This is the primary
   blocking dependency; resolving it alone might still leave the EUR
   tension below unresolved.
2. **The EUR instrument-choice tension** — a deliberate choice between
   Euribor futures (deep history, weaker comparability) and €STR
   futures (comparable, ~3 years of history) needs to be made
   explicitly, informed by how much backtest depth the project is
   willing to sacrifice for cross-currency consistency, or by
   accepting and documenting the comparability gap if Euribor is kept.
3. Several **UNRESOLVED technical items** listed throughout this ADR
   (CME `ZQ`/`SR1` exact listed-month counts and 1988 launch date;
   ICE's own free-vs-paid boundary and settlement-timing/revision
   policy; MX/TMX's settlement-timing/revision policy for `CRA`/`COA`;
   the BoE OIS curve's true historical start date; the ECB's OIS-market
   data-category page, which returned an HTTP 503 during this
   research) should be resolved before writing an implementation
   contract, though none of them alone would flip the verdict away
   from DEFER.

This story should be reopened once (1) is resolved with an actual
licensing decision, at which point (2) and the remaining UNRESOLVED
items become the immediate next work before any FX-50 implementation
contract is written. Absent (1), reopening is not useful — there is
nothing further this project can independently verify or resolve on
its own that would change the licensing-gated outcome.

## Consequences

- `policy_rate_differential` and (if ever built) FX-48's proposed
  `overnight_benchmark_rate_differential` remain this project's only
  currency-differential features — no expected-rate/expectations
  feature exists or is authorized by this story.
- No commercial data subscription has been added, requested, or
  implicitly authorized by this ADR.
- No FX-50 implementation contract is written here (per Section 15,
  only required on GO) — Section 16's reopening conditions above serve
  that purpose for a future story instead.
- This ADR, plus the accompanying `docs/DECISIONS.md` entry, are the
  complete output of FX-49, per its own explicit instruction that a
  carefully evidenced DEFER is a successful outcome, not a failure to
  reach GO.

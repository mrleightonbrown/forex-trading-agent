# ADR 0003: Economic-Calendar Data-Source Feasibility (FX-52)

## Status

**DEFER.** No candidate source investigated -- commercial calendar API,
official government/central-bank source, or consumer aggregator site --
clears this project's own bar for a real, provider-backed economic-
calendar ingestion path today. Nothing found makes the underlying
concept unworkable (this is not NO-GO), but every plausible path has
at least one unresolved material dependency this story has no
authority to resolve unilaterally (this is not GO either): a real,
un-quoted subscription cost; genuinely ambiguous point-in-time
semantics from primary documentation alone; a stable-occurrence-
identity gap; or a structural inability to supply market consensus at
all (true of every official government source, by construction, not a
gap that further research would close).

This mirrors FX-48's and FX-49's own precedent exactly: a feasibility
gate is itself a legitimate FX-EPIC-07 outcome, and "the data doesn't
clear the bar yet" is not a failure of this story -- fabricating
point-in-time-unsafe ingestion to avoid reporting DEFER would be a far
worse outcome, and is exactly what FX-52's own instructions forbid.

## Context

FX-51/FX-51H/FX-51H.1 built the canonical, provider-neutral,
point-in-time-safe domain and persistence model for scheduled economic
events -- `EconomicEventOccurrence` (`occurrence_key` identity),
`EconomicEventScheduleVintage`, `EconomicEventConsensusVintage`,
`EconomicEventActualValueVintage`, `EconomicEventReleaseVintage`, and
the `*_as_of` PIT query contract -- but deliberately never chose or
integrated a real calendar provider, and never populated real data.
FX-52's own purpose is to build the FIRST real, provider-backed
ingestion path onto that model, subject to an explicit source-
feasibility gate: GO only if a source (or small combination of
sources) can supply the required semantics defensibly; DEFER if the
concept is plausible but a material dependency (cost approval,
licensing, unverified historical semantics) is unresolved; NO-GO if no
investigated approach can meet the requirement at all.

This story's own instructions are explicit that DEFER/NO-GO is a valid
outcome and that, on either, implementation must STOP after this
document: "Do not build speculative production adapters around sample
JSON or undocumented assumptions." No code was written as part of this
story; this ADR and its accompanying `docs/DECISIONS.md`/
`CURRENT_STATE.md`/`NEXT_STEPS.md` entries are the entire deliverable.

## Required currency/economy coverage (Section 5)

Verified directly against the repository (`scripts/run_fx46_policy_rate_
differential_research.py::PAIRS`, unchanged since FX-46 and reused by
every FX-EPIC-06 research story): exactly three pairs --
`EUR_USD`/`GBP_USD`/`USD_CAD` -- meaning four economies: **United
States (USD), Euro area (EUR), United Kingdom (GBP), Canada (CAD)**.
JPY and XAU remain out of scope, unchanged from FX-46 onward. This
matches the story's own stated expectation exactly; no scope expansion
was made or considered.

## Proposed canonical event universe (Section 6 -- contingent, not adopted)

`domain.economic_event_category.EconomicEventCategory` already defines
exactly six members -- `INFLATION`, `EMPLOYMENT`, `GROWTH`,
`RETAIL_SALES`, `POLICY_RATE_DECISION`, `CENTRAL_BANK_COMMUNICATION` --
matching this story's own candidate list verbatim; nothing about that
enum needed to change even to consider this scope. A deliberately
small registry consistent with it would cover, per economy: headline
CPI YoY (`INFLATION`), core CPI YoY where separately and comparably
reported (`INFLATION`), the economy's own major employment release
(`EMPLOYMENT` -- e.g. US Non-Farm Payrolls, UK claimant count change,
Euro area unemployment rate, Canada net employment change),
unemployment rate (`EMPLOYMENT`), GDP QoQ (annualized where that is the
economy's own convention) (`GROWTH`), retail sales MoM
(`RETAIL_SALES`), the central bank's own policy-rate decision
(`POLICY_RATE_DECISION`), and its statement/press conference/minutes
where the economy holds one (`CENTRAL_BANK_COMMUNICATION`). This is
NOT adopted as a committed registry -- no `EconomicIndicatorDefinition`
instances were created -- because doing so before a source clears the
gate would be exactly the "choose a provider first and retrofit
requirements around it" anti-pattern Section 3 explicitly forbids in
the other direction (defining a registry no confirmed source can
actually populate). It is recorded here so a future reopening does not
have to re-derive it from scratch.

## Candidate sources investigated

Three parallel research passes (commercial calendar APIs; official
government/central-bank sources; consumer/aggregator sites), each
required to cite primary documentation for every claim and to mark
anything not directly established as UNKNOWN rather than inferred
favorably from a plausible-sounding field name -- exactly Section 8's
own discipline.

### Commercial economic-calendar APIs

**Trading Economics** (`tradingeconomics.com/api/`,
`docs.tradingeconomics.com`) -- the most structurally promising
candidate, and also the one with the clearest unresolved internal
tension. VERIFIED: a dedicated `/economic_calendar/point-in-time/`
endpoint exists, described in its own docs as returning events "exactly
as they appeared on a specific date, preserving the original values
before any subsequent revisions," explicitly for backtesting/auditing
past forecasts; a stable per-occurrence `CalendarId` field; a `Date`
field documented as UTC; a `DateSpan` flag distinguishing known vs.
estimated timing; separate `Actual`/`Previous`/`Revised` fields; a
documented 2 req/sec rate limit and per-request row caps. PARTIALLY
VERIFIED / UNRESOLVED: the SAME provider's schema-reference page
defines `Actual` as "**Latest** released value" (continuously updated
to the most recent revision) and `Revised` as "value reported in the
previous release, before revision" -- this is in real tension with the
Point-in-Time endpoint's own claim of reconstructing pre-revision
snapshots, and the two pages do not reconcile it. Whether the Point-
in-Time endpoint truly returns the historically-first-known forecast/
actual, or merely re-serves today's "latest" values filtered by date,
is genuinely UNKNOWN from primary documentation alone -- exactly the
"historical forecast semantics unverified"/"historical first-release
actual semantics unverified" condition Section 3 names as a DEFER
trigger, not something resolvable by inference. UNKNOWN: real dollar
pricing for the tier that would supply Point-in-Time access (the
pricing page would not render actual figures via fetch; only trial
terms were retrievable -- "Trial users are limited to 100000 data
points and 100 requests," non-refundable, auto-charges after expiry);
no free/no-cost tier exists at all. PARTIALLY VERIFIED (secondary
sourcing only, not the primary terms page, which 404'd): redistribution/
internal-automated-research-use rights appear to differ materially by
tier ("Analytical Subscriptions" exclude redistribution; "Full API
Access Plans" support it "for enterprise clients") -- which tier this
project would actually need, and at what cost, is unresolved.

**Financial Modeling Prep (FMP)** (`site.financialmodelingprep.com/
developer/docs/stable/economics-calendar`) -- VERIFIED: endpoint
`GET /stable/economic-calendar`, `apikey` query-param auth,
`country`/`from`/`to` params, a documented 90-day max range per call; a
genuine $0/month "Basic" tier exists (250 calls/day) on which the
calendar itself is marked "Full Access" (not gated, unlike some other
FMP data classes on that same tier); paid tiers have real published
prices (Starter $19-29/mo, Premium $49-69/mo, Ultimate $99-139/mo,
Enterprise custom-quoted for redistribution rights specifically).
NOTABLE and disqualifying on its own: the endpoint's own embedded
metadata tags its status as `"staging"`. UNKNOWN: the actual response
field schema (whether a "consensus/estimate" field exists at all, its
exact name, units) could not be extracted from primary documentation
in this session -- the interactive schema loads via a separate
client-side call not captured by a static fetch; no statement anywhere
in what WAS retrieved addresses historical forecast-freeze or first-
release-vs-revised semantics; no stable occurrence-or-event-type ID
field was found. A free tier with an undocumented, "staging"-tagged,
PIT-semantics-silent endpoint is not a basis for production ingestion
under Section 8/9's field-by-field evidentiary standard.

**Finnhub** (`finnhub.io/docs/api/economic-calendar`) -- VERIFIED (and
disqualifying): the endpoint's own spec flags itself `"premium":
"Premium Access Required"` and its description states verbatim
"Historical events and surprises are available for **Enterprise**
clients" -- i.e. free/base access explicitly excludes the historical
data this story needs, with Enterprise pricing unpriced/UNKNOWN
(pricing pages returned HTTP redirects, could not be fetched at all).
VERIFIED from the documented sample response schema
(`actual`/`country`/`estimate`/`event`/`impact`/`prev`/`time`/`unit`):
**no event-type ID and no occurrence ID field exists at all** -- a
direct, structural failure of Section 15's hard requirement for stable
provider identity, independent of cost. UNKNOWN: timezone (the sample
`time` value carries no offset or zone marker, and no timezone
statement appears in the docs). Independently corroborating evidence
that revision/first-release semantics are genuinely undocumented, not
merely missed in this research: a public, unresolved Finnhub GitHub
issue (`finnhubio/Finnhub-API#584`, filed the same week as this
research, verified via the public GitHub API, zero replies at time of
checking) asks the vendor directly whether `prev`/`estimate`/`actual`
reflect pre-release/first-release values or get silently restated, and
has received no official answer.

### Official government / central-bank sources

Structural point confirmed across every economy checked, exactly as
expected and not a gap further research would close: **no official
government statistical agency or central bank publishes market
consensus/forecast** -- that is inherently a private-sector survey
product. Any consensus field, if this project ever needs one, must
come from a commercial aggregator (one of the three above, or another
not yet investigated), regardless of how the schedule/actual side is
solved.

**United States** -- the strongest official-source case found. VERIFIED:
BLS publishes a machine-readable release-schedule iCalendar feed
(`bls.gov/schedule/news_release/bls.ics`); BEA publishes a JSON release-
schedule API with no key required
(`apps.bea.gov/API/signup/release_dates.json`) plus ICS/RSS; **ALFRED**
(`alfred.stlouisfed.org`) explicitly documents itself as preserving
"each economic data release (vintage) that was available on a specific
date in history," and the FRED API documents `realtime_start`/
`realtime_end`/`vintage_dates` parameters for exactly this purpose --
this project already has a working, no-API-key FRED adapter
(`infrastructure/policy_rate_providers/fred_client.py`), so ALFRED is a
credible, genuinely PIT-safe path for US first-release-actual values
specifically, standing apart from every commercial candidate above.
PARTIALLY VERIFIED: whether ALFRED/FRED's vintage mechanism actually
covers the specific series this registry would need (CPI, payrolls,
GDP, retail sales) with adequate historical depth was not deep-dived
to series level in this pass -- a real next step if this line is
pursued, not yet confirmed. UNSUITABLE (machine-readability only, not
data existence): the FOMC's own calendar page
(`federalreserve.gov/monetarypolicy/fomccalendars.htm`) is HTML-only,
no RSS/ICS/API found.

**Euro area** -- PARTIALLY VERIFIED: Eurostat's release calendar
(`ec.europa.eu/eurostat/news/release-calendar`) offers an iCal
subscription and states its own timezone (Europe/Luxembourg,
CET/CEST) but no RSS/JSON/CSV export was found; Eurostat's separate
SDMX 2.1 REST data API is real and keyless but is a data-retrieval API,
not a release-calendar API, and no vintage/PIT mechanism analogous to
ALFRED was confirmed for it in this pass -- UNKNOWN whether Eurostat
preserves pre-revision vintages at all. UNSUITABLE (machine-readability):
the ECB Governing Council calendar page lists real future meeting
dates through 2028 but as static HTML with no RSS/ICS/API and no
explicit timezone stated.

**United Kingdom** -- VERIFIED: the ONS API
(`developer.ons.gov.uk`) is open, keyless, and Open-Government-
Licence-v3.0-licensed; the ONS release calendar itself
(`ons.gov.uk/releasecalendar`) has a genuine RSS feed with exact
release times (timezone left implicit/UK-local, not explicitly
labelled). UNKNOWN: whether the ONS API exposes a vintage/first-
release-vs-revised mechanism -- not confirmed in this pass, and the
data appears to be current-value-only as fetched. UNSUITABLE (as
fetched): the specific Bank of England MPC page retrieved was a
document-search portal, not a forward calendar with future dates or a
feed -- a dedicated BoE calendar page may exist elsewhere on the site
but was not located in this pass.

**Canada** -- VERIFIED: the Bank of Canada's own calendar
(`bankofcanada.ca/press/upcoming-events/`) lists concrete future rate-
decision dates WITH exact time and timezone ("09:45 (ET)"), plus an
iCal feed and RSS/email alerts -- the cleanest official schedule source
found in this entire investigation. VERIFIED: Statistics Canada's Web
Data Service (WDS) API is real, documented, rate-limited (50 req/sec
platform-wide, 25/sec per IP), and distinguishes `refPer` (reference
period) from `releaseTime` as separate fields -- but returns current
(revised) values only; no vintage/PIT retrieval mechanism was found.
UNKNOWN (tooling failure, not confirmed absent): StatCan's own release-
schedule pages returned HTTP 500 on fetch in this pass (consistent with
bot-blocking, not necessarily indicative of the page's real content) --
genuinely unresolved, not ruled out.

### Consumer / aggregator sites

All five candidates investigated are ruled out on primary-source
grounds, independent of any PIT-quality question:

- **ForexFactory** -- VERIFIED (via indexed ToS language, since direct
  fetch was blocked by the site's own bot protection): no official API
  exists anywhere on the site; ToS explicitly restricts access to "the
  interface and the instructions that FEI provides." UNSUITABLE.
- **Investing.com** -- VERIFIED directly from its own Terms and
  Conditions page: "It is prohibited to use, store, reproduce, display,
  modify, transmit or distribute the data contained in this website
  without the explicit prior written permission of Fusion Media and/or
  the data provider." No API exists. UNSUITABLE.
- **DailyFX** -- VERIFIED: the standalone site closed permanently on
  2024-09-04 per IG's own announcement; there is no calendar product
  left to evaluate. UNSUITABLE (moot).
- **Econoday** -- VERIFIED: the institutional/API tier exists but
  publishes no price at all -- "Request a Demo" only. A real, un-quoted
  cost is itself the disqualifying obstacle (Section 4 forbids
  committing to an unknown-cost commercial service). UNKNOWN cost,
  cannot proceed without one.
- **Nasdaq Data Link / Quandl** -- VERIFIED: no qualifying economic-
  calendar dataset (schedule + consensus + actual) exists on the
  platform itself. The one related, affiliated product (Wall Street
  Horizon's "Economic Calendar") is explicitly timing-only ("Focuses
  exclusively on when events occur"), has no consensus or actual value
  fields at all, ships through a completely different channel (TMX
  Datalinx SFTP/XML, the SAME licensing-restricted vendor FX-49's own
  ADR 0002 already found NO-GO-adjacent for CAD futures data), and is
  also unpriced. UNSUITABLE.

## Point-in-time assessment (Section 8/9/10/11)

Consolidating the above against FX-51's own PIT requirements:

- **Consensus/forecast**: structurally unavailable from every official
  government source (expected, not a gap). Among commercial sources,
  NONE has verified, unambiguous documentation establishing that a
  historical "forecast" value reflects what was genuinely knowable
  before that release, rather than the current/latest-known value
  re-served under an old date. Trading Economics comes closest to
  addressing this directly but its own two documentation pages
  contradict each other on exactly this point.
- **First-release actual**: VERIFIED as genuinely point-in-time-safe
  for the United States only, via ALFRED's explicit vintage-
  preservation mechanism (series-level depth not yet confirmed).
  UNKNOWN for the Euro area, UK, and Canada from official sources in
  this pass (ONS/Eurostat/StatCan's APIs all appear to expose current-
  value-only data with no vintage mechanism found). UNVERIFIED from
  every commercial source (Trading Economics' own "Actual = latest"
  schema definition is itself evidence AGAINST assuming this without
  vendor clarification; FMP and Finnhub simply do not address it).
- **Retrieval-time-as-availability**: no historical backfill was
  attempted or considered valid absent a verified per-provider vintage
  mechanism -- Section 10's own critical rule ("today's historical API
  response must never automatically be treated as what was known
  historically") was treated as the default assumption throughout this
  research, not something to be overridden by a plausible-sounding
  field name (Section 52's own "acceptable vs. not acceptable" wording
  examples were followed literally).
- **Stable occurrence identity**: Trading Economics documents one
  (`CalendarId`); FMP's existence is UNKNOWN; Finnhub confirmed to have
  NONE at all (a structural disqualifier per Section 15, independent
  of any other factor). No official government source documents a
  release-occurrence identifier at all -- this project would need to
  construct its own (indicator + reference period), which is exactly
  what `occurrence_key` (FX-51H) already supports and does not itself
  block reopening.

## Historical coverage for future FX-53 (Section 12)

No provider's consensus-plus-first-release-actual chain was confirmed
PIT-safe end-to-end for ANY of the four required economies in this
pass -- reporting an exact usable-year-count by economy/indicator, as
Section 12 asks for when data IS good enough, would overstate what
this research actually established. The one partial exception (US
actual values via ALFRED) was identified but not deep-dived to series-
level historical depth. This is reported honestly as an open item
rather than silently narrowed into a smaller "GO for US-only, no
consensus" scope -- Section 12 explicitly instructs treating a
material dependency this way as a reason to STOP for architectural
review, not as license to unilaterally redefine what FX-52/FX-53 cover.

## Access / cost / licensing (Section 4/10/22)

| Candidate | Free tier? | Real price found? | Redistribution/internal-research rights | Verdict |
|---|---|---|---|---|
| Trading Economics | No (trial only, auto-charges) | No (pricing page did not render figures) | Unclear; appears tier-dependent | Cost/rights unresolved |
| Financial Modeling Prep | Yes ($0, 250 calls/day) | Yes (paid tiers priced) | Enterprise-only, custom-quoted | PIT semantics unresolved, not cost |
| Finnhub | Base tier lacks historical data | No (pricing pages inaccessible) | Unknown | Historical access itself gated, unpriced |
| Official government sources (BLS/BEA/ONS/StatCan/BoC/Eurostat) | Yes, free/open | N/A | Open government licences confirmed where checked | No consensus field exists at all |
| ForexFactory / Investing.com | N/A | N/A | Explicitly prohibited | Ruled out |
| DailyFX | N/A | N/A | N/A (discontinued) | Ruled out |
| Econoday | Consumer-only free tier is editorial, not API | No (sales-quote-only) | Unknown | Unpriced, ruled out for now |
| Nasdaq Data Link / Wall Street Horizon | No qualifying product | No (unpriced) | N/A | No qualifying product |

No purchase, trial requiring payment, or new commercial term was made
or accepted anywhere in this research, per Section 4.

## Decision

**DEFER.** Reopening this decision requires, in this order:

1. **Resolve Trading Economics' Point-in-Time-vs-schema ambiguity**
   directly with the vendor (a documentation question, not an
   assumption) -- or identify a different commercial provider whose
   primary documentation unambiguously establishes historical
   consensus-freeze and first-release-actual semantics. This is the
   single most important open question: it is the one candidate whose
   OTHER properties (stable IDs, UTC timestamps, TBD-time flag, an
   actual Point-in-Time-named endpoint) already look aligned with this
   project's own requirements.
2. **Obtain real, quoted pricing** for whatever tier would actually be
   required (Point-in-Time access, adequate historical depth,
   compatible internal-research redistribution rights) and put that
   number to the user for an explicit go-ahead -- this story has no
   authority to commit to a subscription cost, mirroring FX-48's/
   FX-49's own identical constraint.
3. **Confirm internal-automated-research-use / storage rights** at
   whatever tier is actually affordable are compatible with this
   project's own non-redistributive research use -- not merely that a
   tier exists, but that its terms permit what FX-52 would actually do
   with the data.
4. **Deep-dive EUR/GBP/CAD first-release-actual PIT-safety** from
   official sources specifically (Eurostat's SDMX API, ONS's API,
   StatCan's WDS) for any vintage/point-in-time mechanism not
   discovered in this pass -- or explicitly accept relying on a single
   commercial provider for all four economies' actual values once (1)
   is resolved, rather than mixing official-source actuals with
   commercial-source consensus per economy.
5. **Decide, explicitly and not unilaterally, whether a narrower scope
   would even satisfy FX-52's own stated purpose** -- Section 2 requires
   the system to know "what consensus/forecast was known" before an
   event; a scope that dropped consensus (the one fact no official
   source can ever supply) would not be "FX-52, narrowed," it would be
   a materially different story, and choosing that silently is exactly
   what this ADR's own Section 12 discipline forbids.

None of these five steps is authorized by this story's own instructions
to resolve unilaterally; each requires either a human decision (cost
approval, scope redefinition) or further primary-source verification
work explicitly out of THIS story's remaining budget once the gate
result was clear.

## Consequences

- No production ingestion adapter, HTTP client, provider-mapping
  table, canonical indicator registry instance, or database migration
  was written or proposed as code in this story.
- FX-51/FX-51H/FX-51H.1's domain and persistence model is unchanged and
  remains ready to receive real data the moment a source clears this
  gate -- nothing about this DEFER weakens, works around, or
  reinterprets any existing PIT invariant.
- FX-53 (Macro Surprise and Post-Release Drift Research) and FX-54
  (Event-Risk Evidence Snapshot) remain explicitly blocked on this
  reopening; neither was started.
- The canonical event-universe sketch in this ADR's own "Proposed
  canonical event universe" section is informational only, not
  adopted -- a future reopening should treat it as a starting point to
  revise against whichever source is actually selected, not as an
  already-decided registry.

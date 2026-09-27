# ADR 0004: Official Economic-Calendar Timing Sources (FX-52A)

## Status

**Adopted, partial coverage.** Four official, machine-readable sources
were verified against primary documentation and their own live feeds,
and implemented: BLS's public ICS schedule feed (US), ONS's public RSS
schedule feed (UK, one release series only), and Bank of Canada's
public ICS schedule feed plus its public press-release feed (CAD,
both schedule and release-occurrence evidence). The euro area has NO
adopted source in this pass -- no official calendar cleared FX-52A's
own admission bar for EUR (see below); this is a deliberate, honestly-
reported gap, not an oversight. This ADR does NOT reopen or weaken
ADR 0003's own DEFER verdict on FX-52's full commercial consensus/
surprise ingestion, which remains unresolved and untouched.

**FX-52AH correction (2026-09-26):** the "Occurrence identity design"
and "Release/schedule correlation heuristic" sections below describe
FX-52A's ORIGINAL design, which has since been corrected -- see
`docs/DECISIONS.md`'s FX-52AH entry for the full rationale. In summary:
`occurrence_key` is no longer a pure function of `(source,
external_event_id, indicator_key)` (that design made genuine
many-external-IDs-to-one-occurrence resolution structurally
impossible); it is now a provider-neutral minted identity
(`mint_occurrence_key`) plus a persisted `economic_event_source_
mappings` table. Date-based correlation now requires exactly one
candidate, gives an explicit `AMBIGUOUS_CORRELATION` disposition (and
writes nothing) for more than one, and persists a successful
correlation so it is never re-run for the same external identity.
Bank of Canada's RSS `dc:date` is no longer promoted to exact
`released_time` (kept only as `source_published_at` provenance);
`released_time` for BoC release evidence is honestly `None`. The
sections below are left as first-pass historical record; treat the
FX-52AH entry in `docs/DECISIONS.md` as authoritative.

## Context

FX-52 (ADR 0003) DEFERRED because no investigated source could supply
defensible, point-in-time-safe CONSENSUS and first-release-ACTUAL data.
FX-52A is a deliberately separate, narrower story: forward-looking
SCHEDULE timing and positive RELEASE-occurrence evidence only, from
OFFICIAL government/statistical-agency/central-bank sources
exclusively -- no consensus, no numeric actual values, no commercial
provider. Every source below was re-verified directly against its own
live feed in this story's own research pass (ADR 0003's leads were
treated as leads, not conclusions, per this story's own instruction).

## Admission criteria applied

A source was ADOPTED only when directly confirmed to have: official
ownership; a genuine machine-readable format (ICS or RSS, in practice
-- no source in scope offered a documented JSON schedule API); a
stable per-item identifier; usable date/time semantics with a
resolvable timezone; and no requirement to infer cancellation from an
item's mere absence. A source that failed even one of these was
EXCLUDED and the gap documented, never guessed around.

## Sources verified and their disposition

### Adopted

**BLS (Bureau of Labor Statistics) -- schedule, US.**
`https://www.bls.gov/schedule/news_release/bls.ics`. VERIFIED: valid
ICS, `UID` (a GUID) present on every event, `SUMMARY` an exact stable
title ("Consumer Price Index", "Employment Situation"), `DTSTART;
TZID=US-Eastern:...` (a non-IANA TZID resolved via an explicit,
closed alias table -- `ics_parsing._KNOWN_TZID_ALIASES`). No `STATUS`
field on any live event -- cancellation/postponement semantics for
this feed remain UNKNOWN; this adapter never infers either.
**KNOWN LIMITATION, CONFIRMED during this story's own real-source
validation (not merely theoretical)**: a plain server-side `httpx`
request to this feed currently receives an HTTP 403 "Access Denied"
response from BLS's own infrastructure, even with a realistic browser
`User-Agent`/`Accept`/`Accept-Language` header set. This is NOT a
parsing, licensing, or documentation problem -- the feed's real shape
was independently confirmed via a browser-capable fetch during
research, and the adapter's parsing logic is unit-tested against that
exact confirmed shape. It appears to be network/infrastructure-level
bot mitigation. `tests/integration/test_bls_schedule_source_live.py`
is left FAILING, visibly, for this reason -- this adapter must not be
relied on for real ingestion until the underlying reachability issue
is resolved (a different egress path, or confirming with BLS whether
routine automated access requires registration). A SEPARATE, ALSO
UNRESOLVED limitation: whether a BLS calendar item's `UID` stays
identical across separate feed regenerations over time (not merely
within one HTTP response) was not established in this pass.

**ONS (Office for National Statistics) -- schedule, UK.**
`https://www.ons.gov.uk/releasecalendar?rss&release-type=type-
upcoming&limit=20`. VERIFIED live and reachable (no bot-mitigation
issue found). Valid RSS 2.0; `<guid>` equals `<link>`, a genuine,
stable permalink whose URL PATH encodes the release series; `<pubDate>`
carries an EXPLICIT `+0000` UTC offset and is confirmed, by inspecting
real future-dated items, to represent the scheduled RELEASE instant
itself, not merely the feed's own publish time -- resolving ADR 0003's
own "ONS timezone implicit" concern for this specific feed. Only ONE
release series is mapped in this pass -- `/economy/
grossdomesticproductgdp/bulletins/quarterlynationalaccounts/` ->
`GBP_GDP_QOQ` -- because it is the only path DIRECTLY confirmed against
a real live item; CPI/employment/retail-sales paths were not directly
observed in a real feed response during this research and are
deliberately excluded rather than guessed at their conventional ONS
URL shape. `reference_period` is extracted from the title's own
explicit "<Month> to <Month> <Year>" text (e.g. "GDP quarterly
national accounts, UK: April to June 2026") -- source-established, not
derived by arithmetic.

**Bank of Canada -- schedule, CAD.**
`https://www.bankofcanada.ca/?feed=ical&content_type=upcoming-events`.
VERIFIED live and reachable (after fixing a real bug -- see below).
Valid ICS; `UID` a stable-looking, CMS-generated identifier (e.g.
`247309@bank-banque-canada.ca`); `DTSTART` always UTC (`Z` suffix,
no TZID resolution needed at all). Only the exact title "Interest
Rate Announcement and Monetary Policy Report" (or the shorter
"Interest Rate Announcement") is mapped to `CAD_POLICY_RATE_DECISION`;
this feed mixes rate announcements with speeches and holidays, all of
which are correctly UNMAPPED. No `STATUS` field observed.

**Bank of Canada -- release evidence, CAD.**
`https://www.bankofcanada.ca/feed/?content_type=press-releases`.
VERIFIED live: this is genuine RDF/RSS 1.0 (the CBWiki "Central Bank
RSS" schema), NOT RSS 2.0 as initially assumed from the subscribe
page's own generic link text -- confirmed by directly inspecting the
raw feed (`<item rdf:about="...">`, `<dc:date>` with an explicit UTC
offset, a `cb:news`/`cb:occurrenceDate` extension not currently used by
this adapter). `rss_parsing.py` was extended to handle both RSS 2.0 and
this RDF shape rather than writing a second, separate parser, since
both reduce to the same four fields this story needs (identity, title,
a dated instant, a link). Only a title matching "Bank of Canada
(maintains|raises|increases|lowers|cuts|decreases) (the|its) (target
for the overnight rate|policy rate)" is treated as release evidence;
this feed mixes rate announcements with unrelated press releases
(appointments, bank-note launches), all correctly UNMAPPED.

### Excluded / deferred (documented gaps, not oversights)

**BEA (US GDP, Corporate Profits, Trade)**:
`https://apps.bea.gov/API/signup/release_dates.json` -- VERIFIED
reachable, valid JSON, genuinely UTC-explicit timestamps (`+00:00`) --
but carries NO stable per-item identifier at all (only an indicator
name plus an array of future dates) and gives no reference-period
signal for which specific release each date is. Constructing a
reschedule-safe occurrence identity for it would require either
guessing (forbidden) or a fragile positional-index scheme; excluded
from this pass rather than accepting either.

**Eurostat (EUR, all indicators)**: a real iCalendar subscription
mechanism is documented (`ec.europa.eu/eurostat/subscribe/ics.format`),
confirmed to exist and to be refreshed twice daily, but the actual
`.ics` URL is generated by a client-side ("Want to subscribe?") button
and could not be established as a stable, static, directly-fetchable
URL from primary documentation or search in this pass (a previously
plausible URL, `.../cache/RELEASE_CALENDAR/calendar_EN.ics`, 404s).
Per this story's own Section 40 ("resolve from primary docs, or
exclude -- do not infer"), this source is excluded, not guessed at.

**ECB (EUR policy decisions)**: the Governing Council calendar page
(`ecb.europa.eu/press/calendars/mgcgc/html/index.en.html`) remains
HTML-only with no RSS/ICS/JSON feed and no stated timezone for its
listed meeting dates -- confirmed again directly in this pass,
unchanged from ADR 0003's own finding. A general ECB press-release RSS
feed (`ecb.europa.eu/rss/press.html`) does exist and does carry
monetary-policy items, but mixes them with speeches/data releases with
no clean structured filter found in the time available -- excluded
from this pass rather than building a fragile, unverified title filter
against an unfiltered general feed.

**Bank of England (GBP policy decisions)**: no forward, machine-
readable MPC calendar was found (the dedicated calendar page fetched
in this pass is a document-search portal, not a forward calendar with
a feed). A general BoE news RSS feed (`bankofengland.co.uk/rss/news`)
DOES carry a clean, matchable release-evidence title pattern ("Bank
rate maintained/changed at X% - <Month> <Year> Monetary Policy Summary
and Minutes") with an explicit UK-local UTC offset -- this is a
genuine, adoptable RELEASE-evidence source for a follow-up increment,
but was not implemented in this pass purely due to remaining story
budget, not a source-quality problem. Documented here so a future
increment does not have to re-derive it.

**Statistics Canada (CAD, non-policy indicators)**: the release-
schedule page returned HTTP 500 on every fetch attempt in this pass
(consistent with bot-blocking, not confirmed absent content); the
separate Web Data Service API is real and documented but returns
current (revised) DATA, not a forward SCHEDULE, and is out of this
story's scope regardless. CAD's non-policy-rate indicators (CPI,
employment, GDP, retail sales) therefore have NO adopted source in
this pass.

## Occurrence identity design

`occurrence_key` is a PURE, deterministic function of `(source,
external_event_id, indicator_key)` (`domain.economic_calendar_
occurrence_identity.build_occurrence_key`) -- no separate persisted
mapping table, no new migration. This satisfies FX-51H's "provider IDs
must never replace canonical occurrence identity" (the result is this
project's own namespaced string, never the bare external ID) while
avoiding additional persistence this pass did not need; a genuinely
different design (e.g. remapping multiple external IDs onto one
occurrence) can be introduced later without disturbing any
`occurrence_key` already in storage. A release package spanning
multiple canonical indicators (BLS's "Employment Situation" ->
`US_NONFARM_PAYROLLS` + `US_UNEMPLOYMENT_RATE`) gets one
`occurrence_key` PER indicator, sharing one `release_group_key`
(`build_release_group_key`, keyed by source item only, never by
indicator) -- Section 11's own worked example, implemented directly.

## Release/schedule correlation heuristic

Bank of Canada's schedule feed (ICS) and release feed (RDF/RSS) are
two independent feeds with two independent external identifiers for
the SAME real announcement. `IngestOfficialCalendarRelease` resolves
this by searching existing occurrences of the same canonical indicator
for one whose latest known schedule places it on the SAME calendar
date as the release evidence, attaching the release vintage there
instead of minting a duplicate occurrence; if no match is found (true
for FOMC/BoE style sources with no adopted schedule feed at all), a new
occurrence is created lazily. This is a deliberate, documented,
DATE-based heuristic, not a guess at content -- a future story with
better cross-source identity (e.g. if BLS/BoC ever publish a shared
identifier across their own schedule and release feeds) could replace
it without changing the use case's own public contract.

## A real bug found and fixed during this story's own real-source
validation

The Bank of Canada's schedule feed URL (`https://www.bankofcanada.ca/
?feed=ical&content_type=upcoming-events`) returns an HTTP 301 redirect
to a canonicalized URL (`.../content_type/upcoming-events/?feed=ical`).
`httpx.AsyncClient` does not follow redirects by default; the
adapter's own status check (`>= 400`) does not catch a 301, so the
first version silently "succeeded" while parsing an empty redirect
body, yielding zero observations with no error -- exactly the kind of
silent-empty-success-masking-an-outage this story's own Section 34
warns against. Caught by this story's own required real-source
validation step (Section 43), not by unit tests against synthetic
fixtures (which used a 200 response directly and could not have
revealed it). Fixed by passing `follow_redirects=True` to every
adapter's own `httpx.AsyncClient` construction (applied defensively to
all four adapters, not only the one empirically shown to redirect).

## Decision

Adopt the four sources above for FX-52A's own scope (schedule timing +
release-occurrence evidence, no consensus, no numeric actual values).
Document, rather than build around, the five excluded/deferred sources
above. Do not reopen FX-52's own DEFER verdict (ADR 0003) or claim any
consensus/surprise capability here.

## Consequences

- FX-53/FX-54 remain exactly as gated as ADR 0003 already established
  -- FX-52A supplies TIMING evidence only, never consensus/surprise
  inputs, and does not change FX-53's own readiness assessment.
- The euro area has zero FX-52A coverage; USD/GBP/CAD coverage is real
  but partial (no BEA, no BoE/ECB release evidence, no non-policy CAD
  indicators) -- a future increment (BoE news RSS is the most
  immediately actionable next addition) can extend coverage without
  redesigning any of this ADR's own architecture.
- BLS's adapter is implemented and unit-tested but currently BLOCKED
  from live use by a confirmed 403 response; it must not be scheduled
  for production polling until that is resolved.

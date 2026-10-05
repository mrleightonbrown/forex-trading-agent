# ADR 0005: News Intelligence Source Feasibility and Rights (FX-55, hardened FX-55H)

## Status

**Accepted -- 2026-09-29. Hardened -- 2026-09-29 (FX-55H).**

**NEWS SOURCE FEASIBILITY VERDICT: PARTIAL_GO (unchanged by FX-55H).**
A bounded, rights-clear prospective news-evidence source set is viable
today using official/primary, text-bearing sources only (see
"Decision" below); no general financial news provider, commercial
news API/aggregator, or dedicated FX-commentary publisher currently
clears this project's rights/PIT/identity bar. This mirrors FX-52A's
own official-source-only precedent after FX-52's commercial DEFER.
**FX-56 may begin**, scoped to the adopted source set and assumptions
stated in this ADR's own "FX-56 readiness" section.

**FX-55H correction summary** (documentation-only, no code/schema
touched; full detail inline throughout this ADR, in the "FTA
availability invariant" section, and in `docs/DECISIONS.md`'s FX-55H
entry): (1) corrected a wrong PIT exception that let GOV.UK's
`first_published_at` stand in for FTA's own availability anchor --
FTA availability is now stated, without exception, as FTA's own
`first_seen_at` for every source; (2) corrected BoC wording that
presented a Toronto-local `dc:date` reinterpretation as an alternative
to first-seen time rather than as separate source provenance to
preserve alongside the raw value; (3) corrected three source admission
statuses whose unresolved critical rights properties had been
collapsed into an ADOPT verdict -- BEA (ADOPT_PROSPECTIVE -> DEFER),
ECB's bulk speeches CSV (ADOPT_HISTORICAL -> DEFER_HISTORICAL), and
GOV.UK's Search API (implicit ADOPT_HISTORICAL -> DEFER); (4) gave
GDELT one canonical disposition, ADOPT_AUXILIARY_METADATA, and
excluded it from FX-56's initial text-bearing source set everywhere
this document previously implied otherwise; (5) restated FX-56
readiness to reflect all of the above. The core adopted prospective
set -- Fed, ECB press feed, Bank of England, GOV.UK Content API,
Statistics Canada, and Bank of Canada press releases (with mandatory
timestamp handling) -- is unchanged, as are FX-49 (DEFER), FX-52
(DEFER), and FX-53 (BLOCKED).

## Context

FX-EPIC-08 ("News Intelligence") has been explicitly authorized. Its
eventual goal is to let the system answer "what important FX-relevant
news did the system know at this time?" -- selected news and publicly
available market commentary used as SUPPORTING EVIDENCE, never a
trading strategy in itself. FX-55 is the epic's own first story: a
source-feasibility, rights, and semantics gate, deliberately modeled on
ADR 0003 (economic-calendar source feasibility, FX-52, DEFER) and ADR
0004 (official economic-calendar timing sources, FX-52A, GO/partial
adoption) -- the same evidentiary discipline, applied to a materially
different evidence class (textual news/commentary, not scheduled
release timing).

**This is explicitly NOT a repeat of FX-EPIC-07's own calendar work.**
FX-52A/FX-52AH/FX-52AH.1 already ingest official-source SCHEDULE timing
and positive RELEASE-occurrence evidence (e.g. "the Bank of Canada's
policy decision is scheduled for 09:45"). FX-EPIC-08's own news
evidence is a different fact category even when it shares a source
(e.g. "the Bank of Canada publishes its policy statement/commentary
text") -- calendar timing and textual/news evidence remain separate
epics with separate evidence models; FX-55 does not touch, weaken, or
duplicate FX-51 through FX-54's own domain/persistence model or
`EconomicEventRepository` in any way.

**Required currency/pair coverage** (unchanged since FX-46, reused
verbatim): `EUR_USD`/`GBP_USD`/`USD_CAD` -- four economies: **United
States (USD), Euro area (EUR), United Kingdom (GBP), Canada (CAD)**.

**Source universe investigated** (FX-55 Section 6/7): official
government/central-bank press releases, speeches, and statements;
general financial news providers (Reuters, Dow Jones/Factiva,
Bloomberg, AP, FT); news APIs/aggregators (GDELT, NewsAPI, Alpha
Vantage News & Sentiment, Finnhub news, Financial Modeling Prep news,
Marketaux, and others discovered during research); and dedicated
FX/macroeconomic commentary publishers. FX-55 evaluates DATA SOURCES
only -- no topic taxonomy, no canonical identity design, no
deduplication implementation, no classification, no sentiment
adoption, no dashboard work, and no Decision/Risk integration are in
scope (see this ADR's own "Consequences" section for the explicit list
of what was deliberately NOT built).

## Evidentiary discipline (mirrors ADR 0003/0004)

Every claim below is classified as one of:

- **VERIFIED**: directly confirmed against the provider's OWN primary
  documentation (API docs, terms/licensing pages, pricing pages) or a
  bounded, non-destructive live check against a genuinely public
  endpoint.
- **PARTIALLY_VERIFIED**: some but not all of a property's
  sub-questions were confirmed from primary sources; the remaining gap
  is stated explicitly, never silently assumed favorable.
- **UNKNOWN**: not established from primary documentation at all --
  never inferred favorably from a plausible-sounding field name, a
  third-party blog post, or the mere existence of a working endpoint.
  "An API exists and returns JSON" is explicitly NOT equivalent to
  "licensed for our use."
- **UNSUITABLE**: directly disqualified by primary evidence (an
  explicit prohibition, a structural gap, a closed/inaccessible
  service).

No purchase, paid trial, credential signup, or contractual acceptance
was made anywhere in this research. No HTML scraping was performed
past any bot-protection/WAF/robots.txt boundary; where a publisher's
own `robots.txt` named this project's own agent class with `Disallow:
/`, that boundary was honored without argument and no further content
paths on that domain were probed.

## FTA availability invariant (corrected by FX-55H)

FX-55's own initial pass treated GOV.UK's `first_published_at` as an
exception to the availability-anchor rule ("may be used as the anchor
instead") and treated a corrected Toronto-local reinterpretation of
BoC's `dc:date` as an alternative anchor to first-seen time. **Both
were wrong and are corrected here, project-wide, superseding every
conflicting sentence elsewhere in this document.**

**FTA availability is always FTA's own `first_seen_at`/retrieval
timestamp -- the instant FTA's own ingestion process actually observed
the item -- for every prospectively collected news item from every
source, with NO exception.** A source's own publication timestamp,
however well-documented or directly verifiable, however precisely it
appears to describe when the SOURCE published something, is never a
substitute for FTA's own observation time. This holds even for GOV.UK's
`first_published_at`, the single most authoritative SOURCE-side
publication timestamp found in this entire ADR: it tells us when
GOV.UK itself asserts the item was published, never when FTA itself
first saw it. Treating it as an availability anchor would have
reintroduced exactly the failure mode FX-51-54 and FX-52AH exist to
prevent -- backdating FTA's own knowledge to a provider's claimed
timestamp -- just with an unusually well-documented provider.

**FX-56 must model at least five separate, never-conflated concepts
per news item:**

1. **Authoritative FTA availability (`first_seen_at`)** -- FTA's own
   retrieval/ingestion timestamp; the ONLY field any future PIT
   evidence query may treat as "what FTA knew, and when."
2. **Source published timestamp** -- the source's own stated
   publication time (e.g. GOV.UK's `first_published_at`, the Fed's/
   ECB's/BoC's `pubDate`/`dc:date`), persisted verbatim as
   non-authoritative source metadata.
3. **Source updated timestamp**, where available (e.g. GOV.UK's
   `public_updated_at`/`updated_at`) -- also non-authoritative,
   persisted separately from (1) and (2).
4. **Source revision/correction metadata**, where available (e.g.
   GOV.UK's `change_history`, `withdrawn_notice`) -- persisted as its
   own structured record, never collapsed into a single timestamp
   field.
5. **Raw provider timestamp/provenance** -- the literal, unmodified
   value the source transmitted (e.g. BoC's raw, mislabelled `dc:date`
   string), preserved even when a remediated/reinterpreted value is
   also stored, so the original provider fact is never lost to a
   correction.

**Historical backfill is governed by the same invariant, stated
separately because it is easy to violate silently.** A source's own
publication timestamp establishes documented PUBLICATION timing, and
nothing else -- it never establishes that FTA itself possessed the
item at that historical moment. A backfilled row's own FTA-availability
field must honestly reflect the actual backfill/ingestion time, or be
explicitly flagged as backfill-derived and never prospectively
observed; it must never be silently stamped with the source's own
historical publish time as if that were equivalent to real-time
prospective knowledge. This applies to every historical candidate in
this ADR without exception, GOV.UK's Search API and ECB's bulk
speeches CSV included.

**BoC-specific corollary.** FTA availability for the Bank of Canada's
press-releases feed remains first-seen/retrieval time, full stop --
this is not an alternative to a Toronto-local reinterpretation of
`dc:date`, it is the only FTA-availability anchor there is. A verified
Toronto-local reinterpretation of `dc:date`, if and when produced, is
SOURCE publication provenance only (concept 2 above) and must be
stored alongside, never instead of, the raw as-received `dc:date`
string (concept 5 above) -- the raw value must remain queryable even
after remediation, since it is itself evidence of what the source
actually transmitted, malformed offset included.

## Source class A: primary/official government and central-bank sources

Investigated 2026-09-29, live against current endpoints. This is a
re-verification pass, not a reuse of FX-52A's own findings -- FX-52A
investigated SCHEDULE/RELEASE timing feeds; this pass investigated
NEWS-content feeds (statements, speeches, press releases, bulletins)
at the same institutions, which are frequently different endpoints
with different semantics even at a source FX-52A already adopted.

**United States.**

- **Federal Reserve Board / FOMC** -- VERIFIED: `federalreserve.gov`
  publishes seven-plus keyless RSS feeds, most importantly
  `/feeds/press_monetary.xml` (FOMC statements, FOMC minutes, SEP
  releases -- all in one feed) plus `/feeds/speeches.xml`,
  `/feeds/testimony.xml`, and per-governor feeds. VERIFIED stable
  identity (`guid` = canonical URL with the Fed's own
  date+sequence-letter convention). PARTIALLY_VERIFIED timestamps:
  `pubDate` is RFC-822 with explicit `GMT` and matches real release
  times (18:00 GMT = 2:00pm ET), but every observed value sits on the
  exact hour -- sub-hour ordering is not resolvable from the feed, and
  there is no correction/update field. **FX-57A addendum (2026-10-03,
  live-reconfirmed)**: `testimony.xml` additionally carries, for a
  small minority of items, the literal sentinel value `pubDate: Sat,
  30 Dec 1899 ...` -- syntactically valid but semantically impossible,
  almost certainly a CMS default for an empty date field. This
  clarifies rather than changes the finding above: `pubDate` was
  already known to be an unreliable, PARTIALLY_VERIFIED provenance
  field, not an availability anchor; this adds "occasionally a
  provider-side placeholder" to "occasionally only hour-granular,"
  both handled identically downstream (raw value preserved, never
  promoted to FTA's own observation time). Does not change the
  ADOPT_PROSPECTIVE verdict. VERIFIED permitted use: the
  Fed's own disclaimer states information is "in the public domain and
  may be copied and distributed without permission," with attribution
  only requested, not required -- storage, retention, and
  redistribution are all unambiguously clear. Historical depth: feeds
  hold 15-20 items; deeper history is HTML-only yearly archive pages.
  **Verdict: ADOPT_PROSPECTIVE (strong). Historical: DEFER** (HTML-only
  archive, but the public-domain grant is an unusually strong basis for
  an eventual parse).

- **US Treasury** -- VERIFIED **UNSUITABLE**: no machine-readable news
  feed exists at all. Five candidate paths were checked; all failed
  (404s, a 302 to an unrelated OFAC page, and a 403 on the taxonomy
  route indicating active request filtering). A Treasury RSS feed
  existed historically but appears retired since a site rebuild.
  **Verdict: REJECT** -- no feed/API exists; do not scrape.

- **BLS** -- **UNKNOWN, access blocked from this research
  environment**: every path, including `robots.txt` itself, returned
  HTTP 403. Per the no-bypass rule, no further probing (UA variation,
  retries) was attempted. **This surfaces an operational alert
  unrelated to FX-55's own scope but important for the epic to know:**
  `bls.gov/schedule/news_release/bls.ics` is the calendar feed FX-52A
  already adopted for SCHEDULE evidence, and it is 403 from this
  environment today. This may be an IP/UA-scoped block specific to this
  research pass rather than a production regression, but it warrants a
  check from the real ingestion egress IP independent of this story.
  **Verdict: DEFER** -- blocked, not disproven; must be re-tested from
  production before any conclusion is drawn either way.

- **BEA** -- VERIFIED: `apps.bea.gov/rss/rss.xml`, a data-release
  announcement feed (48 items) with a rich non-standard schema
  including the released figure itself and `NextReleaseDate`.
  PARTIALLY_VERIFIED timestamps: real release time with an explicit
  zone, but expressed as the named US-zone abbreviation `EDT`/`EST`
  rather than a numeric offset -- RFC-822 treats named zones other than
  a short standard set as ambiguous, so this needs explicit
  zone-mapping before use. **UNKNOWN permitted use** -- BEA's citation
  guidance page addresses attribution only, never reuse, storage, or
  automated access; US-federal-works public-domain status is generally
  expected but was not asserted by BEA itself, so it is not claimed
  here. **Verdict: DEFER (corrected by FX-55H)** -- reuse/storage
  rights are UNKNOWN from any BEA primary source, and per this
  project's own rule an unresolved critical rights property blocks
  ADOPT status regardless of an otherwise clean technical fit; the
  original ADOPT_PROSPECTIVE classification collapsed "a working feed
  exists" into "licensed for our use," which this ADR's own discipline
  forbids. Reopens once a primary BEA statement establishes reuse/
  storage rights.

**Euro area.**

- **ECB press/speeches/interviews feed** -- VERIFIED: one feed,
  `/rss/press.html`, carries press releases, "key speeches," and
  interviews together, discriminable by a `pr`/`sp`/`in` segment in
  the linked URL's slug. **Correction to any prior assumption of a
  separate ECB speeches feed: none exists** (`/rss/speeches.html` and
  `/rss/pr_date.html` both 404). VERIFIED stable identity (`guid` =
  canonical URL with an embedded content-hash-like token, so an edited
  document would very likely mint a new GUID rather than mutate one --
  inferred from URL shape, not confirmed against an observed
  correction). PARTIALLY_VERIFIED timestamps (explicit `+0200` offset,
  but scheduled-hour granularity). VERIFIED permitted use: the ECB's
  disclaimer grants free use with required attribution -- **with one
  material carve-out**: reproduction of documents "that bear the name
  of their authors, such as ECB Working Papers and ECB Occasional
  Papers" requires prior written authorisation. Only 15 items in the
  feed, so tight polling is required to avoid missing items on a heavy
  release day. **Verdict: ADOPT_PROSPECTIVE (strong, tight-polling
  caveat).** **FX-57B addendum (2026-10-03, live-reconfirmed)**: two
  refinements, neither changing the verdict above. (1) Live sampling
  found pubDate values with genuine sub-hour precision (e.g. `17:45`,
  `04:20`, `18:30`), not purely on-the-hour as this entry's own
  "scheduled-hour granularity" phrasing suggested -- the source
  appears MORE precise than originally characterized, not less; FTA's
  own `observed_at` remains the availability anchor regardless. (2)
  the feed carries a FOURTH URL-slug code beyond the documented `pr`/
  `sp`/`in` trio: `gc`, "Governing Council" decision notices (e.g.
  "Decisions taken by the Governing Council of the ECB (in addition to
  decisions setting interest rates)"). Admitted as `press_release`:
  a Governing Council decision notice bears no individual author's
  name, so it cannot fall inside the Working/Occasional-Paper written-
  authorisation carve-out above, and it is served through this SAME
  single adopted feed URL. Any OTHER, still-unrecognized code
  continues to fail closed as an invalid item, never guessed -- see
  `docs/DECISIONS.md`'s FX-57B entry for the reasoning in full.

- **ECB bulk speeches CSV** (`all_ECB_speeches.csv`) -- the single best
  historical full-text asset found across the entire official-source
  pass: VERIFIED full speech text back to ECB inception, pipe-separated,
  UTC-agnostic. **UNSUITABLE for any intraday PIT use**: the only
  timestamp is a date-only `date` column, no time, no timezone.
  VERIFIED update cadence is monthly (confirmed via a 28-day-stale
  `Last-Modified` header) -- structurally unusable for anything
  prospective. Whether named, author-attributed speeches fall inside
  the ECB's own Working/Occasional-Paper written-authorisation
  carve-out (see above) is genuinely ambiguous and is the single most
  important open ECB question. **Verdict: DEFER_HISTORICAL (corrected
  by FX-55H) / REJECT for prospective.** The original ADOPT_HISTORICAL
  classification treated this ambiguity as a footnote rather than a
  blocker; per this ADR's own rule, an unresolved critical rights
  property -- here, whether the author-attribution carve-out reaches
  named speeches at all -- blocks ADOPT status even for an otherwise
  excellent, high-value asset. Reopens once the ECB's own carve-out
  scope is confirmed one way or the other.

- **Eurostat** -- the well-known legacy feed
  (`rss_estat_news.xml`) is **VERIFIED UNSUITABLE**: it returns HTTP 200
  and parses as valid RSS, but has contained **zero items and an
  unchanged `lastBuildDate` since 2021-09-30** -- a live-looking dead
  shell that would fool any liveness check inspecting only the status
  code. A working feed exists, but only as an internal Liferay portlet
  resource URL discovered as an official link on Eurostat's own
  euro-indicators page, embedding an opaque instance ID
  (`_INSTANCE_OaTpFrwlabNK`) with zero endpoint documentation --
  PARTIALLY_VERIFIED access, structurally fragile. It is, however, the
  **only feed in this entire ADR exposing separate `published` and
  `updated` fields in explicit UTC** -- VERIFIED best-in-class
  timestamp structure, though whether `updated` actually moves on a
  real revision was not observed. VERIFIED permitted use under CC BY
  4.0 (Commission Decision 2011/833/EU), including commercial use.
  **Verdict: DEFER** -- the decision the ADR needs is whether an
  officially-linked but wholly undocumented portlet endpoint is an
  acceptable ingestion dependency.

**United Kingdom.**

- **Bank of England** -- VERIFIED: three keyless RSS feeds
  (`/rss/news` -- which includes MPC minutes --, `/rss/speeches`,
  `/rss/publications`), 50 items each. VERIFIED stable identity: an
  **opaque CMS GUID decoupled from the URL** (`isPermaLink="false"`),
  the best identity design among the RSS-based sources -- a slug
  rename does not break it. PARTIALLY_VERIFIED timestamps with a
  concrete defect: the speeches feed mixes RFC-822 numeric offsets
  (`+0100`) with the bare military-zone form (`Z`) within the same
  document -- a parser must handle both or December-era items
  misparse. PARTIALLY_VERIFIED permitted use, narrower than default
  assumption: BoE's Open Government Licence covers only the Bank's
  statistical Database, **not site content**; site content itself may
  be used for "personal use or internal use within an individual
  organisation for non-commercial purposes" -- which covers FTA's
  current research/paper-trading use, but would need reconsideration
  if FTA became commercial. Redistribution requires permission.
  Historical depth: rolling 50-item window only, no archive feed, and
  `/search` is robots-disallowed. **Verdict: ADOPT_PROSPECTIVE
  (strong) / REJECT for historical.**

- **HM Treasury via GOV.UK** -- **the single best-instrumented source
  found across all four research passes**, and also the source whose
  own PIT framing this ADR most needed correcting (see "FTA
  availability invariant" above). Three routes verified live: an Atom
  feed (exposes only `updated`, no `published` -- insufficient alone),
  the **GOV.UK Content API** (`gov.uk/api/content/<path>`), and the
  GOV.UK Search API. The Content API VERIFIED-provides, on a real
  item: a stable UUID (`content_id`) fully decoupled from the URL
  slug; three genuinely distinct SOURCE-side timestamps
  (`first_published_at`, `public_updated_at`, `updated_at`, all with
  explicit offsets) -- each one authoritative as GOV.UK's own claim
  about GOV.UK's own publication history, **none of them a substitute
  for FTA's own `first_seen_at`**; an explicit **correction log**
  (`details.change_history`, each entry with its own timestamped note);
  explicit **retraction representation** (`withdrawn_notice`); embargo
  visibility (`publishing_scheduled_at`); and full body text. VERIFIED
  permitted use, unusually explicit: "Anyone can use this API for any
  purpose. There is no need for onboarding or signing any agreements,"
  under Open Government Licence v3.0. VERIFIED rate limit: documented
  10 requests/second, no authentication required. One caveat: the
  Content API is self-described as "beta software" with no versioning
  guarantee, so schema drift is a live risk. **Verdict: ADOPT_PROSPECTIVE
  (Content API)** -- FTA availability for every item retrieved through
  it is still FTA's own `first_seen_at`; the Content API's rich
  timestamps/correction log/retraction flag are adopted as source
  provenance to persist in full, not as an availability anchor.

- **GOV.UK Search API (corrected by FX-55H, split out from the Content
  API above)** -- the Search API returned 9,819 HM-Treasury documents,
  sortable and paginated by `public_timestamp` -- a genuine documented
  historical-enumeration mechanism, which almost no other source in
  this ADR offers. The original pass folded this into the Content
  API's own "ADOPT_HISTORICAL" verdict; that was premature. **The
  Search API's own terms and rate limits were never separately
  verified** -- only that it functions -- and per this ADR's own rule,
  an unresolved critical access property blocks ADOPT status
  regardless of how useful the mechanism looks. **Verdict: DEFER.**
  Reopens once the Search API's own governing terms/rate limits are
  confirmed from a primary GOV.UK source (they may simply be identical
  to the Content API's OGL v3.0 grant -- but that has not been
  verified, and must not be assumed).

- **ONS** -- **VERIFIED UNSUITABLE on timestamp semantics, confirmed
  twice independently.** A working feed exists only at
  `/publications?rss` (10 items, undocumented; the sibling
  `/news/news?rss` silently returns HTML instead of failing loudly --
  a trap for any check that inspects only the status code). Every
  observed `pubDate` in the feed is exactly `23:00:00 +0000` --
  midnight-local-to-UTC, i.e. a date-only value disguised as a precise
  timestamp, not a real publication instant. Independently
  corroborated via the ONS search API: the August 2026 CPI bulletin's
  `release_date` is stated as 8 hours before the bulletin's actual
  07:00 BST release. A previously-relied-upon convenience ("append
  `/data` to any ONS page for JSON") is now confirmed decommissioned
  (404, "legacy endpoint... no longer available"). Permitted use is
  **UNKNOWN** -- no general ONS reuse statement was located from a
  primary ONS terms page. **Verdict: REJECT for any time-sensitive
  prospective use; DEFER for historical/contextual use** where
  date-only granularity is acceptable and retrieval-time anchoring is
  applied regardless.

**Canada.**

- **Bank of Canada** -- VERIFIED, and carrying the two most dangerous
  defects found in this entire research effort. Three RSS/RDF feeds
  exist (press-releases, speeches, site-wide), using the RSS-CB
  central-bank extension. **Defect 1, confirmed against three
  independent event anchors plus the feed's own prose:** `dc:date`
  presents America/Toronto **local time falsely labelled `+00:00`** --
  e.g. a rate decision at 9:45 a.m. ET appears as
  `2026-09-02T09:45:53+00:00`, which if taken literally would place
  the announcement at 5:45 a.m. Eastern, before it existed. This
  **independently reconfirms FX-52AH's own prior decision** to stop
  promoting BoC RSS `dc:date` to an exact `released_time` -- that
  decision was correct and remains settled; FX-55 changes nothing
  about it. **Defect 2:** the speeches feed contains **future-dated
  entries** (a speech scheduled two days ahead appeared in the feed
  with `dc:date` in the future) -- a direct look-ahead-bias vector if
  ingested naively, and a defect distinct from the press-releases feed.
  VERIFIED permitted use is broad (free reproduction/distribution with
  attribution, no commercial restriction) and the terms are the only
  ones in this ADR that explicitly address rate limits (prohibiting
  circumvention of unpublished request limits). **Verdict:
  ADOPT_PROSPECTIVE for the press-releases feed only, contingent on
  mandatory timestamp handling (corrected by FX-55H): FTA availability
  is always first-seen/retrieval time, never the feed's own `dc:date`
  in any form -- a verified Toronto-local reinterpretation of `dc:date`
  is not an alternative anchor, it is SOURCE publication provenance to
  be persisted alongside the raw, as-received (malformed) `dc:date`
  string, never in place of it. REJECT the speeches feed as
  published** (would need an explicit `dc:date > now` quarantine filter
  before any adoption).

- **Statistics Canada (The Daily)** -- VERIFIED: 34 documented,
  keyless Atom feeds (33 by subject plus "all subjects"), each
  described by StatCan itself as covering "the latest releases by
  subject (100 days)." VERIFIED stable identity with a clever
  intra-day-ordering recovery: the item `id` embeds a date plus a
  sequence letter (`dq260929a`, `dq260929g`) that recovers same-day
  ordering the timestamp itself cannot express, since **every same-day
  entry shares an identical `08:30:00-04:00` timestamp** (correct in
  substance -- all Daily releases drop simultaneously -- but
  order-blind on its own). VERIFIED permitted use is **the most
  permissive licence found in this entire ADR**: a worldwide,
  royalty-free, sub-licensable right to "use, reproduce, publish,
  freely distribute, or sell" the content, attribution required in a
  specified format. `robots.txt` sets an explicit `Crawl-delay: 2`,
  which must be honoured. Historical depth is a hard 100-day rolling
  window in the feed; a predictable date-addressed HTML archive exists
  beyond that. **Verdict: ADOPT_PROSPECTIVE (strong). Historical:
  DEFER** (licence clearly permits it; mechanism is still HTML).
  **FX-57E addendum (2026-10-05, live-reconfirmed)**: the official
  feed-index page (`https://www.statcan.gc.ca/en/sc/rss`) currently
  lists 33 total `dai-quo` feed rows (32 by subject plus "All
  subjects"), not 34 -- a one-row decrease from this entry's original
  count, confirmed by direct enumeration of every listed `.atom` link.
  The four adopted macro feeds (prices/`18`, labour/`14`, economic
  accounts/`36`, international trade/`12`) remain present and
  unchanged at their original URLs. This is taxonomy/feed-index
  drift, not a rights or PIT change -- the `ADOPT_PROSPECTIVE`
  verdict and licence/`Crawl-delay`/100-day-window findings above are
  all independently reconfirmed live and unchanged. Separately, live
  research for FX-57E found that Statistics Canada legitimately
  cross-lists the SAME Daily release under more than one of its own
  subject feeds simultaneously -- a genuine SOURCE-SHAPE fact, not a
  rights/PIT finding, so it does not belong in this ADR; it is
  recorded, with the application-layer model correction it required,
  in `docs/adr/0006-multi-channel-news-provenance.md` instead. Also
  live-reconfirmed, unchanged: every same-day entry still shares one
  identical `08:30:00-04:00` timestamp; the sequence-letter identity
  scheme is unchanged; the Open Licence terms and required attribution
  notice format are unchanged; zero future-dated items were found
  across all four adopted feeds.

- **Department of Finance Canada** (`api.io.canada.ca`) -- a real,
  functioning, parameterised news API (department/date-range/sort
  filters, Atom output) with **no located primary developer
  documentation at all**, and a visible internal-configuration leak (a
  `localhost:8181` self-link inside the feed) reinforcing that this is
  not a carefully-managed public contract. VERIFIED timestamps are
  genuinely good (distinct, second-precision, correctly offset), but
  the field is named `updated` with no separate `published`, so
  first-publication is not distinguishable from a later edit.
  PARTIALLY_VERIFIED permitted use: the governing canada.ca terms allow
  non-commercial reproduction with attribution but **explicitly
  prohibit commercial redistribution without written permission** --
  materially narrower than StatCan's own licence, so the two Canadian
  sources must be tracked under separate rights records, never
  conflated. **Verdict: DEFER** -- functional and well-timestamped, but
  undocumented and licence-narrower than its StatCan sibling.

**Cross-cutting finding governing all future FX-56 design (official
sources):** only GOV.UK's Content API exposes correction and
retraction semantics at all. For every other official source
investigated, update/correction behaviour is UNKNOWN, and BoC's and
ONS's own stated timestamps are independently confirmed *wrong*, not
merely coarse. **First-seen/retrieval time is the FTA availability
anchor for every official source without exception, GOV.UK included**
(corrected by FX-55H -- see "FTA availability invariant" above; the
original text exempted GOV.UK on the strength of `first_published_at`
being directly verifiable, which conflated source-side verifiability
with FTA's own observation time). Provider-stated publication times
should always be persisted as a separate, clearly-labelled,
non-authoritative field.

## Source class B: general financial news providers (Reuters, Dow Jones/Factiva, Bloomberg, AP, FT)

Investigated 2026-09-29 against each vendor's own public developer
portal, terms, and pricing pages; no signup, trial, payment, or sales
contact was made anywhere. **Class-level headline finding: every one
of the five named providers is a sales-gated enterprise licence. Not
one publishes a price, and not one publishes the licence language that
would fully answer FTA's storage/retention/derived-processing
questions.** Two vendors (Dow Jones and FT) at least publish the
*shape* of the rights that would need negotiating; Bloomberg publishes
none of it.

- **Reuters (routed through LSEG for our customer category)** --
  VERIFIED a real, documented product: LSEG's **Machine Readable News
  (MRN)** (streaming/request-response/bulk-file delivery, JSON,
  explicitly marketed for NLP/sentiment/quant use) plus a documented
  Reuters GraphQL API and a new "Reuters MCP" gateway -- all
  "Contact sales" only. **The single most consequential finding for
  this vendor:** LSEG's own public developer Terms of Use state
  verbatim that "nothing in this Agreement entitles Member... to use,
  copy, store or distribute any Refinitiv Content except as separately
  licensed," and separately forbid using anything from the free
  developer tier "in any live environment" -- so **the only publicly
  readable licence affirmatively forbids the exact things FTA would
  need to do**; a separate, unpriced commercial licence is mandatory.
  Historical archive is claimed back to 1996 as "point-in-time
  streamed news data," but this is marketing copy, not a documented
  methodology, so it is only PARTIALLY_VERIFIED. **Verdict: DEFER.**
  Technically the strongest fit of the five on paper (documented
  archive depth, explicit NLP-oriented design, an FX/macro content set)
  but entirely unpriceable and unrighted from public sources.

- **Dow Jones / Factiva** -- VERIFIED the most transparently documented
  of the five: a real Developer Platform, official Python SDKs, News
  dataset with Snapshots (bulk Avro) and Streams (continuous feed).
  **The single most useful quotation found across this whole
  provider class**, from Dow Jones's own News dataset page: "Content
  usage rights vary based on the specific content, API, or feed
  combination. These rights include: Display for human consumption or
  text mining for machine consumption. Content retention period." This
  is the only vendor that names FTA's own rights *axes* (a
  machine-consumption/text-mining right distinct from display; a
  retention period as an explicit, varying, per-source dimension) in
  its own documentation -- meaning a real Dow Jones conversation would
  be substantively productive rather than exploratory, even though
  price remains entirely sales-gated ("Request a Trial... wait for a
  Dow Jones representative to reach out"). **Verdict: DEFER** -- ranked
  first among the five for a future vendor conversation, on the
  strength of this rights-dimension transparency.

- **Bloomberg** -- a clearly-named product (Event-Driven Feeds, News
  Analytics with sentiment/novelty scoring, ECO/EcoNext economic data)
  but **zero public developer documentation of any kind**: no API
  reference, no field schema, no terms page, no price -- every
  property except bare product existence is UNKNOWN. This is a finding
  in itself, not a research gap: Bloomberg enterprise data licensing is
  well understood to presuppose an existing Terminal/enterprise
  relationship FTA does not have. **Verdict: REJECT as a near-term
  candidate**; DEFER only if a human deliberately opens a sales
  conversation.

- **Associated Press (AP)** -- VERIFIED the best-engineered technical
  fit of the five, via a genuinely public, keyless Swagger 2.0 spec for
  the AP Media API: a stable `uri` identifier, a monotonic `version`
  field with a `versions=all` retrieval mode, **dual**
  `firstcreated`/`versioncreated` timestamps, machine-readable
  `usageterms` and `copyrightnotice` fields, and explicit editorial
  types (`Corrective`, `Clarification`, `Kill`, `Writethru`) that are
  structurally exactly the correction/retraction primitives FTA wants.
  **It is disqualified for historical use by a directly documented
  fact, not an inference**: AP's own product page states "30 days of
  content is available" for text (the deep archive AP offers is
  pictures/video/audio/graphics, not stories), and the Swagger spec
  itself references a right that "expires at 30 days." For prospective
  use, the blocker is cost structure: `/account/plans` and
  `/account/downloads` VERIFIED a **per-download metered billing
  model with overage charges**, unpriced, scaling poorly against a
  continuously-ingesting research workload. Site terms (distinct from
  the API licence) separately and explicitly forbid scraping and state
  "You may not archive or retain any Content without the express prior
  written consent of AP." **Verdict: DEFER for prospective (best
  technical fit, cost/licence unresolved); REJECT for historical**
  (documented 30-day text window, not a backfill).

- **Financial Times (FT)** -- VERIFIED the only named licence product
  in this entire provider class that already grants what FTA would
  need: FT's own "Datamining Licence," described verbatim as letting a
  licensee "Host the full text of FT articles and meta data on your
  servers to run your own search algorithms for data mining purposes
  (royalty required)... Apply your own meta data and analysis tools."
  This is undermined by a **materially disqualifying termination
  clause**: "At our request, you must destroy or delete all copies of
  our Content in your possession or control," combined with an at-will
  termination right -- fundamentally incompatible with a permanent,
  point-in-time research corpus. Whether "data mining" as licensed
  extends to embeddings, model training, or generated summaries is
  UNKNOWN and, given FT's own careful public litigation of AI content
  rights elsewhere, must not be assumed favourably. Royalty is
  unpriced. **Verdict: DEFER** -- ranked alongside Dow Jones as the
  closest fit on rights language, closed off by the destroy-on-
  termination obligation.

- **Notable additional finding (not one of the five originally
  scoped, but directly FX-relevant and worth recording): Nasdaq Data
  Link's "Live Briefs by MT Newswires."** This is the only candidate in
  the entire provider class for which a **complete field schema** was
  obtained from a vendor-published spec, including a sample record that
  is itself an FX story ("Australian Dollar Firm As Traders Bet on
  Lockdown End"). VERIFIED fields include `TransmissionID` (stable
  document ID), `RevisionID` (a revision counter), and `Retract` (an
  explicit retraction flag) -- but whether a revision reuses or mints a
  new `TransmissionID` is undocumented. **A genuine point-in-time
  hazard was found**: the documented timestamp format carries no
  timezone or offset at all, while the sample article's own body text
  embeds "10:26 AM EDT" -- strongly implying an unlabelled US-Eastern
  local time, which would require explicit vendor confirmation before
  any ingestion, since a wrong assumption here would silently corrupt
  every event-time alignment. Cost and storage/derived-processing
  rights are entirely UNKNOWN (onboarding-gated). **Verdict: DEFER.**

- **Structural finding to carry into cost expectations:** both Reuters
  ("AI Training & RAG") and Dow Jones ("Newswires for GenAI," "Factiva
  Sentiment Signals") sell derived-AI/NLP rights as **separate, named
  product lines** distinct from their editorial news feeds. The
  reasonable inference -- untested, not assumed as fact -- is that
  derived NLP/embedding rights are commonly a distinct, separately
  priced licence tier across this industry, not something bundled into
  a base news feed. If a future story's design depends on embeddings or
  model training over a licensed commercial feed, the realistic
  expectation should be **two licences, not one**.

**Class-level verdict: DEFER as a whole class**, structurally the same
shape as FX-49's and FX-52's own prior findings in this project's
history -- the blocker is commercial gating (no public price, no
public storage/retention terms), not point-in-time methodology or
technical feasibility. The two vendors worth an actual future
conversation are Dow Jones/Factiva (most transparent about rights
*structure*) and FT (only vendor with a named licence product that
already grants the needed storage right, undermined by its
termination clause). Consistent with FX-52's own precedent in this
project, the more realistic near-term path is official-source-only
ingestion (Source class A, above) rather than a commercial general-news
provider.

## Source class C: news APIs / aggregator platforms

Investigated 2026-09-29 against each vendor's own documentation, terms
of service, and pricing pages; no account was created except where
noted below, no payment information was entered, and no trial or
sales conversation was initiated.

- **GDELT Project** -- VERIFIED the only source in this entire ADR
  whose primary terms grant genuinely unrestricted use: "all datasets
  released by the GDELT Project are available for unlimited and
  unrestricted use for any academic, commercial, or governmental use
  of any kind without fee," with express redistribution and mirroring
  rights and no term limit. **This is not, however, a headline/article
  aggregator**: VERIFIED from the GKG 2.1 field codebook, a GDELT
  Global Knowledge Graph record contains a source URL, domain,
  language, extracted themes/locations/persons/organizations, a
  provider-generated tone score, and extracted quotations/amounts --
  **there is no headline field and no article-body field anywhere in
  the schema.** VERIFIED identity is unusually strong: each record's ID
  embeds the 15-minute processing-batch timestamp in which GDELT
  created it, which is the closest thing to a genuine point-in-time
  availability primitive found across any source in this ADR (a file
  published at time T contains, by construction, only records
  available at T). PARTIALLY_VERIFIED timestamps: the codebook's own
  description of `V2.1DATE` is internally self-contradictory (it claims
  both "date of publication" and "will be the same for all rows in a
  file"), and the DOC 2.0 API's separate `seendate` field is entirely
  undocumented -- both require empirical resolution before reliance.
  **Live validation was attempted and is informative in its failure**:
  five bounded keyless queries to the DOC 2.0 API all returned HTTP 429
  with an unauthenticated, IP-scoped throttle notice directing
  high-traffic users to the bulk-file/BigQuery channel instead --
  confirming DOC 2.0 cannot be treated as an availability-guaranteed
  ingestion dependency, independent of our own request rate. Provider
  tone/theme scores are recorded as available metadata only, never
  adopted as ground truth. **Verdict: ADOPT_AUXILIARY_METADATA
  (corrected by FX-55H, bulk GKG raw-file/BigQuery channel only; the
  DOC 2.0 API itself remains DEFER).** This single canonical
  disposition replaces the original pass's "ADOPT_PROSPECTIVE and
  ADOPT_HISTORICAL," which -- although rights-wise accurate -- implied
  GDELT belongs alongside the text-bearing official sources in Source
  class A. It does not: GDELT structurally cannot supply a headline or
  article body under any rights posture, so it is **explicitly excluded
  from FX-56's initial text-bearing source set** and is not counted
  toward this ADR's own "official sources only" prospective-set claim.
  It remains available as an optional, rights-clear auxiliary metadata
  complement (tone/theme/entity signals keyed to a source URL) that a
  future story may choose to pair with a text-bearing source, never as
  a substitute for one.

- **NewsAPI.org** -- VERIFIED **REJECT**: the only tier evaluable
  without payment explicitly prohibits our exact use -- its Developer
  plan "cannot be used in a staging or production environment
  (including internally)" -- and the cheapest compliant tier is
  $449/month for content capped at a 200-character body stub with no
  per-article identifier and no ingestion timestamp (only
  `publishedAt`, further undermined on the free tier by a disclosed
  24-hour delay between publication and availability). The
  price-to-evidentiary-value ratio is the worst of any candidate
  examined in this ADR.

- **Alpha Vantage `NEWS_SENTIMENT`** -- live-validated end to end using
  the `demo` key Alpha Vantage itself publishes as a clickable
  documentation example (no account created) -- HTTP 200, a genuinely
  same-day live article, self-documenting sentiment/relevance score
  definitions returned inline. VERIFIED the best native FX/macro topic
  fit of any commercial aggregator investigated: first-class
  `economy_monetary` ("interest rates, inflation"), `economy_fiscal`,
  and `economy_macro` topic filters plus `FOREX:USD`-style ticker
  filtering -- the only source making "what did the press say about
  central-bank policy" a structured query rather than keyword
  guesswork. PARTIALLY_VERIFIED, narrowly-scoped permitted use: the
  free-tier licence covers "investment analysis, research, testing,
  monitoring... individual in nature," but is classified commercial (a
  written agreement required) if operated "as or on behalf of a
  corporation, firm, partnership, trust or any other association," or
  by anyone "employed or... affiliated with" a list of financial-industry
  roles -- so adoptability turns on facts about FTA's own operator,
  not on technical design, and must be resolved before adoption, not
  assumed favourably. **UNKNOWN on storage/retention**: the terms of
  service contain no storage or retention clause in either direction.
  Free tier capped at 25 requests/day. One live-observed data-quality
  defect: `source_domain` returned a publisher name ("Benzinga") rather
  than an actual domain, weakening it as a syndication signal.
  **Verdict: DEFER, leaning ADOPT_PROSPECTIVE**, conditional on written
  clarification of the operator-affiliation question and the
  storage/retention silence.

- **Finnhub** -- VERIFIED **REJECT**, disqualified on a single explicit
  clause: "All data must be deleted should your subscription to that
  data ends" -- flatly incompatible with a permanent point-in-time
  archive, and triggered by any subscription ending, not only
  termination for cause. This is a genuinely instructive rejection: a
  native `category=forex` filter and a monotonic integer `id` usable as
  a forward-walking cursor would otherwise have made Finnhub the most
  mechanically PIT-friendly prospective feed in this entire source
  class; the blocker is purely contractual, and `/news` offers no
  date-range backfill at all regardless.

- **Financial Modeling Prep (FMP)** -- VERIFIED **REJECT** on two
  independently sufficient grounds: the personal-tier licence states
  the customer "may not copy or download any content from the
  Services except with the prior written approval of FMP," and a
  separate termination clause mandates deleting "all Data... including
  data cached" plus signing a Data Deletion Agreement, with FMP
  reserving audit rights. FMP's own contract contains an internal
  contradiction between this deletion clause and a separate clause
  permitting retained copies absent termination for cause -- neither
  reading is safe to rely on. The response schema for its dedicated
  `forex-latest` endpoint is not publicly documented at all.

- **Marketaux** -- VERIFIED the best-engineered field model of any
  aggregator examined: a stable `uuid` explicitly documented for
  single-article retrieval, microsecond-precision UTC `published_at`,
  per-article `language`, a first-class `currency` entity type, and the
  only genuine duplicate-story primitive found in this ADR (`similar` +
  a `group_similar` grouping parameter). **UNKNOWN on rights, and
  structurally so**: the only governing document is a generic
  website-wide Terms of Use granting a licence "solely for your
  personal, non-commercial use" and stating "commercial endeavors"
  require specific approval -- directly contradicting Marketaux's own
  $29-199/month API price list. This is not a resolvable-by-careful-
  reading ambiguity; no API-specific data licence exists to read.
  One operational trap for a future story if this is ever adopted:
  `group_similar` **defaults to true**, so an un-configured integration
  would silently discard duplicate coverage rather than recording it --
  exactly the kind of provider-duplication failure this project's own
  testing discipline exists to catch, arriving here as a default rather
  than a bug. **Verdict: DEFER** -- the clearest "one clarifying email
  away from adoptable" candidate in this source class.

- **Polygon.io (now redirecting to massive.com)** -- noted as a
  domain-migration correction for any future story (pre-existing notes
  referencing `polygon.io` are stale). VERIFIED the deepest explicitly-
  dated archive of any aggregator (history to 2016-06-22 on paid
  tiers), a stable per-article `id`, and an unusually transparent
  provider-sentiment field pairing a score with natural-language
  `sentiment_reasoning`. **UNSUITABLE for FX/macro purposes as
  structured**: the news endpoint is ticker-keyed equity news with no
  macro or currency entity model -- central-bank/FX coverage would be
  incidental to equity-ticker tagging, not queryable. **Verdict:
  DEFER**, a distant fourth candidate in this source class.

**Class-level synthesis.** GDELT (ADOPT_AUXILIARY_METADATA) is the
only source in this entire ADR -- across all four source classes --
with unambiguous, unrestricted, fee-free usage rights, but it
structurally cannot supply headline or article text, only metadata and
derived features; it is excluded from FX-56's initial text-bearing
source set and, if ever paired with a text-bearing source in a future
story, must never be treated as a standalone news feed in its own
right. Every commercial aggregator examined exposes **publication time
only** (no ingestion/first-seen timestamp), which independently
confirms this ADR's own governing invariant (see "FTA availability
invariant" above): FTA's defensible availability anchor is always
FTA's own retrieval/first-seen time, never any provider-stated
`published_at`.
Three candidates (NewsAPI, Finnhub, FMP) are REJECTed on contractual
grounds alone, each for a distinct, individually sufficient reason
(scope-of-use prohibition, mandatory data deletion on subscription end,
and a copy/download prohibition respectively) -- this is a genuinely
heterogeneous set of legal failure modes, not one repeated pattern.
Two candidates (Alpha Vantage, Marketaux) are DEFER and are the
priority follow-ups in this source class, both resolvable by a single
written vendor clarification rather than by further research.

## Source class D: dedicated FX/macroeconomic commentary publishers

Investigated 2026-09-30, live against current endpoints. **Class
verdict: DEFER as a whole class** -- automation is technically the easy
part (four candidates serve well-formed RSS with genuinely good
identity/timestamp properties), but the class fails on RIGHTS in three
distinct, independent ways, and zero candidates clear the full bar.

**FXStreet** (`fxstreet.com`) -- VERIFIED: three working RSS feeds
(`/rss`, `/rss/news`, `/rss/analysis`, all HTTP 200, not disallowed by
`robots.txt`) plus a separately documented commercial API portal
(`docs.fxstreet.com` -- News/Economic-Calendar/Daily-Market-Analysis/
Market-Tools APIs, OAuth2, XML/RSS/JSON delivery, webhooks). VERIFIED
stable identity: opaque UUID `guid isPermaLink="false"` per item --
the best identity of any candidate in this class. VERIFIED timestamps:
RFC-822 `pubDate` with explicit `GMT`, but no `updated` field, so
revisions are undetectable via the feed alone. **UNSUITABLE on
terms**: the site's own Terms & Conditions
(`/info/terms-conditions`) state verbatim that reproduction/
retransmission/redistribution of site content, "**regardless of its
purpose and the means used for it**," is prohibited without prior
authorization, limited to "personal and private use" -- a purpose-
blind prohibition with no RSS carve-out anywhere, squarely covering
automated ingestion into a persisted internal research store. The
commercial API's own terms/pricing are UNKNOWN (sales-gated; not
pursued, per this story's own no-purchase/no-sales-contact rule).
Content depth confirmed snippet-only (zero `content:encoded` across
30 sampled items). Verdict: **DEFER** (free RSS REJECTed on terms; the
documented commercial API is the only rights-clear path but requires a
negotiated, unpriced contract).

**ForexLive -- now InvestingLive** (`forexlive.com` 301-redirects
permanently to `investinglive.com`, a real domain migration this
project's own prior research never encountered). VERIFIED and
**UNSUITABLE, decisively**: `investinglive.com/robots.txt` individually
names `ClaudeBot`, `anthropic-ai`, and `Claude-Web` with `Disallow: /`
at the site root, and its CloudFront edge returns HTTP 403 to
non-browser clients even for `robots.txt` itself. This research
deliberately stopped at that point and did not probe for a feed, terms
page, or article content on this domain -- an explicit, machine-
readable refusal of this exact agent class requires no further
evidence and must be honored without argument. Verdict: **REJECT**.

**Action Forex** (`actionforex.com`) -- VERIFIED: a fully permissive
`robots.txt` (`Disallow:` empty = allow all, no AI-specific
exclusions) and a working `/feed/` (RFC-822 `pubDate` with explicit
`+0000`; stable WordPress numeric-post-id `guid isPermaLink="false"`
that survives URL/slug changes). **UNKNOWN on terms**: the site's own
disclaimer page contains no clause at all -- neither granting nor
prohibiting -- automated access, reproduction, or commercial use;
"silence" must be read as UNKNOWN, never as permission, per this
story's own discipline. A materially disqualifying rights-chain
concern independent of ActionForex's own terms: sampled feed items are
substantially third-party syndicated bank research (e.g. `dc:creator:
KBC Bank`), and the site's own WordPress plugin stack
(`rss-feed-post-generator-echo`) confirms it auto-generates posts from
other publishers' feeds -- ActionForex likely does not itself hold the
rights it would need to pass onward. Some categories (e.g. Economic
Calendar) emit pure boilerplate descriptions with no usable content at
all. Verdict: **DEFER** (would become ADOPT_PROSPECTIVE only on
written confirmation from the publisher; adopting on silence alone
would be exactly the favorable-inference this project's discipline
forbids).

**MarketPulse** (OANDA's own market-analysis site, `marketpulse.com`)
-- the single most seductive candidate in this pass, and rejected
after direct verification specifically because of that. This project
already integrates OANDA's Practice API for its own broker adapter;
verified independently that this confers NO licensing benefit --
MarketPulse is operated by a legally separate entity ("OANDA Business
Information and Services Inc."), and nothing in its own terms
references broker-account holders. VERIFIED: a working `/feed/`, full
`content:encoded` article text (~6,900 characters sampled), and --
uniquely among every candidate checked in this entire ADR -- an
explicit clause in the site's own Terms of Use (effective 2025-04-03)
naming RSS as a sanctioned reproduction/redistribution route. But that
carve-out's own conditions -- a canonical tag on "your content"
pointing back to the original MarketPulse URL, plus a "do follow"
link to the source -- are conditions of PUBLIC republication; FTA
would not be republishing anything, has no "your content" to tag and
no public page to carry a link-back, so the carve-out's conditions are
structurally impossible for FTA to satisfy. That leaves only the
general clauses: "personal and non-commercial use," and an explicit,
unconditional prohibition on "any computerised or automatic mechanism,
including, without limitation, any web scraper, spider, or robot, to
access, extract and/or download any information from MarketPulse" --
which is precisely what a polling ingestion job is. Independently of
rights: the feed exposes **exactly one item** at time of check against
a real publishing cadence of roughly 1-3 items/week -- prospective
polling on this feed would systematically lose articles between polls,
failing FTA's own completeness requirements even under perfect
licensing. Verdict: **REJECT** for the current architecture (DEFER
only via a real, citable negotiation path -- `info@marketpulse.com` --
not pursued in this story).

**DailyFX** (`dailyfx.com`) -- FX-52A's own prior finding
RE-VERIFIED and CONFIRMED still true: the standalone site closed
permanently 2024-09-04 per IG Group's own announcement
(`ig.com/uk/trading-strategies/dailyfx--now-get-your-trading-insights-on-ig-240906`).
Content did not resurface as a separately-fed FX-commentary property;
it was absorbed into IG's general broker-marketing/education site, a
different source class entirely. The bare domain now returns HTTP 403
at the Akamai edge to a plain client. Verdict: **REJECT** (moot;
no further re-verification needed unless IG launches a genuinely new
FX-specific feed).

**Named FX commentators without an independent feed** (e.g. Kathy
Lien / BK Asset Management) -- VERIFIED: `bkassetmanagement.com` has no
`/feed`/`/rss` at conventional endpoints (HTTP 404); this commentator's
work reaches the public only through third-party aggregator platforms
(e.g. an FXStreet contributor page), which means any ingestion would
inherit that aggregator's own already-UNSUITABLE terms. Verdict:
**REJECT** (no feed exists to evaluate independently).

**Reuters/Bloomberg FX-specific feeds** (checked only to confirm
genuine distinctness from the general-financial-news research pass,
not duplicated here) -- VERIFIED: no FX-specific Reuters RSS exists at
all (`feeds.reuters.com` no longer resolves in DNS; currencies-specific
paths return 401/404). Bloomberg serves one live general-markets feed
(`feeds.bloomberg.com/markets/news.rss`, all-rights-reserved channel
copyright), confirmed NOT FX-scoped (sampled items are
commodities/equities) -- deliberately not claimed as an FX-commentary
candidate here; flagged for the general-financial-news source class
instead.

**Forex Factory** (`forexfactory.com`) -- VERIFIED: `robots.txt`
contains no `User-agent`/`Disallow` directives at all (one line, a
bare sitemap reference) -- no permission signal in either direction --
and every feed-shaped endpoint checked (`/rss.php`, `/rss`, `/feed`)
returns HTTP 403 to a plain client; not pursued past that edge
control. Also topically a calendar/forum property, not a commentary
publisher. Verdict: **REJECT**.

**ING THINK** (`think.ing.com`, ING Bank's own economics/FX/rates
research desk) -- discovered during this pass, not on the original
candidate list, and the strongest single candidate found in this
entire source class. VERIFIED: a working `/rss` feed (ISO-8601
`dc:date` with explicit `+00:00` offsets -- the cleanest, least
ambiguous timestamps found in this pass); a 631-entry `robots.txt`
nuisance-bot blocklist that notably does NOT name this project's own
agent class (`ClaudeBot`/`anthropic-ai`/`Claude-Web`/`Google-Extended`
are all absent) and explicitly permits `ChatGPT-User`; and -- uniquely
among every source investigated across this entire ADR -- an
affirmative licence grant in its own Terms of Use: "ING grants you the
license to use, distribute, reproduce, modify, adapt, publicly perform
and publicly display such Content by mentioning ING Bank N.V. as
copyright owner," with no non-commercial restriction on ING-owned
content. **PARTIALLY_VERIFIED, not adopted**: ING's own separate
Disclaimer page directly CONTRADICTS its Terms of Use, prohibiting use
"for any other purposes than that of this site" with "All rights are
reserved," and separately asserts EU sui-generis DATABASE rights -- a
legal hook aimed specifically at systematic extraction into a store,
exactly what FTA would do. Two conflicting primary documents from the
same publisher means the favorable reading is NOT established under
this project's own discipline; the ToU's grant cannot be relied upon
while the Disclaimer stands unresolved. Identity is PARTIALLY_VERIFIED
(`guid` = article URL + `#When:<time>Z`, which embeds publish time and
would change if an article were re-slugged or re-timestamped -- not a
durable opaque key without local handling). Content depth confirmed
snippet-only. Verdict: **DEFER** -- the single highest-value follow-up
identified anywhere in this research: one clarifying question to ING
resolving the ToU/Disclaimer conflict could plausibly clear this
candidate for prospective adoption.

**Class-level finding on scraping (Section 8's own governing rule,
tested against a real, tempting counter-example):** no candidate in
this class justifies HTML scraping. Every path that would require it
is blocked by something stronger than inconvenience: an explicit,
purpose-blind prohibition (FXStreet), an explicit anti-automation
clause (MarketPulse), a named-agent `Disallow: /` (InvestingLive), or
active edge/WAF controls returning 403 to plain clients (InvestingLive,
DailyFX, Forex Factory). No User-Agent was spoofed, no edge control was
defeated, and no content path was probed on a domain whose own
`robots.txt` excluded this project's agent class -- in the InvestingLive
case, "does a feed even exist" was left genuinely UNKNOWN rather than
answered improperly.

## Consolidated source matrix

Verdicts use this ADR's own taxonomy: **ADOPT_PROSPECTIVE**,
**ADOPT_HISTORICAL**, **DEFER** (a real candidate, blocked on an
unresolved legal/operational question -- a written clarification or a
production retest would plausibly resolve it), **REJECT** (disqualified
by primary evidence). A source can carry different prospective and
historical verdicts. Two additional labels, introduced by FX-55H's own
correction pass, refine this taxonomy rather than replacing it:

- **DEFER_HISTORICAL**: identical in meaning to DEFER, scoped
  specifically to the historical axis, used when a source's
  prospective verdict is independently settled (ADOPT_PROSPECTIVE or
  REJECT) but its historical-only rights or semantics carry their own,
  separately unresolved question. Applied here to the ECB bulk
  speeches CSV (author-attribution carve-out ambiguity) in place of
  this document's original, premature ADOPT_HISTORICAL classification.
- **ADOPT_AUXILIARY_METADATA**: a source whose rights are fully clear
  (no unresolved property) but whose content is structurally
  metadata/derived-feature-only, with no headline or article text
  under any rights posture. Adopted for that limited purpose only, and
  never counted toward an "official sources only" or "text-bearing
  news source" claim. Applied here to GDELT's bulk GKG channel in
  place of this document's original ADOPT_PROSPECTIVE/ADOPT_HISTORICAL
  classification, which incorrectly implied parity with a headline/
  text-bearing source.

**FTA availability, for every ADOPT_PROSPECTIVE source in this matrix
without exception, is FTA's own `first_seen_at`** -- see "FTA
availability invariant" above. No verdict below should be read as
granting any source's own timestamp anchor status.

| Source | Class | Content | Identity | Timestamps | Rights | Verdict |
|---|---|---|---|---|---|---|
| Fed Board (press/speeches/testimony RSS) | A | News, minutes, SEP, speeches | VERIFIED | PARTIALLY_VERIFIED (hour-granular) | VERIFIED (public domain) | **ADOPT_PROSPECTIVE** |
| US Treasury | A | -- | -- | -- | -- | **REJECT** (no feed exists) |
| BLS | A | News releases | UNKNOWN (access blocked) | UNKNOWN | UNKNOWN | **DEFER** (retest from prod IP) |
| BEA (`rss.xml`) | A | Data-release news | VERIFIED | PARTIALLY_VERIFIED (named-zone hazard) | UNKNOWN | **DEFER** (corrected by FX-55H; reuse rights unresolved) |
| ECB (`/rss/press.html`) | A | Press/speeches/interviews | VERIFIED | PARTIALLY_VERIFIED | VERIFIED (Working/Occasional Papers carved out) | **ADOPT_PROSPECTIVE** |
| ECB (`all_ECB_speeches.csv`) | A | Speeches, full text, historical | PARTIALLY_VERIFIED | UNSUITABLE (date-only) | PARTIALLY_VERIFIED (author-carve-out ambiguity) | **DEFER_HISTORICAL** (corrected by FX-55H) |
| Eurostat (legacy feed) | A | -- | -- | -- | -- | **REJECT** (dead since 2021) |
| Eurostat (portlet Atom) | A | Euro-indicator releases | PARTIALLY_VERIFIED | VERIFIED (best UTC structure) | VERIFIED (CC BY 4.0) | **DEFER** (undocumented endpoint) |
| BoE (news/speeches/publications RSS) | A | News, minutes, speeches | VERIFIED (opaque GUID) | PARTIALLY_VERIFIED (mixed tz format) | PARTIALLY_VERIFIED (non-commercial) | **ADOPT_PROSPECTIVE** |
| GOV.UK Content API (HM Treasury) | A | News, speeches, statements | VERIFIED (UUID) | **VERIFIED source metadata** (first_published/updated/change_history -- never an FTA-availability anchor) | **VERIFIED** (OGL v3, any purpose) | **ADOPT_PROSPECTIVE** |
| GOV.UK Search API (historical enumeration) | A | HM Treasury document index | VERIFIED (reuses Content API identity) | N/A | UNKNOWN (own terms/limits unverified) | **DEFER** (corrected by FX-55H) |
| ONS | A | Bulletin announcements | VERIFIED (URL guid) | **UNSUITABLE** (confirmed 8h wrong) | UNKNOWN | **REJECT** prospective / DEFER historical |
| BoC press-releases feed | A | Press releases, rate decisions | VERIFIED | **UNSUITABLE as published** (mislabelled offset) | VERIFIED | ADOPT_PROSPECTIVE **with mandatory remediation** |
| BoC speeches feed | A | Speeches + future-dated items | VERIFIED | UNSUITABLE | VERIFIED | **REJECT as published** (look-ahead vector) |
| StatCan (The Daily, 34 feeds) | A | Release bulletins | VERIFIED (URL + sequence letter) | PARTIALLY_VERIFIED (no intra-day order) | **VERIFIED** (most permissive licence found) | **ADOPT_PROSPECTIVE** |
| Dept of Finance Canada | A | News, statements | VERIFIED (URL) | VERIFIED (real per-item times) | PARTIALLY_VERIFIED (non-commercial only) | **DEFER** |
| Reuters / LSEG (MRN) | B | Wire news, macro | PARTIALLY_VERIFIED | UNKNOWN | **UNSUITABLE on free tier**, commercial unpriced | **DEFER** |
| Dow Jones / Factiva | B | Wire news, 33 languages | UNKNOWN | UNKNOWN | PARTIALLY_VERIFIED (rights axes named, values unpriced) | **DEFER** |
| Bloomberg | B | Wire/markets news | UNKNOWN | UNKNOWN | UNKNOWN (no public docs at all) | **REJECT** (pending sales contact) |
| Associated Press | B | Wire news | **VERIFIED** (best technical fit) | VERIFIED (dual timestamps) | UNSUITABLE historical (30-day text window); metered cost | DEFER prospective / **REJECT historical** |
| Financial Times | B | Macro/markets commentary | PARTIALLY_VERIFIED | PARTIALLY_VERIFIED | PARTIALLY_VERIFIED (Datamining Licence; destroy-on-termination) | **DEFER** |
| Nasdaq / MT Newswires | B | FX-categorised wire news | PARTIALLY_VERIFIED | PARTIALLY_VERIFIED (unlabelled tz hazard) | UNKNOWN | **DEFER** |
| GDELT (bulk GKG) | C | Metadata/derived features only, no headline/text | **VERIFIED** (batch-embedded ID) | PARTIALLY_VERIFIED (self-contradictory field docs) | **VERIFIED** (unrestricted, fee-free) | **ADOPT_AUXILIARY_METADATA** (corrected by FX-55H; excluded from FX-56's text-bearing set) |
| GDELT DOC 2.0 API | C | Same, real-time query | VERIFIED but rate-limited | -- | VERIFIED | **DEFER** (IP-throttled, unusable for systematic ingestion) |
| NewsAPI.org | C | Headlines + 200-char stub | PARTIALLY_VERIFIED (URL only) | PARTIALLY_VERIFIED (published only; 24h delay on free) | **UNSUITABLE on usable tier** | **REJECT** |
| Alpha Vantage `NEWS_SENTIMENT` | C | Headline + summary, macro-topic-tagged | PARTIALLY_VERIFIED (URL only) | PARTIALLY_VERIFIED (published only) | PARTIALLY_VERIFIED (operator-dependent; storage UNKNOWN) | **DEFER** |
| Finnhub | C | Headline + summary, `category=forex` | VERIFIED (monotonic id) | VERIFIED (published only) | **UNSUITABLE** (deletion on subscription end) | **REJECT** |
| Financial Modeling Prep | C | Headline + snippet, forex-specific endpoint | UNKNOWN (schema undocumented) | UNKNOWN | **UNSUITABLE** (copy/download prohibited; deletion mandated) | **REJECT** |
| Marketaux | C | Headline + snippet | **VERIFIED** (uuid) | PARTIALLY_VERIFIED (published only) | UNKNOWN (no API-specific licence exists) | **DEFER** |
| Polygon.io / Massive | C | Equity-ticker news | VERIFIED (id) | PARTIALLY_VERIFIED (published only) | PARTIALLY_VERIFIED | **DEFER** (wrong topical shape) |
| FXStreet | D | FX/macro commentary | VERIFIED (UUID) | PARTIALLY_VERIFIED | **UNSUITABLE** (purpose-blind prohibition) | **DEFER** |
| ForexLive / InvestingLive | D | FX/macro commentary | -- | -- | **UNSUITABLE** (names ClaudeBot in robots.txt) | **REJECT** |
| Action Forex | D | FX/macro commentary | VERIFIED | VERIFIED | UNKNOWN (silent terms; syndication concern) | **DEFER** |
| MarketPulse (OANDA) | D | FX/macro commentary | -- | -- | **UNSUITABLE** (explicit anti-automation clause) | **REJECT** |
| DailyFX | D | -- | -- | -- | -- | **REJECT** (closed 2024-09-04) |
| Kathy Lien / BK Asset Mgmt | D | -- | -- | -- | -- | **REJECT** (no independent feed) |
| Forex Factory | D | -- | -- | -- | -- | **REJECT** (no accessible feed) |
| ING THINK | D | FX/macro/rates commentary | PARTIALLY_VERIFIED | **VERIFIED** (cleanest offsets found) | PARTIALLY_VERIFIED (ToU/Disclaimer conflict) | **DEFER** (strongest in class) |

## Point-in-time assessment

This ADR's own research independently reconfirms and extends FX-51
through FX-54's own PIT discipline into the news domain:

- **No source anywhere in this ADR -- across all four classes -- exposes
  FTA's own ingestion/first-seen timestamp; only FTA's own retrieval
  process can produce that value.** Every provider, GOV.UK included,
  exposes at best its own publication or last-updated timestamp -- a
  SOURCE-side fact, not an FTA-side one. FX-55's own initial pass
  treated GOV.UK's `first_published_at` as a partial exception to this
  rule ("primary-verifiable... sufficiently authoritative to serve as
  an availability anchor"); **that was wrong and is corrected by
  FX-55H** -- see "FTA availability invariant" above. GOV.UK's own
  metadata is uniquely rich and uniquely well-verified as SOURCE
  provenance, which is exactly why it must be persisted in full, but
  verifiability of a source's own claim is not the same property as
  that claim being FTA's own observation time.
- **Therefore: first-seen/retrieval time is the FTA availability
  anchor for every source in this ADR, without exception.** Provider-
  stated publication times must always be persisted as a separate,
  clearly labelled, non-authoritative field -- never promoted to the
  availability anchor, mirroring the FX-51-54 treatment of provider
  `published_at` fields and the FX-52AH treatment of BoC's own
  `dc:date`.
- **The same invariant governs historical backfill, and is easy to
  violate silently**: a source's own publication timestamp establishes
  documented publication timing only, never that FTA itself possessed
  the item at that historical moment. A backfilled row must record its
  actual backfill/ingestion time as its own FTA-availability field, or
  be explicitly flagged as backfill-derived -- never silently stamped
  with the source's historical publish time as if equivalent to
  real-time prospective knowledge. This applies to GOV.UK's Search API
  and ECB's bulk speeches CSV exactly as it applies to every other
  historical candidate in this ADR.
- **Two independently confirmed timestamp defects materially change
  what "PIT-safe" means for specific sources, and must not be
  papered over in FX-56:** ONS's `pubDate`/`release_date` is
  demonstrably wrong by approximately eight hours (a date-midnight
  artifact, not the true ~07:00 BST release instant), confirmed via two
  independent primary endpoints; and the Bank of Canada's `dc:date`
  presents America/Toronto local time under a literal, incorrect
  `+00:00` label, confirmed against three independent event anchors
  and the feed's own prose. Neither defective value may ever serve as
  FTA's own availability anchor, remediated or not (see "FTA
  availability invariant" above): each must either be excluded from
  any timestamp-bearing role, or, where a remediation is independently
  verified (e.g. a confirmed Toronto-local reinterpretation of BoC's
  `dc:date`), persisted as SOURCE publication provenance alongside --
  never in place of -- the raw as-received value and FTA's own
  `first_seen_at`.
- **One look-ahead-bias vector was found and must be excluded, not
  merely down-weighted:** the Bank of Canada's speeches RSS feed
  contains genuinely future-dated entries (a speech scheduled days
  ahead already present in the feed). Any adoption of this feed
  requires an explicit `dc:date > now` quarantine filter.
- **GDELT's bulk GKG channel (ADOPT_AUXILIARY_METADATA, excluded from
  FX-56's text-bearing scope) is the one source offering a structurally
  different, stronger PIT primitive**: its record identity embeds the
  15-minute processing-batch timestamp in which GDELT itself created
  the record, meaning a batch file is intrinsically time-bounded by
  construction. This does not extend to the DOC 2.0 API, whose
  `seendate` field is undocumented and must not be assumed equivalent,
  and it does not change GDELT's own exclusion from the text-bearing
  set: it is noted here only in case a future story pairs it, as
  auxiliary metadata, with a text-bearing source.

## Historical coverage assessment

Prospective and historical access separate cleanly across this
research, exactly as this story anticipated, and the two are **not**
uniformly correlated:

- **Two candidates that looked like genuinely strong historical assets
  are corrected here, not adopted outright (FX-55H).** The ECB's bulk
  speeches CSV (full text back to ECB inception, monthly-updated,
  date-only granularity) is real and technically excellent, but its
  author-attribution carve-out ambiguity is an unresolved critical
  rights property -- **DEFER_HISTORICAL**, not ADOPT_HISTORICAL, per
  this ADR's own admission rule. GOV.UK's Search API (9,819 HM Treasury
  documents, date-sortable) is a genuine documented enumeration
  mechanism, but its own terms and rate limits were never separately
  verified from the Content API's -- **DEFER**, not ADOPT_HISTORICAL,
  for the same reason. GOV.UK's Content API itself remains adopted for
  prospective retrieval of any already-known item; a real historical
  backfill for GOV.UK depends on resolving the Search API's own terms
  first. GDELT's bulk GKG archive is historically deep and immediately
  usable under its unrestricted licence (ADOPT_AUXILIARY_METADATA), but
  supplies metadata/derived features only, never a headline or article
  body, and is excluded from FX-56's initial text-bearing scope.
- **Several strong prospective sources have weak or absent historical
  depth**: Fed feeds hold 15-20 items with only an HTML yearly archive
  beyond that; ECB's press/speech/interview feed holds 15 items; BoE
  feeds hold a rolling 50-item window with `/search` robots-disallowed;
  StatCan's Daily feeds hold a hard 100-day rolling window. None of
  these has a documented feed-based archive; a backfill would require
  HTML retrieval against a predictable but undocumented URL pattern --
  an explicit ADR decision this document defers to whoever reopens
  FX-56's historical scope, not a default yes.
- **AP is the clearest illustration of the story's own anticipated
  outcome ("prospective GO, historical DEFER/REJECT is an acceptable
  and important valid result")**: AP's Media API is the single best
  technically-engineered fit found in the commercial-provider class
  (stable IDs, dual timestamps, explicit correction/retraction editorial
  types) yet its own documentation states its text archive is a
  documented 30-day window -- not a backfill by any definition. This is
  recorded as DEFER prospective / REJECT historical rather than being
  allowed to contaminate the prospective verdict, per this story's own
  Section 36 instruction.
- **No commercial general-news provider (class B) or FX-commentary
  publisher (class D) currently offers a rights-clear historical
  archive.** Reuters/LSEG's claimed 1996+ "point-in-time streamed news"
  archive remains marketing copy (PARTIALLY_VERIFIED), not a documented
  methodology.
- **Conclusion for future backtesting/reputation work**: near-term
  historical FX-relevant news depth is bounded and source-specific
  (ECB speeches, GOV.UK, GDELT's bulk archive), not a general
  capability. Any future story requiring deep multi-year historical
  news coverage across all four source classes should expect to remain
  gated on the same commercial licensing questions this ADR leaves
  open in class B, exactly as FX-49 was gated on commercial
  rate-expectations data.

## Decision

**NEWS SOURCE FEASIBILITY VERDICT: PARTIAL_GO.**

A useful, bounded, rights-clear prospective news-evidence source set
is viable today using **official/primary, text-bearing sources only
(source class A)** -- directly mirroring FX-52A's own precedent in
FX-EPIC-07, where an official-source-only adoption was the correct and
sufficient outcome after commercial economic-calendar providers failed
to clear the gate. No general financial news provider (class B),
commercial news API/aggregator (class C), or dedicated FX-commentary
publisher (class D) currently clears this project's own rights/PIT/
identity bar without either a priced commercial contract this story is
expressly forbidden from entering, or a written vendor clarification
this story is expressly forbidden from sending. Coverage is therefore
intentionally partial, skewed toward official communications and away
from third-party commentary or wire-service breadth -- this is treated
as an acceptable and expected outcome, not a shortfall to be closed by
force. **FTA availability, for every source below, is always FTA's own
`first_seen_at`** -- see "FTA availability invariant" above; no source
in this ADR is exempt.

**Adopted for prospective ingestion (source class A, text-bearing set
only), subject to each source's own stated caveat:**

1. Federal Reserve Board / FOMC -- `press_monetary.xml` (statements,
   minutes, SEP), `speeches.xml`, `testimony.xml`, per-governor feeds.
2. ECB -- `/rss/press.html` (press releases, speeches, interviews in
   one feed, discriminable by URL slug segment), excluding Working/
   Occasional Papers per ECB's own carve-out.
3. Bank of England -- `/rss/news` (incl. minutes), `/rss/speeches`,
   `/rss/publications`, for FTA's current non-commercial research use
   only.
4. GOV.UK Content API (HM Treasury) -- the strongest single source
   found in this entire ADR for prospective retrieval. Its
   `first_published_at`/`public_updated_at`/`updated_at`/
   `change_history`/`withdrawn_notice` are adopted as source
   provenance to persist in full; **none of them is FTA's availability
   anchor, which remains `first_seen_at` for every item, exactly as for
   every other source on this list** (corrected by FX-55H). Historical
   backfill via the Search API is NOT included in this adoption -- see
   below.
5. Statistics Canada -- the relevant subject-specific Daily Atom feeds
   (Prices, Labour, Economic accounts, International trade at minimum).
6. Bank of Canada -- `press-releases/feed/` **only**, and **only** with
   the following mandatory adapter-level handling (corrected by
   FX-55H): FTA availability is `first_seen_at`, full stop, never any
   form of `dc:date`; if a Toronto-local reinterpretation of `dc:date`
   is independently verified, it is persisted as SOURCE publication
   provenance alongside -- never in place of -- the raw, as-received
   (malformed) `dc:date` string. The BoC speeches feed is explicitly
   NOT adopted as published (see below).

BEA's `rss.xml` and GDELT's bulk GKG channel are **not** part of this
adopted text-bearing list (both corrected by FX-55H, below).

**Not adopted, but rights-clear for a limited, non-text-bearing
purpose (FX-55H correction):**

- **GDELT bulk GKG channel** (raw files / BigQuery, not the DOC 2.0
  API) -- **ADOPT_AUXILIARY_METADATA**: unrestricted, fee-free rights,
  but structurally metadata/derived-feature evidence only, with no
  headline or article text under any rights posture. Available as an
  optional complement to a text-bearing source in a future story;
  **explicitly excluded from FX-56's initial text-bearing source set**
  and not counted toward the "official sources only" claim above.

**No source in this ADR is adopted for historical ingestion as of this
correction.** The two closest candidates are corrected from this
document's original ADOPT_HISTORICAL classification to DEFER/
DEFER_HISTORICAL, each for an unresolved critical property, not a
technical gap:

- **ECB bulk speeches CSV** (full-text, date-only granularity) --
  **DEFER_HISTORICAL**: whether named/author-attributed speeches fall
  inside the ECB's own Working/Occasional-Paper written-authorisation
  carve-out remains genuinely ambiguous and unresolved from primary
  documentation.
- **GOV.UK Search API** (9,819 HM Treasury documents, date-sortable)
  -- **DEFER**: a real, documented enumeration mechanism, but its own
  terms and rate limits were never separately verified from the
  Content API's.
- GDELT's bulk GKG archive is historically deep and rights-clear
  (ADOPT_AUXILIARY_METADATA) but, as above, is metadata-only and not a
  headline/text historical source.

**Explicitly NOT adopted, with each one's own reopening condition:**

- **US Treasury, Eurostat's legacy feed, Forex Factory, DailyFX,
  Kathy Lien/BK Asset Management, ForexLive/InvestingLive, MarketPulse**
  -- REJECT. No feed/API exists, the feed is a confirmed-dead shell, or
  automation is explicitly and unambiguously prohibited by the
  publisher's own primary documentation. Reopens only if the publisher
  ships a new documented feed/API, or in InvestingLive's specific case,
  only if that publisher's own `robots.txt` ever stops naming this
  project's agent class -- which must never be worked around.
- **BLS** -- DEFER. Every path, including `robots.txt` itself, returned
  HTTP 403 from this research environment; this may be specific to this
  session's egress rather than a production regression. Reopens on a
  clean re-test from the actual production ingestion environment --
  and this test should happen regardless of FX-56's own scope, since
  BLS's calendar feed is already relied upon by FX-52A.
- **ONS** -- REJECT for prospective use, DEFER for historical/contextual
  use. Reopens only if an ONS endpoint is found exposing the genuine
  ~07:00 BST release instant rather than a date-midnight value, or if
  FX-56 explicitly accepts date-only granularity for this source.
- **BEA `rss.xml`** (corrected by FX-55H, moved here from the adopted
  list) -- DEFER. Reuse/storage rights are UNKNOWN from any primary BEA
  source. Reopens once a primary BEA statement establishes those
  rights.
- **ECB bulk speeches CSV, GOV.UK Search API** (corrected by FX-55H,
  moved here from an implied "adopted historical" status) -- DEFER/
  DEFER_HISTORICAL, per their own stated conditions immediately above.
- **BoC speeches feed, Eurostat's portlet Atom, Dept of Finance Canada,
  Reuters/LSEG, Dow Jones/Factiva, Bloomberg, AP, Financial Times,
  Nasdaq/MT Newswires, Alpha Vantage, Marketaux, Polygon.io/Massive,
  GDELT DOC 2.0 API, FXStreet, Action Forex, ING THINK** -- DEFER. Each
  reopens independently, on its own stated condition (a written vendor
  clarification -- prepared, not sent, in the appendix below --, a
  quarantine filter for future-dated items, or confirmation of an
  undocumented endpoint's stability). No DEFER source is bundled into
  the adopted set above; reopening one does not reopen any other.
- **NewsAPI.org, Finnhub, Financial Modeling Prep** -- REJECT. Each is
  disqualified by an explicit, independently sufficient contractual
  clause (scope-of-use prohibition; mandatory deletion on subscription
  end; copy/download prohibition). Reopens only if the vendor's own
  published terms change.

## FX-56 readiness

**Status update: FX-56 is complete (2026-10-01)**, built exactly to
this section's own stated assumptions -- see `docs/DECISIONS.md`'s own
FX-56 entry for the implementation. This section's content below is
left as originally written (the design brief FX-56 was built against),
not rewritten in hindsight.

**FX-56 (Point-in-Time News Evidence Model) may begin.** It may safely
assume, as a starting design surface:

- **Adopted source kinds**: government/central-bank press releases,
  minutes, speeches, and statements (RSS/Atom/JSON, all keyless) --
  Fed, ECB press/speech/interview feed, Bank of England, GOV.UK
  Content API, Statistics Canada, Bank of Canada press-releases feed.
  This is the entire text-bearing set; **BEA is not included**
  (corrected by FX-55H -- DEFER, unresolved reuse rights). GDELT's bulk
  GKG channel is a separate, optional, metadata-only auxiliary
  (ADOPT_AUXILIARY_METADATA) that FX-56 may pair with a text-bearing
  source but must **not** treat as part of, or a substitute for, this
  text-bearing set; if FX-56 chooses to incorporate it, the design must
  say so explicitly rather than silently folding it into "official
  sources." No headline/text-bearing commercial provider is assumed
  available.
- **Availability/PIT semantics (hardened by FX-55H -- see "FTA
  availability invariant" above): FTA availability is `first_seen_at`
  for every adopted source without exception, GOV.UK included.** The
  original version of this ADR exempted GOV.UK's Content API on the
  strength of its `first_published_at` field; that exemption was wrong
  and is withdrawn. FX-56 must model at least five separate concepts
  per item -- authoritative FTA `first_seen_at`; source published
  timestamp; source updated timestamp where available; source
  revision/correction metadata where available; and raw provider
  timestamp/provenance, preserved even after any remediation -- and
  must never let a source timestamp stand in for FTA's own observation
  time, for any source, including the best-instrumented one. Every
  provider-stated publication timestamp must be persisted as a
  separate, explicitly-labelled, non-authoritative field. FX-56 must
  design for per-source timestamp remediation (BoC's mislabelled
  offset, BEA's named-zone ambiguity if BEA is ever reopened, ONS's
  date-midnight artifact if ONS is ever included) rather than assuming
  a single uniform parser suffices, and must preserve each source's own
  raw, as-received timestamp string even where a remediated value is
  also stored. FX-56 must also design an explicit future-dated-item
  quarantine capability, since at least one adopted-source-family
  member (BoC speeches) demonstrated this failure mode even though it
  is not itself adopted. **The same invariant governs any future
  historical backfill**: a source's own publication timestamp
  establishes documented publication timing only, never that FTA
  itself possessed the item at that historical moment -- a backfilled
  row's own availability field must honestly reflect the actual
  backfill/ingestion time, or be explicitly flagged as backfill-derived,
  never silently presented as equivalent to real-time prospective
  knowledge.
- **Identity semantics**: stable identity quality varies by source and
  must be modelled per-source, not assumed uniform -- GOV.UK's UUID and
  BoE's opaque GUID are decoupled from URL/slug; the Fed's, ECB's, and
  BoC's are URL-embedded and may change if a publisher re-slugs;
  StatCan's requires combining the URL with an intra-day sequence
  letter to recover ordering. FX-56 must not design a single canonical
  ID scheme that assumes URL stability across all sources.
- **Content retention allowed**: full-text/headline/metadata storage,
  and permanent retention, is affirmatively and clearly granted for
  every source in the adopted prospective set (public-domain or
  open-licence terms in every case except BoE, which restricts to
  non-commercial internal use -- compatible with FTA's current research
  scope but not with any future commercial posture without revisiting
  this ADR).
- **Required provenance fields**: FX-56 must capture, per item, at
  minimum: source/publisher identity, canonical URL/ID as provided by
  the source, the source's own stated publication timestamp (labelled
  non-authoritative), FTA's own first-seen/retrieval timestamp
  (authoritative), and a content-type discriminator (news vs. speech
  vs. minutes vs. interview) where a single feed serves several types
  (as ECB's does).
- **Unresolved historical limitations FX-56 must carry forward, not
  silently resolve**: most adopted prospective sources have shallow or
  no feed-based historical depth (Fed, ECB press feed, BoE, StatCan);
  a genuine historical backfill for these would require HTML retrieval
  against undocumented-but-predictable URL patterns, which this ADR
  explicitly leaves as an open decision for whoever scopes that work,
  not a default yes. **No source is currently ADOPT_HISTORICAL at all**
  (corrected by FX-55H): the ECB bulk speeches CSV is DEFER_HISTORICAL
  (author-attribution ambiguity) and GOV.UK's Search API is DEFER (own
  terms unverified) -- FX-56 has no adopted historical-backfill
  mechanism yet, prospective-only ingestion is the entire initial
  scope, and any historical work must reopen one of those two DEFER
  items first, then apply the same first-seen-vs-published-time
  separation to backfilled rows as to prospective ones.
- **Explicitly out of scope for FX-56 per this ADR and per FX-55's own
  authorization**: any commercial provider (class B), any DEFER-class
  news API/aggregator or FX-commentary source (classes C/D), BEA
  (corrected out of the adopted set by FX-55H -- DEFER, unresolved
  reuse rights), GDELT's bulk GKG channel (ADOPT_AUXILIARY_METADATA --
  rights-clear but metadata-only; an optional future complement, not
  part of this initial text-bearing scope), topic/relevance
  classification, deduplication, sentiment adoption, or any Decision/
  Risk Engine or dashboard consumption of this evidence.

**If FX-56 needs broader source coverage than the above** (e.g.
general financial-news breadth, or dedicated FX/macro commentary), it
must treat that as a reopening of this ADR's own DEFER list -- via the
prepared-but-unsent vendor clarification questions below -- not as an
implicit expansion of FX-55's own adopted set.

## Vendor clarification questions (PREPARED, NOT SENT)

Per this story's own explicit prohibition, none of the following were
sent to any vendor. They are recorded here, source-specific, so a
future authorized outreach does not need to re-derive them. (The full,
source-specific question sets produced by each research pass are
preserved in this ADR's own source-class sections above and are not
repeated in full here; this section lists only the single highest-
priority question per DEFER candidate, as a starting point for
whoever is authorized to send them. Three official-source questions
were added by FX-55H, for the three sources this correction pass moved
out of the adopted set.)

- **BEA**: does BEA assert any reuse/storage/automated-access
  position for `apps.bea.gov/rss/rss.xml` content -- e.g. a
  public-domain statement analogous to the Federal Reserve's -- beyond
  the citation-only guidance currently published?
- **ECB (bulk speeches CSV)**: does the Working/Occasional-Paper
  written-authorisation carve-out in the ECB's disclaimer extend to
  named, author-attributed speeches distributed via the bulk speeches
  CSV, or is that carve-out limited to formally published Working and
  Occasional Papers specifically?
- **GOV.UK (Search API)**: does the Search API's own use fall under
  the same Open Government Licence v3.0 / "any purpose, no agreement"
  terms published for the Content API, and does it carry any
  documented rate limit distinct from the Content API's 10 req/s?
- **Dow Jones/Factiva**: for an internal, non-redistributive FX/macro
  research and paper-trading platform, which Snapshots/Streams tier
  and "text mining for machine consumption" rights class applies, and
  what content retention period would govern it?
- **Financial Times**: does the Datamining Licence's destroy-on-
  termination obligation admit any exception for a permanently-retained
  internal research corpus, and does "data mining" extend to
  embeddings/model training?
- **Reuters/LSEG**: for a single-site, non-display internal-research
  deployment, what is the annual price and storage/retention grant for
  an MRN tier, separate from the free developer tier's explicit
  no-storage restriction?
- **Alpha Vantage**: does a solo/individual, non-commercial,
  never-published research system fall inside the free personal
  licence's "individual in nature" carve-out, and may returned content
  be permanently retained given the ToS's complete silence on storage?
- **Marketaux**: is there a data-specific API licence governing paid
  and free API access, distinct from the generic website Terms of Use
  currently in force -- and may retrieved records be permanently
  retained?
- **ING THINK**: which of the two conflicting primary documents
  governs automated use of RSS content -- the Terms of Use's
  affirmative licence grant, or the Disclaimer's "no purpose other than
  this site" prohibition and asserted database right?
- **FXStreet**: does the documented commercial News API admit an
  internal-research-only, non-redistributive licence tier, and at what
  price?
- **Action Forex**: does the publisher hold sub-licensable rights to
  the third-party bank research it syndicates, and does it permit
  automated internal storage of its own content specifically?

## Consequences

- **No production code, schema, migration, or dependency changes were
  made in FX-55, nor in FX-55H's own correction pass.** Both are
  documentation-only, as required.
- **FX-55H's own corrections are additive/corrective to this document
  in place, not a new adopted-source event.** No source's rights
  changed between FX-55 and FX-55H; what changed is this ADR's own
  prior misstatement of three admission verdicts (BEA, ECB's bulk
  speeches CSV, GOV.UK's Search API) and a PIT-anchor exception that
  should never have been granted (GOV.UK, BoC). The overall PARTIAL_GO
  verdict and the core Fed/ECB-press/BoE/GOV.UK-Content-API/StatCan/
  BoC-press-releases adopted set are unchanged.
- **No Decision/Risk Engine, dashboard, or Market Context change was
  made or is implied.** FX-61 (the eventual news visualization story)
  remains untouched and unscheduled.
- FX-EPIC-08 now has a documented, evidence-based starting scope for
  FX-56: an official-source-only prospective news ingestion surface,
  materially narrower than FX-EPIC-08's own originally-imagined
  commercial-provider breadth, mirroring FX-EPIC-07's own
  official-source-only precedent (FX-52A) after FX-52's commercial
  DEFER.
- Two operational alerts surfaced by this research fall **outside**
  FX-55's own scope but should be independently tracked: (1) BLS
  returned HTTP 403 on every path, including `robots.txt`, from this
  research environment -- FX-52A's already-adopted `bls.ics` calendar
  feed should be independently re-verified from the real production
  egress IP, since this story cannot determine whether the block is
  session-specific; (2) the Bank of Canada's `dc:date` mislabelling and
  its speeches feed's future-dated items independently reconfirm
  FX-52AH's own prior decision not to promote BoC RSS `dc:date` to an
  exact `released_time` -- that decision required no change and is
  reaffirmed, not reopened, by this ADR.
- A materially large set of DEFER-classified sources across all four
  classes now has documented, source-specific reopening conditions
  (this ADR's own Decision section and the vendor-clarification
  appendix above), so a future authorized outreach effort does not
  need to repeat this story's own research.
- This ADR does not modify, weaken, or reference the verdicts of ADR
  0003 or ADR 0004 except as cross-links; FX-49 and FX-52 remain DEFER,
  FX-53 remains BLOCKED, entirely independent of this document.

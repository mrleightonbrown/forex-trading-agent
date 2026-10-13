# ADR 0012: Structured Forecast Capture & Historical Provenance (FX-64)

## Status

**Accepted -- code/schema/tests complete, and real-data pilot examples
ACTIVATED against three real, independently-verified survey sources,
2026-10-13.**

## Context

FX-EPIC-09 Phase A (FX-62/62H/63/63H) gave FTA source identity,
attribution, and operational-reliability infrastructure. Gate G09
cleared Phase B: structured forecast **capture and provenance**, not
evaluation. FX-64 preserves what a forecaster actually asserted,
exactly as asserted, without adding unstated precision, retroactively
reinterpreting it, or pretending FTA possessed material before it
actually acquired it. FX-65 (outcome adjudication) is explicitly not
authorized by this story.

## Repository discovery findings

FX-62's `IntelligenceSource`/vintage/determinism contracts, FX-57's
`NewsItemVintage` basis-pinning, FX-58/59's canonicalization/semantic
append-only patterns, and FX-63's observation contracts were all
inspected. No existing abstraction represents a structured forecast:
`EconomicEventConsensusVintage` (FX-51) is a DIFFERENT concept --
market consensus tied to an `EconomicEventOccurrence` on the official
calendar, with no forecaster/publisher distinction, no target-
definition precision, and no production/retrospective split. FX-64
does not extend it, link to it, or duplicate it; the two remain
genuinely separate evidence layers, exactly as FX-58/59 remain
separate from FX-51-54's own calendar evidence. No backlog collision
was found. `domain.economic_indicator_registry`'s own small-curated-
registry pattern is reused directly for `forecast_target_registry`.

## Decisions

**1. `ForecastClaim` is minimal and immutable; everything that can
evolve or be corrected lives on the append-only `StructuredForecast
Vintage`** -- mirroring FX-62's `IntelligenceSource`/`SourceIdentity
Vintage` split exactly. `claim_key` is ALWAYS caller-supplied, built
from stable, source-backed logical identifiers -- never from the
forecast VALUE alone (Section 5's own explicit rule: two forecasters
predicting the same value are distinct assertions). A genuinely NEW
survey round is a DISTINCT `claim_key`, never a revision of an
earlier round's own claim -- proven with REAL data (see below): the
ECB SPF's own Q1 2025 and Q2 2025 rounds are two separate claims for
the IDENTICAL target and period, neither overwriting the other.

**2. Attribution structurally distinguishes forecaster from
publisher, and forbids inventing an identity the source itself does
not supply.** `ForecastAttributionKind` has three members: `NAMED_
INSTITUTION` (forecaster REQUIRED), `AGGREGATE_SURVEY_CONSENSUS`
(forecaster and anonymous-respondent id BOTH forbidden -- an
aggregate statistic has no personal originator), `ANONYMOUS_
RESPONDENT` (forecaster forbidden; a pseudonymous id is optional and
never invented). `publisher_source_key` is ALWAYS required and reuses
FX-62 identities verbatim, directly answering the architect's own
stated concern: the real pilot data shows the Bank of Canada and the
ECB as `publisher_source_key` for their own survey aggregates, with
`attribution_kind=AGGREGATE_SURVEY_CONSENSUS` and `forecaster_source_
key=None` -- neither institution is ever recorded as having
personally made the forecast.

**3. Exact target semantics are a small, curated registry, never a
bare `(family, year, value)` tuple.** `ForecastTargetDefinition`
carries `measurement_convention` as a first-class, comparable field
specifically so two genuinely different conventions for "the same"
family/jurisdiction are always two different target definitions --
proven with REAL verified data: `US_REAL_GDP_GROWTH_QOQ_SAAR`
(Philadelphia Fed SPF's own quarter-over-quarter annualized
convention) and `CA_REAL_GDP_GROWTH_YOY_YEAR_END` (the Bank of
Canada MPS's own year-over-year convention) coexist as genuinely
distinct `GDP_GROWTH`-family definitions, exactly the architect's own
named example. `supported_forecast_types` additionally ties each
definition to the forecast class(es) it actually admits (a policy-
rate LEVEL target supports only `NUMERIC_POINT`; a policy-rate
DECISION target supports only `CATEGORICAL_EVENT`) -- a mismatched
combination is rejected as `UNSUPPORTED_FORECAST_TYPE`, never
silently reinterpreted.

**4. Production PIT and retrospective research are separate
dimensions, with NO implicit fallback (Section 7's own single most
important requirement).** `StructuredForecastRepository` exposes TWO
differently-NAMED read paths -- `latest_production_observed_vintage_
as_of`/`list_production_observed_claims_as_of` (filter to `PRODUCTION_
OBSERVED` only, used by `GetForecastClaimAsOf`/`ListForecastClaimsAs
Of`) and `latest_vintage_as_of_for_research` (either provenance mode,
used ONLY by `GetRetrospectiveForecastResearchView`, which takes its
OWN `research_as_of` parameter, never named `as_of`) -- there is no
single method, and no boolean research flag on the production path,
that could let a caller reach a retrospective vintage by accident.
Proven with REAL data: all five pilot claims are `RETROSPECTIVE_
RESEARCH` (every one was acquired in October 2026, long after its own
real 2025 publication date) and are confirmed, by a dedicated real-
Postgres test, invisible to `latest_production_observed_vintage_as_
of` at any `as_of`, however far in the future.

**5. Historical determinism mirrors FX-62H's own corrected lesson
exactly: the full derived payload, not merely the value, is compared,
and the full evidence object (not merely its kind) is part of the
historical basis.** The determinism key is `(claim_key, algorithm_
version, evidence)`; the compared payload is `(forecast_type, target_
key, target_period, numeric_value, unit, categorical_outcome,
attribution)` -- EVERY one of Section 13's own named dimensions
(value, unit, period, target definition, attribution) is individually
tested and individually enforced. A genuinely different evidence
object (e.g. a source-issued correction, or FTA's own second,
independent re-check of a document) is a different basis and mints a
new append-only revision -- proven with a REAL within-claim
correction (see below) and with a synthetic `v1(A) -> v2(B) -> v1(A)`
/`v1(A) -> v2(B) -> v1(C)` worked-example test pair.

**6. Capture eligibility is checked FIRST, unconditionally, and a
rejected candidate is NEVER persisted.** `ValidateStructuredForecast
Candidate` is pure and side-effect-free: it attempts to build each
strict value object from the caller's own RAW candidate fields
(mirroring FX-56's own `NormalizedNewsObservation` flat-DTO
convention), and classifies any resulting construction failure into
one of `INSUFFICIENT_SPECIFICATION`/`AMBIGUOUS_ATTRIBUTION`/
`UNSUPPORTED_FORECAST_TYPE`/`UNVERIFIED_EVIDENCE` -- never letting a
malformed candidate reach the repository, proven by a dedicated real-
Postgres test that a rejected candidate writes nothing at all.

**7. No forecast-series linking table in this story.** Section 5
permits ("may be") an explicit forecast-series relationship for a
later, genuinely new prediction -- deliberately NOT built here,
favouring the smaller model the architect's own notes asked for. The
required invariant ("do not force all updated predictions into one
mutable claim") is satisfied structurally by distinct `claim_key`s
alone, proven with REAL data (the ECB SPF Q1/Q2 2025 example above);
an explicit series-linking entity is deferred to a future story if a
real need for cross-claim navigation emerges.

**8. No schema for evidence/attribution/target-period as separate
tables -- every FX-64 value object is flattened directly onto
`structured_forecast_vintages`**, mirroring FX-62's own flattening
convention. `publisher_source_key`/`forecaster_source_key` carry
real, nullable FKs onto `intelligence_sources` (FX-62 reuse, never a
new identity mapping); `(news_item_key, basis_revision_sequence)`
carries FX-59/62's own exact composite basis-pinning FK onto
`news_item_vintages`, automatically satisfied/skipped by Postgres
whenever either column is `NULL` (the external-document-evidence
case). No existing table is touched, mutated, or gains a column.

## Real-data pilot examples (Section 16)

All five examples below were independently verified against each
source's own public documentation immediately before implementation;
none is backdated to imply earlier FTA knowledge -- every one carries
its own real `availability` (FTA's actual registration instant,
2026-10-13) alongside its own real, distinct `original_publication_
at`/`publisher_declared_publication_at`.

1. **ECB Survey of Professional Forecasters, Q1 2025** (published
   2025-01-31): HICP annual-average inflation forecast for 2025 =
   2.1%, 60 respondents. `AGGREGATE_SURVEY_CONSENSUS`, publisher
   `EUROPEAN_CENTRAL_BANK` (FX-62's own real identity, reused
   verbatim).
2. **ECB SPF, Q2 2025** (published 2025-04-22): HICP forecast for
   2025 = 2.2%, 54 respondents -- a genuinely DISTINCT claim from #1
   (Section 5's own "separate forecast issue" rule, proven with real
   data, not merely a synthetic test).
3. **Bank of Canada Market Participants Survey, Q1 2025** (published
   2025-04-28; conducted 2025-03-13 to 2025-03-20): median overnight
   rate forecast of 2.25% for the scheduled 2025-12-10 Governing
   Council decision. `POLICY_MEETING` period, independently grounded
   by the Bank's own fixed announcement-date press release for that
   decision. Publisher `BANK_OF_CANADA`.
4. **The SAME BoC MPS Q1 2025 document**: median real GDP growth
   forecast of 1.0% year-over-year as of the end of 2025 -- a
   DIFFERENT target (GDP_GROWTH, not POLICY_RATE) supported by the
   SAME evidence document, proving one evidence reference can
   legitimately support more than one claim.
5. **A CLEARLY LABELED SYNTHETIC example** (`claim_key` prefixed
   `SYNTHETIC-ILLUSTRATIVE`, never presented as real): a within-claim
   correction -- an initial transcription (2.0%) corrected, under
   DIFFERENT evidence, to 2.2% after a second independent review.
   Demonstrates the append-only correction mechanics this story's own
   tests cannot exercise with real data (no real documented case of a
   source correcting an already-published figure was found).

`scripts/import_pilot_structured_forecasts.py` records all five,
idempotently -- confirmed via three repeated real runs, the last two
reporting `UNCHANGED`/`already recorded, skipping`.

## Consequences

- FX-65 (outcome adjudication) is explicitly NOT authorized by this
  story; FX-66/FX-67 remain behind their own future gates.
- **Architectural gap flagged, per Section 21's own explicit
  instruction**: no real `PRODUCTION_OBSERVED` pilot example exists.
  FX-64 authorizes no live/contemporaneous acquisition adapter, so
  every real pilot example is, honestly, `RETROSPECTIVE_RESEARCH` --
  acquired today, long after its own real publication. `PRODUCTION_
  OBSERVED` mechanics are proven correct by synthetic unit and real-
  Postgres integration tests instead, never by a fabricated "FTA knew
  this contemporaneously" claim. A future forward-looking acquisition
  story (explicitly out of scope here) would be needed to produce a
  genuine `PRODUCTION_OBSERVED` example.
- The `forecast_target_registry` is deliberately narrow (six
  definitions, three real surveys) -- a future story extending it to
  new variable families or jurisdictions should verify each new
  definition against its own primary source documentation before
  admission, exactly as this story did.

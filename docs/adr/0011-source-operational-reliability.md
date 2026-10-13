# ADR 0011: Source Operational Reliability (FX-63)

## Status

**Accepted -- code/schema/tests complete, and real-data instrumentation
ACTIVATED against all six live sources, 2026-10-13.**

## Context

FX-62 gave FTA a durable identity and attribution registry -- WHO is
responsible for a piece of evidence. It answers nothing about HOW
reliably FTA itself has been able to retrieve that evidence: how
often an acquisition attempt against a technical feed succeeds,
fails, times out, or needs a retry, and how FX-56/57's own already-
durable `NewsItem`/`NewsItemVintage` history behaves over time
(revisions, withdrawals, corrections). FX-63 is Phase A's second
story, adding exactly that operational-reliability layer -- still
explicitly NOT a credibility, trust, or forecast-accuracy score.

## Discovery findings

Before writing any code, the existing ingestion stack
(`infrastructure.news_sources.http_fetch`, the six adapters,
`IngestNewsSourceOnce`, the six `scripts/ingest_*.py` entrypoints) was
inspected in full. Findings:

- `http_fetch.fetch_text` already retries a transport failure/429/5xx
  internally, but no attempt -- successful or not, including an
  internal retry -- was ever durably recorded anywhere; only the
  FINAL outcome of one logical call was visible to its own caller.
- `IngestNewsSourceOnce` catches a channel's own `NewsSourceUnavailable
  Error` and collects it into an in-memory `NewsIngestionResult.errors`
  tuple, which every `scripts/ingest_*.py` entrypoint only ever
  **prints** -- nothing before this story persisted it.
- A source-side parse failure (`MalformedNewsFeedError`, etc.) is
  re-raised by each adapter AS a `NewsSourceUnavailableError`,
  indistinguishable from a transport failure at that boundary without
  guessing from a string message -- which this story refuses to do.
- **Conclusion: zero durable historical attempt-level evidence exists
  for any of the six sources.** Per the story's own explicit
  instruction, no historical attempt record is fabricated; acquisition
  coverage for any window before this story's own instrumentation
  began recording is honestly `UNAVAILABLE`.
- Content-level evidence (items/revisions/withdrawals) is, by
  contrast, ALREADY fully durable -- a successfully parsed and
  persisted `NewsItemVintage` IS the record of a successful fetch and
  parse. No second, independently-maintained "successful parse"
  observation is needed for that fact.

## Decisions

**1. Two genuinely different evidence bases, never merged into one
blanket judgment.** Acquisition metrics (attempts/successes/failures/
retries) come ONLY from `SourceOperationalObservation` rows this
story itself records, going forward. Content metrics (items/
revisions/withdrawals/corrections) come ONLY from FX-56/57's own
already-durable evidence. A profile's `acquisition.coverage` and
`content.coverage` are independent, metric-specific judgments
(`OperationalMetricCoverage`: `OBSERVED`/`PARTIAL`/`UNAVAILABLE`/
`NOT_APPLICABLE`) -- a source can have complete content history and
zero acquisition-reliability history simultaneously, and both are
reported honestly side by side.

**2. Minimal, additive, forward-looking instrumentation at the
narrowest existing boundary -- no rewrite of FX-57's approved
ingestion behaviour.** `http_fetch.fetch_text` gained ONE new optional
parameter, `on_attempt: OnAttemptFn | None = None`, invoked after
EVERY attempt it makes (success, a retried failure, or the final
failure that raises) -- mirroring the EXACT precedent the module's
own `before_attempt` hook already established. `None` (every existing
caller's own default) preserves byte-for-byte existing behaviour; the
six existing adapters were extended with one new optional constructor
parameter each (`on_acquisition_attempt`), forwarded unchanged into
their own existing `fetch_text` call. Zero behavior change for any
caller that does not opt in -- proven by every pre-existing adapter/
`http_fetch` test passing unmodified.

**3. Technical feed identity, never publisher judgment.**
`SourceOperationalObservation.source_key` is ALWAYS the technical
feed FTA actually used (e.g. `"BOE"`), reusing FX-56/57's own
`news_source_registry` keys verbatim -- never the resolved publisher's
own FX-62 identity. An HTTP 403, timeout, or network failure is
recorded against the technical feed; `GetSourceOperationalProfileAsOf`
resolves a descriptive publisher association separately, at most once
per profile (against the source's own most-recently-first-seen item),
reusing FX-62's `ResolvePublisherForNewsItemAsOf` -- never substituted
for the technical feed's own identity when unresolved.

**4. Deliberately NO foreign key from `source_operational_observations`
onto `intelligence_sources`.** Acquisition instrumentation must keep
recording regardless of whether FX-62's own bootstrap has registered
this technical feed yet -- proven by a dedicated integration test.
FX-62 identity/attribution reuse happens entirely at READ time, in
`GetSourceOperationalProfileAsOf`, never at write time.

**5. Stable, caller-minted idempotency key, never `(source, timestamp)`
alone.** `(source_key, run_id, attempt_number)` is the natural key.
`run_id` is minted fresh, once per logical acquisition run (one call
to fetch one channel), inside each adapter's own fetch method (`bind_
acquisition_recorder`, `infrastructure.news_sources.http_fetch`);
`attempt_number` is 1-based and counts every attempt WITHIN that run,
including internal retries. A duplicate delivery of the exact same
`(source_key, run_id, attempt_number)` is always a no-op, never
compared for content equality -- there is no revision/correction
concept here at all, unlike every FX-56/58/59/62 vintage table.

**6. No historical attempt data fabricated; "zero recorded attempts"
is never silently reported as a 0% success rate.** `AcquisitionMetrics.
success_rate` is `None`, not `0`, whenever `recorded_attempts == 0`.
Acquisition coverage for a window is `OBSERVED` only when
instrumentation's own earliest PIT-filtered observation is at or
before that window's own `window_start`; `PARTIAL` when instrumentation
started partway through the window; `UNAVAILABLE` when no observation
exists at or before the requested `as_of` at all. This last check is
itself PIT-filtered (`earliest_observation_availability_for_source`
takes `as_of`) -- a future attempt must never leak into a historical
coverage judgment about an earlier instant, caught by a failing unit
test during implementation (see Deviations below).

**7. Content metrics reuse FX-56/57's own vintage shape exactly, with
no new persistence.** `GetSourceOperationalProfileAsOf` reads via two
NEW batch methods added directly to `SqlAlchemyNewsRepository`
(`list_item_keys_for_source`, `list_vintages_for_items`) -- NOT a
widening of the global `NewsRepository` Protocol, mirroring FX-60H's
own narrow-local-Protocol precedent exactly. A correction is
distinguished from an ordinary revision only via `NewsSourceRevision
Fact.kind == CORRECTION`/`WITHDRAWAL` -- reusing FX-56's own existing
enum verbatim rather than inventing a parallel one; an ordinary
revision with no such metadata is `unclassified`, never silently
counted as an error.

**8. No reputation, credibility, weighting, or trading signal anywhere
in this layer.** `SourceOperationalProfile` structurally has no
`reputation_score`/`trust_score`/`source_weight`/`forecast_accuracy`/
`trading_confidence`/`market_impact_score` field, and no overall PASS/
FAIL judgment. `success_rate` is explicitly documented as an FTA
acquisition metric, never a publisher availability score.

## Real-data instrumentation result

The six real ingest scripts (`scripts/ingest_*.py`) were extended with
this story's own `on_acquisition_attempt` wiring and RUN LIVE against
all six real sources. Result: 33 genuine acquisition-attempt
observations recorded, including one GENUINE `TIMEOUT` on StatCan's
own `statcan_prices` channel, retried once, succeeding on the second
attempt (attempt_number 1 then 2, same `run_id`) -- an entirely
organic, non-fabricated confirmation that attempt/retry-level
instrumentation works correctly in production. The live run also
discovered 36 genuinely new real-world items published since FX-62's
own last bootstrap (FED +4, ECB +1, BOE +17, GOVUK_HMT +5, STATCAN +9,
BOC +0; plus 6 GOV.UK revisions), growing the real corpus from 358 to
394 `NewsItem`s -- `scripts/bootstrap_source_registry.py` was re-run
afterward and attributed all 36 new items' own `PUBLISHER` role
correctly (36 new `CONFIRMED` attribution vintages, zero `UNRESOLVED`),
exactly matching the real operational flow this story measures.

## Consequences

- FX-64 through FX-67 remain behind Gate G09, unaffected by this
  story.
- Acquisition-reliability history before 2026-10-13 is honestly
  `UNAVAILABLE` for all six sources -- this is a genuine historical
  gap, not a defect, and is reported as such rather than fabricated.
- A future story adding attempt-level granularity for CONTENT-
  VALIDATION or PARSING failures (distinct from today's transport-
  level `HTTP_FAILURE`/`TIMEOUT`/`NETWORK_FAILURE` taxonomy) would
  need its own narrow instrumentation pass through each adapter's own
  parse step -- deliberately deferred here, not fabricated.

## Deviations found during implementation

**The acquisition-coverage check initially compared a GLOBALLY
earliest-ever-recorded observation against a requested `window_start`,
ignoring the profile's own `as_of`.** A unit test for "observation
after T is excluded" caught this: a future attempt (not yet recorded,
as of an earlier historical `as_of`) was leaking into a coverage
judgment about that earlier instant, reporting `PARTIAL` instead of
the correct `UNAVAILABLE`. Fixed by adding `as_of` to `earliest_
observation_availability_for_source`'s own signature, filtering to
`availability <= as_of` before taking the minimum -- restoring the
historical-immutability guarantee every other `*_as_of` method in
this codebase already provides. No real data was ever written or read
incorrectly under the old signature; this was caught and corrected
entirely within application-layer logic before any production
profile was computed.

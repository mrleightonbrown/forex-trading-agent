# ADR 0006: Multi-Channel News Provenance Model (FX-57E0)

## Status

**Accepted -- 2026-10-05.**

Supersedes a durable architecture assumption introduced in FX-57B and
hardened (incorrectly, as this ADR establishes) in FX-57CH: that a
`NewsItemVintage` is observed through at most ONE `source_channel` "at
a time," and that the same external identity appearing under a
different channel within one ingestion run is inherently ambiguous
and must fail closed. Live Statistics Canada research (FX-57E, paused
for this exact reason) proved that assumption false for at least one
real, adopted-shape source.

## Context

FX-57B introduced `source_channel` (a stable, provider-neutral
technical identifier for which configured feed/endpoint produced an
item) as a required, singular field on `NormalizedNewsObservation`/
`NewsSourceFetchOutcome`/`NewsItemVintage`, after ECB proved it was a
genuinely separate concept from `source_content_type`. FX-57CH then
added a hard guard (`CrossChannelIdentityCollisionError`): if the SAME
`(source_key, external_item_id)` was observed under two DISTINCT
channels within one `IngestNewsSourceOnce` run, the whole run failed
closed, on the reasoning that a single-valued `source_channel` per
vintage cannot represent simultaneous multi-channel membership without
inventing a false temporal transition (`revision 0 channel=A,
revision 1 channel=B` when the source never actually transitioned
between the two).

That reasoning's CONCLUSION (don't invent a false transition) was
correct; its PREMISE (simultaneous multi-channel membership is always
ambiguous/invalid) was not. FX-57E's own pre-implementation research
for Statistics Canada's "The Daily" feeds -- four adopted subject
feeds (prices, labour, economic accounts, international trade) --
found, via a live, reproducible, two-pass pairwise comparison of
every adopted feed's own Atom entry ids:

| Pair | Overlap found |
|---|---|
| prices ∩ labour | 0 |
| prices ∩ economic_accounts | 2 |
| prices ∩ international_trade | 3 |
| labour ∩ economic_accounts | 2 |
| labour ∩ international_trade | 0 |
| economic_accounts ∩ international_trade | 3 |

Every overlapping pair was confirmed to be the EXACT SAME Atom `<id>`,
SAME title, SAME content -- e.g. `dq260903a` ("Canadian international
merchandise trade, July 2026") appears, identically, in BOTH the
`prices` feed AND the `international_trade` feed. Statistics Canada
genuinely, legitimately cross-lists some Daily releases under more
than one of its own subject feeds simultaneously -- this is not
source drift, a parsing bug, or a feed-reliability issue; it reflects
StatCan's own subject taxonomy, where one release can substantively
be about more than one subject at once (a trade release is reasonably
both a "prices" and an "international trade" fact).

Per FX-57E's own spec and CLAUDE.md's "stop before implementing an
architectural change" discipline, FX-57E paused at this exact finding
rather than picking an arbitrary resolution (choosing one channel,
concatenating channel names, minting separate items, or silently
dropping a membership -- all explicitly rejected as unsafe guesses).
This ADR records the resolution; FX-57E0 implements it.

## Decision

**Identity is unchanged**: `(source_key, external_item_id)` remains
the sole identity key. Channel is NEVER part of identity; no separate
`NewsItem` is ever minted per channel.

**`source_channel` keeps its exact prior meaning, narrowed in
wording**: it names the channel through which FTA received the
observation that produced THIS PARTICULAR vintage. It remains
singular (one HTTP response belongs to one configured channel) and
required.

**A new field, `NewsItemVintage.observed_source_channels: tuple[str,
...]`**, carries the canonical (sorted, deduped), CUMULATIVE,
non-empty set of every channel FTA has observed this item through by
this vintage's own `availability`. It always contains this vintage's
own `source_channel`. Channel membership is MONOTONIC knowledge: it
only ever grows. An item's disappearance from one feed proves nothing
about whether its publisher classification changed, so no code path
anywhere in this codebase ever removes a channel from this set.

**Modeled-fact equality changes**: the bare `source_channel` no
longer participates in the comparison that decides `CREATED`/
`REVISION_ADDED`/`UNCHANGED` -- `observed_source_channels` does
instead. Re-observing an identity through an ALREADY-known channel,
with otherwise-identical content, remains `UNCHANGED` (the cumulative
set is unchanged). Observing it through a genuinely NEW channel mints
a `REVISION_ADDED` even when every other field is byte-identical,
because FTA's own cumulative knowledge of this item's provenance just
grew -- itself a fact worth recording, on the same discipline as any
other content change. This is NEVER documented, surfaced, or
interpreted as "the publisher reclassified the item at this instant"
-- it is FTA learning an ADDITIONAL, independently-true fact about an
item it already knew.

**`CrossChannelIdentityCollisionError` is retired** (removed, not
kept as a parallel concept -- CLAUDE.md's own discipline against
unused/overlapping abstractions). The common orchestration
(`IngestNewsSourceOnce`) now groups a run's own whole-run observation
list by external identity: a DISTINCT channel whose own NON-CHANNEL
facts agree with every other channel already seen for that identity
is genuine additional provenance and is KEPT (both observations reach
`RecordNewsObservation`, which performs the cumulative merge above).
Only a genuine disagreement on a NON-CHANNEL fact -- regardless of
whether the colliding observations share a channel or not -- still
fails the WHOLE run closed, via the existing (broadened)
`ConflictingDuplicateExternalIdError`: FTA cannot safely tell, from
one run alone, whether that disagreement is a genuine source update
between requests, a feed inconsistency, or a parser bug.

**Processing order**: once a run is confirmed internally consistent,
surviving observations are persisted in `observed_at` ascending order
(ties broken by original configured-fetch order, never by channel
name), so FTA's own cumulative channel knowledge accumulates in the
actual order it was learned -- never the order a dict/set happened to
iterate.

**This is a provider-neutral domain/application change, not a
StatCan-specific one.** No `statcan_subjects`/`statcan_channels`/
`is_cross_listed` concept exists anywhere in the domain. Statistics
Canada is merely the first real adopted source to demonstrate the
general multi-channel-provenance case; Fed/ECB/BoE/GOV.UK are
unaffected in practice today (none of their own currently-adopted
feeds have ever been found to cross-list the same identity under
genuinely-agreeing non-channel facts), but the model is now capable of
representing it correctly for any of them, or any future source, if
it is ever discovered.

## Consequences

- `news_item_vintages` gains a `NOT NULL` JSONB column, `observed_
  source_channels`, backfilled CUMULATIVELY for every existing row
  (migration `73b1423a5949`) -- never merely `[that row's own
  source_channel]`, since a genuinely sequential cross-run channel
  change (always legal, before and after this ADR) could in principle
  have left a multi-channel history even though no currently-stored
  row does.
- `RecordNewsObservationResult`/`NewsIngestionResult` each gain a new,
  additive counter (`channel_added`/`channel_memberships_added`)
  distinguishing "FTA learned a new channel" from an ordinary content
  revision, without removing or redefining any existing counter.
- Fed's and BoE's own existing cross-channel regression tests were
  corrected: Fed's own case still fails closed (its `source_content_
  type` genuinely differs per channel, so a real conflict remains);
  BoE's own benign-overlap case (identical content across channels)
  now succeeds, merged, rather than failing. Both adapters' own
  `live_source` tests keep actively re-checking their own currently-
  observed channel-disjointness as a drift DIAGNOSTIC (Section 23) --
  common ingestion correctness no longer depends on that disjointness
  holding.
- FX-57E (Statistics Canada ingestion itself) remains paused pending
  this ADR's own review and FX-57E0's own sign-off; it resumes as a
  separate, later story, building the StatCan adapter on top of this
  now-corrected model.

## Alternatives considered and rejected

- **Pick one channel, discard the others**: silently loses real
  provenance FTA actually observed; arbitrary and unjustifiable to a
  future reader of the stored history.
- **Concatenate channel names into one string**
  (`"statcan_prices+statcan_international_trade"`): an unbounded,
  unparseable, non-canonical identifier that breaks every existing
  channel-equality comparison and display convention.
- **Add channel to identity** (mint a separate `NewsItem` per
  channel): directly contradicts FX-56's own "one external identity,
  one item" invariant, and would make the SAME real-world release
  appear as two unrelated items in every evidence query.
- **Keep `CrossChannelIdentityCollisionError` and add a StatCan-
  specific exemption**: reintroduces exactly the kind of source-
  specific policy embedded in provider-neutral application code this
  project has consistently avoided (see `domain.news_source_registry`
  and every prior FX-57 story's own "no source-specific policy in the
  domain" discipline); also does not generalize to a future source
  that discovers the same legitimate shape.

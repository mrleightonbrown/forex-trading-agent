"""FX-45: pure point-in-time state selection over an already-fetched
policy-rate vintage history -- the domain-layer answer to "which
decision governs this currency's policy rate at instant T," kept
deliberately split into TWO distinct notions that must never
substitute for one another (FX-45 section 1, building directly on the
`released_at != effective_at` distinction FX-44H/FX-44H.1 established):

- ANNOUNCED (market-known): the latest decision the market could know
  about at T, gated on `released_at <= T` -- the same filter
  `MacroObservationRepository.latest_available_as_of` already applies
  at the repository layer, reimplemented here as a pure function over
  an in-memory sequence because FX-45's differential feature needs to
  evaluate MULTIPLE point-in-time queries (current, previous, ~3
  months back, ~6 months back) against one already-fetched, already
  research-readiness-checked history, not re-query the database once
  per instant.
- EFFECTIVE (operationally in force): the latest decision whose
  `effective_at` is populated AND `<= T`. Deliberately excludes any
  vintage with `effective_at is None` from consideration -- FX-45
  section 6 is explicit that the effective-rate feature must be
  UNAVAILABLE, never guessed, when a source only establishes a
  release/announcement fact and no separately-verified effective date.
  This is why `announced_state_as_of` and `effective_state_as_of` are
  two distinctly-named functions rather than one function taking a
  mode flag: a caller cannot accidentally pass the wrong mode and
  silently get the other semantics.

FX-45H hardening (two real bugs found after FX-45 shipped, both fixed
here):

1. **Point-in-time safety for EFFECTIVE.** The original `effective_
   state_as_of` selected the latest `effective_at <= T` WITHOUT also
   requiring `released_at <= T` -- wrong: a REVISION can carry an old
   `effective_at` but a `released_at` that is itself still in the
   future relative to `T` (e.g. a retroactively-disclosed or corrected
   effective date, published later than the date it claims to
   describe). Such a revision must stay invisible before its own
   `released_at`, exactly like ANNOUNCED already required. `known_
   as_of` below is the single shared PIT filter (`released_at <= T`)
   every function in this module now applies before doing anything
   else with a vintage -- a fact that was never released by `T` cannot
   affect ANY point-in-time query evaluated at `T`, no matter how
   favorably its other dates line up.

2. **Fail closed on an intervening decision with unknown effective
   timing.** Even after (1), a second gap remained: if an OLD decision
   has a populated, PIT-safe `effective_at`, but a NEWER decision has
   already been released (`released_at <= T`) and its own `effective_
   at` is not yet established, the old decision's rate cannot be
   defensibly reported as "the" effective state at `T` -- the newer
   decision might already have taken effect by `T` for all this code
   can verify, or might not have; either way, the true effective state
   is genuinely unresolved until whichever decision governs `T` gets a
   defensibly-established `effective_at` of its own. `effective_state_
   as_of`/`previous_effective_state` both detect this (by `observation_
   period` -- the only ordering axis available for a vintage that has
   no `effective_at` to order by) and return `None` rather than
   silently keeping the old decision's rate. This is a distinct
   failure mode from "no candidate exists at all"; both currently
   collapse to `None` at this layer (the application layer's `Differ
   entialUnavailable.reason` text covers both possibilities in its
   wording -- see `application.use_cases.compute_policy_rate_
   differential`).

Neither function consults `domain.research_readiness` itself -- this
module answers "what does the stored history say," not "is it safe to
trust." Every caller MUST run `require_research_ready_interval` (or
`is_research_safe` per-vintage) over the relevant window BEFORE
treating either function's result as research-safe; see
`application.use_cases.compute_policy_rate_differential`.
"""

from collections.abc import Sequence
from datetime import datetime

from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.timestamps import UtcTimestamp


def _latest(
    dated: list[tuple[datetime, int, MacroObservationVintage]],
) -> MacroObservationVintage | None:
    if not dated:
        return None
    return max(dated, key=lambda entry: (entry[0], entry[1]))[2]


def known_as_of(
    vintages: Sequence[MacroObservationVintage], as_of: UtcTimestamp
) -> tuple[MacroObservationVintage, ...]:
    """Every vintage that was actually KNOWABLE at `as_of`: `released_at
    <= as_of`, regardless of its own `observation_period`/`effective_
    at`. The point-in-time foundation every other function in this
    module builds on (FX-45H section 1/3) -- a vintage that had not yet
    been released cannot affect ANY point-in-time query evaluated
    before its own release, no matter how favorably its other dates
    might otherwise line up. Order is preserved from the input.

    Safe to use as a pre-filter for `domain.research_readiness.
    require_research_ready_interval`'s own `full_series_history`
    argument too: unlike filtering by `observation_period` to an
    interval (which that function's own docstring warns can silently
    drop the carry-in state), this filters on a completely different
    axis (`released_at`) that this registry's real data keeps within
    about a day of `observation_period` in either direction -- far
    inside both the multi-month lookbacks and the readiness window's
    own margin -- so a genuine carry-in candidate is never excluded by
    this filter in practice, only a vintage that truly was not yet
    known.
    """
    return tuple(v for v in vintages if v.released_at.value <= as_of.value)


def _has_unresolved_later_decision(
    known: Sequence[MacroObservationVintage],
    candidate_observation_period: datetime,
    *,
    before: datetime | None = None,
) -> bool:
    """FX-45H section 2: does `known` (already PIT-filtered to `released_
    at <= as_of`) contain a vintage that represents a genuinely LATER
    policy decision than `candidate_observation_period` -- ordered by
    `observation_period`, the only axis available for a vintage that
    has no `effective_at` to order by -- whose own `effective_at` is
    not populated? `before`, when given, additionally bounds the
    search to decisions strictly earlier than it (used by `previous_
    effective_state` to only consider decisions between the found
    predecessor and `current`, never `current` itself or anything at
    or after it)."""
    for v in known:
        if v.effective_at is not None:
            continue
        if v.observation_period.value <= candidate_observation_period:
            continue
        if before is not None and v.observation_period.value >= before:
            continue
        return True
    return False


def announced_state_as_of(
    vintages: Sequence[MacroObservationVintage], as_of: UtcTimestamp
) -> MacroObservationVintage | None:
    """The latest policy-rate decision the market could KNOW about at
    `as_of`: the vintage with the greatest `released_at <= as_of`,
    tie-broken by `revision_sequence` descending (the same convention
    FX-41H established for the repository's own point-in-time query
    methods). `None` if no vintage in `vintages` has `released_at <=
    as_of` at all.

    A decision never becomes visible before its OWN `released_at` --
    including a decision whose `effective_at` is still in the future:
    per FX-45 section 5, "if a future-effective rate has already been
    announced, it IS the announced policy rate even though it is not
    yet the effective rate. This is deliberate." (FX-45H section 3
    reconfirms this must keep holding: a released-but-future-effective
    decision stays fully visible here -- only `effective_state_as_of`
    treats its `effective_at` specially.)
    """
    dated = [(v.released_at.value, v.revision_sequence, v) for v in known_as_of(vintages, as_of)]
    return _latest(dated)


def effective_state_as_of(
    vintages: Sequence[MacroObservationVintage], as_of: UtcTimestamp
) -> MacroObservationVintage | None:
    """The policy rate OPERATIONALLY IN FORCE at `as_of`: the vintage
    with the greatest `effective_at <= as_of` among those whose
    `effective_at` is actually populated, tie-broken by `revision_
    sequence` descending -- restricted throughout to `known_as_of(
    vintages, as_of)` (FX-45H section 1: a vintage not yet released by
    `as_of` can never govern a query evaluated at `as_of`, even if its
    `effective_at` would otherwise qualify).

    `None` in three distinct cases, deliberately not told apart at this
    layer (all mean "do not report an effective rate"): no vintage has
    a populated, PIT-safe `effective_at <= as_of` at all; every
    candidate vintage exists but simply lacks a verified effective date
    (FX-45 section 6: never fall back to `released_at`/`observation_
    period` for such a vintage); or a newer decision has already been
    released by `as_of` with its OWN `effective_at` still unestablished
    (FX-45H section 2) -- in which case reporting the OLDER decision's
    rate would silently ignore that a more recent, already-known change
    might already govern `as_of`, which this function refuses to guess
    either way.
    """
    known = known_as_of(vintages, as_of)
    dated = [
        (v.effective_at.value, v.revision_sequence, v)
        for v in known
        if v.effective_at is not None and v.effective_at.value <= as_of.value
    ]
    candidate = _latest(dated)
    if candidate is None:
        return None
    if _has_unresolved_later_decision(known, candidate.observation_period.value):
        return None
    return candidate


def previous_announced_state(
    vintages: Sequence[MacroObservationVintage], current: MacroObservationVintage
) -> MacroObservationVintage | None:
    """The vintage that was the announced state immediately BEFORE
    `current` became the announced state -- the latest vintage with
    `released_at` strictly earlier than `current.released_at`. `None`
    if `current` is (as far as `vintages` shows) the earliest
    announced state on record.

    No separate PIT filter is needed here: any candidate this finds
    has `released_at < current.released_at`, and `current` itself is
    only ever passed in already having satisfied `released_at <=
    as_of` (it came from `announced_state_as_of`) -- so every candidate
    is transitively `released_at <= as_of` too, automatically.
    """
    dated = [
        (v.released_at.value, v.revision_sequence, v)
        for v in vintages
        if v.released_at.value < current.released_at.value
    ]
    return _latest(dated)


def previous_effective_state(
    vintages: Sequence[MacroObservationVintage],
    current: MacroObservationVintage,
    as_of: UtcTimestamp,
) -> MacroObservationVintage | None:
    """The vintage that was the effective state immediately BEFORE
    `current` became the effective state -- the latest OTHER vintage
    with a populated `effective_at` strictly earlier than `current.
    effective_at`. `None` if `current.effective_at` is itself `None`
    (a caller should never pass such a `current` here -- only a
    vintage `effective_state_as_of` returned, which is guaranteed to
    have `effective_at` populated) or if `current` is the earliest
    effective state on record.

    FX-45H section 2: takes `as_of` explicitly (unlike `previous_
    announced_state`, which does not need it -- see that function's own
    docstring for why ANNOUNCED's single-axis ordering makes the
    distinction moot there). EFFECTIVE's two axes (`released_at` for
    knowability, `effective_at` for operational force) do NOT stand in
    the same transitive relationship: a vintage with an early `
    effective_at` can still have a late `released_at` (a retroactively-
    disclosed effective date), so "previous" must apply the identical
    `known_as_of(vintages, as_of)` PIT filter `effective_state_as_of`
    applies for `current`, using the SAME `as_of` -- not a filter
    derived from `current.effective_at`, which would answer a different
    question (point-in-time safety is about what `as_of` could know,
    not about `current`'s own timeline). Also applies the same
    unresolved-later-decision check as `effective_state_as_of`, bounded
    to decisions strictly between the found predecessor and `current`
    itself: an intervening decision released by `as_of` whose own
    `effective_at` is unestablished makes it impossible to say whether
    THAT decision, not the found predecessor, was actually in force
    immediately before `current` took hold.
    """
    if current.effective_at is None:
        return None
    known = known_as_of(vintages, as_of)
    dated = [
        (v.effective_at.value, v.revision_sequence, v)
        for v in known
        if v.effective_at is not None and v.effective_at.value < current.effective_at.value
    ]
    candidate = _latest(dated)
    if candidate is None:
        return None
    if _has_unresolved_later_decision(
        known,
        candidate.observation_period.value,
        before=current.observation_period.value,
    ):
        return None
    return candidate

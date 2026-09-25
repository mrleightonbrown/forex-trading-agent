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
   `released_at`, exactly like ANNOUNCED already required.

2. **Fail closed on an intervening decision with unknown effective
   timing.** Even after (1), a second gap remained: if an OLD decision
   has a populated, PIT-safe `effective_at`, but a NEWER decision has
   already been released (`released_at <= T`) and its own `effective_
   at` is not yet established, the old decision's rate cannot be
   defensibly reported as "the" effective state at `T` -- the newer
   decision might already have taken effect by `T` for all this code
   can verify, or might not have; either way, the true effective state
   is genuinely unresolved until whichever decision governs `T` gets a
   defensibly-established `effective_at` of its own.

FX-45H.1 hardening (three further real gaps found after FX-45H
shipped, none of them requiring any new external research -- all
fixed by correcting this module's own logic):

3. **A provisional `released_at` is a proxy, not proof.** FX-45H's own
   `known_as_of` (`released_at <= T`) was used both for state selection
   AND to pre-filter the history handed to `domain.research_readiness.
   require_research_ready_interval`. That conflates two different
   questions. For a PROVISIONAL vintage (`released_at_is_verified=
   False` and `released_at_is_conservative_bound=False` -- FX-43H),
   `released_at` may be nothing more than a same-day proxy (e.g. "the
   date a provider's raw series shows a value change"), not a verified
   knowability instant. Treating `released_at > T` as PROOF such a row
   was not yet public at `T` is exactly the kind of unverified
   assumption this codebase's fail-closed philosophy exists to forbid
   -- the row might genuinely have been known earlier; the proxy simply
   does not say either way. State selection may still use this
   mechanical filter (it must pick SOME candidate, and `released_at` is
   the only field available to order by for ANNOUNCED), but research
   READINESS must never have its input pre-narrowed by it: `require_
   research_ready_interval` needs the series' COMPLETE stored history
   (exactly as FX-44H's own docstring already required) so a relevant
   provisional row is examined and correctly fails the interval closed,
   rather than silently vanishing from consideration because its own
   unverified proxy happened to read later than `T`. See `application.
   use_cases.compute_policy_rate_differential`, which now passes the
   COMPLETE history to the readiness check, never a PIT-pre-filtered
   view. `known_as_of` is renamed `_released_at_on_or_before` and made
   private specifically so it cannot be reached for that purpose again
   by accident -- see its own docstring.

4. **ANNOUNCED state selects by observation identity, not raw
   `released_at`.** `announced_state_as_of` picked "the vintage with
   the greatest `released_at <= T`" outright -- wrong once revisions
   exist: a REVISION published later for an OLDER observation_period
   (a correction to a stale figure) has a `released_at` that can
   exceed a genuinely newer, unrevised observation's `released_at`,
   which would wrongly resurrect the older observation as "current"
   merely because it was republished more recently. The correct
   two-step selection: among vintages knowable at `T`, find the latest
   `observation_period` with any representative at all, THEN -- among
   vintages sharing that one observation_period -- pick the latest
   admissible revision (by `released_at`, tie-broken by `revision_
   sequence`). A correction to an old figure never changes WHICH
   decision currently governs; it only ever updates what is known
   about that same decision. `previous_announced_state` needed the
   identical two-step treatment, and consequently gained an explicit
   `as_of` parameter (see its own docstring for why this is not
   optional, unlike before).

5. **A same-observation higher revision can ALSO leave EFFECTIVE
   unresolved**, not only a later, different observation_period.
   `_has_unresolved_later_decision` originally only matched a vintage
   with a strictly later `observation_period`. It missed a REVISION of
   the SAME observation_period whose own `effective_at` is
   unestablished: `revision_sequence` is reserved for genuine changes
   to the value FX-43H/`MacroObservationVintage`'s own docstring), so
   a higher-revision sibling supersedes what an older, lower-revision
   sibling says about that SAME decision -- if that higher revision's
   own effective timing is unresolved, the older revision cannot be
   trusted as "the" effective state either, even though no NEW,
   different decision has occurred. Both `effective_state_as_of` and
   `previous_effective_state` now check for this sibling case too.

Neither `announced_state_as_of`/`effective_state_as_of` nor their
`previous_*` counterparts consult `domain.research_readiness`
themselves -- this module answers "what does the stored history say,"
not "is it safe to trust." Every caller MUST run `require_research_
ready_interval` (or `is_research_safe` per-vintage) over the relevant
window, against the COMPLETE stored history, BEFORE treating either
function's result as research-safe; see `application.use_cases.
compute_policy_rate_differential`.
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


def _released_at_on_or_before(
    vintages: Sequence[MacroObservationVintage], as_of: UtcTimestamp
) -> tuple[MacroObservationVintage, ...]:
    """A purely MECHANICAL filter on the stored `released_at` field:
    every vintage with `released_at <= as_of`, in input order. Deliber-
    ately private, and deliberately NOT named/documented as "known" or
    "safe" (FX-45H.1 section 3/5) -- for a VERIFIED or CONSERVATIVE-
    SAFE-BOUND vintage this genuinely reflects trustworthy knowability,
    but for a PROVISIONAL vintage `released_at` may be an uncorrobo-
    rated proxy (FX-43H), and this function has no way to tell the
    difference; it must never be read as proof either way.

    Exists ONLY for STATE SELECTION, where some visibility criterion is
    structurally required to pick a candidate at all -- `announced_
    state_as_of`/`effective_state_as_of`/`previous_effective_state` use
    it internally. It must NEVER be used to pre-filter the history
    handed to `domain.research_readiness.require_research_ready_
    interval`, which needs the series' COMPLETE stored history to
    correctly fail closed on a relevant provisional vintage -- filtering
    it out here first would let that vintage silently vanish from
    consideration instead (FX-45H.1's own real bug: this function, then
    named `known_as_of` and public, was used for exactly that).
    """
    return tuple(v for v in vintages if v.released_at.value <= as_of.value)


def _latest_observation_state(
    vintages: Sequence[MacroObservationVintage],
) -> MacroObservationVintage | None:
    """Among an already PIT-filtered `vintages`, the one representing
    the CURRENT policy state (FX-45H.1 section 4): the latest
    `observation_period` present, then -- among vintages sharing that
    SAME observation_period -- the latest admissible revision (by
    `released_at`, tie-broken by `revision_sequence`). A later-
    published revision of an OLDER observation_period must never
    resurrect that older observation as "current" merely because it
    was republished more recently; only a genuinely later observation_
    period can change which decision currently governs.
    """
    if not vintages:
        return None
    winning_period = max(v.observation_period.value for v in vintages)
    same_period = [v for v in vintages if v.observation_period.value == winning_period]
    return max(same_period, key=lambda v: (v.released_at.value, v.revision_sequence))


def _has_unresolved_later_decision(
    known: Sequence[MacroObservationVintage],
    candidate: MacroObservationVintage,
    *,
    before: datetime | None = None,
) -> bool:
    """FX-45H section 2, generalized by FX-45H.1 section 5: does
    `known` (already PIT-filtered to `released_at <= as_of`) contain a
    vintage whose own `effective_at` is unpopulated and which
    supersedes `candidate` -- either (a) a genuinely LATER policy
    decision (a strictly later `observation_period`), the only axis
    available for a vintage that has no `effective_at` to order by; or
    (b) a HIGHER-revision sibling of `candidate`'s OWN observation_
    period (same `observation_period`, greater `revision_sequence`) --
    a correction that has changed what is known about that SAME
    decision, whose own effective timing is not yet established.
    `before`, when given, additionally bounds case (a) to decisions
    strictly earlier than it (used by `previous_effective_state` to
    only consider decisions between the found predecessor and
    `current`, never `current` itself or anything at or after it) --
    case (b) is about `candidate`'s own integrity and is never bounded
    by `before`.
    """
    for v in known:
        if v.effective_at is not None:
            continue
        if (
            v.observation_period.value == candidate.observation_period.value
            and v.revision_sequence > candidate.revision_sequence
        ):
            return True
        if v.observation_period.value <= candidate.observation_period.value:
            continue
        if before is not None and v.observation_period.value >= before:
            continue
        return True
    return False


def announced_state_as_of(
    vintages: Sequence[MacroObservationVintage], as_of: UtcTimestamp
) -> MacroObservationVintage | None:
    """The policy decision currently ANNOUNCED (market-known) at
    `as_of`: among vintages with `released_at <= as_of`, the one
    representing the latest observation_period, using its own latest
    admissible revision (FX-45H.1 section 4 -- see `_latest_
    observation_state`). `None` if no vintage in `vintages` has
    `released_at <= as_of` at all.

    A decision never becomes visible before its OWN `released_at` --
    including a decision whose `effective_at` is still in the future:
    per FX-45 section 5, "if a future-effective rate has already been
    announced, it IS the announced policy rate even though it is not
    yet the effective rate. This is deliberate." A LATER republished
    revision of an OLDER observation never resurrects that older
    observation as current, either (FX-45H.1 section 4) -- only a
    genuinely later observation_period changes which decision governs.
    """
    return _latest_observation_state(_released_at_on_or_before(vintages, as_of))


def effective_state_as_of(
    vintages: Sequence[MacroObservationVintage], as_of: UtcTimestamp
) -> MacroObservationVintage | None:
    """The policy rate OPERATIONALLY IN FORCE at `as_of`: the vintage
    with the greatest `effective_at <= as_of` among those whose
    `effective_at` is actually populated, tie-broken by `revision_
    sequence` descending -- restricted throughout to vintages with
    `released_at <= as_of` (FX-45H section 1: a vintage not yet
    released by `as_of` can never govern a query evaluated at `as_of`,
    even if its `effective_at` would otherwise qualify).

    `None` in several distinct cases, deliberately not told apart at
    this layer (all mean "do not report an effective rate"): no
    vintage has a populated, PIT-safe `effective_at <= as_of` at all;
    every candidate vintage exists but simply lacks a verified
    effective date (FX-45 section 6: never fall back to `released_at`/
    `observation_period` for such a vintage); a newer decision has
    already been released by `as_of` with its OWN `effective_at` still
    unestablished (FX-45H section 2); or a higher-revision sibling of
    the SAME observation as the would-be candidate has been released
    with its own `effective_at` unestablished (FX-45H.1 section 5) --
    in any of the latter two cases, reporting the older/lower-revision
    rate would silently ignore that a more recent, already-known fact
    might already govern `as_of`, which this function refuses to guess
    either way.
    """
    known = _released_at_on_or_before(vintages, as_of)
    dated = [
        (v.effective_at.value, v.revision_sequence, v)
        for v in known
        if v.effective_at is not None and v.effective_at.value <= as_of.value
    ]
    candidate = _latest(dated)
    if candidate is None:
        return None
    if _has_unresolved_later_decision(known, candidate):
        return None
    return candidate


def previous_announced_state(
    vintages: Sequence[MacroObservationVintage],
    current: MacroObservationVintage,
    as_of: UtcTimestamp,
) -> MacroObservationVintage | None:
    """The vintage that was the announced state immediately BEFORE
    `current` became the announced state: among vintages knowable at
    `as_of` whose `observation_period` is strictly earlier than
    `current`'s own, the one representing that latest earlier
    observation_period, using its own latest admissible revision
    (FX-45H.1 section 4 -- the same two-step selection `announced_
    state_as_of` itself uses, restricted to observation_periods before
    `current`'s). `None` if `current` is (as far as `vintages` and
    `as_of` show) the earliest announced state on record.

    Takes `as_of` explicitly (a real signature change from before
    FX-45H.1): the two-step selection can no longer rely on simple
    transitivity from `current.released_at` the way a pure `released_
    at`-ordering scheme could, since a "previous" observation could
    itself have a later, out-of-order revision whose own `released_at`
    must be checked against the SAME `as_of` `current` was resolved
    against -- not an implicit bound derived from `current` alone.
    """
    known = _released_at_on_or_before(vintages, as_of)
    earlier = [v for v in known if v.observation_period.value < current.observation_period.value]
    return _latest_observation_state(earlier)


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

    FX-45H section 2: takes `as_of` explicitly -- EFFECTIVE's two axes
    (`released_at` for knowability, `effective_at` for operational
    force) do NOT stand in the same transitive relationship ANNOUNCED's
    single axis does: a vintage with an early `effective_at` can still
    have a late `released_at` (a retroactively-disclosed effective
    date), so "previous" must apply the identical PIT filter `
    effective_state_as_of` applies for `current`, using the SAME
    `as_of` -- not one derived from `current.effective_at`, which would
    answer a different question entirely (point-in-time safety is
    about what `as_of` could know, not about `current`'s own timeline).
    Also applies the same unresolved-later-decision check as
    `effective_state_as_of` (FX-45H.1 section 5 included), bounded to
    decisions strictly between the found predecessor and `current`
    itself for the later-observation_period case.
    """
    if current.effective_at is None:
        return None
    known = _released_at_on_or_before(vintages, as_of)
    dated = [
        (v.effective_at.value, v.revision_sequence, v)
        for v in known
        if v.effective_at is not None and v.effective_at.value < current.effective_at.value
    ]
    candidate = _latest(dated)
    if candidate is None:
        return None
    if _has_unresolved_later_decision(known, candidate, before=current.observation_period.value):
        return None
    return candidate

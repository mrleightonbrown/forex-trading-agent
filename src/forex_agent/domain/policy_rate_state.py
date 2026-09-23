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
    yet the effective rate. This is deliberate."
    """
    dated = [
        (v.released_at.value, v.revision_sequence, v)
        for v in vintages
        if v.released_at.value <= as_of.value
    ]
    return _latest(dated)


def effective_state_as_of(
    vintages: Sequence[MacroObservationVintage], as_of: UtcTimestamp
) -> MacroObservationVintage | None:
    """The policy rate OPERATIONALLY IN FORCE at `as_of`: the vintage
    with the greatest `effective_at <= as_of` among those whose
    `effective_at` is actually populated, tie-broken by `revision_
    sequence` descending. `None` if no vintage in `vintages` has a
    populated `effective_at <= as_of` -- including when every
    candidate vintage exists but simply lacks a verified effective
    date (FX-45 section 6: "If the code cannot defensibly establish
    when a particular rate became effective, the effective-rate
    feature must be unavailable rather than guessed" -- this function
    never falls back to `released_at` or `observation_period` for a
    vintage missing `effective_at`).
    """
    dated = [
        (v.effective_at.value, v.revision_sequence, v)
        for v in vintages
        if v.effective_at is not None and v.effective_at.value <= as_of.value
    ]
    return _latest(dated)


def previous_announced_state(
    vintages: Sequence[MacroObservationVintage], current: MacroObservationVintage
) -> MacroObservationVintage | None:
    """The vintage that was the announced state immediately BEFORE
    `current` became the announced state -- the latest vintage with
    `released_at` strictly earlier than `current.released_at`. `None`
    if `current` is (as far as `vintages` shows) the earliest
    announced state on record."""
    dated = [
        (v.released_at.value, v.revision_sequence, v)
        for v in vintages
        if v.released_at.value < current.released_at.value
    ]
    return _latest(dated)


def previous_effective_state(
    vintages: Sequence[MacroObservationVintage], current: MacroObservationVintage
) -> MacroObservationVintage | None:
    """The vintage that was the effective state immediately BEFORE
    `current` became the effective state -- the latest OTHER vintage
    with a populated `effective_at` strictly earlier than `current.
    effective_at`. `None` if `current.effective_at` is itself `None`
    (a caller should never pass such a `current` here -- only a
    vintage `effective_state_as_of` returned, which is guaranteed to
    have `effective_at` populated) or if `current` is the earliest
    effective state on record."""
    if current.effective_at is None:
        return None
    dated = [
        (v.effective_at.value, v.revision_sequence, v)
        for v in vintages
        if v.effective_at is not None and v.effective_at.value < current.effective_at.value
    ]
    return _latest(dated)

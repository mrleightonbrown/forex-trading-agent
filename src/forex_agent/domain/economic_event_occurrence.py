from dataclasses import dataclass

from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class EconomicEventOccurrence:
    """One specific occurrence of a canonical economic event -- e.g.
    "US CPI for August 2026," or "FOMC press conference, September
    2026" (FX-51 Section 5.2; identity model revised by FX-51H).

    Identity is `occurrence_key` alone -- a stable, caller-assigned,
    provider-neutral identifier, deliberately NOT derived from a
    scheduled timestamp, NOT a database-generated surrogate key
    referenced by other tables, and NOT a provider's own event ID (a
    provider ID is a MAPPING onto this identity, FX-52's own future
    job, never the identity itself). FX-51's original design used
    `(indicator_key, reference_period)` as identity; FX-51H replaced
    it because that pair cannot represent an occurrence for which a
    reference period is not meaningful at all -- an FOMC press
    conference or a set of meeting minutes is not "for" a calendar
    period the way a CPI print is "for August 2026," and forcing one
    onto it would fabricate a fact that does not exist. A reschedule --
    even a schedule moving from one calendar date to a completely
    different one -- is a new SCHEDULE VINTAGE of this SAME occurrence
    (same `occurrence_key`), never a new occurrence; nothing about this
    identity depends on scheduling.

    This type IS persisted (unlike `EconomicIndicatorDefinition`,
    which never is) because it carries two genuine facts that do not
    belong on any vintage: `reference_period` and `release_group_key`.
    Neither changes over time the way a schedule, consensus, or actual
    value does -- vintaging either would invent PIT sensitivity that
    does not exist in the real world.

    Fields:
        occurrence_key: this occurrence's own stable canonical
            identity (see above). Every schedule/consensus/actual-
            value/release vintage in this story references its
            occurrence by this key alone, never by a synthetic
            surrogate ID and never by a provider ID.
        indicator_key: the `EconomicIndicatorDefinition.key` this
            occurrence is one instance of.
        reference_period: which period this occurrence describes (e.g.
            "August 2026", normalized to a single instant the same way
            `MacroObservationVintage.observation_period` already is --
            a calendar fact, not a knowledge fact; it says nothing
            about when anyone could see it), or `None` when a
            reference period is not a meaningful concept for this
            occurrence at all -- a qualitative/irregular event (a
            press conference, an unscheduled statement) is not "for" a
            period the way a periodic release is. `None` here is a
            genuine domain fact, never a placeholder for a period that
            simply has not been determined yet.
        release_group_key: optional shared identifier for occurrences
            published together in one statistical release (e.g.
            headline CPI and core CPI from the same release, or
            payrolls/unemployment/wages from one Employment Situation
            report) -- `None` for an occurrence that is not part of a
            known group, or whose group is not yet known. Each grouped
            occurrence keeps its own separate canonical indicator
            identity and its own separate vintage histories; this
            field is a descriptive tag only, consulted by a future
            story (FX-54) deciding whether several simultaneous
            releases should be treated as one event-risk window --
            FX-51/FX-51H make no such interpretation themselves. Unlike
            every other field on this type, `release_group_key` MAY be
            set once, later, after the occurrence already exists (FX-51H
            Section 5) -- via the repository's own narrowly-scoped
            `attach_release_group`, never via this constructor being
            called twice for the same `occurrence_key`. This is not a
            vintage and not a destructive rewrite: grouping was never a
            temporal fact the way a schedule or value is, so a single
            guarded NULL-to-value transition is the correct, minimal
            shape -- not a reason to vintage it.
    """

    occurrence_key: str
    indicator_key: str
    reference_period: UtcTimestamp | None = None
    release_group_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence_key, str) or not self.occurrence_key.strip():
            raise ValueError(
                f"occurrence_key must be a non-empty string, got {self.occurrence_key!r}"
            )
        if not isinstance(self.indicator_key, str) or not self.indicator_key.strip():
            raise ValueError(
                f"indicator_key must be a non-empty string, got {self.indicator_key!r}"
            )
        if self.reference_period is not None and not isinstance(
            self.reference_period, UtcTimestamp
        ):
            raise TypeError(
                "reference_period must be a UtcTimestamp or None, "
                f"got {type(self.reference_period).__name__}"
            )
        if self.release_group_key is not None and (
            not isinstance(self.release_group_key, str) or not self.release_group_key.strip()
        ):
            raise ValueError(
                f"release_group_key must be a non-empty string or None, "
                f"got {self.release_group_key!r}"
            )

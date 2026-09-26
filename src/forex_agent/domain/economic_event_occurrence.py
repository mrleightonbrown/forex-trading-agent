from dataclasses import dataclass

from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class EconomicEventOccurrence:
    """One specific occurrence of a canonical economic event -- e.g.
    "US CPI for August 2026" (FX-51 Section 5.2).

    Identity is `(indicator_key, reference_period)` -- deliberately NOT
    a scheduled timestamp, and deliberately NOT a database-generated
    surrogate key referenced by other tables: exactly like
    `MacroObservationVintage` uses `(series_key, observation_period)`
    as its own natural identity axis, every schedule/consensus/actual
    vintage in this story references an occurrence by this SAME
    natural key, never by a synthetic ID. A reschedule -- even a
    schedule moving from one calendar date to a completely different
    one -- is a new SCHEDULE VINTAGE of this SAME occurrence, never a
    new occurrence; the reference period is the one fact that defines
    "which economic release this is," and it does not change when the
    release's own timing does.

    This type IS persisted (unlike `EconomicIndicatorDefinition`,
    which never is) because it carries one genuine fact that does not
    belong on any vintage: `release_group_key`. Grouping is a
    structural fact about which occurrences were published together
    (FX-51 Section 8), not something that changes over time the way a
    schedule, consensus, or actual value does -- vintaging it would
    invent PIT sensitivity that does not exist in the real world, and
    denormalizing it onto every vintage row instead would risk two
    vintages of the same occurrence silently disagreeing about their
    own group. One row per occurrence, set once, is the correct shape.

    Fields:
        indicator_key: the `EconomicIndicatorDefinition.key` this
            occurrence is one instance of.
        reference_period: which period this occurrence describes (e.g.
            "August 2026", normalized to a single instant the same way
            `MacroObservationVintage.observation_period` already is --
            a calendar fact, not a knowledge fact; it says nothing
            about when anyone could see it).
        release_group_key: optional shared identifier for occurrences
            published together in one statistical release (e.g.
            headline CPI and core CPI from the same release, or
            payrolls/unemployment/wages from one Employment Situation
            report) -- `None` for an occurrence that is not part of a
            known group. Each grouped occurrence keeps its own separate
            canonical indicator identity and its own separate schedule/
            consensus/actual vintage history; this field is a
            descriptive tag only, consulted by a future story (FX-54)
            deciding whether several simultaneous releases should be
            treated as one event-risk window -- FX-51 makes no such
            interpretation itself.
    """

    indicator_key: str
    reference_period: UtcTimestamp
    release_group_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.indicator_key, str) or not self.indicator_key.strip():
            raise ValueError(
                f"indicator_key must be a non-empty string, got {self.indicator_key!r}"
            )
        if not isinstance(self.reference_period, UtcTimestamp):
            raise TypeError(
                "reference_period must be a UtcTimestamp, "
                f"got {type(self.reference_period).__name__}"
            )
        if self.release_group_key is not None and (
            not isinstance(self.release_group_key, str) or not self.release_group_key.strip()
        ):
            raise ValueError(
                f"release_group_key must be a non-empty string or None, "
                f"got {self.release_group_key!r}"
            )

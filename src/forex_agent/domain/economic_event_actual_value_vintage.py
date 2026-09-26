from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain._guards import (
    require_availability_consistency,
    require_decimal,
    require_revision_sequence,
)
from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class EconomicEventActualValueVintage:
    """One point-in-time-safe fact: "occurrence X's actual released
    value was known, from `availability` onward, to be `actual_value`"
    (FX-51 Section 5.5).

    `revision_sequence == 0` is the FIRST release; every later
    correction (a revision) is a NEW vintage with a later `availability`
    and a higher `revision_sequence` -- the first-release row is never
    updated or replaced. A backtest evaluating this occurrence
    immediately after publication must see the `revision_sequence == 0`
    vintage; a query evaluated after a revision may legitimately see a
    later one -- both remain independently recoverable in storage,
    forever (FX-51 Section 5.5's own worked example: first release
    150k, revision 140k, second revision 137k -- an as-of query
    immediately after publication must return 150k, never 137k).

    Deliberately holds no `previous_value`/`surprise` field of any
    kind -- FX-51 Section 6/7 are explicit that a provider's displayed
    "previous" value is a PIT trap (the prior release may itself have
    been revised since), and that a raw surprise must be DERIVABLE,
    never stored as a single mutable source of truth that a later
    revision could silently rewrite. Both concepts are correctly
    computed later (FX-52/FX-53) from this SAME vintage history: the
    canonical "prior first-release value" is `first_release_as_of`
    called on the PREVIOUS occurrence's own vintages; the canonical
    "prior latest-known-as-of value" is `latest_actual_as_of` called
    on it instead; a raw surprise is `first_release_as_of(this
    occurrence, release_availability) - latest_consensus_as_of(this
    occurrence, release_availability)`. A source-reported "previous"
    field, if a future story needs to retain it at all, must be stored
    with its own explicit provenance, never silently treated as either
    of the two canonical values above.

    Fields:
        indicator_key: the `EconomicIndicatorDefinition.key` this
            actual-value vintage's occurrence belongs to.
        reference_period: the occurrence's own reference period (see
            `EconomicEventOccurrence`).
        revision_sequence: 0 for the first release, incrementing for
            each subsequent revision.
        actual_value: the released value itself. Not every occurrence
            has one -- a qualitative event (FX-51 Section 18) simply
            never has an `EconomicEventActualValueVintage` at all,
            rather than one existing with a null value.
        availability: when this exact actual-value fact became
            knowable, or `None` if genuinely `UNKNOWN` -- see
            `AvailabilityConfidence`. This is the field a backfill's
            own insertion time must never be silently substituted for
            (FX-51 Section 13).
        availability_confidence: how strongly `availability` is
            evidenced. Must be `AvailabilityConfidence.UNKNOWN` if and
            only if `availability` is `None`.
        source: free-form provenance label -- never branched on by
            domain logic.
        raw_source_value: the source's own unmodified representation
            of this actual value, if useful to retain for audit, or
            `None` if not captured. Never interpreted by domain logic.
    """

    indicator_key: str
    reference_period: UtcTimestamp
    revision_sequence: int
    actual_value: Decimal
    availability: UtcTimestamp | None
    availability_confidence: AvailabilityConfidence
    source: str
    raw_source_value: str | None = None

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
        require_revision_sequence(self.revision_sequence)
        require_decimal("actual_value", self.actual_value)
        require_availability_consistency(self.availability, self.availability_confidence)
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError(f"source must be a non-empty string, got {self.source!r}")
        if self.raw_source_value is not None and not isinstance(self.raw_source_value, str):
            raise TypeError(
                f"raw_source_value must be a str or None, got {type(self.raw_source_value)!r}"
            )

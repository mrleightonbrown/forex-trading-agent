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
class EconomicEventConsensusVintage:
    """One point-in-time-safe fact: "occurrence X's market consensus
    was known, from `availability` onward, to be `consensus_value`"
    (FX-51 Section 5.4).

    Same immutable-fact-per-row shape as `EconomicEventScheduleVintage`
    and `MacroObservationVintage`: a revised consensus is a NEW vintage
    with a later `availability` and a higher `revision_sequence`,
    never a mutation of an earlier one. A consensus shown ten minutes
    before release and a consensus shown two days before release are
    both historically real and both preserved -- FX-51 Section 5.4 is
    explicit that "the model must permit multiple consensus/forecast
    vintages," and this type is that permission.

    Deliberately holds no `unit` field -- the unit belongs to the
    occurrence's own `EconomicIndicatorDefinition.unit` and is not
    duplicated per vintage, the same choice `MacroObservationVintage`
    already makes for its own `value`.

    Fields:
        indicator_key: the `EconomicIndicatorDefinition.key` this
            consensus vintage's occurrence belongs to.
        reference_period: the occurrence's own reference period (see
            `EconomicEventOccurrence`).
        revision_sequence: 0 for the first-known consensus of this
            occurrence, incrementing for each subsequent revision.
        consensus_value: the consensus/forecast value itself.
        availability: when this exact consensus fact became knowable,
            or `None` if genuinely `UNKNOWN` -- see
            `AvailabilityConfidence`.
        availability_confidence: how strongly `availability` is
            evidenced. Must be `AvailabilityConfidence.UNKNOWN` if and
            only if `availability` is `None`.
        source: free-form provenance label -- never branched on by
            domain logic.
        raw_source_value: the source's own unmodified representation
            of this consensus, if useful to retain for audit (FX-51
            Section 12), or `None` if not captured. Never interpreted
            by domain logic -- provenance only.
    """

    indicator_key: str
    reference_period: UtcTimestamp
    revision_sequence: int
    consensus_value: Decimal
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
        require_decimal("consensus_value", self.consensus_value)
        require_availability_consistency(self.availability, self.availability_confidence)
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError(f"source must be a non-empty string, got {self.source!r}")
        if self.raw_source_value is not None and not isinstance(self.raw_source_value, str):
            raise TypeError(
                f"raw_source_value must be a str or None, got {type(self.raw_source_value)!r}"
            )

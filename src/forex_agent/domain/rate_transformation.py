from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class RateTransformationKind(Enum):
    """A closed, small set of deterministic rules for turning one or
    more raw provider values into the single canonical scalar a
    `PolicyRateDefinition` (FX-42) represents.

    Central banks do not all publish a single target number: the
    Federal Reserve has, since December 2008, published a target
    RANGE (upper and lower bound) rather than a single target point.
    Turning that range into one canonical Decimal is exactly the kind
    of transformation this story's spec calls out ("If a canonical
    scalar requires a deterministic transformation, make that
    transformation explicit and versioned") -- `RateTransformation`
    below pairs a `RateTransformationKind` with an explicit `version`
    string so the rule itself is auditable and can be revised without
    silently changing history.
    """

    IDENTITY = "IDENTITY"
    """The provider publishes a single scalar already; it is used as-is."""

    TARGET_RANGE_MIDPOINT = "TARGET_RANGE_MIDPOINT"
    """The provider publishes an upper and lower target bound; the
    canonical scalar is their arithmetic mean."""


@dataclass(frozen=True, slots=True)
class RateTransformation:
    """A specific, versioned instance of a `RateTransformationKind`
    (FX-42).

    `version` exists separately from `kind` so the deterministic rule
    itself is pinned and auditable: if this story's own
    TARGET_RANGE_MIDPOINT arithmetic (a straight average) is ever
    replaced by a different rule (e.g. a weighted average, or a
    different tie-break for asymmetric bands), that is a new version,
    not a silent behavior change under the same name -- a downstream
    consumer that recorded which version produced a given observation
    can tell the two apart.
    """

    kind: RateTransformationKind
    version: str
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RateTransformationKind):
            raise TypeError(f"kind must be a RateTransformationKind, got {type(self.kind)!r}")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError(f"version must be a non-empty string, got {self.version!r}")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError(f"description must be a non-empty string, got {self.description!r}")

    def apply(self, *raw_values: Decimal) -> Decimal:
        """Deterministically map raw provider value(s) onto the
        canonical scalar this transformation describes.

        Pure arithmetic only -- no I/O, no provider knowledge. FX-43's
        ingestion adapter is expected to call this once it has parsed a
        provider's raw response into `Decimal`s, not reimplement the
        rule itself.
        """
        for value in raw_values:
            if not isinstance(value, Decimal):
                raise TypeError(f"raw values must be Decimal, got {type(value).__name__}")

        if self.kind is RateTransformationKind.IDENTITY:
            if len(raw_values) != 1:
                raise ValueError(f"IDENTITY requires exactly one raw value, got {len(raw_values)}")
            return raw_values[0]

        if self.kind is RateTransformationKind.TARGET_RANGE_MIDPOINT:
            if len(raw_values) != 2:
                raise ValueError(
                    f"TARGET_RANGE_MIDPOINT requires exactly two raw values "
                    f"(upper, lower), got {len(raw_values)}"
                )
            upper, lower = raw_values
            if upper < lower:
                raise ValueError(
                    f"upper bound ({upper}) must not be less than lower bound ({lower})"
                )
            return (upper + lower) / 2

        raise NotImplementedError(f"no apply() rule implemented for {self.kind}")

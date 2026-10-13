from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain._guards import require_decimal, require_revision_sequence
from forex_agent.domain.forecast_attribution import ForecastAttribution
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class StructuredForecastVintage:
    """FX-64 Section 12: one immutable, append-only fact about a
    `ForecastClaim`'s own structured forecast payload -- mirroring
    FX-62's `SourceIdentityVintage`/FX-59's semantic-annotation
    vintage shape exactly: a correction, a source-issued revision, or
    a later re-assertion is ALWAYS a NEW, higher-`revision_sequence`
    row, never a mutation of an earlier one. Every field below except
    `claim_key`/`revision_sequence`/`availability`/`algorithm_
    version`/`correction_reason` is part of the FULL determinism
    payload (Section 13) -- see `application.use_cases.record_
    structured_forecast`'s own docstring for the exact determinism
    key and why every one of these fields must be compared, not just
    the numeric/categorical value.

    `forecast_type` structurally determines which of `numeric_value`/
    `unit` vs. `categorical_outcome` are populated (never both, never
    neither) -- see `__post_init__`. `availability` is ALWAYS FTA's
    own knowledge instant, for BOTH `ForecastProvenanceMode` values
    (Section 7) -- `original_publication_at`/the evidence's own
    `publisher_declared_publication_at` preserve the TRUE original
    publication time, purely descriptively, NEVER promoted here."""

    claim_key: str
    revision_sequence: int
    availability: UtcTimestamp
    algorithm_version: str
    forecast_type: ForecastType
    target_key: str
    target_period: ForecastTargetPeriod
    attribution: ForecastAttribution
    provenance_mode: ForecastProvenanceMode
    evidence: ForecastEvidenceReference
    numeric_value: Decimal | None = None
    unit: str | None = None
    categorical_outcome: str | None = None
    original_publication_at: UtcTimestamp | None = None
    correction_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.claim_key, str) or not self.claim_key.strip():
            raise ValueError(f"claim_key must be a non-empty string, got {self.claim_key!r}")
        require_revision_sequence(self.revision_sequence)
        if not isinstance(self.availability, UtcTimestamp):
            raise TypeError(
                f"availability must be a UtcTimestamp, got {type(self.availability).__name__}"
            )
        if not isinstance(self.algorithm_version, str) or not self.algorithm_version.strip():
            raise ValueError(
                f"algorithm_version must be a non-empty string, got {self.algorithm_version!r}"
            )
        if not isinstance(self.forecast_type, ForecastType):
            raise TypeError(
                f"forecast_type must be a ForecastType, got {type(self.forecast_type).__name__}"
            )
        if not isinstance(self.target_key, str) or not self.target_key.strip():
            raise ValueError(f"target_key must be a non-empty string, got {self.target_key!r}")
        if not isinstance(self.target_period, ForecastTargetPeriod):
            raise TypeError(
                f"target_period must be a ForecastTargetPeriod, got "
                f"{type(self.target_period).__name__}"
            )
        if not isinstance(self.attribution, ForecastAttribution):
            raise TypeError(
                f"attribution must be a ForecastAttribution, got {type(self.attribution).__name__}"
            )
        if not isinstance(self.provenance_mode, ForecastProvenanceMode):
            raise TypeError(
                "provenance_mode must be a ForecastProvenanceMode, got "
                f"{type(self.provenance_mode).__name__}"
            )
        if not isinstance(self.evidence, ForecastEvidenceReference):
            raise TypeError(
                f"evidence must be a ForecastEvidenceReference, got {type(self.evidence).__name__}"
            )
        if self.original_publication_at is not None and not isinstance(
            self.original_publication_at, UtcTimestamp
        ):
            raise TypeError(
                "original_publication_at must be a UtcTimestamp or None, got "
                f"{type(self.original_publication_at).__name__}"
            )
        if self.correction_reason is not None and (
            not isinstance(self.correction_reason, str) or not self.correction_reason.strip()
        ):
            raise ValueError(
                f"correction_reason must be a non-empty string or None, got "
                f"{self.correction_reason!r}"
            )

        if self.forecast_type is ForecastType.NUMERIC_POINT:
            if self.numeric_value is None:
                raise ValueError("numeric_value is required for NUMERIC_POINT")
            require_decimal("numeric_value", self.numeric_value)
            if not isinstance(self.unit, str) or not self.unit.strip():
                raise ValueError("unit must be a non-empty string for NUMERIC_POINT")
            if self.categorical_outcome is not None:
                raise ValueError("categorical_outcome must be None for NUMERIC_POINT")
        elif self.forecast_type is ForecastType.CATEGORICAL_EVENT:
            if (
                not isinstance(self.categorical_outcome, str)
                or not self.categorical_outcome.strip()
            ):
                raise ValueError(
                    "categorical_outcome must be a non-empty string for CATEGORICAL_EVENT"
                )
            if self.numeric_value is not None:
                raise ValueError("numeric_value must be None for CATEGORICAL_EVENT")
            if self.unit is not None:
                raise ValueError("unit must be None for CATEGORICAL_EVENT")

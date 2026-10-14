from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain._guards import require_decimal, require_revision_sequence
from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastOutcomeVintage:
    """FX-65 Section 5: one immutable, append-only fact about an
    independently observed outcome -- mirrors FX-64's own `Structured
    ForecastVintage` shape exactly, including its NUMERIC_POINT/
    CATEGORICAL_EVENT payload-shape rule. `outcome_key` is the stable,
    caller-supplied identity (mirrors `claim_key`); a later release or
    source correction is a NEW, higher `revision_sequence` row, never
    a mutation (Section 5's own explicit "do not update or overwrite"
    rule).

    `definition_key`/`definition_version_sequence` pin the EXACT
    `ForecastOutcomeDefinition` version this observation was captured
    under (Section 11). `authentication_review` is REQUIRED -- an
    outcome observation with no human-reviewed evidentiary basis
    cannot be constructed at all, mirroring this epic's own
    "unconstructable to violate" convention. `provider_release_
    identifier`/`provider_published_at` preserve the SOURCE's own
    release identity/timestamp, distinct from `availability` (FTA's
    own acquisition instant) exactly as `ForecastEvidenceReference.
    publisher_declared_publication_at` already does for forecasts."""

    outcome_key: str
    revision_sequence: int
    definition_key: str
    definition_version_sequence: int
    availability: UtcTimestamp
    target_period: ForecastTargetPeriod
    outcome_type: ForecastType
    evidence: ForecastEvidenceReference
    authentication_review: EvidenceAuthenticationReview
    provenance_mode: ForecastProvenanceMode
    numeric_value: Decimal | None = None
    unit: str | None = None
    categorical_outcome: str | None = None
    provider_release_identifier: str | None = None
    provider_published_at: UtcTimestamp | None = None
    content_integrity_reference: str | None = None
    correction_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome_key, str) or not self.outcome_key.strip():
            raise ValueError(f"outcome_key must be a non-empty string, got {self.outcome_key!r}")
        require_revision_sequence(self.revision_sequence)
        if not isinstance(self.definition_key, str) or not self.definition_key.strip():
            raise ValueError(
                f"definition_key must be a non-empty string, got {self.definition_key!r}"
            )
        require_revision_sequence(self.definition_version_sequence)
        if not isinstance(self.availability, UtcTimestamp):
            raise TypeError(
                f"availability must be a UtcTimestamp, got {type(self.availability).__name__}"
            )
        if not isinstance(self.target_period, ForecastTargetPeriod):
            raise TypeError(
                f"target_period must be a ForecastTargetPeriod, got "
                f"{type(self.target_period).__name__}"
            )
        if not isinstance(self.outcome_type, ForecastType):
            raise TypeError(
                f"outcome_type must be a ForecastType, got {type(self.outcome_type).__name__}"
            )
        if not isinstance(self.evidence, ForecastEvidenceReference):
            raise TypeError(
                f"evidence must be a ForecastEvidenceReference, got {type(self.evidence).__name__}"
            )
        if not isinstance(self.authentication_review, EvidenceAuthenticationReview):
            raise TypeError(
                "authentication_review must be an EvidenceAuthenticationReview, got "
                f"{type(self.authentication_review).__name__}"
            )
        if not isinstance(self.provenance_mode, ForecastProvenanceMode):
            raise TypeError(
                "provenance_mode must be a ForecastProvenanceMode, got "
                f"{type(self.provenance_mode).__name__}"
            )
        for optional_text in (
            self.provider_release_identifier,
            self.content_integrity_reference,
            self.correction_reason,
        ):
            if optional_text is not None and (
                not isinstance(optional_text, str) or not optional_text.strip()
            ):
                raise ValueError(
                    f"optional text fields must be non-empty strings or None, got {optional_text!r}"
                )
        if self.provider_published_at is not None and not isinstance(
            self.provider_published_at, UtcTimestamp
        ):
            raise TypeError(
                "provider_published_at must be a UtcTimestamp or None, got "
                f"{type(self.provider_published_at).__name__}"
            )

        if self.outcome_type is ForecastType.NUMERIC_POINT:
            if self.numeric_value is None:
                raise ValueError("numeric_value is required for NUMERIC_POINT")
            require_decimal("numeric_value", self.numeric_value)
            if not isinstance(self.unit, str) or not self.unit.strip():
                raise ValueError("unit must be a non-empty string for NUMERIC_POINT")
            if self.categorical_outcome is not None:
                raise ValueError("categorical_outcome must be None for NUMERIC_POINT")
        elif self.outcome_type is ForecastType.CATEGORICAL_EVENT:
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

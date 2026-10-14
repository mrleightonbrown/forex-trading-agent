from dataclasses import dataclass

from forex_agent.domain._guards import require_revision_sequence
from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_evaluation_result import ForecastEvaluationResult
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class StructuredForecastEvaluationVintage:
    """FX-65 Section 11: one immutable, append-only fact: "FTA
    evaluated forecast claim X (at this EXACT vintage) under protocol
    Y (at this EXACT version) against outcome Z (at this EXACT
    vintage), and got this result." `evaluation_key` is the stable,
    caller-supplied identity tying one `(forecast_claim_key, protocol_
    key)` pair together across however many re-evaluations are later
    appended (mirrors `claim_key`); EVERYTHING else below -- including
    which forecast/outcome/protocol VERSION was used -- can legitimately
    differ across revisions of the SAME `evaluation_key`, exactly as a
    `StructuredForecastVintage`'s own payload can differ across
    revisions of the SAME `claim_key`.

    No `admissibility` field: mirrors `StructuredForecastVintage`
    carrying no `eligibility` field -- a non-`ADMISSIBLE` assessment
    is never persisted at all (Section 8's own "a rejected candidate
    is never persisted" rule), so every row that exists was `ADMISSIBLE`
    by construction; storing a constant would be pure noise.

    `availability` here is the EVALUATION's own recording instant --
    the THIRD of Section 10's three distinct timelines (forecast
    availability, outcome availability, evaluation availability),
    always caller-supplied, never defaulted to wall-clock time."""

    evaluation_key: str
    revision_sequence: int
    forecast_claim_key: str
    forecast_revision_sequence: int
    protocol_key: str
    protocol_version_sequence: int
    outcome_definition_key: str
    outcome_definition_version_sequence: int
    outcome_key: str
    outcome_revision_sequence: int
    evaluation_mode: ForecastProvenanceMode
    algorithm_version: str
    availability: UtcTimestamp
    result: ForecastEvaluationResult
    forecast_authentication_review: EvidenceAuthenticationReview
    correction_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.evaluation_key, str) or not self.evaluation_key.strip():
            raise ValueError(
                f"evaluation_key must be a non-empty string, got {self.evaluation_key!r}"
            )
        require_revision_sequence(self.revision_sequence)
        for name, value in (
            ("forecast_claim_key", self.forecast_claim_key),
            ("protocol_key", self.protocol_key),
            ("outcome_definition_key", self.outcome_definition_key),
            ("outcome_key", self.outcome_key),
            ("algorithm_version", self.algorithm_version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string, got {value!r}")
        require_revision_sequence(self.forecast_revision_sequence)
        require_revision_sequence(self.protocol_version_sequence)
        require_revision_sequence(self.outcome_definition_version_sequence)
        require_revision_sequence(self.outcome_revision_sequence)
        if not isinstance(self.evaluation_mode, ForecastProvenanceMode):
            raise TypeError(
                f"evaluation_mode must be a ForecastProvenanceMode, got "
                f"{type(self.evaluation_mode).__name__}"
            )
        if not isinstance(self.availability, UtcTimestamp):
            raise TypeError(
                f"availability must be a UtcTimestamp, got {type(self.availability).__name__}"
            )
        if not isinstance(self.result, ForecastEvaluationResult):
            raise TypeError(
                f"result must be a ForecastEvaluationResult, got {type(self.result).__name__}"
            )
        if not isinstance(self.forecast_authentication_review, EvidenceAuthenticationReview):
            raise TypeError(
                "forecast_authentication_review must be an EvidenceAuthenticationReview, got "
                f"{type(self.forecast_authentication_review).__name__}"
            )
        if self.correction_reason is not None and (
            not isinstance(self.correction_reason, str) or not self.correction_reason.strip()
        ):
            raise ValueError(
                f"correction_reason must be a non-empty string or None, got "
                f"{self.correction_reason!r}"
            )

from dataclasses import dataclass

from forex_agent.domain.forecast_target_registry import target_by_key
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.outcome_vintage_selection_policy import OutcomeVintageSelectionPolicy
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastOutcomeDefinition:
    """FX-65 Section 4: ONE append-only version of a durable outcome
    definition -- `(definition_key, version_sequence)` is the row's
    own identity; a later correction is a NEW, higher `version_
    sequence` row, never a mutation (Section 4's own lifecycle rule).

    Deliberately does NOT restate `unit`/`measurement_convention`/
    `target_period_kind` as its own separate fields -- those live on
    the linked `ForecastTargetDefinition` (FX-64's own `forecast_
    target_registry`) and are reached ONLY via `target_key`, so there
    is exactly one place these facts can drift, never two. `__post_
    init__` cross-validates `target_key` against that registry and
    that `outcome_type` is one of the target's own `supported_
    forecast_types` -- Section 4's own "do not match variables based
    only on display names" enforced structurally, not by convention.

    `provider_source_key` reuses an FX-62 `intelligence_sources`
    identity (the authoritative outcome provider); `required_source_
    series_identifier` is a free-form, human-readable citation for the
    provider's own series/release (deliberately NOT a foreign key onto
    any existing macro/economic-event table -- Section 2's own
    explicit warning against attaching outcomes by name similarity to
    data this story did not independently verify)."""

    definition_key: str
    version_sequence: int
    target_key: str
    outcome_type: ForecastType
    provider_source_key: str
    required_source_series_identifier: str
    outcome_vintage_selection_policy: OutcomeVintageSelectionPolicy
    availability: UtcTimestamp
    supporting_definition_reference: str
    correction_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.definition_key, str) or not self.definition_key.strip():
            raise ValueError(
                f"definition_key must be a non-empty string, got {self.definition_key!r}"
            )
        if not isinstance(self.version_sequence, int) or isinstance(self.version_sequence, bool):
            raise TypeError(
                f"version_sequence must be an int, got {type(self.version_sequence).__name__}"
            )
        if self.version_sequence < 0:
            raise ValueError(f"version_sequence must not be negative, got {self.version_sequence}")
        if not isinstance(self.outcome_type, ForecastType):
            raise TypeError(
                f"outcome_type must be a ForecastType, got {type(self.outcome_type).__name__}"
            )
        if not isinstance(self.provider_source_key, str) or not self.provider_source_key.strip():
            raise ValueError(
                f"provider_source_key must be a non-empty string, got {self.provider_source_key!r}"
            )
        if (
            not isinstance(self.required_source_series_identifier, str)
            or not self.required_source_series_identifier.strip()
        ):
            raise ValueError(
                "required_source_series_identifier must be a non-empty string, got "
                f"{self.required_source_series_identifier!r}"
            )
        if not isinstance(self.outcome_vintage_selection_policy, OutcomeVintageSelectionPolicy):
            raise TypeError(
                "outcome_vintage_selection_policy must be an OutcomeVintageSelectionPolicy, got "
                f"{type(self.outcome_vintage_selection_policy).__name__}"
            )
        if not isinstance(self.availability, UtcTimestamp):
            raise TypeError(
                f"availability must be a UtcTimestamp, got {type(self.availability).__name__}"
            )
        if (
            not isinstance(self.supporting_definition_reference, str)
            or not self.supporting_definition_reference.strip()
        ):
            raise ValueError(
                "supporting_definition_reference must be a non-empty string, got "
                f"{self.supporting_definition_reference!r}"
            )
        if self.correction_reason is not None and (
            not isinstance(self.correction_reason, str) or not self.correction_reason.strip()
        ):
            raise ValueError(
                f"correction_reason must be a non-empty string or None, got "
                f"{self.correction_reason!r}"
            )

        target = target_by_key(self.target_key)
        if target is None:
            raise ValueError(
                f"target_key={self.target_key!r} is not in the admitted forecast target registry "
                "-- an outcome definition must be associated with an approved FX-64 target"
            )
        if self.outcome_type not in target.supported_forecast_types:
            raise ValueError(
                f"outcome_type={self.outcome_type.value!r} is not supported by "
                f"target_key={self.target_key!r} (admits only "
                f"{[t.value for t in target.supported_forecast_types]!r})"
            )

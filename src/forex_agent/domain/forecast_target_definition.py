from dataclasses import dataclass

from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.forecast_variable_family import ForecastVariableFamily


@dataclass(frozen=True, slots=True)
class ForecastTargetDefinition:
    """FX-64 Section 9: ONE admitted, reusable target definition --
    mirroring `domain.economic_indicator_registry`'s own admission
    discipline (a small, curated set, never an unrestricted taxonomy).
    The EXACT statistical definition is load-bearing (Section 9's own
    explicit examples: annual-average inflation differs from December
    Y/Y inflation; Y/Y GDP growth differs from QoQ annualized growth)
    -- `measurement_convention` exists specifically so two DIFFERENT
    conventions for the "same" variable_family/jurisdiction are always
    two DIFFERENT target definitions, never conflated into one.

    Fields:
        target_key: durable, caller-facing key (e.g. `"EA_HICP_YOY_
            ANNUAL_AVERAGE"`).
        variable_family: the broad economic concept (Section 9's own
            four initial families).
        jurisdiction: the economic area, country, or market this
            variable concerns (e.g. `"EURO_AREA"`, `"CANADA"`).
        variable_name: a human-readable description of the exact
            variable (e.g. `"HICP (All-items), annual average
            year-on-year"`).
        unit: the measurement unit (e.g. `"PERCENT_YOY"`), or `None`
            for a target that supports ONLY `CATEGORICAL_EVENT`
            forecasts (a categorical outcome has no numeric unit).
        measurement_convention: the EXACT statistical convention
            distinguishing this definition from any other definition
            that might otherwise look similar (e.g. `"ANNUAL_
            AVERAGE"` vs. `"DECEMBER_YOY"`; `"QOQ_SAAR"` vs. `"YOY"`).
        period_frequency: which `ForecastTargetPeriodKind` every
            forecast against this target must use -- a candidate
            using a mismatched period kind is rejected (Section 11),
            never silently reinterpreted.
        supported_forecast_types: which `ForecastType`(s) this exact
            target admits -- e.g. a policy-rate LEVEL target supports
            only `NUMERIC_POINT`, while a policy-rate DECISION target
            supports only `CATEGORICAL_EVENT`. A candidate proposing
            an unsupported combination is rejected as `UNSUPPORTED_
            FORECAST_TYPE` (Section 11), never silently reinterpreted.
        authoritative_definition_reference: free-form citation of the
            official source defining this exact convention (e.g. the
            originating survey's own questionnaire).
    """

    target_key: str
    variable_family: ForecastVariableFamily
    jurisdiction: str
    variable_name: str
    measurement_convention: str
    period_frequency: ForecastTargetPeriodKind
    supported_forecast_types: tuple[ForecastType, ...]
    authoritative_definition_reference: str
    unit: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("target_key", self.target_key),
            ("jurisdiction", self.jurisdiction),
            ("variable_name", self.variable_name),
            ("measurement_convention", self.measurement_convention),
            ("authoritative_definition_reference", self.authoritative_definition_reference),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string, got {value!r}")
        if self.unit is not None and (not isinstance(self.unit, str) or not self.unit.strip()):
            raise ValueError(f"unit must be a non-empty string or None, got {self.unit!r}")
        if not isinstance(self.variable_family, ForecastVariableFamily):
            raise TypeError(
                "variable_family must be a ForecastVariableFamily, got "
                f"{type(self.variable_family).__name__}"
            )
        if not isinstance(self.period_frequency, ForecastTargetPeriodKind):
            raise TypeError(
                "period_frequency must be a ForecastTargetPeriodKind, got "
                f"{type(self.period_frequency).__name__}"
            )
        if (
            not isinstance(self.supported_forecast_types, tuple)
            or not self.supported_forecast_types
        ):
            raise ValueError(
                "supported_forecast_types must be a non-empty tuple, got "
                f"{self.supported_forecast_types!r}"
            )
        for forecast_type in self.supported_forecast_types:
            if not isinstance(forecast_type, ForecastType):
                raise TypeError(
                    f"every supported_forecast_types entry must be a ForecastType, got "
                    f"{type(forecast_type).__name__}"
                )
        if ForecastType.NUMERIC_POINT in self.supported_forecast_types and self.unit is None:
            raise ValueError(
                "unit is required when NUMERIC_POINT is a supported_forecast_types entry"
            )

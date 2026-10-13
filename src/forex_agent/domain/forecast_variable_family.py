from enum import Enum


class ForecastVariableFamily(Enum):
    """FX-64 Section 9: the initial candidate variable families --
    deliberately small, mirroring `domain.economic_indicator_registry`'s
    own admission discipline (do not build an unrestricted global
    taxonomy). A family describes only the broad economic concept; the
    EXACT statistical definition (annual average vs. December Y/Y,
    QoQ SAAR vs. Y/Y, ...) lives on `ForecastTargetDefinition` itself,
    never inferred from the family alone."""

    INFLATION = "INFLATION"
    UNEMPLOYMENT = "UNEMPLOYMENT"
    GDP_GROWTH = "GDP_GROWTH"
    POLICY_RATE = "POLICY_RATE"

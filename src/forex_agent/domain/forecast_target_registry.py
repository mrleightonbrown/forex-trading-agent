"""FX-64 Section 9/16: the admitted structured-forecast target
registry -- deliberately small (six definitions, three real,
publicly-documented surveys), mirroring `domain.economic_indicator_
registry`'s own admission discipline exactly: a definition is only
added here once its own exact statistical convention has been
verified against the originating survey's own public documentation,
never added speculatively for symmetric coverage.

Covers exactly the three controlled real-source surveys named in this
story's own Section 16 priority list -- the ECB Survey of Professional
Forecasters, the Federal Reserve Bank of Philadelphia Survey of
Professional Forecasters, and the Bank of Canada Market Participants
Survey. `US_REAL_GDP_GROWTH_QOQ_SAAR` and `CA_REAL_GDP_GROWTH_YOY_
YEAR_END` are DELIBERATELY two separate GDP-growth definitions,
verified live against each survey's own real published figures
(Section 16) -- the architect's own explicit example of two
conventions ("Y/Y GDP growth differs from QoQ annualized growth")
that a smaller model would wrongly conflate."""

from forex_agent.domain.forecast_target_definition import ForecastTargetDefinition
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.forecast_variable_family import ForecastVariableFamily

EA_HICP_YOY_ANNUAL_AVERAGE = ForecastTargetDefinition(
    target_key="EA_HICP_YOY_ANNUAL_AVERAGE",
    variable_family=ForecastVariableFamily.INFLATION,
    jurisdiction="EURO_AREA",
    variable_name="HICP (All-items), annual average year-on-year inflation",
    unit="PERCENT_YOY",
    measurement_convention="ANNUAL_AVERAGE",
    period_frequency=ForecastTargetPeriodKind.CALENDAR_YEAR,
    supported_forecast_types=(ForecastType.NUMERIC_POINT,),
    authoritative_definition_reference=(
        "ECB Survey of Professional Forecasters (SPF) questionnaire -- respondents are asked "
        "for annual-average HICP inflation for specified calendar years, distinct from a "
        "December year-on-year rate."
    ),
)

US_REAL_GDP_GROWTH_QOQ_SAAR = ForecastTargetDefinition(
    target_key="US_REAL_GDP_GROWTH_QOQ_SAAR",
    variable_family=ForecastVariableFamily.GDP_GROWTH,
    jurisdiction="UNITED_STATES",
    variable_name="Real GDP growth, quarter-over-quarter, seasonally adjusted annualized rate",
    unit="PERCENT_QOQ_SAAR",
    measurement_convention="QOQ_SAAR",
    period_frequency=ForecastTargetPeriodKind.CALENDAR_QUARTER,
    supported_forecast_types=(ForecastType.NUMERIC_POINT,),
    authoritative_definition_reference=(
        "Federal Reserve Bank of Philadelphia Survey of Professional Forecasters (SPF) "
        "questionnaire -- respondents forecast quarterly real GDP growth at a seasonally "
        "adjusted annualized rate, distinct from a year-on-year growth rate."
    ),
)

CA_REAL_GDP_GROWTH_YOY_YEAR_END = ForecastTargetDefinition(
    target_key="CA_REAL_GDP_GROWTH_YOY_YEAR_END",
    variable_family=ForecastVariableFamily.GDP_GROWTH,
    jurisdiction="CANADA",
    variable_name="Real GDP growth, year-over-year, as of the end of a specified calendar year",
    unit="PERCENT_YOY",
    measurement_convention="YEAR_END_YOY",
    period_frequency=ForecastTargetPeriodKind.CALENDAR_YEAR,
    supported_forecast_types=(ForecastType.NUMERIC_POINT,),
    authoritative_definition_reference=(
        "Bank of Canada Market Participants Survey (MPS) questionnaire -- respondents forecast "
        "year-over-year real GDP growth as of the end of a specified calendar year, distinct "
        "from the Philadelphia Fed SPF's own quarter-over-quarter annualized convention (see "
        "US_REAL_GDP_GROWTH_QOQ_SAAR) -- the architect's own explicit example of two genuinely "
        "different GDP growth conventions that must never be conflated."
    ),
)

CA_POLICY_RATE_LEVEL_AFTER_MEETING = ForecastTargetDefinition(
    target_key="CA_POLICY_RATE_LEVEL_AFTER_MEETING",
    variable_family=ForecastVariableFamily.POLICY_RATE,
    jurisdiction="CANADA",
    variable_name=(
        "Bank of Canada overnight rate target, level immediately following a specified "
        "Governing Council interest-rate decision"
    ),
    unit="PERCENT",
    measurement_convention="LEVEL_AFTER_MEETING",
    period_frequency=ForecastTargetPeriodKind.POLICY_MEETING,
    supported_forecast_types=(ForecastType.NUMERIC_POINT,),
    authoritative_definition_reference=(
        "Bank of Canada Market Participants Survey (MPS) questionnaire -- respondents are "
        "asked for the expected overnight rate target level following a specified, scheduled "
        "Governing Council decision date, distinct from the AMOUNT of change at that meeting."
    ),
)

CA_POLICY_RATE_DECISION_HIKE_HOLD_CUT = ForecastTargetDefinition(
    target_key="CA_POLICY_RATE_DECISION_HIKE_HOLD_CUT",
    variable_family=ForecastVariableFamily.POLICY_RATE,
    jurisdiction="CANADA",
    variable_name=(
        "Bank of Canada Governing Council interest-rate decision direction (HIKE/HOLD/CUT) at "
        "a specified, scheduled meeting"
    ),
    unit=None,
    measurement_convention="MEETING_DECISION_DIRECTION",
    period_frequency=ForecastTargetPeriodKind.POLICY_MEETING,
    supported_forecast_types=(ForecastType.CATEGORICAL_EVENT,),
    authoritative_definition_reference=(
        "Bank of Canada Market Participants Survey (MPS) questionnaire -- respondents are "
        "asked whether they expect the Bank to raise, hold, or lower its policy rate at a "
        "specified meeting, distinct from the resulting LEVEL (see CA_POLICY_RATE_LEVEL_"
        "AFTER_MEETING)."
    ),
)

CA_UNEMPLOYMENT_RATE_QUARTERLY_AVERAGE = ForecastTargetDefinition(
    target_key="CA_UNEMPLOYMENT_RATE_QUARTERLY_AVERAGE",
    variable_family=ForecastVariableFamily.UNEMPLOYMENT,
    jurisdiction="CANADA",
    variable_name="Unemployment rate, quarterly average",
    unit="PERCENT",
    measurement_convention="QUARTERLY_AVERAGE",
    period_frequency=ForecastTargetPeriodKind.CALENDAR_QUARTER,
    supported_forecast_types=(ForecastType.NUMERIC_POINT,),
    authoritative_definition_reference=(
        "Bank of Canada Market Participants Survey (MPS) questionnaire -- respondents forecast "
        "the quarterly-average unemployment rate for a specified calendar quarter."
    ),
)

FORECAST_TARGET_REGISTRY: tuple[ForecastTargetDefinition, ...] = (
    EA_HICP_YOY_ANNUAL_AVERAGE,
    US_REAL_GDP_GROWTH_QOQ_SAAR,
    CA_REAL_GDP_GROWTH_YOY_YEAR_END,
    CA_POLICY_RATE_LEVEL_AFTER_MEETING,
    CA_POLICY_RATE_DECISION_HIKE_HOLD_CUT,
    CA_UNEMPLOYMENT_RATE_QUARTERLY_AVERAGE,
)


def target_by_key(target_key: str) -> ForecastTargetDefinition | None:
    """`None` if `target_key` is not in the admitted registry -- never
    guessed or synthesized from a free-form description (Section 9's
    own "reject materially ambiguous target definitions" rule)."""
    return next((t for t in FORECAST_TARGET_REGISTRY if t.target_key == target_key), None)

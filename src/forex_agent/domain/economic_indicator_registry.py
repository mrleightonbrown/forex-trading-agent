"""Canonical, provider-independent economic-indicator registry (FX-52A).

Deliberately small -- five indicators, three economies -- mirroring
FX-51's own explicit instruction ("do not build a 500-event
taxonomy") and FX-52A's own admission rule: an indicator is only
added here once a real, official, machine-readable source for its
SCHEDULE or its RELEASE-OCCURRENCE evidence has been directly verified
against primary documentation (see `docs/adr/0004-official-economic-
calendar-timing-sources.md`), not because a provider or plan calls for
symmetric coverage. EUR has NO entry: no official source cleared
FX-52A's own admission bar for the euro area in this pass (Eurostat's
real iCalendar URL could not be established without a browser session;
the ECB Governing Council calendar remains HTML-only with no stated
timezone) -- this is a documented, honest gap, not an oversight.

Every `EconomicIndicatorDefinition` here is `is_numeric=True` because
each ONE genuinely has a number in the real world (a CPI print, a
payroll count, a policy rate) -- `is_numeric` describes the
INDICATOR's own true nature, not what THIS story chooses to ingest.
FX-52A itself never populates `EconomicEventActualValueVintage` for
any of them regardless (see `infrastructure.economic_calendar_sources`
module docstrings) -- that restriction is a STORY-SCOPE decision, kept
separate from this registry's own honest domain claim.

`US_NONFARM_PAYROLLS` and `US_UNEMPLOYMENT_RATE` are deliberately two
SEPARATE canonical indicators even though BLS schedules them as one
release package ("Employment Situation") -- FX-52A Section 11's own
worked example. Both occurrences derived from that one release share a
`release_group_key` (see `domain.economic_calendar_occurrence_
identity.build_release_group_key`); this registry itself does not
model grouping at all, exactly as `EconomicEventOccurrence.
release_group_key`'s own docstring already established -- grouping is
an occurrence-level fact, not a canonical-indicator-level one.
"""

from forex_agent.domain.economic_event_category import EconomicEventCategory
from forex_agent.domain.economic_indicator_definition import EconomicIndicatorDefinition
from forex_agent.domain.macro_frequency import MacroFrequency

US_CPI_YOY = EconomicIndicatorDefinition(
    key="US_CPI_YOY",
    name="US Consumer Price Index (YoY)",
    economy="US",
    currency="USD",
    category=EconomicEventCategory.INFLATION,
    is_numeric=True,
    unit="PERCENT",
    frequency=MacroFrequency.MONTHLY,
)

US_NONFARM_PAYROLLS = EconomicIndicatorDefinition(
    key="US_NONFARM_PAYROLLS",
    name="US Nonfarm Payrolls (change)",
    economy="US",
    currency="USD",
    category=EconomicEventCategory.EMPLOYMENT,
    is_numeric=True,
    unit="THOUSANDS",
    frequency=MacroFrequency.MONTHLY,
)

US_UNEMPLOYMENT_RATE = EconomicIndicatorDefinition(
    key="US_UNEMPLOYMENT_RATE",
    name="US Unemployment Rate",
    economy="US",
    currency="USD",
    category=EconomicEventCategory.EMPLOYMENT,
    is_numeric=True,
    unit="PERCENT",
    frequency=MacroFrequency.MONTHLY,
)

GBP_GDP_QOQ = EconomicIndicatorDefinition(
    key="GBP_GDP_QOQ",
    name="UK GDP Quarterly National Accounts",
    economy="GB",
    currency="GBP",
    category=EconomicEventCategory.GROWTH,
    is_numeric=True,
    unit="PERCENT",
    frequency=MacroFrequency.QUARTERLY,
)

CAD_POLICY_RATE_DECISION = EconomicIndicatorDefinition(
    key="CAD_POLICY_RATE_DECISION",
    name="Bank of Canada Interest Rate Announcement",
    economy="CA",
    currency="CAD",
    category=EconomicEventCategory.POLICY_RATE_DECISION,
    is_numeric=True,
    unit="PERCENT",
    frequency=MacroFrequency.IRREGULAR,
)

ECONOMIC_INDICATOR_DEFINITIONS: tuple[EconomicIndicatorDefinition, ...] = (
    US_CPI_YOY,
    US_NONFARM_PAYROLLS,
    US_UNEMPLOYMENT_RATE,
    GBP_GDP_QOQ,
    CAD_POLICY_RATE_DECISION,
)

_BY_KEY: dict[str, EconomicIndicatorDefinition] = {d.key: d for d in ECONOMIC_INDICATOR_DEFINITIONS}
if len(_BY_KEY) != len(ECONOMIC_INDICATOR_DEFINITIONS):
    raise ValueError("ECONOMIC_INDICATOR_DEFINITIONS contains duplicate keys")  # fail fast


def indicator_by_key(key: str) -> EconomicIndicatorDefinition | None:
    """The canonical definition for `key`, or `None` if `key` is not in
    this registry -- a source adapter must treat `None` as UNMAPPED,
    never fabricate a definition on the fly."""
    return _BY_KEY.get(key)

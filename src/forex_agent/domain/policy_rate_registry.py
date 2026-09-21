"""Canonical, provider-independent policy-rate registry (FX-42).

Defines semantics and provider mappings for the five currencies in the
research universe (USD, EUR, GBP, JPY, CAD). Deliberately does not
ingest, fetch, or store any actual rate history -- see each
`PolicyRateDefinition`'s docstring and `docs/DECISIONS.md`'s FX-42
entry for what is and is not in scope.

Every date below is this story's good-faith research into each
institution's operational history, not a value confirmed against a
live provider -- see `ProviderSeriesMapping.verified` (always `False`
here) and each definition's own `notes`. FX-43 must confirm dates and
provider identifiers before relying on them for ingestion.
"""

from collections import defaultdict
from datetime import UTC, datetime
from itertools import pairwise

from forex_agent.domain.macro_category import MacroCategory
from forex_agent.domain.macro_frequency import MacroFrequency
from forex_agent.domain.macro_series_definition import MacroSeriesDefinition
from forex_agent.domain.policy_rate_definition import PolicyRateDefinition
from forex_agent.domain.provider_series_mapping import ProviderSeriesMapping
from forex_agent.domain.rate_transformation import RateTransformation, RateTransformationKind
from forex_agent.domain.timestamps import UtcTimestamp

REQUIRED_CURRENCIES: frozenset[str] = frozenset({"USD", "EUR", "GBP", "JPY", "CAD"})


def _ts(year: int, month: int, day: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, tzinfo=UTC))


# ---------------------------------------------------------------------------
# USD -- Federal Reserve
#
# The Federal Open Market Committee (FOMC) set a single numeric target rate
# for the effective federal funds rate until December 16, 2008, when (amid
# the financial crisis, approaching the zero lower bound) it switched to
# announcing a target RANGE instead -- a genuine instrument change, not a
# cosmetic one, and this story's primary example of "do not silently splice
# unlike concepts": represented here as two effective-dated definitions
# sharing one canonical series key, with an explicit, versioned
# TARGET_RANGE_MIDPOINT transformation for the second era.
# ---------------------------------------------------------------------------

_USD_SERIES = MacroSeriesDefinition(
    key="USD_POLICY_RATE",
    economy="US",
    currency="USD",
    category=MacroCategory.POLICY_RATE,
    unit="PERCENT",
    frequency=MacroFrequency.IRREGULAR,
)

_USD_TARGET_POINT = PolicyRateDefinition(
    series=_USD_SERIES,
    institution="Federal Reserve",
    instrument_name="Federal Funds Target Rate (single target point)",
    transformation=RateTransformation(
        kind=RateTransformationKind.IDENTITY,
        version="v1",
        description="FOMC-announced single numeric target used as-is.",
    ),
    valid_from=_ts(1954, 7, 1),
    valid_to=_ts(2008, 12, 16),
    provider_mappings=(
        ProviderSeriesMapping(
            provider="FRED",
            provider_series_ids=("DFEDTAR",),
            notes=(
                "FRED's discontinued daily federal funds target rate series "
                "(single target point, pre-December-2008). Commonly cited "
                "FRED series ID; exact availability/start date should be "
                "confirmed against the live FRED API before FX-43 "
                "ingestion. Note: the FOMC's practice of publicly announcing "
                "an explicit numeric target became standardized only in "
                "February 1994; this definition's 1954-07-01 valid_from "
                "instead follows the earlier availability of the "
                "market-observed effective federal funds rate (FRED series "
                "FEDFUNDS/DFF), which is a related but distinct concept "
                "from an FOMC-announced target. FX-43 should treat "
                "pre-1994 target reconstructions with care and document "
                "which of these two concepts it actually ingests."
            ),
        ),
    ),
    notes=(
        "Single target point era. Superseded by a target range starting "
        "December 16, 2008 (FOMC's near-zero-rate policy response to the "
        "financial crisis) -- see the target-range definition below."
    ),
)

_USD_TARGET_RANGE = PolicyRateDefinition(
    series=_USD_SERIES,
    institution="Federal Reserve",
    instrument_name="Federal Funds Target Range Midpoint",
    transformation=RateTransformation(
        kind=RateTransformationKind.TARGET_RANGE_MIDPOINT,
        version="v1",
        description=(
            "Arithmetic mean of the FOMC's published upper and lower target range bounds."
        ),
    ),
    valid_from=_ts(2008, 12, 16),
    valid_to=None,
    provider_mappings=(
        ProviderSeriesMapping(
            provider="FRED",
            provider_series_ids=("DFEDTARU", "DFEDTARL"),
            notes=(
                "FRED's federal funds target range upper/lower bound "
                "series (order matches RateTransformation.apply's "
                "expected (upper, lower) argument order). Commonly cited "
                "FRED series IDs; require confirmation against the live "
                "FRED API before FX-43 ingestion."
            ),
        ),
    ),
    notes=(
        "Target range era, current as of this story. The FOMC has "
        "published an upper/lower target range (rather than a single "
        "target point) continuously since December 16, 2008."
    ),
)


# ---------------------------------------------------------------------------
# EUR -- European Central Bank
#
# The ECB has published three key interest rates since the euro's 1999
# launch: the Main Refinancing Operations (MRO) rate, the Marginal Lending
# Facility rate, and the Deposit Facility Rate (DFR). This registry treats
# the Deposit Facility Rate as the single continuous canonical concept
# throughout: its own definition has not changed, only its RELATIVE
# importance as the euro area's binding money-market signal has shifted
# (particularly since the ECB's post-2014 structural liquidity surplus,
# where the DFR -- not the MRO rate -- is the effective floor for
# overnight rates). That shift in emphasis is documented below, not
# represented as a semantic splice, because the DFR's own definition is
# unchanged across the whole period.
# ---------------------------------------------------------------------------

_EUR_SERIES = MacroSeriesDefinition(
    key="EUR_POLICY_RATE",
    economy="EA",
    currency="EUR",
    category=MacroCategory.POLICY_RATE,
    unit="PERCENT",
    frequency=MacroFrequency.IRREGULAR,
)

_EUR_DEFINITION = PolicyRateDefinition(
    series=_EUR_SERIES,
    institution="European Central Bank",
    instrument_name="Deposit Facility Rate",
    transformation=RateTransformation(
        kind=RateTransformationKind.IDENTITY,
        version="v1",
        description="ECB-announced deposit facility rate used as-is.",
    ),
    valid_from=_ts(1999, 1, 1),
    valid_to=None,
    provider_mappings=(
        ProviderSeriesMapping(
            provider="ECB_SDW",
            provider_series_ids=("FM.D.U2.EUR.4F.KR.DFR.LEV",),
            notes=(
                "Best-effort ECB Data Portal / Statistical Data Warehouse "
                "series key for the deposit facility rate, following the "
                "ECB's documented 'Key ECB interest rates' dataset naming "
                "convention. Exact key string is NOT confirmed against the "
                "live ECB Data Portal in this story -- FX-43 must verify "
                "before ingestion."
            ),
        ),
    ),
    notes=(
        "Chosen over the Main Refinancing Operations (MRO) rate -- the "
        "more commonly cited pre-2008-crisis policy signal -- because, "
        "under the ECB's post-2014 structural liquidity surplus operating "
        "framework, the Deposit Facility Rate (not the MRO rate) is the "
        "effective floor and binding signal for euro area overnight money "
        "markets. The DFR's own definition has been continuous since the "
        "euro's January 1, 1999 launch (Stage Three of EMU); only its "
        "relative importance versus the MRO rate has changed, which this "
        "registry treats as a documentation matter, not a semantic splice. "
        "Negative-rate period: the DFR was negative from June 11, 2014 "
        "(cut to -0.10%) until July 27, 2022 (raised back to 0.00%) -- a "
        "genuinely negative canonical value during that window, not a "
        "data error."
    ),
)


# ---------------------------------------------------------------------------
# GBP -- Bank of England
# ---------------------------------------------------------------------------

_GBP_SERIES = MacroSeriesDefinition(
    key="GBP_POLICY_RATE",
    economy="GB",
    currency="GBP",
    category=MacroCategory.POLICY_RATE,
    unit="PERCENT",
    frequency=MacroFrequency.IRREGULAR,
)

_GBP_DEFINITION = PolicyRateDefinition(
    series=_GBP_SERIES,
    institution="Bank of England",
    instrument_name="Bank Rate",
    transformation=RateTransformation(
        kind=RateTransformationKind.IDENTITY,
        version="v1",
        description="MPC-announced Bank Rate used as-is.",
    ),
    valid_from=_ts(1997, 6, 1),
    valid_to=None,
    provider_mappings=(
        ProviderSeriesMapping(
            provider="BOE_DATABASE",
            provider_series_ids=("IUDBEDR",),
            notes=(
                "Best-effort Bank of England Interactive Statistical "
                "Database series code for Bank Rate, following commonly "
                "cited public references. NOT confirmed against the live "
                "BoE database in this story -- FX-43 must verify."
            ),
        ),
    ),
    notes=(
        "valid_from marks the Monetary Policy Committee's establishment "
        "(June 1997, operational independence for UK interest-rate "
        "policy), a well-documented modern-framework starting point -- not "
        "a claim about the earliest Bank of England rate-setting history. "
        "The single continuous instrument was renamed from 'Repo Rate' to "
        "'Bank Rate' in 2006; this is a label change to the same "
        "operational instrument, not a semantic splice, so it is "
        "documented here rather than represented as a second definition."
    ),
)


# ---------------------------------------------------------------------------
# JPY -- Bank of Japan
# ---------------------------------------------------------------------------

_JPY_SERIES = MacroSeriesDefinition(
    key="JPY_POLICY_RATE",
    economy="JP",
    currency="JPY",
    category=MacroCategory.POLICY_RATE,
    unit="PERCENT",
    frequency=MacroFrequency.IRREGULAR,
)

_JPY_DEFINITION = PolicyRateDefinition(
    series=_JPY_SERIES,
    institution="Bank of Japan",
    instrument_name="Short-Term Policy Interest Rate",
    transformation=RateTransformation(
        kind=RateTransformationKind.IDENTITY,
        version="v1",
        description="BoJ-announced short-term policy rate used as-is.",
    ),
    valid_from=_ts(1998, 4, 1),
    valid_to=None,
    provider_mappings=(
        ProviderSeriesMapping(
            provider="BOJ_TIME_SERIES_DATA_SEARCH",
            provider_series_ids=("VERIFY_BOJ_SHORT_TERM_POLICY_RATE",),
            notes=(
                "Placeholder -- no specific Bank of Japan Time-Series Data "
                "Search series code is asserted here with confidence. "
                "FX-43 must identify and verify the correct code (and "
                "confirm whether FRED or another aggregator offers an "
                "equivalent, better-documented series) before ingestion."
            ),
        ),
    ),
    notes=(
        "valid_from marks the new Bank of Japan Act taking effect (April "
        "1, 1998), which gave the BoJ its current operational "
        "independence -- a well-documented modern-framework starting "
        "point, not a claim about earlier BoJ history. Represented as a "
        "single continuous concept ('the short-term interest rate the BoJ "
        "sets as its primary policy instrument') despite substantial "
        "operational-framework change over time: an uncollateralized "
        "overnight call rate target before 2016; a negative rate "
        "(-0.10%) applied to a tier of financial institutions' current "
        "account balances ('the policy-rate balance') under "
        "quantitative/qualitative easing with yield curve control from "
        "January 29, 2016 (effective February 16, 2016) to March 19, "
        "2024; and an uncollateralized overnight call rate target again "
        "from March 19, 2024 onward, when negative rates and yield curve "
        "control ended. In every regime the BoJ has published a single "
        "target number (not a range), so IDENTITY remains the correct "
        "transformation throughout -- only the *mechanism* by which that "
        "number was implemented changed, not its role as a single "
        "canonical scalar. If FX-43 ingestion finds this mechanism change "
        "in fact requires different derivation logic (not just a "
        "different rate level), this single definition should be split "
        "into effective-dated definitions at that point, following the "
        "USD precedent above."
    ),
)


# ---------------------------------------------------------------------------
# CAD -- Bank of Canada
# ---------------------------------------------------------------------------

_CAD_SERIES = MacroSeriesDefinition(
    key="CAD_POLICY_RATE",
    economy="CA",
    currency="CAD",
    category=MacroCategory.POLICY_RATE,
    unit="PERCENT",
    frequency=MacroFrequency.IRREGULAR,
)

_CAD_DEFINITION = PolicyRateDefinition(
    series=_CAD_SERIES,
    institution="Bank of Canada",
    instrument_name="Overnight Rate Target",
    transformation=RateTransformation(
        kind=RateTransformationKind.IDENTITY,
        version="v1",
        description="Bank-of-Canada-announced overnight rate target used as-is.",
    ),
    valid_from=_ts(1991, 2, 1),
    valid_to=None,
    provider_mappings=(
        ProviderSeriesMapping(
            provider="BOC_VALET",
            provider_series_ids=("VERIFY_BOC_OVERNIGHT_RATE_TARGET",),
            notes=(
                "Placeholder -- no specific Bank of Canada Valet API "
                "series code is asserted here with confidence. FX-43 must "
                "identify and verify the correct code before ingestion."
            ),
        ),
    ),
    notes=(
        "valid_from marks the Bank of Canada and Government of Canada's "
        "joint announcement of explicit inflation-control targets "
        "(February 1991), a well-documented modern-framework starting "
        "point -- not a claim about earlier Bank of Canada rate-setting "
        "history or about exactly when the current overnight-rate-target "
        "operating-band mechanism (the Bank Rate and deposit rate each "
        "sitting 25bp above/below the target) was formalized; that detail "
        "should be confirmed, and split into an effective-dated "
        "definition if it turns out to represent a genuine derivation "
        "change, before FX-43 ingestion."
    ),
)


POLICY_RATE_DEFINITIONS: tuple[PolicyRateDefinition, ...] = (
    _USD_TARGET_POINT,
    _USD_TARGET_RANGE,
    _EUR_DEFINITION,
    _GBP_DEFINITION,
    _JPY_DEFINITION,
    _CAD_DEFINITION,
)


def validate_registry(definitions: tuple[PolicyRateDefinition, ...]) -> None:
    """Registry-wide invariants that no single `PolicyRateDefinition`
    can check on its own -- run at import time below (fail fast on a
    malformed registry) and reusable directly in tests against
    deliberately broken fixtures.

    Checks, per currency:
      - all definitions share exactly one canonical `series.key`;
      - validity windows do not overlap;
      - validity windows leave no gap between consecutive definitions
        (every instant from the earliest `valid_from` onward is
        covered by exactly one definition).
    """
    by_currency: dict[str, list[PolicyRateDefinition]] = defaultdict(list)
    for definition in definitions:
        by_currency[definition.series.currency].append(definition)

    for currency, currency_definitions in by_currency.items():
        keys = {d.series.key for d in currency_definitions}
        if len(keys) != 1:
            raise ValueError(
                f"{currency}: all definitions must share one canonical series key, "
                f"got {sorted(keys)}"
            )

        ordered = sorted(currency_definitions, key=lambda d: d.valid_from.value)
        for earlier, later in pairwise(ordered):
            if earlier.valid_to is None:
                raise ValueError(
                    f"{currency}: definition starting {earlier.valid_from.value.isoformat()} "
                    "has no valid_to but is followed by another definition "
                    f"starting {later.valid_from.value.isoformat()} -- overlapping validity"
                )
            if earlier.valid_to.value > later.valid_from.value:
                raise ValueError(
                    f"{currency}: overlapping validity windows between definitions "
                    f"starting {earlier.valid_from.value.isoformat()} and "
                    f"{later.valid_from.value.isoformat()}"
                )
            if earlier.valid_to.value < later.valid_from.value:
                raise ValueError(
                    f"{currency}: gap in validity between definitions starting "
                    f"{earlier.valid_from.value.isoformat()} and "
                    f"{later.valid_from.value.isoformat()}"
                )

    missing = REQUIRED_CURRENCIES - set(by_currency)
    if missing:
        raise ValueError(f"registry is missing required currencies: {sorted(missing)}")


validate_registry(POLICY_RATE_DEFINITIONS)  # fail fast at import time


def definitions_for_currency(currency: str) -> tuple[PolicyRateDefinition, ...]:
    """All effective-dated definitions for `currency`, ordered by
    `valid_from`. Empty if `currency` is not in the registry."""
    matches = [d for d in POLICY_RATE_DEFINITIONS if d.series.currency == currency]
    return tuple(sorted(matches, key=lambda d: d.valid_from.value))


def definition_as_of(currency: str, as_of: UtcTimestamp) -> PolicyRateDefinition | None:
    """The single definition for `currency` whose validity window
    covers `as_of`, or `None` if `currency` is not in the registry or
    `as_of` precedes that currency's earliest `valid_from`."""
    for definition in definitions_for_currency(currency):
        if definition.covers(as_of):
            return definition
    return None


def canonical_series_for_currency(currency: str) -> MacroSeriesDefinition | None:
    """The one canonical `MacroSeriesDefinition` shared by every
    definition of `currency`, or `None` if `currency` is not in the
    registry. Stable across effective-dated definitions -- see
    `validate_registry`."""
    matches = definitions_for_currency(currency)
    return matches[0].series if matches else None

"""Canonical, provider-independent policy-rate registry (FX-42; hardened
FX-42H, FX-42H.1).

Defines semantics and provider mappings for the five currencies in the
research universe (USD, EUR, GBP, JPY, CAD). Deliberately does not
ingest, fetch, or store any actual rate history -- see each
`PolicyRateDefinition`'s docstring and `docs/DECISIONS.md`'s FX-42/
FX-42H/FX-42H.1 entries for what is and is not in scope.

Every date below is this story's good-faith research into each
institution's operational history, not a value confirmed against a
live provider -- see `ProviderSeriesMapping.verified` (always `False`
here) and each definition's own `notes`. FX-43 must confirm dates and
provider identifiers before relying on them for ingestion.

FX-42H hardening summary (see `docs/DECISIONS.md`'s FX-42H entry for
the full reasoning):
  - USD's target-point era now starts February 4, 1994 (the first FOMC
    meeting after which policy changes were announced immediately/
    explicitly), not 1954 -- the earlier FRED `DFEDTAR` history is a
    retrospective reconstruction, not contemporaneously published data.
  - EUR's canonical scalar is now the ECB Main Refinancing Operations
    (MRO) minimum-bid/fixed rate, not the Deposit Facility Rate (DFR)
    continuously -- DFR is documented as a candidate future
    regime-aware feature instead.
  - JPY no longer claims one continuous short-term policy-rate
    definition: genuine operational-regime changes are represented as
    distinct definitions, with gaps during quantity-target eras where
    `definition_as_of` correctly returns `None`.
  - CAD's overnight-target framework now starts February 1999, not 1991.
  - `validate_registry` checks that every definition for one currency
    shares not just the same `series.key` string but fully identical
    `MacroSeriesDefinition` semantics.

FX-42H.1 hardening summary (see `docs/DECISIONS.md`'s FX-42H.1 entry
for the full reasoning):
  - FX-42H's blanket gap tolerance (ANY gap between consecutive
    definitions was silently accepted) is replaced by
    `DeclaredPolicyRateGap`: every gap must now be explicitly declared,
    with a non-empty reason, or registry validation fails. An
    undeclared gap is a validation error, not a silently accepted state.
  - JPY's 2006-2013 overnight-call-rate era is split at October 5,
    2010, when the BoJ changed its target from a single point
    (~0.1%) to an explicit range (~0% to 0.1%) under "Comprehensive
    Monetary Easing" -- the same target-range/midpoint pattern already
    used for USD and JPY's 2024 transitional range.
  - JPY's Policy-Rate Balance era now starts February 16, 2016 (the
    -0.10% rate's EFFECTIVE date), not January 29, 2016 (its
    ANNOUNCEMENT/release date) -- `released_at` can precede
    `effective_at` (FX-41's own distinction), and the preceding QQE
    quantity-target gap is extended to cover the announcement-to-effect
    window, since the prior operating framework arguably still governed
    until the new one actually took effect.
"""

from collections import defaultdict
from datetime import UTC, datetime
from itertools import pairwise

from forex_agent.domain.declared_policy_rate_gap import DeclaredPolicyRateGap
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
#
# FX-42H: the target-point era's valid_from moved from 1954-07-01 to
# 1994-02-04 -- see that definition's notes for why.
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
    valid_from=_ts(1994, 2, 4),
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
                "ingestion."
            ),
        ),
    ),
    notes=(
        "FX-42H correction: valid_from is February 4, 1994 -- the first "
        "FOMC meeting after which the Committee began announcing policy "
        "changes immediately and explicitly, the point at which an "
        "explicit numeric target became a contemporaneously PUBLISHED "
        "fact rather than something market participants had to infer. "
        "FRED's DFEDTAR series extends back further (into the early "
        "1980s), but that earlier portion is a RETROSPECTIVE "
        "RECONSTRUCTION by the data provider/researchers, not a value "
        "that was itself publicly announced at the time -- it is "
        "therefore unsuitable as pristine point-in-time historical "
        "information, and this registry does not claim any canonical "
        "definition covers it. If a future story finds a genuine "
        "historical need for the pre-1994 reconstructed data, it should "
        "be modeled as an explicitly-labeled separate, lower-trust "
        "definition, not silently folded into this one. Single target "
        "point era superseded by a target range starting December 16, "
        "2008 (FOMC's near-zero-rate policy response to the financial "
        "crisis) -- see the target-range definition below."
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
# FX-42H correction: the canonical scalar is now the Main Refinancing
# Operations (MRO) minimum-bid/fixed rate, not the Deposit Facility Rate
# (DFR). FX-42 originally chose DFR for its post-2014 structural-liquidity-
# surplus relevance, but MRO is the historically comparable scalar that has
# been the ECB's headline-cited policy rate across its full history,
# including the pre-2008 corridor-system era when DFR was a rarely-binding
# floor rather than a meaningful policy signal. DFR is retained here only
# as documentation of a candidate future regime-aware feature -- this
# registry does NOT silently switch MRO to DFR to improve any later
# research result; a switch, if ever made, must be an explicit, documented
# registry change with its own reasoning, not a quiet substitution.
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
    instrument_name="Main Refinancing Operations Rate (minimum bid/fixed rate)",
    transformation=RateTransformation(
        kind=RateTransformationKind.IDENTITY,
        version="v1",
        description="ECB-announced MRO minimum bid rate / fixed rate used as-is.",
    ),
    valid_from=_ts(1999, 1, 1),
    valid_to=None,
    provider_mappings=(
        ProviderSeriesMapping(
            provider="ECB_SDW",
            provider_series_ids=("FM.D.U2.EUR.4F.KR.MRR_RT.LEV",),
            notes=(
                "ECB Data Portal / Statistical Data Warehouse series key "
                "for the MRO minimum-bid/fixed rate, per FX-42H's explicit "
                "instruction -- use this key unless primary-source "
                "verification shows a better continuous choice. Exact key "
                "string is NOT confirmed against the live ECB Data Portal "
                "in this story -- FX-43 must verify before ingestion."
            ),
        ),
    ),
    notes=(
        "FX-42H correction: chosen over the Deposit Facility Rate (DFR) -- "
        "FX-42's original choice -- for the INITIAL cross-currency "
        "policy-rate-differential feature, because MRO is the "
        "historically comparable scalar across the ECB's full history "
        "(the euro's January 1, 1999 launch onward): under the ECB's "
        "pre-2008 'corridor system', MRO was the actively-managed, "
        "headline-cited policy rate, with DFR a rarely-binding floor far "
        "below it. Only under the post-2014 structural-liquidity-surplus "
        "'floor system' does DFR become the effective binding rate for "
        "overnight money markets -- a genuine regime difference, not "
        "just an emphasis shift, which is why FX-42's DFR choice did not "
        "hold up under this hardening pass. DFR is documented here as a "
        "CANDIDATE for a later, explicitly regime-aware feature (e.g. "
        "applicable only from the floor-system era onward), not "
        "discarded -- but this initial single continuous series must not "
        "silently switch from MRO to DFR merely because doing so would "
        "improve some later research result; any such switch requires "
        "its own explicit, documented registry change. Negative-rate "
        "period, for context: the DFR (not MRO) was negative from June "
        "11, 2014 until July 27, 2022; MRO itself only briefly touched "
        "0.00% (March 2016-July 2022) and was never negative."
    ),
)


# ---------------------------------------------------------------------------
# GBP -- Bank of England (unchanged by FX-42H/FX-42H.1)
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
                "Bank of England Interactive Statistical Database series "
                "code for Bank Rate -- a confirmed candidate ID per FX-42H "
                "(kept unchanged from FX-42). Still NOT confirmed against "
                "the live BoE database in this story -- FX-43 must verify."
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
#
# FX-42H correction: FX-42 originally claimed ONE continuous short-term
# policy-rate definition for the BoJ's entire post-1998 history. That
# claim does not survive scrutiny: the BoJ's OPERATING TARGET itself has
# genuinely changed instrument type multiple times, not just level --
# during its quantitative-easing eras the operating target was the
# outstanding BALANCE of current accounts at the BoJ (a quantity, in yen,
# not a rate in percent), which is not a "policy rate" in this registry's
# sense at all. Representing those eras with a borrowed/nearby rate value
# would misrepresent what was actually being targeted.
#
# FX-42H.1: the 2006-2013 overnight-call-rate era is further split at
# October 5, 2010 (the BoJ's "Comprehensive Monetary Easing" switch from a
# single-point target to an explicit 0%-0.1% range), and the Policy-Rate
# Balance era now starts at the -0.10% rate's EFFECTIVE date (February 16,
# 2016), not its announcement date (January 29, 2016) -- see that
# definition's own notes on released_at vs effective_at. Both
# quantity-target gaps are now DECLARED explicitly (`_JPY_GAPS` below),
# not just silently tolerated.
#
# This registry represents six distinct rate-target eras, with two
# explicitly DECLARED gaps during the quantity-target eras:
#
#   1998-04-01 .. 2001-03-19   overnight call rate target        (JPY-1)
#   2001-03-19 .. 2006-03-09   [DECLARED GAP] QEP (balance target)
#   2006-03-09 .. 2010-10-05   overnight call rate target        (JPY-2A)
#   2010-10-05 .. 2013-04-04   overnight call rate target RANGE  (JPY-2B)
#   2013-04-04 .. 2016-02-16   [DECLARED GAP] QQE (monetary base target)
#   2016-02-16 .. 2024-03-19   policy-rate balance (NIRP + YCC)  (JPY-3)
#   2024-03-19 .. 2024-07-31   call rate target range 0-0.1%     (JPY-4)
#   2024-07-31 ..              call rate target (single point)  (JPY-5)
#
# Every boundary date above is this story's good-faith research, held to
# a LOWER confidence bar than the other four currencies given the
# operational complexity involved -- FX-42H/FX-42H.1 are explicit that
# exact boundaries/effective dates must be confirmed against BoJ primary
# sources before FX-43 relies on any of them. BoJ provider identifiers
# remain entirely unresolved (see each mapping's notes) -- no
# primary-source mapping has been established for any BoJ era yet.
# ---------------------------------------------------------------------------

_JPY_SERIES = MacroSeriesDefinition(
    key="JPY_POLICY_RATE",
    economy="JP",
    currency="JPY",
    category=MacroCategory.POLICY_RATE,
    unit="PERCENT",
    frequency=MacroFrequency.IRREGULAR,
)

_JPY_CALL_RATE_ERA_1 = PolicyRateDefinition(
    series=_JPY_SERIES,
    institution="Bank of Japan",
    instrument_name="Uncollateralized Overnight Call Rate Target",
    transformation=RateTransformation(
        kind=RateTransformationKind.IDENTITY,
        version="v1",
        description="BoJ-announced overnight call rate target used as-is.",
    ),
    valid_from=_ts(1998, 4, 1),
    valid_to=_ts(2001, 3, 19),
    provider_mappings=(
        ProviderSeriesMapping(
            provider="BOJ_TIME_SERIES_DATA_SEARCH",
            provider_series_ids=("VERIFY_BOJ_CALL_RATE_TARGET_1998_2001",),
            notes=(
                "Unresolved (FX-42H): no specific Bank of Japan "
                "Time-Series Data Search series code is asserted here. "
                "FX-43 must identify and verify the correct code before "
                "ingestion -- BoJ provider mapping is entirely "
                "unestablished for every JPY era in this registry."
            ),
        ),
    ),
    notes=(
        "valid_from marks the new Bank of Japan Act taking effect (April "
        "1, 1998), which gave the BoJ its current operational "
        "independence. Covers the early explicit call-rate-target era, "
        "including the Zero Interest Rate Policy (ZIRP, February "
        "1999-August 2000). Ends when the BoJ adopted Quantitative "
        "Easing Policy (QEP) on March 19, 2001, switching its OPERATING "
        "TARGET from the overnight call rate to the outstanding balance "
        "of current accounts at the BoJ -- a quantity target, not a rate "
        "target, and therefore not representable by this registry (see "
        "the declared gap that follows)."
    ),
)

_JPY_CALL_RATE_ERA_2A = PolicyRateDefinition(
    series=_JPY_SERIES,
    institution="Bank of Japan",
    instrument_name="Uncollateralized Overnight Call Rate Target",
    transformation=RateTransformation(
        kind=RateTransformationKind.IDENTITY,
        version="v1",
        description="BoJ-announced overnight call rate target used as-is.",
    ),
    valid_from=_ts(2006, 3, 9),
    valid_to=_ts(2010, 10, 5),
    provider_mappings=(
        ProviderSeriesMapping(
            provider="BOJ_TIME_SERIES_DATA_SEARCH",
            provider_series_ids=("VERIFY_BOJ_CALL_RATE_TARGET_2006_2010",),
            notes=(
                "Unresolved (FX-42H.1): no specific Bank of Japan "
                "Time-Series Data Search series code is asserted here. "
                "FX-43 must identify and verify."
            ),
        ),
    ),
    notes=(
        "Reversion to an explicit single-point overnight call rate "
        "target when QEP ended (March 9, 2006), through the 2008-2010 "
        "financial-crisis rate cuts. Ends October 5, 2010, when the BoJ "
        "introduced 'Comprehensive Monetary Easing' and changed its "
        "target from a single point (around 0.1%) to an explicit range "
        "(around 0% to 0.1%) -- a genuine instrument-shape change, not "
        "just a level change, represented by splitting into a second, "
        "TARGET_RANGE_MIDPOINT definition (FX-42H.1) rather than folding "
        "a range into this single-point definition."
    ),
)

_JPY_CALL_RATE_ERA_2B = PolicyRateDefinition(
    series=_JPY_SERIES,
    institution="Bank of Japan",
    instrument_name="Uncollateralized Overnight Call Rate Target Range",
    transformation=RateTransformation(
        kind=RateTransformationKind.TARGET_RANGE_MIDPOINT,
        version="v1",
        description=(
            "Arithmetic mean of the BoJ's published 'Comprehensive Monetary "
            "Easing' call rate target range (around 0% to 0.1%)."
        ),
    ),
    valid_from=_ts(2010, 10, 5),
    valid_to=_ts(2013, 4, 4),
    provider_mappings=(
        ProviderSeriesMapping(
            provider="BOJ_TIME_SERIES_DATA_SEARCH",
            provider_series_ids=(
                "VERIFY_BOJ_CALL_RATE_UPPER_2010_2013",
                "VERIFY_BOJ_CALL_RATE_LOWER_2010_2013",
            ),
            notes=(
                "Unresolved (FX-42H.1): no specific Bank of Japan "
                "Time-Series Data Search series codes are asserted here. "
                "FX-43 must identify and verify both the upper and lower "
                "bound series."
            ),
        ),
    ),
    notes=(
        "FX-42H.1: split out from the preceding single-point definition "
        "because the BoJ explicitly changed its target from a single "
        "point (around 0.1%) to a range (around 0% to 0.1%) on October "
        "5, 2010 under 'Comprehensive Monetary Easing' -- the registry "
        "already represents published target ranges via "
        "TARGET_RANGE_MIDPOINT for USD and JPY's 2024 transitional "
        "range, so the same treatment applies here rather than silently "
        "keeping this era under a single-point IDENTITY definition. Ends "
        "April 4, 2013, when the BoJ adopted Quantitative and "
        "Qualitative Monetary Easing (QQE), switching its main operating "
        "target to the monetary base -- again a quantity target, not a "
        "rate target (see the declared gap that follows). This "
        "QQE-start date carries lower confidence than most other "
        "boundaries in this registry and should be an early FX-43 "
        "verification priority."
    ),
)

_JPY_POLICY_RATE_BALANCE = PolicyRateDefinition(
    series=_JPY_SERIES,
    institution="Bank of Japan",
    instrument_name="Interest Rate on Policy-Rate Balances (Negative Interest Rate Policy + YCC)",
    transformation=RateTransformation(
        kind=RateTransformationKind.IDENTITY,
        version="v1",
        description="BoJ-announced rate on the policy-rate tier of current account balances.",
    ),
    valid_from=_ts(2016, 2, 16),
    valid_to=_ts(2024, 3, 19),
    provider_mappings=(
        ProviderSeriesMapping(
            provider="BOJ_TIME_SERIES_DATA_SEARCH",
            provider_series_ids=("VERIFY_BOJ_POLICY_RATE_BALANCE_2016_2024",),
            notes=(
                "Unresolved (FX-42H): no specific Bank of Japan "
                "Time-Series Data Search series code is asserted here. "
                "FX-43 must identify and verify."
            ),
        ),
    ),
    notes=(
        "A genuinely different operational instrument from the plain "
        "overnight call rate target, not just a lower rate level: "
        "'Quantitative and Qualitative Monetary Easing with a Negative "
        "Interest Rate' applies -0.10% to only the 'policy-rate balance' "
        "tier of financial institutions' current accounts at the BoJ (a "
        "three-tier structure, not a single economy-wide rate). Yield "
        "Curve Control (YCC) was added September 2016, targeting the "
        "10-year JGB yield alongside this short-term rate -- not itself "
        "represented here (out of scope: this registry tracks the "
        "SHORT-TERM policy rate only). Ends when the BoJ ended both NIRP "
        "and YCC on March 19, 2024. "
        "FX-42H.1 correction: valid_from is February 16, 2016 -- the "
        "date the -0.10% rate actually took EFFECT -- not January 29, "
        "2016, when the BoJ ANNOUNCED the policy. released_at "
        "(announcement/publication) can precede effective_at (when a "
        "value takes legal/economic effect); FX-41's "
        "`MacroObservationVintage` already carries both fields "
        "separately for exactly this reason. FX-43 should therefore "
        "expect, for the observation marking this transition, "
        "released_at around January 29, 2016 and effective_at around "
        "February 16, 2016 -- and must not collapse the two into a "
        "single timestamp. The preceding QQE quantity-target gap is "
        "extended through February 16, 2016 (not just to the January 29 "
        "announcement) since the prior monetary-base-target framework "
        "arguably still governed policy until the new rate actually took "
        "effect."
    ),
)

_JPY_CALL_RATE_RANGE_2024 = PolicyRateDefinition(
    series=_JPY_SERIES,
    institution="Bank of Japan",
    instrument_name="Uncollateralized Overnight Call Rate Target Range",
    transformation=RateTransformation(
        kind=RateTransformationKind.TARGET_RANGE_MIDPOINT,
        version="v1",
        description="Arithmetic mean of the BoJ's published 0% to 0.1% call rate target range.",
    ),
    valid_from=_ts(2024, 3, 19),
    valid_to=_ts(2024, 7, 31),
    provider_mappings=(
        ProviderSeriesMapping(
            provider="BOJ_TIME_SERIES_DATA_SEARCH",
            provider_series_ids=(
                "VERIFY_BOJ_CALL_RATE_UPPER_2024",
                "VERIFY_BOJ_CALL_RATE_LOWER_2024",
            ),
            notes=(
                "Unresolved (FX-42H): no specific Bank of Japan "
                "Time-Series Data Search series codes are asserted here. "
                "FX-43 must identify and verify both the upper and lower "
                "bound series."
            ),
        ),
    ),
    notes=(
        "Short transitional regime immediately following the March 19, "
        "2024 end of NIRP/YCC: the BoJ guided the uncollateralized "
        "overnight call rate to 'around 0 to 0.1 percent' -- a range, "
        "not a single point, hence TARGET_RANGE_MIDPOINT like USD's "
        "post-2008 target-range era and JPY's own 2010-2013 range era. "
        "Ends July 31, 2024, when the BoJ raised the target to a single "
        "point (around 0.25%)."
    ),
)

_JPY_CALL_RATE_ERA_CURRENT = PolicyRateDefinition(
    series=_JPY_SERIES,
    institution="Bank of Japan",
    instrument_name="Uncollateralized Overnight Call Rate Target",
    transformation=RateTransformation(
        kind=RateTransformationKind.IDENTITY,
        version="v1",
        description="BoJ-announced overnight call rate target used as-is.",
    ),
    valid_from=_ts(2024, 7, 31),
    valid_to=None,
    provider_mappings=(
        ProviderSeriesMapping(
            provider="BOJ_TIME_SERIES_DATA_SEARCH",
            provider_series_ids=("VERIFY_BOJ_CALL_RATE_TARGET_2024_PRESENT",),
            notes=(
                "Unresolved (FX-42H): no specific Bank of Japan "
                "Time-Series Data Search series code is asserted here. "
                "FX-43 must identify and verify."
            ),
        ),
    ),
    notes=(
        "Single-point call rate target regime resumed July 31, 2024 "
        "(raised to around 0.25%), current as of this story -- subject "
        "to further single-point target changes over time within this "
        "same definition (a rate LEVEL change is not an instrument "
        "change and does not require a new definition, matching how "
        "every other currency in this registry handles ordinary rate "
        "moves)."
    ),
)

_JPY_GAPS: tuple[DeclaredPolicyRateGap, ...] = (
    DeclaredPolicyRateGap(
        currency="JPY",
        start=_ts(2001, 3, 19),
        end=_ts(2006, 3, 9),
        reason=(
            "Quantitative Easing Policy (QEP): the BoJ's operating target "
            "was the outstanding balance of current accounts at the BoJ "
            "(a quantity, denominated in yen), not a scalar short-term "
            "interest rate -- no canonical POLICY_RATE definition can "
            "represent this window without misrepresenting what was "
            "actually being targeted."
        ),
    ),
    DeclaredPolicyRateGap(
        currency="JPY",
        start=_ts(2013, 4, 4),
        end=_ts(2016, 2, 16),
        reason=(
            "Quantitative and Qualitative Monetary Easing (QQE): the "
            "BoJ's main operating target was the monetary base (again a "
            "quantity, not a rate). Extended through February 16, 2016 "
            "(the -0.10% policy-rate balance's EFFECTIVE date) rather "
            "than stopping at January 29, 2016 (its announcement date) "
            "-- see _JPY_POLICY_RATE_BALANCE's notes on released_at vs "
            "effective_at."
        ),
    ),
)


# ---------------------------------------------------------------------------
# CAD -- Bank of Canada
#
# FX-42H correction: valid_from moved from 1991-02-01 (the Bank of
# Canada/Government of Canada's joint inflation-control target
# announcement) to 1999-02-01 -- per FX-42H's explicit guidance, the
# verified modern overnight-target framework boundary, giving a clean,
# internationally comparable single-point target definition rather than
# reaching back to a period whose operating framework has not been
# confirmed to match.
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
    valid_from=_ts(1999, 2, 1),
    valid_to=None,
    provider_mappings=(
        ProviderSeriesMapping(
            provider="BOC_VALET",
            provider_series_ids=("V39079",),
            notes=(
                "Bank of Canada Valet API series code for the overnight "
                "rate target, per FX-42H's explicit instruction -- "
                "replaces FX-42's placeholder. Still subject to FX-43's "
                "live API verification before ingestion."
            ),
        ),
    ),
    notes=(
        "FX-42H correction: valid_from is February 1999 -- the verified "
        "modern overnight-target framework boundary, giving a clean, "
        "internationally comparable single-point target definition. "
        "FX-42's original 1991-02-01 (the Bank of Canada/Government of "
        "Canada's joint inflation-control target announcement) reached "
        "back to a period whose operating framework was not confirmed to "
        "match this definition's instrument, and has been removed rather "
        "than retained as a separate earlier era -- if a future story "
        "confirms the pre-1999 framework's exact instrument via BoC "
        "primary sources, it should be added as its own explicitly "
        "distinct definition, not backdated into this one."
    ),
)


POLICY_RATE_DEFINITIONS: tuple[PolicyRateDefinition, ...] = (
    _USD_TARGET_POINT,
    _USD_TARGET_RANGE,
    _EUR_DEFINITION,
    _GBP_DEFINITION,
    _JPY_CALL_RATE_ERA_1,
    _JPY_CALL_RATE_ERA_2A,
    _JPY_CALL_RATE_ERA_2B,
    _JPY_POLICY_RATE_BALANCE,
    _JPY_CALL_RATE_RANGE_2024,
    _JPY_CALL_RATE_ERA_CURRENT,
    _CAD_DEFINITION,
)

DECLARED_GAPS: tuple[DeclaredPolicyRateGap, ...] = _JPY_GAPS


def validate_registry(
    definitions: tuple[PolicyRateDefinition, ...],
    gaps: tuple[DeclaredPolicyRateGap, ...] = (),
) -> None:
    """Registry-wide invariants that no single `PolicyRateDefinition`
    can check on its own -- run at import time below (fail fast on a
    malformed registry) and reusable directly in tests against
    deliberately broken fixtures.

    Checks, per currency:
      - all definitions share fully identical canonical
        `MacroSeriesDefinition` semantics -- not merely the same
        `series.key` string (FX-42H: a currency's definitions could
        otherwise share a key while silently disagreeing on economy,
        unit, category, or frequency);
      - no declared gap overlaps a policy-rate definition of the same
        currency (FX-42H.1);
      - definitions do not overlap each other;
      - any gap between two consecutive definitions is covered by
        EXACTLY one declared gap with a matching `start`/`end` --
        otherwise this is an UNDECLARED gap and validation fails
        (FX-42H.1: replaces FX-42H's blanket gap tolerance, which could
        not distinguish an intentional gap from an accidental one);
      - declared gaps for the same currency do not overlap each other.

    `gaps` defaults to `()` -- a registry with no currency needing a
    gap need not pass any.
    """
    by_currency: dict[str, list[PolicyRateDefinition]] = defaultdict(list)
    for definition in definitions:
        by_currency[definition.series.currency].append(definition)

    gaps_by_currency: dict[str, list[DeclaredPolicyRateGap]] = defaultdict(list)
    for gap in gaps:
        gaps_by_currency[gap.currency].append(gap)

    for currency, currency_definitions in by_currency.items():
        distinct_series = {d.series for d in currency_definitions}
        if len(distinct_series) != 1:
            raise ValueError(
                f"{currency}: all definitions must share identical canonical "
                f"MacroSeriesDefinition semantics, not merely the same key -- "
                f"got {len(distinct_series)} distinct series definitions"
            )

        currency_gaps = gaps_by_currency.get(currency, [])

        for definition in currency_definitions:
            definition_end = definition.valid_to.value if definition.valid_to else None
            for gap in currency_gaps:
                overlaps_definition = definition.valid_from.value < gap.end.value and (
                    definition_end is None or definition_end > gap.start.value
                )
                if overlaps_definition:
                    raise ValueError(
                        f"{currency}: declared gap "
                        f"{gap.start.value.isoformat()}..{gap.end.value.isoformat()} "
                        f"overlaps a policy-rate definition starting "
                        f"{definition.valid_from.value.isoformat()}"
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
                matching = [
                    gap
                    for gap in currency_gaps
                    if gap.start.value == earlier.valid_to.value
                    and gap.end.value == later.valid_from.value
                ]
                if not matching:
                    raise ValueError(
                        f"{currency}: undeclared gap between the definition ending "
                        f"{earlier.valid_to.value.isoformat()} and the definition "
                        f"starting {later.valid_from.value.isoformat()} -- declare it "
                        "explicitly via a DeclaredPolicyRateGap, or fix the boundary "
                        "if this was unintentional"
                    )

        ordered_gaps = sorted(currency_gaps, key=lambda g: g.start.value)
        for earlier_gap, later_gap in pairwise(ordered_gaps):
            if earlier_gap.end.value > later_gap.start.value:
                raise ValueError(
                    f"{currency}: declared gaps overlap -- "
                    f"{earlier_gap.start.value.isoformat()}..{earlier_gap.end.value.isoformat()} "
                    f"and "
                    f"{later_gap.start.value.isoformat()}..{later_gap.end.value.isoformat()}"
                )

    missing = REQUIRED_CURRENCIES - set(by_currency)
    if missing:
        raise ValueError(f"registry is missing required currencies: {sorted(missing)}")


validate_registry(POLICY_RATE_DEFINITIONS, DECLARED_GAPS)  # fail fast at import time


def definitions_for_currency(currency: str) -> tuple[PolicyRateDefinition, ...]:
    """All effective-dated definitions for `currency`, ordered by
    `valid_from`. Empty if `currency` is not in the registry."""
    matches = [d for d in POLICY_RATE_DEFINITIONS if d.series.currency == currency]
    return tuple(sorted(matches, key=lambda d: d.valid_from.value))


def definition_as_of(currency: str, as_of: UtcTimestamp) -> PolicyRateDefinition | None:
    """The single definition for `currency` whose validity window
    covers `as_of`, or `None` if `currency` is not in the registry,
    `as_of` precedes that currency's earliest `valid_from`, or `as_of`
    falls within a declared gap between two definitions (FX-42H.1 --
    see JPY's quantity-target eras)."""
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

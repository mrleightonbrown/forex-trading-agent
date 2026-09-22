from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.declared_policy_rate_gap import DeclaredPolicyRateGap
from forex_agent.domain.macro_category import MacroCategory
from forex_agent.domain.macro_frequency import MacroFrequency
from forex_agent.domain.macro_series_definition import MacroSeriesDefinition
from forex_agent.domain.policy_rate_definition import PolicyRateDefinition
from forex_agent.domain.policy_rate_registry import (
    DECLARED_GAPS,
    POLICY_RATE_DEFINITIONS,
    REQUIRED_CURRENCIES,
    canonical_series_for_currency,
    definition_as_of,
    definitions_for_currency,
    validate_registry,
)
from forex_agent.domain.provider_series_mapping import ProviderSeriesMapping
from forex_agent.domain.rate_transformation import RateTransformation, RateTransformationKind
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(*args: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(*args, tzinfo=UTC))


def _series(key: str, currency: str, **overrides: object) -> MacroSeriesDefinition:
    defaults: dict[str, object] = {
        "key": key,
        "economy": currency[:2],
        "currency": currency,
        "category": MacroCategory.POLICY_RATE,
        "unit": "PERCENT",
        "frequency": MacroFrequency.IRREGULAR,
    }
    defaults.update(overrides)
    return MacroSeriesDefinition(**defaults)  # type: ignore[arg-type]


def _definition(
    series: MacroSeriesDefinition, valid_from: UtcTimestamp, valid_to: UtcTimestamp | None
) -> PolicyRateDefinition:
    return PolicyRateDefinition(
        series=series,
        institution="Test Bank",
        instrument_name="Test Rate",
        transformation=RateTransformation(
            kind=RateTransformationKind.IDENTITY, version="v1", description="raw value used as-is"
        ),
        valid_from=valid_from,
        valid_to=valid_to,
        provider_mappings=(ProviderSeriesMapping(provider="TEST", provider_series_ids=("X",)),),
    )


def _gap(
    currency: str, start: UtcTimestamp, end: UtcTimestamp, reason: str = "test gap"
) -> DeclaredPolicyRateGap:
    return DeclaredPolicyRateGap(currency=currency, start=start, end=end, reason=reason)


# ---------------------------------------------------------------------------
# The real, module-level registry
# ---------------------------------------------------------------------------


def test_registry_covers_all_five_required_currencies() -> None:
    represented = {d.series.currency for d in POLICY_RATE_DEFINITIONS}

    assert represented == REQUIRED_CURRENCIES
    assert {"USD", "EUR", "GBP", "JPY", "CAD"} == REQUIRED_CURRENCIES


def test_each_currency_shares_one_canonical_series_object() -> None:
    for currency in REQUIRED_CURRENCIES:
        series_set = {d.series for d in definitions_for_currency(currency)}
        assert len(series_set) == 1


def test_real_registry_passes_its_own_validation() -> None:
    validate_registry(POLICY_RATE_DEFINITIONS, DECLARED_GAPS)  # must not raise


@pytest.mark.parametrize("currency", sorted(REQUIRED_CURRENCIES))
def test_canonical_series_for_currency_is_resolvable(currency: str) -> None:
    series = canonical_series_for_currency(currency)

    assert series is not None
    assert series.currency == currency
    assert series.category is MacroCategory.POLICY_RATE


def test_canonical_series_for_unknown_currency_is_none() -> None:
    assert canonical_series_for_currency("ZZZ") is None


@pytest.mark.parametrize("currency", sorted(REQUIRED_CURRENCIES))
def test_every_definition_has_at_least_one_provider_mapping(currency: str) -> None:
    for definition in definitions_for_currency(currency):
        assert len(definition.provider_mappings) >= 1


@pytest.mark.parametrize("currency", sorted(REQUIRED_CURRENCIES))
def test_no_mapping_in_the_registry_is_research_usable_yet(currency: str) -> None:
    # FX-42H: do not mark any mapping POINT_IN_TIME_SAFE merely because
    # the value series exists -- every mapping in this story's registry
    # must still be unverified/unknown, fail closed by construction.
    for definition in definitions_for_currency(currency):
        for mapping in definition.provider_mappings:
            assert mapping.verified is False
            assert mapping.point_in_time_safety.value == "UNKNOWN"


# ---------------------------------------------------------------------------
# The required effective-dated example: USD's Dec 16, 2008 target-range switch
# ---------------------------------------------------------------------------


def test_usd_target_point_era_starts_february_1994_not_1954() -> None:
    # FX-42H correction: 1954 wrongly implied the FOMC target-rate concept
    # itself starts there; the corrected boundary is the first FOMC meeting
    # after which policy changes were announced immediately (Feb 4, 1994).
    assert definition_as_of("USD", _ts(1994, 2, 3)) is None

    definition = definition_as_of("USD", _ts(1994, 2, 4))
    assert definition is not None
    assert definition.instrument_name == "Federal Funds Target Rate (single target point)"


def test_usd_before_2008_switch_uses_target_point_identity_definition() -> None:
    definition = definition_as_of("USD", _ts(2008, 12, 15))

    assert definition is not None
    assert definition.instrument_name == "Federal Funds Target Rate (single target point)"
    assert definition.transformation.kind is RateTransformationKind.IDENTITY


def test_usd_on_switch_date_uses_target_range_definition() -> None:
    # The switch date itself belongs to the new (target-range) definition --
    # valid_to is an exclusive upper bound, valid_from an inclusive lower one.
    definition = definition_as_of("USD", _ts(2008, 12, 16))

    assert definition is not None
    assert definition.instrument_name == "Federal Funds Target Range Midpoint"
    assert definition.transformation.kind is RateTransformationKind.TARGET_RANGE_MIDPOINT


def test_usd_after_2008_switch_uses_target_range_definition() -> None:
    definition = definition_as_of("USD", _ts(2020, 1, 1))

    assert definition is not None
    assert definition.instrument_name == "Federal Funds Target Range Midpoint"


def test_usd_both_eras_share_one_canonical_series_key() -> None:
    pre = definition_as_of("USD", _ts(2000, 1, 1))
    post = definition_as_of("USD", _ts(2020, 1, 1))

    assert pre is not None
    assert post is not None
    assert pre.series.key == post.series.key == "USD_POLICY_RATE"


def test_usd_target_range_transformation_computes_correct_midpoint() -> None:
    # Not silently splicing unlike concepts: the transformation applied
    # actually differs by era, and the range-era transformation is
    # concretely, numerically correct.
    definition = definition_as_of("USD", _ts(2020, 1, 1))
    assert definition is not None

    result = definition.transformation.apply(Decimal("1.75"), Decimal("1.50"))

    assert result == Decimal("1.625")


def test_definition_as_of_before_earliest_valid_from_is_none() -> None:
    assert definition_as_of("USD", _ts(1900, 1, 1)) is None


def test_definition_as_of_unknown_currency_is_none() -> None:
    assert definition_as_of("ZZZ", _ts(2020, 1, 1)) is None


# ---------------------------------------------------------------------------
# EUR: corrected canonical scalar (MRO, not DFR continuously)
# ---------------------------------------------------------------------------


def test_eur_canonical_instrument_is_mro_not_deposit_facility_rate() -> None:
    definition = definition_as_of("EUR", _ts(2020, 1, 1))

    assert definition is not None
    assert "Main Refinancing Operations" in definition.instrument_name
    assert "Deposit Facility" not in definition.instrument_name


def test_eur_provider_mapping_uses_mro_series_key() -> None:
    definition = definition_as_of("EUR", _ts(2020, 1, 1))

    assert definition is not None
    ids = {i for m in definition.provider_mappings for i in m.provider_series_ids}
    assert "FM.D.U2.EUR.4F.KR.MRR_RT.LEV" in ids


def test_eur_deposit_facility_rate_is_documented_not_used() -> None:
    # FX-42H: DFR must be documented as a candidate future regime-aware
    # feature, not silently substituted into the initial series.
    definition = definition_as_of("EUR", _ts(2020, 1, 1))

    assert definition is not None
    assert "Deposit Facility Rate" in definition.notes
    assert "regime-aware" in definition.notes.lower()


# ---------------------------------------------------------------------------
# CAD: corrected boundary and provider ID
# ---------------------------------------------------------------------------


def test_cad_overnight_target_starts_february_1999_not_1991() -> None:
    assert definition_as_of("CAD", _ts(1999, 1, 31)) is None

    definition = definition_as_of("CAD", _ts(1999, 2, 1))
    assert definition is not None
    assert definition.instrument_name == "Overnight Rate Target"


def test_cad_provider_mapping_uses_v39079() -> None:
    definition = definition_as_of("CAD", _ts(2020, 1, 1))

    assert definition is not None
    ids = {i for m in definition.provider_mappings for i in m.provider_series_ids}
    assert "V39079" in ids


# ---------------------------------------------------------------------------
# JPY: distinct operational-regime eras with explicitly declared gaps
# ---------------------------------------------------------------------------


def test_jpy_no_longer_claims_one_continuous_definition() -> None:
    # FX-42H.1: six eras now (the 2006-2013 era split at 2010-10-05).
    assert len(definitions_for_currency("JPY")) >= 6


def test_jpy_overnight_call_rate_target_era_one() -> None:
    definition = definition_as_of("JPY", _ts(2000, 1, 1))

    assert definition is not None
    assert definition.instrument_name == "Uncollateralized Overnight Call Rate Target"


def test_jpy_returns_none_during_quantitative_easing_gap_2001_2006() -> None:
    # The required "definition_as_of returns None in a quantitative-target
    # era" case: 2001-2006 QEP targeted the outstanding balance of current
    # accounts (a quantity), not a scalar short-term interest rate.
    assert definition_as_of("JPY", _ts(2003, 1, 1)) is None
    assert definition_as_of("JPY", _ts(2001, 3, 19)) is None
    assert definition_as_of("JPY", _ts(2006, 3, 8)) is None


def test_jpy_overnight_call_rate_target_era_two_a() -> None:
    definition = definition_as_of("JPY", _ts(2006, 3, 9))

    assert definition is not None
    assert definition.instrument_name == "Uncollateralized Overnight Call Rate Target"
    assert definition.transformation.kind is RateTransformationKind.IDENTITY


def test_jpy_2010_10_04_uses_identity_transformation() -> None:
    # FX-42H.1: the last day of the single-point target era, immediately
    # before the October 5, 2010 "Comprehensive Monetary Easing" switch.
    definition = definition_as_of("JPY", _ts(2010, 10, 4))

    assert definition is not None
    assert definition.instrument_name == "Uncollateralized Overnight Call Rate Target"
    assert definition.transformation.kind is RateTransformationKind.IDENTITY


def test_jpy_2010_10_05_uses_target_range_midpoint_transformation() -> None:
    # FX-42H.1: the BoJ explicitly changed the target from a single point
    # (~0.1%) to a range (~0-0.1%) on this date -- represented as a new
    # definition using TARGET_RANGE_MIDPOINT, matching how the registry
    # already represents published target ranges elsewhere.
    definition = definition_as_of("JPY", _ts(2010, 10, 5))

    assert definition is not None
    assert definition.instrument_name == "Uncollateralized Overnight Call Rate Target Range"
    assert definition.transformation.kind is RateTransformationKind.TARGET_RANGE_MIDPOINT


def test_jpy_2010_2013_range_midpoint_of_zero_and_tenth_percent() -> None:
    definition = definition_as_of("JPY", _ts(2011, 1, 1))
    assert definition is not None

    midpoint = definition.transformation.apply(Decimal("0.1"), Decimal("0.0"))

    assert midpoint == Decimal("0.05")


def test_jpy_returns_none_during_qqe_gap_2013_2016() -> None:
    # A second declared gap: 2013-2016 QQE targeted the monetary base.
    assert definition_as_of("JPY", _ts(2014, 6, 1)) is None
    assert definition_as_of("JPY", _ts(2013, 4, 4)) is None
    assert definition_as_of("JPY", _ts(2016, 1, 28)) is None


def test_jpy_2016_02_15_returns_no_canonical_policy_rate_definition() -> None:
    # FX-42H.1: the QQE gap now extends through the -0.10% policy-rate
    # balance's EFFECTIVE date (Feb 16, 2016), not its Jan 29 announcement.
    assert definition_as_of("JPY", _ts(2016, 2, 15)) is None


def test_jpy_2016_02_16_returns_policy_rate_balance_definition() -> None:
    definition = definition_as_of("JPY", _ts(2016, 2, 16))

    assert definition is not None
    assert "Policy-Rate Balance" in definition.instrument_name


def test_jpy_policy_rate_balance_regime_2016_2024() -> None:
    definition = definition_as_of("JPY", _ts(2020, 1, 1))

    assert definition is not None
    assert "Policy-Rate Balance" in definition.instrument_name
    assert definition.transformation.kind is RateTransformationKind.IDENTITY


def test_jpy_transitional_range_march_to_july_2024() -> None:
    definition = definition_as_of("JPY", _ts(2024, 5, 1))

    assert definition is not None
    assert definition.instrument_name == "Uncollateralized Overnight Call Rate Target Range"
    assert definition.transformation.kind is RateTransformationKind.TARGET_RANGE_MIDPOINT

    midpoint = definition.transformation.apply(Decimal("0.1"), Decimal("0.0"))
    assert midpoint == Decimal("0.05")


def test_jpy_single_point_target_resumes_july_2024() -> None:
    definition = definition_as_of("JPY", _ts(2024, 7, 31))

    assert definition is not None
    assert definition.instrument_name == "Uncollateralized Overnight Call Rate Target"
    assert definition.transformation.kind is RateTransformationKind.IDENTITY
    assert definition.valid_to is None


def test_jpy_all_eras_share_one_canonical_series_key() -> None:
    keys = {d.series.key for d in definitions_for_currency("JPY")}
    assert keys == {"JPY_POLICY_RATE"}


def test_jpy_declared_gaps_have_currency_start_end_and_reason() -> None:
    jpy_gaps = [g for g in DECLARED_GAPS if g.currency == "JPY"]
    assert len(jpy_gaps) == 2
    for gap in jpy_gaps:
        assert gap.currency == "JPY"
        assert gap.start.value < gap.end.value
        assert gap.reason.strip() != ""


# ---------------------------------------------------------------------------
# validate_registry against deliberately broken fixtures
# ---------------------------------------------------------------------------


def test_validate_registry_rejects_split_series_keys_for_one_currency() -> None:
    series_a = _series("ZZZ_POLICY_RATE_A", "ZZZ")
    series_b = _series("ZZZ_POLICY_RATE_B", "ZZZ")
    broken = (
        _definition(series_a, _ts(2000, 1, 1), _ts(2010, 1, 1)),
        _definition(series_b, _ts(2010, 1, 1), None),
    )

    with pytest.raises(ValueError, match="identical canonical MacroSeriesDefinition semantics"):
        validate_registry(broken)


def test_validate_registry_rejects_same_key_but_different_semantics() -> None:
    # FX-42H: the stricter check -- two definitions can share a key string
    # while disagreeing on economy/unit/category/frequency, and that must
    # still be rejected.
    series_a = _series("ZZZ_POLICY_RATE", "ZZZ", unit="PERCENT")
    series_b = _series("ZZZ_POLICY_RATE", "ZZZ", unit="BASIS_POINTS")
    broken = (
        _definition(series_a, _ts(2000, 1, 1), _ts(2010, 1, 1)),
        _definition(series_b, _ts(2010, 1, 1), None),
    )

    with pytest.raises(ValueError, match="identical canonical MacroSeriesDefinition semantics"):
        validate_registry(broken)


def test_validate_registry_rejects_overlapping_windows() -> None:
    series = _series("ZZZ_POLICY_RATE", "ZZZ")
    broken = (
        _definition(series, _ts(2000, 1, 1), _ts(2011, 1, 1)),
        _definition(series, _ts(2010, 1, 1), None),
    )

    with pytest.raises(ValueError, match="overlapping validity"):
        validate_registry(broken)


def test_validate_registry_rejects_an_arbitrary_undeclared_one_day_gap() -> None:
    # FX-42H.1: blanket gap tolerance is gone -- ANY undeclared gap, even a
    # single day, must now fail validation.
    series = _series("ZZZ_POLICY_RATE", "ZZZ")
    broken = (
        _definition(series, _ts(2000, 1, 1), _ts(2005, 1, 1)),
        _definition(series, _ts(2005, 1, 2), None),  # one day undeclared
    )

    with pytest.raises(ValueError, match="undeclared gap"):
        validate_registry(broken)


def test_validate_registry_accepts_a_declared_gap_with_matching_boundaries() -> None:
    series = _series("ZZZ_POLICY_RATE", "ZZZ")
    with_gap = (
        _definition(series, _ts(2000, 1, 1), _ts(2005, 1, 1)),
        _definition(series, _ts(2010, 1, 1), None),
    )
    gap = _gap("ZZZ", _ts(2005, 1, 1), _ts(2010, 1, 1))

    # Combined with the real registry so the required-currency check
    # doesn't mask this -- same pattern used elsewhere in this file.
    validate_registry(POLICY_RATE_DEFINITIONS + with_gap, (*DECLARED_GAPS, gap))  # must not raise


def test_validate_registry_rejects_a_declared_gap_with_mismatched_boundaries() -> None:
    # A declared gap that does not exactly match the actual gap between
    # consecutive definitions still leaves the real gap undeclared.
    series = _series("ZZZ_POLICY_RATE", "ZZZ")
    with_gap = (
        _definition(series, _ts(2000, 1, 1), _ts(2005, 1, 1)),
        _definition(series, _ts(2010, 1, 1), None),
    )
    mismatched_gap = _gap("ZZZ", _ts(2005, 1, 1), _ts(2009, 1, 1))  # ends too early

    with pytest.raises(ValueError, match="undeclared gap"):
        validate_registry(with_gap, (mismatched_gap,))


def test_validate_registry_rejects_a_gap_overlapping_a_definition() -> None:
    series = _series("ZZZ_POLICY_RATE", "ZZZ")
    definitions = (_definition(series, _ts(2000, 1, 1), None),)
    overlapping_gap = _gap("ZZZ", _ts(2005, 1, 1), _ts(2006, 1, 1))

    with pytest.raises(ValueError, match="overlaps a policy-rate definition"):
        validate_registry(definitions, (overlapping_gap,))


def test_validate_registry_rejects_overlapping_declared_gaps() -> None:
    # Isolated from the "undeclared gap" check: a single open-ended
    # definition with two overlapping declared gaps entirely BEFORE it,
    # so no pairwise inter-definition gap exists to confuse the failure
    # reason -- only the gap/gap overlap check can fire here.
    series = _series("ZZZ_POLICY_RATE", "ZZZ")
    definitions = (_definition(series, _ts(2010, 1, 1), None),)
    gap_one = _gap("ZZZ", _ts(2000, 1, 1), _ts(2006, 1, 1))
    gap_two = _gap("ZZZ", _ts(2005, 1, 1), _ts(2010, 1, 1))  # overlaps gap_one

    with pytest.raises(ValueError, match="declared gaps overlap"):
        validate_registry(definitions, (gap_one, gap_two))


def test_validate_registry_rejects_a_non_terminal_open_ended_definition() -> None:
    series = _series("ZZZ_POLICY_RATE", "ZZZ")
    broken = (
        _definition(series, _ts(2000, 1, 1), None),  # open-ended but not last
        _definition(series, _ts(2010, 1, 1), None),
    )

    with pytest.raises(ValueError, match="overlapping validity"):
        validate_registry(broken)


def test_validate_registry_rejects_missing_required_currency() -> None:
    only_usd = tuple(d for d in POLICY_RATE_DEFINITIONS if d.series.currency == "USD")

    with pytest.raises(ValueError, match="missing required currencies"):
        validate_registry(only_usd)


def test_validate_registry_accepts_well_formed_contiguous_windows() -> None:
    series = _series("ZZZ_POLICY_RATE", "ZZZ")
    ok = (
        _definition(series, _ts(2000, 1, 1), _ts(2010, 1, 1)),
        _definition(series, _ts(2010, 1, 1), None),
    )

    # Missing-required-currencies would still fire for "ZZZ" alone, so check
    # only that the per-currency window checks themselves don't raise by
    # calling the same logic against a registry that also satisfies the
    # currency-coverage requirement.
    combined = POLICY_RATE_DEFINITIONS + ok
    validate_registry(combined, DECLARED_GAPS)  # must not raise


def test_validate_registry_accepts_each_real_declared_jpy_gap() -> None:
    # The real registry itself relies on declared-gap tolerance -- confirm
    # it directly (not just via a synthetic ZZZ fixture), and that each
    # individual JPY gap is what makes the registry pass, not an accident
    # of ordering: removing either declared gap must break validation.
    jpy_definitions = definitions_for_currency("JPY")
    assert len(jpy_definitions) >= 6
    validate_registry(POLICY_RATE_DEFINITIONS, DECLARED_GAPS)  # must not raise

    for missing_gap in DECLARED_GAPS:
        remaining = tuple(g for g in DECLARED_GAPS if g != missing_gap)
        with pytest.raises(ValueError, match="undeclared gap"):
            validate_registry(POLICY_RATE_DEFINITIONS, remaining)

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.macro_category import MacroCategory
from forex_agent.domain.macro_frequency import MacroFrequency
from forex_agent.domain.macro_series_definition import MacroSeriesDefinition
from forex_agent.domain.policy_rate_definition import PolicyRateDefinition
from forex_agent.domain.policy_rate_registry import (
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


def _series(key: str, currency: str) -> MacroSeriesDefinition:
    return MacroSeriesDefinition(
        key=key,
        economy=currency[:2],
        currency=currency,
        category=MacroCategory.POLICY_RATE,
        unit="PERCENT",
        frequency=MacroFrequency.IRREGULAR,
    )


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


# ---------------------------------------------------------------------------
# The real, module-level registry
# ---------------------------------------------------------------------------


def test_registry_covers_all_five_required_currencies() -> None:
    represented = {d.series.currency for d in POLICY_RATE_DEFINITIONS}

    assert represented == REQUIRED_CURRENCIES
    assert {"USD", "EUR", "GBP", "JPY", "CAD"} == REQUIRED_CURRENCIES


def test_each_currency_shares_one_canonical_series_key() -> None:
    for currency in REQUIRED_CURRENCIES:
        keys = {d.series.key for d in definitions_for_currency(currency)}
        assert len(keys) == 1


def test_real_registry_passes_its_own_validation() -> None:
    validate_registry(POLICY_RATE_DEFINITIONS)  # must not raise


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


# ---------------------------------------------------------------------------
# The required effective-dated example: USD's Dec 16, 2008 target-range switch
# ---------------------------------------------------------------------------


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
# validate_registry against deliberately broken fixtures
# ---------------------------------------------------------------------------


def test_validate_registry_rejects_split_series_keys_for_one_currency() -> None:
    series_a = _series("ZZZ_POLICY_RATE_A", "ZZZ")
    series_b = _series("ZZZ_POLICY_RATE_B", "ZZZ")
    broken = (
        _definition(series_a, _ts(2000, 1, 1), _ts(2010, 1, 1)),
        _definition(series_b, _ts(2010, 1, 1), None),
    )

    with pytest.raises(ValueError, match="one canonical series key"):
        validate_registry(broken)


def test_validate_registry_rejects_overlapping_windows() -> None:
    series = _series("ZZZ_POLICY_RATE", "ZZZ")
    broken = (
        _definition(series, _ts(2000, 1, 1), _ts(2011, 1, 1)),
        _definition(series, _ts(2010, 1, 1), None),
    )

    with pytest.raises(ValueError, match="overlapping validity"):
        validate_registry(broken)


def test_validate_registry_rejects_gaps_between_windows() -> None:
    series = _series("ZZZ_POLICY_RATE", "ZZZ")
    broken = (
        _definition(series, _ts(2000, 1, 1), _ts(2009, 1, 1)),
        _definition(series, _ts(2010, 1, 1), None),
    )

    with pytest.raises(ValueError, match="gap in validity"):
        validate_registry(broken)


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
    validate_registry(combined)  # must not raise

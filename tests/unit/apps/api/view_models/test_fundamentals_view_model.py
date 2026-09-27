"""FX-54V: unit tests for `build_fundamentals_view`/
`build_policy_rate_history_view` -- pure, no I/O."""

from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.apps.api.view_models.fundamentals_view_model import (
    RAW_DIFFERENTIAL_LABEL,
    build_fundamentals_view,
    build_policy_rate_history_view,
)
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.policy_rate_differential import (
    CurrencyRateState,
    FundamentalRateEvidence,
    PolicyRateHistory,
    RateSemantics,
)
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(year: int, month: int, day: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, tzinfo=UTC))


def _state(currency: str, rate: str) -> CurrencyRateState:
    return CurrencyRateState(
        currency=currency,
        rate=Decimal(rate),
        series_key=f"{currency}_POLICY_RATE",
        observation_period=_ts(2026, 9, 1),
        revision_sequence=0,
        released_at=_ts(2026, 9, 1),
        effective_at=None,
        released_at_is_verified=True,
        released_at_is_conservative_bound=False,
    )


def test_build_fundamentals_view_both_sides_available() -> None:
    evidence = FundamentalRateEvidence(
        pair="GBP/USD",
        as_of=_ts(2026, 9, 20),
        rate_semantics=RateSemantics.ANNOUNCED,
        base_currency="GBP",
        quote_currency="USD",
        base=_state("GBP", "3.75"),
        base_unavailable_reason=None,
        quote=_state("USD", "3.875"),
        quote_unavailable_reason=None,
        differential=Decimal("-0.125"),
    )

    view = build_fundamentals_view(evidence)

    assert view["pair"] == "GBP/USD"
    assert view["base"]["available"] is True
    assert view["base"]["rate_percent"] == "3.75"  # exact Decimal string, never a float
    assert view["differential"] == {
        "available": True,
        "label": RAW_DIFFERENTIAL_LABEL,
        "value_pp": "-0.125",
    }


def test_build_fundamentals_view_missing_side_is_visible_not_hidden() -> None:
    evidence = FundamentalRateEvidence(
        pair="GBP/USD",
        as_of=_ts(2026, 9, 20),
        rate_semantics=RateSemantics.EFFECTIVE,
        base_currency="GBP",
        quote_currency="USD",
        base=None,
        base_unavailable_reason="no EFFECTIVE policy-rate state is defensibly established for GBP",
        quote=_state("USD", "3.875"),
        quote_unavailable_reason=None,
        differential=None,
    )

    view = build_fundamentals_view(evidence)

    assert view["base"] == {
        "available": False,
        "unavailable_reason": ("no EFFECTIVE policy-rate state is defensibly established for GBP"),
    }
    assert view["quote"]["available"] is True  # the other side still shown
    assert view["differential"] == {"available": False, "label": RAW_DIFFERENTIAL_LABEL}


def test_differential_label_is_always_raw_never_directional() -> None:
    # FX-54V Section 7/15's own enforcement point.
    assert RAW_DIFFERENTIAL_LABEL == "Raw policy-rate differential"
    for forbidden in ("advantage", "strength", "bias", "bullish", "bearish"):
        assert forbidden not in RAW_DIFFERENTIAL_LABEL.lower()


def test_build_policy_rate_history_view_preserves_points_and_empties() -> None:
    base_point = MacroObservationVintage(
        series_key="GBP_POLICY_RATE",
        observation_period=_ts(2026, 1, 1),
        value=Decimal("5.00"),
        released_at=_ts(2026, 1, 1),
        revision_sequence=0,
        source="test",
    )
    history = PolicyRateHistory(
        base_currency="GBP",
        quote_currency="USD",
        rate_semantics=RateSemantics.ANNOUNCED,
        base_history=(base_point,),
        quote_history=(),
    )

    view = build_policy_rate_history_view(history)

    assert view["base_currency"] == "GBP"
    assert len(view["base_history"]) == 1
    assert view["base_history"][0]["rate_percent"] == "5.00"
    assert view["quote_history"] == []  # empty, never fabricated

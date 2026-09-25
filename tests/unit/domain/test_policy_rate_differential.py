from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.policy_rate_differential import (
    CurrencyRateState,
    DifferentialDirection,
    PolicyRateDifferentialSnapshot,
    RateSemantics,
    classify_direction,
    format_pair,
    pair_differential_change_since_previous,
    rate_differential,
)
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    microsecond: int = 0,
) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, minute, second, microsecond, tzinfo=UTC))


def _state(currency: str, rate: str, **overrides: object) -> CurrencyRateState:
    defaults: dict[str, object] = {
        "currency": currency,
        "rate": Decimal(rate),
        "series_key": f"{currency}_POLICY_RATE",
        "observation_period": _ts(2026, 9, 17),
        "revision_sequence": 0,
        "released_at": _ts(2026, 9, 16, 18, 0, 0),
        "effective_at": _ts(2026, 9, 17),
        "released_at_is_verified": True,
        "released_at_is_conservative_bound": False,
    }
    defaults.update(overrides)
    return CurrencyRateState(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# rate_differential -- Decimal-only, orientation
# ---------------------------------------------------------------------------


def test_rate_differential_is_base_minus_quote() -> None:
    result = rate_differential(Decimal("3.75"), Decimal("5.125"))

    assert result == Decimal("-1.375")
    assert isinstance(result, Decimal)


def test_rate_differential_reversed_arguments_reverses_sign() -> None:
    # FX-45 section 9's own required invariant.
    forward = rate_differential(Decimal("3.75"), Decimal("5.125"))
    reversed_ = rate_differential(Decimal("5.125"), Decimal("3.75"))

    assert forward == -reversed_


def test_rate_differential_rejects_float() -> None:
    with pytest.raises(TypeError, match="base_rate"):
        rate_differential(3.75, Decimal("5.125"))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="quote_rate"):
        rate_differential(Decimal("3.75"), 5.125)  # type: ignore[arg-type]


def test_rate_differential_preserves_decimal_precision() -> None:
    # FX-44/FX-43's own theme, carried through: no float round-trip loss.
    result = rate_differential(Decimal("0.15"), Decimal("0.05"))

    assert result == Decimal("0.10")
    assert str(result) == "0.10"


def test_rate_differential_is_deterministic() -> None:
    a = rate_differential(Decimal("3.75"), Decimal("5.125"))
    b = rate_differential(Decimal("3.75"), Decimal("5.125"))

    assert a == b


# ---------------------------------------------------------------------------
# classify_direction
# ---------------------------------------------------------------------------


def test_classify_direction_widening_for_positive_change() -> None:
    assert classify_direction(Decimal("0.25")) is DifferentialDirection.WIDENING


def test_classify_direction_narrowing_for_negative_change() -> None:
    assert classify_direction(Decimal("-0.25")) is DifferentialDirection.NARROWING


def test_classify_direction_unchanged_for_exact_zero() -> None:
    assert classify_direction(Decimal("0")) is DifferentialDirection.UNCHANGED


def test_classify_direction_none_for_none() -> None:
    # Never coerced into UNCHANGED -- an unavailable change stays unavailable.
    assert classify_direction(None) is None


def test_classify_direction_tiny_nonzero_is_not_unchanged() -> None:
    # No fuzzy "neutral" band (FX-45 section 8).
    assert classify_direction(Decimal("0.001")) is DifferentialDirection.WIDENING
    assert classify_direction(Decimal("-0.001")) is DifferentialDirection.NARROWING


# ---------------------------------------------------------------------------
# format_pair
# ---------------------------------------------------------------------------


def test_format_pair_uses_slash_form() -> None:
    assert format_pair("EUR", "USD") == "EUR/USD"
    assert format_pair("USD", "CAD") == "USD/CAD"


# ---------------------------------------------------------------------------
# CurrencyRateState / PolicyRateDifferentialSnapshot -- Decimal-only
# ---------------------------------------------------------------------------


def test_currency_rate_state_rejects_float_rate() -> None:
    # Constructed directly, not via _state(): _state's own `rate: str`
    # positional parameter always converts through Decimal(rate) before
    # CurrencyRateState ever sees it, so a bad type passed that way could
    # never reach (or test) CurrencyRateState.__post_init__'s own guard.
    with pytest.raises(TypeError, match="rate"):
        CurrencyRateState(
            currency="EUR",
            rate=3.75,  # type: ignore[arg-type]
            series_key="EUR_POLICY_RATE",
            observation_period=_ts(2026, 9, 17),
            revision_sequence=0,
            released_at=_ts(2026, 9, 16, 18, 0, 0),
            effective_at=_ts(2026, 9, 17),
            released_at_is_verified=True,
            released_at_is_conservative_bound=False,
        )


def test_snapshot_rejects_float_differential() -> None:
    base = _state("EUR", "3.75")
    quote = _state("USD", "5.125")
    with pytest.raises(TypeError, match="differential"):
        PolicyRateDifferentialSnapshot(
            pair="EUR/USD",
            as_of=_ts(2026, 9, 17),
            rate_semantics=RateSemantics.ANNOUNCED,
            base=base,
            quote=quote,
            differential=-1.375,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# pair_differential_change_since_previous
# ---------------------------------------------------------------------------


def test_change_since_previous_reverts_only_the_leg_that_moved() -> None:
    # Base moved most recently (later released_at) -- only base reverts.
    current_base = _state("EUR", "3.75", released_at=_ts(2026, 9, 16, 12, 0, 0))
    current_quote = _state("USD", "5.125", released_at=_ts(2026, 9, 1, 18, 0, 0))
    previous_base = _state("EUR", "3.50", released_at=_ts(2026, 6, 1, 12, 0, 0))
    previous_quote = _state("USD", "4.875", released_at=_ts(2026, 5, 1, 18, 0, 0))

    current_differential = rate_differential(current_base.rate, current_quote.rate)  # -1.375
    change = pair_differential_change_since_previous(
        current_differential,
        RateSemantics.ANNOUNCED,
        current_base,
        current_quote,
        previous_base,
        previous_quote,
    )

    # previous differential = previous_base(3.50) - current_quote(5.125) = -1.625
    # change = -1.375 - (-1.625) = 0.25
    assert change == Decimal("0.25")


def test_change_since_previous_reverts_quote_when_quote_moved_last() -> None:
    current_base = _state("EUR", "3.75", released_at=_ts(2026, 5, 1, 12, 0, 0))
    current_quote = _state("USD", "5.125", released_at=_ts(2026, 9, 1, 18, 0, 0))
    previous_base = _state("EUR", "3.50", released_at=_ts(2026, 1, 1, 12, 0, 0))
    previous_quote = _state("USD", "4.875", released_at=_ts(2026, 3, 1, 18, 0, 0))

    current_differential = rate_differential(current_base.rate, current_quote.rate)
    change = pair_differential_change_since_previous(
        current_differential,
        RateSemantics.ANNOUNCED,
        current_base,
        current_quote,
        previous_base,
        previous_quote,
    )

    # previous differential = current_base(3.75) - previous_quote(4.875) = -1.125
    # current = 3.75 - 5.125 = -1.375; change = -1.375 - (-1.125) = -0.25
    assert change == Decimal("-0.25")


def test_change_since_previous_none_when_mover_has_no_predecessor() -> None:
    current_base = _state("EUR", "3.75", released_at=_ts(2026, 9, 16, 12, 0, 0))
    current_quote = _state("USD", "5.125", released_at=_ts(2026, 9, 1, 18, 0, 0))

    change = pair_differential_change_since_previous(
        Decimal("-1.375"),
        RateSemantics.ANNOUNCED,
        current_base,
        current_quote,
        None,  # base has no previous state
        _state("USD", "4.875"),
    )

    assert change is None


def test_change_since_previous_uses_effective_at_for_effective_semantics() -> None:
    current_base = _state("EUR", "3.75", effective_at=_ts(2026, 9, 20))
    current_quote = _state("USD", "5.125", effective_at=_ts(2026, 9, 1))
    previous_base = _state("EUR", "3.50", effective_at=_ts(2026, 6, 1))
    previous_quote = _state("USD", "4.875", effective_at=_ts(2026, 5, 1))

    current_differential = rate_differential(current_base.rate, current_quote.rate)
    change = pair_differential_change_since_previous(
        current_differential,
        RateSemantics.EFFECTIVE,
        current_base,
        current_quote,
        previous_base,
        previous_quote,
    )

    # base's effective_at (9/20) is later than quote's (9/1) -- base moved last.
    # previous differential = 3.50 - 5.125 = -1.625; current = -1.375; change = 0.25
    assert change == Decimal("0.25")

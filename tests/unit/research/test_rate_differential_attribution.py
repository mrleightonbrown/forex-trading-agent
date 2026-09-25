"""FX-47: rate-differential attribution tests."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.instrument import Instrument
from forex_agent.domain.money import Money
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide
from forex_agent.research.policy_rate_differential_research import (
    ChangeEvent,
    ChangeGroup,
    Disposition,
    FeatureEvaluation,
    LevelGroup,
    TransitionStatus,
)
from forex_agent.research.rate_differential_attribution import (
    LevelAttribution,
    attribute_trade_change,
    attribute_trade_level,
    attribute_trades,
    change_bucket_label,
    classify_level_attribution,
    find_governing_daily_evaluation,
    level_bucket_label,
)

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")


def _ts(day: int, hour: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2020, 1, day, hour, tzinfo=UTC))


def _trade(side: TradeSide, entry_day: int, entry_hour: int = 0) -> SimulatedTrade:
    return SimulatedTrade(
        instrument=EUR_USD,
        side=side,
        entry_price=Decimal("1.1000"),
        entry_time=_ts(entry_day, entry_hour),
        exit_price=Decimal("1.1010"),
        exit_time=_ts(entry_day + 1, entry_hour),
        pnl=Money(Decimal("0.0010"), "USD"),
    )


# --- classify_level_attribution ---------------------------------------------


@pytest.mark.parametrize(
    "side,group,expected",
    [
        (TradeSide.LONG, LevelGroup.POSITIVE, LevelAttribution.SUPPORTS),
        (TradeSide.LONG, LevelGroup.NEGATIVE, LevelAttribution.OPPOSES),
        (TradeSide.LONG, LevelGroup.ZERO, LevelAttribution.NEUTRAL),
        (TradeSide.SHORT, LevelGroup.POSITIVE, LevelAttribution.OPPOSES),
        (TradeSide.SHORT, LevelGroup.NEGATIVE, LevelAttribution.SUPPORTS),
        (TradeSide.SHORT, LevelGroup.ZERO, LevelAttribution.NEUTRAL),
    ],
)
def test_classify_level_attribution(
    side: TradeSide, group: LevelGroup, expected: LevelAttribution
) -> None:
    assert classify_level_attribution(side, group) is expected


# --- attribute_trade_level ---------------------------------------------------


def test_attribute_trade_level_usable_long_positive_supports() -> None:
    trade = _trade(TradeSide.LONG, entry_day=10)
    evaluation = FeatureEvaluation(
        as_of=trade.entry_time,
        disposition=Disposition.USABLE,
        differential=Decimal("0.5"),
        reason=None,
    )
    result = attribute_trade_level(trade, evaluation)
    assert result.disposition is Disposition.USABLE
    assert result.attribution is LevelAttribution.SUPPORTS
    assert result.reason is None
    assert level_bucket_label(result) == "SUPPORTS"


def test_attribute_trade_level_blocked_passes_through_reason() -> None:
    trade = _trade(TradeSide.LONG, entry_day=10)
    evaluation = FeatureEvaluation(
        as_of=trade.entry_time,
        disposition=Disposition.BLOCKED,
        differential=None,
        reason="provisional_timing",
    )
    result = attribute_trade_level(trade, evaluation)
    assert result.disposition is Disposition.BLOCKED
    assert result.attribution is None
    assert result.reason == "provisional_timing"
    assert level_bucket_label(result) == "BLOCKED"


def test_attribute_trade_level_unavailable_passes_through_reason() -> None:
    trade = _trade(TradeSide.SHORT, entry_day=10)
    evaluation = FeatureEvaluation(
        as_of=trade.entry_time,
        disposition=Disposition.UNAVAILABLE,
        differential=None,
        reason="no_baseline",
    )
    result = attribute_trade_level(trade, evaluation)
    assert result.disposition is Disposition.UNAVAILABLE
    assert result.attribution is None
    assert result.reason == "no_baseline"
    assert level_bucket_label(result) == "UNAVAILABLE"


def test_attribute_trade_level_rejects_as_of_mismatch() -> None:
    trade = _trade(TradeSide.LONG, entry_day=10)
    evaluation = FeatureEvaluation(
        as_of=_ts(11),  # deliberately mismatched
        disposition=Disposition.USABLE,
        differential=Decimal("0.5"),
        reason=None,
    )
    with pytest.raises(ValueError, match="does not match"):
        attribute_trade_level(trade, evaluation)


# --- find_governing_daily_evaluation ------------------------------------------


def _daily_eval(day: int, disposition: Disposition = Disposition.USABLE) -> FeatureEvaluation:
    return FeatureEvaluation(
        as_of=_ts(day),
        disposition=disposition,
        differential=Decimal("0.1") if disposition is Disposition.USABLE else None,
        reason=None if disposition is Disposition.USABLE else "provisional_timing",
    )


def test_find_governing_daily_evaluation_exact_match() -> None:
    daily = [_daily_eval(5), _daily_eval(10), _daily_eval(15)]
    result = find_governing_daily_evaluation(daily, _ts(10).value)
    assert result is not None
    assert result.as_of == _ts(10)


def test_find_governing_daily_evaluation_nearest_before() -> None:
    daily = [_daily_eval(5), _daily_eval(10), _daily_eval(15)]
    result = find_governing_daily_evaluation(daily, _ts(12).value)
    assert result is not None
    assert result.as_of == _ts(10)


def test_find_governing_daily_evaluation_before_all_is_none() -> None:
    daily = [_daily_eval(5), _daily_eval(10)]
    assert find_governing_daily_evaluation(daily, _ts(1).value) is None


def test_find_governing_daily_evaluation_rejects_non_ascending() -> None:
    daily = [_daily_eval(10), _daily_eval(5)]
    with pytest.raises(ValueError, match="ascending"):
        find_governing_daily_evaluation(daily, _ts(10).value)


# --- attribute_trade_change ----------------------------------------------------


def test_attribute_trade_change_admissible_transition() -> None:
    daily = [_daily_eval(5), _daily_eval(10)]
    event = ChangeEvent(
        as_of=_ts(10),
        differential=Decimal("0.2"),
        status=TransitionStatus.ADMISSIBLE,
        group=ChangeGroup.INCREASED,
        delta=Decimal("0.1"),
    )
    events_by_as_of = {_ts(10).value: event}
    result = attribute_trade_change(_ts(12).value, daily, events_by_as_of)
    assert result.disposition is Disposition.USABLE
    assert result.status is TransitionStatus.ADMISSIBLE
    assert result.group is ChangeGroup.INCREASED
    assert change_bucket_label(result) == "INCREASED"


def test_attribute_trade_change_gap_transition() -> None:
    daily = [_daily_eval(10)]
    event = ChangeEvent(
        as_of=_ts(10),
        differential=Decimal("0.2"),
        status=TransitionStatus.GAP,
        group=None,
        delta=None,
    )
    events_by_as_of = {_ts(10).value: event}
    result = attribute_trade_change(_ts(11).value, daily, events_by_as_of)
    assert result.disposition is Disposition.USABLE
    assert result.status is TransitionStatus.GAP
    assert result.group is None
    assert change_bucket_label(result) == "TRANSITION_UNKNOWN_DUE_TO_GAP"


def test_attribute_trade_change_governing_day_blocked() -> None:
    daily = [_daily_eval(10, disposition=Disposition.BLOCKED)]
    result = attribute_trade_change(_ts(11).value, daily, {})
    assert result.disposition is Disposition.BLOCKED
    assert result.status is None
    assert result.reason == "provisional_timing"
    assert change_bucket_label(result) == "BLOCKED"


def test_attribute_trade_change_no_governing_day() -> None:
    daily = [_daily_eval(10)]
    result = attribute_trade_change(_ts(1).value, daily, {})
    assert result.disposition is Disposition.BLOCKED
    assert result.reason == "no_governing_day_before_entry"
    assert change_bucket_label(result) == "NO_GOVERNING_DAY"


# --- attribute_trades (end to end) --------------------------------------------


def test_attribute_trades_end_to_end() -> None:
    trade = _trade(TradeSide.LONG, entry_day=12)
    level_eval = FeatureEvaluation(
        as_of=trade.entry_time,
        disposition=Disposition.USABLE,
        differential=Decimal("0.3"),
        reason=None,
    )
    daily = [_daily_eval(10)]
    event = ChangeEvent(
        as_of=_ts(10),
        differential=Decimal("0.3"),
        status=TransitionStatus.ADMISSIBLE,
        group=ChangeGroup.UNCHANGED,
        delta=Decimal("0"),
    )
    events_by_as_of = {_ts(10).value: event}

    [result] = attribute_trades([trade], [level_eval], daily, events_by_as_of)
    assert result.trade is trade
    assert result.level.attribution is LevelAttribution.SUPPORTS
    assert result.change.group is ChangeGroup.UNCHANGED


def test_attribute_trades_rejects_length_mismatch() -> None:
    trade = _trade(TradeSide.LONG, entry_day=12)
    with pytest.raises(ValueError, match="same length"):
        attribute_trades([trade], [], [], {})

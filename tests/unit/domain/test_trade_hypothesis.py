from datetime import UTC, datetime

import pytest

from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_hypothesis import TradeHypothesis, params_from_dict
from forex_agent.domain.trade_side import TradeSide

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
NOW = UtcTimestamp(datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC))


def _hypothesis(**overrides: object) -> TradeHypothesis:
    defaults: dict[str, object] = {
        "instrument": EUR_USD,
        "side": TradeSide.LONG,
        "generated_at": NOW,
        "timeframe": Granularity.M1,
        "strategy_key": "ema_crossover_v1",
        "strategy_version": "1",
        "parameters": (("fast_period", "20"), ("slow_period", "50")),
        "rationale": "fast MA crossed above slow MA",
    }
    defaults.update(overrides)
    return TradeHypothesis(**defaults)  # type: ignore[arg-type]


def test_valid_trade_hypothesis() -> None:
    hypothesis = _hypothesis()

    assert hypothesis.instrument == EUR_USD
    assert hypothesis.side is TradeSide.LONG
    assert hypothesis.generated_at == NOW
    assert hypothesis.timeframe is Granularity.M1
    assert hypothesis.strategy_key == "ema_crossover_v1"
    assert hypothesis.strategy_version == "1"
    assert hypothesis.parameters == (("fast_period", "20"), ("slow_period", "50"))
    assert hypothesis.rationale == "fast MA crossed above slow MA"


def test_is_hashable() -> None:
    # A dict-valued parameters field would break this — the whole reason
    # parameters is a tuple of pairs, not a dict.
    hash(_hypothesis())


def test_rejects_wrong_type_for_instrument() -> None:
    with pytest.raises(TypeError, match="instrument"):
        _hypothesis(instrument="EUR_USD")


def test_rejects_wrong_type_for_side() -> None:
    with pytest.raises(TypeError, match="side"):
        _hypothesis(side="LONG")


def test_rejects_wrong_type_for_generated_at() -> None:
    with pytest.raises(TypeError, match="generated_at"):
        _hypothesis(generated_at=datetime(2026, 1, 1, tzinfo=UTC))


def test_rejects_wrong_type_for_timeframe() -> None:
    with pytest.raises(TypeError, match="timeframe"):
        _hypothesis(timeframe="M1")


@pytest.mark.parametrize("strategy_key", ["", "   "])
def test_rejects_empty_strategy_key(strategy_key: str) -> None:
    with pytest.raises(ValueError, match="strategy_key"):
        _hypothesis(strategy_key=strategy_key)


@pytest.mark.parametrize("strategy_version", ["", "   "])
def test_rejects_empty_strategy_version(strategy_version: str) -> None:
    with pytest.raises(ValueError, match="strategy_version"):
        _hypothesis(strategy_version=strategy_version)


def test_rejects_non_tuple_parameters() -> None:
    with pytest.raises(TypeError, match="parameters"):
        _hypothesis(parameters={"fast_period": "20"})


def test_rejects_malformed_parameter_entry() -> None:
    with pytest.raises(TypeError, match="parameters"):
        _hypothesis(parameters=(("fast_period",),))


def test_rejects_non_string_parameter_value() -> None:
    with pytest.raises(TypeError, match="parameters"):
        _hypothesis(parameters=(("fast_period", 20),))


def test_rejects_duplicate_parameter_keys() -> None:
    with pytest.raises(ValueError, match="duplicate parameter key"):
        _hypothesis(parameters=(("fast_period", "20"), ("fast_period", "30")))


def test_empty_parameters_is_allowed() -> None:
    _hypothesis(parameters=())  # does not raise


@pytest.mark.parametrize("rationale", ["", "   "])
def test_rejects_empty_rationale(rationale: str) -> None:
    with pytest.raises(ValueError, match="rationale"):
        _hypothesis(rationale=rationale)


# --- params_from_dict -------------------------------------------------------


def test_params_from_dict_stringifies_values() -> None:
    assert params_from_dict({"fast_period": 20, "slow_period": 50}) == (
        ("fast_period", "20"),
        ("slow_period", "50"),
    )


def test_params_from_dict_empty() -> None:
    assert params_from_dict({}) == ()


def test_params_from_dict_result_is_valid_parameters() -> None:
    _hypothesis(parameters=params_from_dict({"fast_period": 20}))  # does not raise

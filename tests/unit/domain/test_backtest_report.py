"""FX-40: `backtest_report` serializer tests."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.backtest_metrics import compute_metrics
from forex_agent.domain.backtest_report import (
    SCHEMA_VERSION,
    config_identifier,
    report_filename,
    to_report_dict,
)
from forex_agent.domain.candle_source import CandleSource
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.money import Money
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
USD_JPY = Instrument(base_currency="USD", quote_currency="JPY")


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2024, 1, 1, hour, 0, 0, tzinfo=UTC))


def _trade(
    entry_hour: int,
    exit_hour: int,
    pnl: str,
    side: TradeSide = TradeSide.LONG,
    instrument: Instrument = EUR_USD,
    currency: str = "USD",
) -> SimulatedTrade:
    return SimulatedTrade(
        instrument=instrument,
        side=side,
        entry_price=Decimal("1.1000"),
        entry_time=_ts(entry_hour),
        exit_price=Decimal("1.1050"),
        exit_time=_ts(exit_hour),
        pnl=Money(Decimal(pnl), currency),
    )


def _base_kwargs(**overrides: object) -> dict[str, object]:
    trades = overrides.pop("trades", [_trade(0, 1, "10"), _trade(2, 3, "-5")])
    metrics = overrides.pop("metrics", compute_metrics(trades) if trades else None)  # type: ignore[arg-type]
    kwargs: dict[str, object] = {
        "strategy_key": "ema_crossover_v1",
        "strategy_version": "1",
        "strategy_parameters": {"fast_period": 20, "slow_period": 50},
        "instrument": EUR_USD,
        "granularity": Granularity.H1,
        "source": CandleSource.NATIVE,
        "requested_start": UtcTimestamp(datetime(2024, 1, 1, tzinfo=UTC)),
        "requested_end": UtcTimestamp(datetime(2025, 12, 31, tzinfo=UTC)),
        "git_commit": "abc123",
        "trades": trades,
        "metrics": metrics,
        "generated_at": UtcTimestamp(datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)),
    }
    kwargs.update(overrides)
    return kwargs


# --- exact shape --------------------------------------------------------


def test_exact_report_shape() -> None:
    trades = [_trade(0, 1, "10"), _trade(2, 3, "-5")]
    metrics = compute_metrics(trades)

    report = to_report_dict(**_base_kwargs(trades=trades, metrics=metrics))  # type: ignore[arg-type]

    assert report == {
        "schema_version": 1,
        "generated_at": "2026-09-21T12:00:00Z",
        "strategy": {
            "key": "ema_crossover_v1",
            "version": "1",
            "parameters": {"fast_period": 20, "slow_period": 50},
        },
        "instrument": "EUR_USD",
        "granularity": "H1",
        "source": "NATIVE",
        "from": "2024-01-01T00:00:00Z",
        "to": "2025-12-31T00:00:00Z",
        "git_commit": "abc123",
        "metrics": {
            "trade_count": 2,
            "win_count": 1,
            "loss_count": 1,
            "breakeven_count": 0,
            "win_rate": str(metrics.win_rate),
            "average_win": str(metrics.average_win.amount),  # type: ignore[union-attr]
            "average_loss": str(metrics.average_loss.amount),  # type: ignore[union-attr]
            "expectancy": str(metrics.expectancy.amount),
            "profit_factor": str(metrics.profit_factor),
            "total_pnl": str(metrics.total_pnl.amount),
            "max_drawdown": str(metrics.max_drawdown.amount),
            "sharpe": str(metrics.sharpe),
            "sortino": str(metrics.sortino),
        },
        "trades": [
            {
                "side": "LONG",
                "entry_time": "2024-01-01T00:00:00Z",
                "entry_price": "1.1000",
                "exit_time": "2024-01-01T01:00:00Z",
                "exit_price": "1.1050",
                "pnl": "10",
            },
            {
                "side": "LONG",
                "entry_time": "2024-01-01T02:00:00Z",
                "entry_price": "1.1000",
                "exit_time": "2024-01-01T03:00:00Z",
                "exit_price": "1.1050",
                "pnl": "-5",
            },
        ],
    }


def test_schema_version_constant_matches_output() -> None:
    report = to_report_dict(**_base_kwargs())  # type: ignore[arg-type]
    assert report["schema_version"] == SCHEMA_VERSION == 1


# --- Decimal-as-string rule ----------------------------------------------


def test_decimal_prices_serialize_as_strings() -> None:
    report = to_report_dict(**_base_kwargs())  # type: ignore[arg-type]
    trade = report["trades"][0]
    assert isinstance(trade["entry_price"], str)
    assert isinstance(trade["exit_price"], str)


def test_decimal_pnl_serializes_as_string() -> None:
    report = to_report_dict(**_base_kwargs())  # type: ignore[arg-type]
    for trade in report["trades"]:
        assert isinstance(trade["pnl"], str)


def test_decimal_metrics_serialize_as_strings() -> None:
    report = to_report_dict(**_base_kwargs())  # type: ignore[arg-type]
    m = report["metrics"]
    for field in (
        "win_rate",
        "average_win",
        "average_loss",
        "expectancy",
        "profit_factor",
        "total_pnl",
        "max_drawdown",
        "sharpe",
        "sortino",
    ):
        assert isinstance(m[field], str), f"{field} must be a string"


def test_decimal_strategy_parameter_serializes_as_string_int_parameter_stays_int() -> None:
    kwargs = _base_kwargs(
        strategy_parameters={"lookback": 20, "expansion_threshold": Decimal("1.5")}
    )
    report = to_report_dict(**kwargs)  # type: ignore[arg-type]
    params = report["strategy"]["parameters"]
    assert params["lookback"] == 20
    assert isinstance(params["lookback"], int)
    assert params["expansion_threshold"] == "1.5"
    assert isinstance(params["expansion_threshold"], str)


# --- integers stay integers ----------------------------------------------


def test_integer_counts_remain_integers() -> None:
    report = to_report_dict(**_base_kwargs())  # type: ignore[arg-type]
    m = report["metrics"]
    for field in ("trade_count", "win_count", "loss_count", "breakeven_count"):
        assert isinstance(m[field], int), f"{field} must be an int"


# --- timestamps -----------------------------------------------------------


def test_timestamps_are_utc_iso8601_with_z_suffix() -> None:
    report = to_report_dict(**_base_kwargs())  # type: ignore[arg-type]
    assert report["generated_at"] == "2026-09-21T12:00:00Z"
    assert report["from"] == "2024-01-01T00:00:00Z"
    assert report["to"] == "2025-12-31T00:00:00Z"
    trade = report["trades"][0]
    assert trade["entry_time"].endswith("Z")
    assert trade["exit_time"].endswith("Z")


# --- side -------------------------------------------------------------


def test_side_serializes_as_long_or_short() -> None:
    trades = [_trade(0, 1, "10", side=TradeSide.LONG), _trade(2, 3, "10", side=TradeSide.SHORT)]
    report = to_report_dict(**_base_kwargs(trades=trades, metrics=compute_metrics(trades)))  # type: ignore[arg-type]
    sides = [t["side"] for t in report["trades"]]
    assert sides == ["LONG", "SHORT"]


# --- undefined optional metrics -> null -----------------------------------


def test_undefined_profit_factor_serializes_as_null() -> None:
    # All wins, no losses -> gross_loss=0 -> profit_factor is None.
    trades = [_trade(0, 1, "10"), _trade(2, 3, "5")]
    report = to_report_dict(**_base_kwargs(trades=trades, metrics=compute_metrics(trades)))  # type: ignore[arg-type]
    assert report["metrics"]["profit_factor"] is None


def test_zero_trades_reports_all_metrics_as_null_not_fabricated_zero() -> None:
    report = to_report_dict(**_base_kwargs(trades=[], metrics=None))  # type: ignore[arg-type]
    m = report["metrics"]
    assert m["trade_count"] == 0
    for field in (
        "win_rate",
        "average_win",
        "average_loss",
        "expectancy",
        "profit_factor",
        "total_pnl",
        "max_drawdown",
        "sharpe",
        "sortino",
    ):
        assert m[field] is None, f"{field} must be null, not a fabricated value"
    assert report["trades"] == []


def test_trades_and_metrics_emptiness_must_agree() -> None:
    with pytest.raises(ValueError, match="emptiness"):
        to_report_dict(**_base_kwargs(trades=[], metrics=compute_metrics([_trade(0, 1, "10")])))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="emptiness"):
        to_report_dict(**_base_kwargs(trades=[_trade(0, 1, "10")], metrics=None))  # type: ignore[arg-type]


# --- trade order -------------------------------------------------------


def test_trades_preserve_deterministic_input_order() -> None:
    trades = [_trade(4, 5, "1"), _trade(0, 1, "2"), _trade(2, 3, "3")]
    report = to_report_dict(**_base_kwargs(trades=trades, metrics=compute_metrics(trades)))  # type: ignore[arg-type]
    pnls = [t["pnl"] for t in report["trades"]]
    assert pnls == ["1", "2", "3"], "must preserve the CALLER's own order, not re-sort"


# --- no recomputation ---------------------------------------------------


def test_serializer_performs_no_metric_recalculation() -> None:
    """Pass METRICS that deliberately do NOT match the trades (a
    fabricated BacktestMetrics unrelated to the real ones) and confirm
    the report reflects exactly the metrics object PASSED IN, not
    something recomputed from `trades` -- proving there is no hidden
    recomputation happening inside the serializer."""
    trades = [_trade(0, 1, "10"), _trade(2, 3, "-5")]
    fabricated = compute_metrics([_trade(0, 1, "999999")])  # unrelated to `trades`

    report = to_report_dict(**_base_kwargs(trades=trades, metrics=fabricated))  # type: ignore[arg-type]

    assert report["metrics"]["trade_count"] == 1
    assert report["metrics"]["total_pnl"] == "999999"
    assert len(report["trades"]) == 2


def test_git_commit_and_generated_at_are_not_computed_internally() -> None:
    """The caller's own git_commit/generated_at pass straight through
    unmodified -- confirms the function never calls out to git or the
    system clock itself (which would make it impure and untestable)."""
    report = to_report_dict(**_base_kwargs(git_commit="deadbeef"))  # type: ignore[arg-type]
    assert report["git_commit"] == "deadbeef"


# --- config_identifier / report_filename ------------------------------


def test_config_identifier_is_deterministic() -> None:
    params: dict[str, int | str | Decimal] = {"fast_period": 20, "slow_period": 50}
    assert config_identifier(params) == config_identifier(dict(params))


def test_config_identifier_differs_for_different_parameters() -> None:
    a = config_identifier({"fast_period": 20, "slow_period": 50})
    b = config_identifier({"fast_period": 10, "slow_period": 50})
    assert a != b


def test_config_identifier_is_key_order_independent() -> None:
    a = config_identifier({"fast_period": 20, "slow_period": 50})
    b = config_identifier({"slow_period": 50, "fast_period": 20})
    assert a == b


def test_config_identifier_treats_decimal_and_equal_string_as_equivalent() -> None:
    """A Decimal(\"1.5\") parameter and the pre-formatted string \"1.5\"
    must hash identically -- config_identifier's own job is to
    fingerprint the FORMATTED value actually written into the report,
    not the raw Python type used to express it."""
    a = config_identifier({"expansion_threshold": Decimal("1.5")})
    b = config_identifier({"expansion_threshold": "1.5"})
    assert a == b


def test_config_identifier_is_not_pythons_builtin_hash() -> None:
    params: dict[str, int | str | Decimal] = {"fast_period": 20, "slow_period": 50}
    assert config_identifier(params) != str(hash(frozenset(params.items())))
    # sha256 hex digest, truncated to 8 chars -- always valid lowercase hex.
    identifier = config_identifier(params)
    assert len(identifier) == 8
    int(identifier, 16)  # raises ValueError if not valid hex


def test_report_filename_default_configuration_has_no_suffix() -> None:
    filename = report_filename(
        strategy_key="ema_crossover_v1",
        instrument=EUR_USD,
        granularity=Granularity.H1,
        requested_start=UtcTimestamp(datetime(2024, 1, 1, tzinfo=UTC)),
        requested_end=UtcTimestamp(datetime(2025, 12, 31, tzinfo=UTC)),
        strategy_parameters={"fast_period": 20, "slow_period": 50},
        is_default_configuration=True,
    )

    assert filename == "ema_crossover_v1_EUR_USD_H1_20240101_20251231.json"


def test_report_filename_non_default_configuration_has_deterministic_suffix() -> None:
    params: dict[str, int | str | Decimal] = {"fast_period": 10, "slow_period": 30}
    kwargs: dict[str, object] = {
        "strategy_key": "ema_crossover_v1",
        "instrument": EUR_USD,
        "granularity": Granularity.H1,
        "requested_start": UtcTimestamp(datetime(2024, 1, 1, tzinfo=UTC)),
        "requested_end": UtcTimestamp(datetime(2025, 12, 31, tzinfo=UTC)),
        "strategy_parameters": params,
    }

    filename = report_filename(**kwargs, is_default_configuration=False)  # type: ignore[arg-type]

    expected_suffix = config_identifier(params)
    assert filename == f"ema_crossover_v1_EUR_USD_H1_20240101_20251231_{expected_suffix}.json"


def test_report_filename_different_configurations_never_collide() -> None:
    common: dict[str, object] = {
        "strategy_key": "ema_crossover_v1",
        "instrument": EUR_USD,
        "granularity": Granularity.H1,
        "requested_start": UtcTimestamp(datetime(2024, 1, 1, tzinfo=UTC)),
        "requested_end": UtcTimestamp(datetime(2025, 12, 31, tzinfo=UTC)),
        "is_default_configuration": False,
    }
    a = report_filename(strategy_parameters={"fast_period": 10, "slow_period": 30}, **common)  # type: ignore[arg-type]
    b = report_filename(strategy_parameters={"fast_period": 15, "slow_period": 30}, **common)  # type: ignore[arg-type]
    assert a != b


def test_report_filename_different_instruments_differ() -> None:
    common: dict[str, object] = {
        "strategy_key": "ema_crossover_v1",
        "granularity": Granularity.H1,
        "requested_start": UtcTimestamp(datetime(2024, 1, 1, tzinfo=UTC)),
        "requested_end": UtcTimestamp(datetime(2025, 12, 31, tzinfo=UTC)),
        "strategy_parameters": {"fast_period": 20, "slow_period": 50},
        "is_default_configuration": True,
    }
    a = report_filename(instrument=EUR_USD, **common)  # type: ignore[arg-type]
    b = report_filename(instrument=USD_JPY, **common)  # type: ignore[arg-type]
    assert a != b
    assert "EUR_USD" in a
    assert "USD_JPY" in b

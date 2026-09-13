from datetime import UTC, datetime

import pytest

from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_hypothesis import TradeHypothesis
from forex_agent.domain.trade_side import TradeSide

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
NOW = UtcTimestamp(datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC))


def test_valid_trade_hypothesis() -> None:
    hypothesis = TradeHypothesis(
        instrument=EUR_USD,
        side=TradeSide.LONG,
        generated_at=NOW,
        rationale="fast MA crossed above slow MA",
    )

    assert hypothesis.instrument == EUR_USD
    assert hypothesis.side is TradeSide.LONG
    assert hypothesis.generated_at == NOW
    assert hypothesis.rationale == "fast MA crossed above slow MA"


def test_rejects_wrong_type_for_instrument() -> None:
    with pytest.raises(TypeError, match="instrument"):
        TradeHypothesis(
            instrument="EUR_USD",  # type: ignore[arg-type]
            side=TradeSide.LONG,
            generated_at=NOW,
            rationale="x",
        )


def test_rejects_wrong_type_for_side() -> None:
    with pytest.raises(TypeError, match="side"):
        TradeHypothesis(
            instrument=EUR_USD,
            side="LONG",  # type: ignore[arg-type]
            generated_at=NOW,
            rationale="x",
        )


def test_rejects_wrong_type_for_generated_at() -> None:
    with pytest.raises(TypeError, match="generated_at"):
        TradeHypothesis(
            instrument=EUR_USD,
            side=TradeSide.LONG,
            generated_at=datetime(2026, 1, 1, tzinfo=UTC),  # type: ignore[arg-type]
            rationale="x",
        )


@pytest.mark.parametrize("rationale", ["", "   "])
def test_rejects_empty_rationale(rationale: str) -> None:
    with pytest.raises(ValueError, match="rationale"):
        TradeHypothesis(
            instrument=EUR_USD, side=TradeSide.LONG, generated_at=NOW, rationale=rationale
        )

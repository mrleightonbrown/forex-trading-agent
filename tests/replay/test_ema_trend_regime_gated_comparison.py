"""FX-28: the third leg of the regime-conditioning comparison FX-21
started. `test_ema_regime_conditioned.py` (FX-21/FX-21H) covers
unconditional EMA vs. entry-regime ATTRIBUTION (label trades after the
fact; which trades occur never changes). This test adds actual
regime-GATING: `EmaCrossoverTrendRegimeGatedStrategy` structurally
refuses (goes FLAT on) a crossover signal unless `TrendRegime.TRENDING`
confirms it -- a genuinely different trade set, not a relabeling of the
same one.

Runs both strategies against the same real OANDA practice H1 candles.
Auto-skipped when OANDA credentials aren't configured.

Deliberately asserts only STRUCTURAL properties -- never that gating
"beats" the unconditional baseline. Which one performs better on any
given real-data sample is the actual empirical question this comparison
exists to surface (reported as a dated finding in docs/DECISIONS.md),
not something to hard-code an assertion around -- same honesty norm as
FX-21's own replay test.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from forex_agent.apps.settings import get_settings
from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.backtest_metrics import compute_metrics
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.regime_segmentation import segment_trades_by_regime
from forex_agent.domain.strategies.ema_crossover import EmaCrossoverStrategy
from forex_agent.domain.strategies.ema_crossover_trend_regime_gated import (
    EmaCrossoverTrendRegimeGatedStrategy,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_simulation import simulate_trades
from forex_agent.infrastructure.broker_oanda.market_data_adapter import OandaMarketDataAdapter


def _oanda_credentials_available() -> bool:
    return bool(get_settings().oanda_api_key)


pytestmark = pytest.mark.skipif(
    not _oanda_credentials_available(),
    reason="OANDA_API_KEY not configured; skipping live OANDA check",
)


@pytest.fixture
async def adapter() -> AsyncIterator[OandaMarketDataAdapter]:
    settings = get_settings()
    assert settings.oanda_api_key is not None

    market_data = OandaMarketDataAdapter(
        api_key=settings.oanda_api_key, base_url=settings.oanda_api_base_url
    )
    try:
        yield market_data
    finally:
        await market_data.aclose()


@pytest.mark.asyncio
async def test_ema_unconditional_vs_attribution_vs_gating(
    adapter: OandaMarketDataAdapter,
) -> None:
    eur_usd = Instrument(base_currency="EUR", quote_currency="USD")
    end = UtcTimestamp(datetime.now(UTC).replace(minute=0, second=0, microsecond=0))
    start = UtcTimestamp(end.value - timedelta(days=90))

    candles = await adapter.get_candles(eur_usd, Granularity.H1, start, end)
    finalized = [c for c in candles if c.is_finalized]
    assert len(finalized) > 200, "expected enough live H1 candles for a meaningful run"

    # Leg 1: unconditional.
    unconditional = EmaCrossoverStrategy()
    unconditional_trades = simulate_trades(run_backtest(unconditional, finalized), finalized)

    # Leg 2: entry-regime attribution (FX-21/FX-23, unmodified) over the
    # same unconditional trade set.
    segmented = segment_trades_by_regime(unconditional_trades, finalized)
    assert len(segmented.trending) + len(segmented.ranging) + len(segmented.unclassified) == len(
        unconditional_trades
    )

    # Leg 3: actual gating -- a genuinely different, independently
    # generated trade set.
    gated = EmaCrossoverTrendRegimeGatedStrategy()
    gated_trades = simulate_trades(run_backtest(gated, finalized), finalized)

    # compute_metrics must not raise on any non-empty leg.
    if unconditional_trades:
        compute_metrics(unconditional_trades)
    if segmented.trending:
        compute_metrics(segmented.trending)
    if segmented.ranging:
        compute_metrics(segmented.ranging)
    if gated_trades:
        compute_metrics(gated_trades)

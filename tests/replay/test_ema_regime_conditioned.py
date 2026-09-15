"""FX-21: the regime-conditioned experiment itself. Runs EmaCrossoverStrategy
against real OANDA practice H1 candles, segments the resulting trades by
the TrendRegime in effect at entry, and compares unconditional vs.
TRENDING-only vs. RANGING-only metrics.

Auto-skipped when OANDA credentials aren't configured — same pattern as
every other live test.

Deliberately asserts only STRUCTURAL properties (every trade lands in
exactly one bucket, compute_metrics doesn't raise on any non-empty
bucket) — never that one bucket's metrics "beat" another's. Which bucket
performs better on any given real-data sample is the actual empirical
question this test exists to surface, not something to hard-code an
assertion around; asserting a specific winner would be dishonest test
design against non-reproducible live market data. The real observed
numbers from running this are recorded as a dated finding in
docs/DECISIONS.md, not asserted here.
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
async def test_ema_regime_conditioned_experiment(adapter: OandaMarketDataAdapter) -> None:
    eur_usd = Instrument(base_currency="EUR", quote_currency="USD")
    end = UtcTimestamp(datetime.now(UTC).replace(minute=0, second=0, microsecond=0))
    # H1 candles, bounded by the existing single-request cap (FX-6): a
    # few months of H1 stays comfortably under 5000 candles and gives
    # classify_regime's default period=14 (needs 28 candles) and EMA's
    # default slow_period=50 (needs 51) plenty of room, with many trades
    # left over for a meaningful comparison.
    start = UtcTimestamp(end.value - timedelta(days=90))

    candles = await adapter.get_candles(eur_usd, Granularity.H1, start, end)
    finalized = [c for c in candles if c.is_finalized]
    assert len(finalized) > 200, "expected enough live H1 candles for a meaningful run"

    strategy = EmaCrossoverStrategy()  # default 20/50 SMA-seeded EMA
    hypotheses = run_backtest(strategy, finalized)
    trades = simulate_trades(hypotheses, finalized)
    assert len(trades) > 0, "expected at least one trade over this window"

    segmented = segment_trades_by_regime(trades, finalized)

    # Every trade lands in exactly one bucket.
    assert len(segmented.trending) + len(segmented.ranging) + len(segmented.unclassified) == len(
        trades
    )

    baseline_metrics = compute_metrics(trades)
    assert baseline_metrics.trade_count == len(trades)

    # compute_metrics must not raise on any non-empty bucket -- it's
    # already proven itself on arbitrary trade lists (FX-17); this just
    # confirms the segmentation output is valid input to it.
    if segmented.trending:
        compute_metrics(segmented.trending)
    if segmented.ranging:
        compute_metrics(segmented.ranging)

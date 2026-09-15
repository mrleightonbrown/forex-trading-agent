"""FX-23: the Mean-Reversion entry-regime-attribution experiment — the
roadmap's other named example ("Mean Reversion alone vs. Mean Reversion
when RANGING"), now that segment_trades_by_regime (FX-21, look-ahead
fixed FX-21H) exists. Runs MeanReversionStrategy unconditionally against
real OANDA practice H1 candles, segments the resulting trades by the
TrendRegime prevailing strictly BEFORE each trade's entry, and compares
unconditional vs. TRENDING-only vs. RANGING-only metrics.

Same entry-regime ATTRIBUTION framing as FX-21's EMA experiment, not
regime-GATING: MeanReversionStrategy runs exactly as it always does,
taking every signal it would normally take; regime only labels completed
trades afterward. See docs/DECISIONS.md (FX-21H's entry) for why that
distinction matters and what a true gating experiment would need to
decide.

Auto-skipped when OANDA credentials aren't configured — same pattern as
every other live test.

Deliberately asserts only STRUCTURAL properties (every trade lands in
exactly one bucket, compute_metrics doesn't raise on any non-empty
bucket) — never that one bucket's metrics "beat" another's, for the same
reason as FX-21's own replay test: asserting a specific winner against
non-reproducible live market data would be dishonest test design. The
real observed numbers are recorded as a dated finding in
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
from forex_agent.domain.strategies.mean_reversion import MeanReversionStrategy
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
async def test_mean_reversion_regime_conditioned_experiment(
    adapter: OandaMarketDataAdapter,
) -> None:
    eur_usd = Instrument(base_currency="EUR", quote_currency="USD")
    end = UtcTimestamp(datetime.now(UTC).replace(minute=0, second=0, microsecond=0))
    # Same window shape as FX-21's EMA experiment, for direct
    # comparability: ~90 days of H1, well under the single-request cap.
    start = UtcTimestamp(end.value - timedelta(days=90))

    candles = await adapter.get_candles(eur_usd, Granularity.H1, start, end)
    finalized = [c for c in candles if c.is_finalized]
    assert len(finalized) > 200, "expected enough live H1 candles for a meaningful run"

    strategy = MeanReversionStrategy()  # default period=20, entry_threshold=2.0
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

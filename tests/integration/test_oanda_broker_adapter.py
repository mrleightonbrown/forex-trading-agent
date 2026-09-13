"""Live end-to-end check against the real OANDA practice API.

Auto-skipped when OANDA credentials aren't configured — so CI (no OANDA
secrets) skips cleanly, and a developer machine with `.env` populated runs
it for real. See docs/DECISIONS.md.
"""

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest

from forex_agent.apps.settings import get_settings
from forex_agent.domain.instrument import Instrument
from forex_agent.infrastructure.broker_oanda.adapter import OandaBrokerAdapter


def _oanda_credentials_available() -> bool:
    settings = get_settings()
    return bool(settings.oanda_api_key and settings.oanda_account_id)


pytestmark = pytest.mark.skipif(
    not _oanda_credentials_available(),
    reason="OANDA_API_KEY/OANDA_ACCOUNT_ID not configured; skipping live OANDA check",
)


@pytest.fixture
async def adapter() -> AsyncIterator[OandaBrokerAdapter]:
    settings = get_settings()
    assert settings.oanda_api_key is not None
    assert settings.oanda_account_id is not None

    broker = OandaBrokerAdapter(
        api_key=settings.oanda_api_key,
        account_id=settings.oanda_account_id,
        base_url=settings.oanda_api_base_url,
    )
    try:
        yield broker
    finally:
        await broker.aclose()


@pytest.mark.asyncio
async def test_get_account_balance_against_live_practice_api(adapter: OandaBrokerAdapter) -> None:
    balance = await adapter.get_account_balance()

    assert balance.amount > Decimal("0")
    assert len(balance.currency) == 3


@pytest.mark.asyncio
async def test_get_price_against_live_practice_api(adapter: OandaBrokerAdapter) -> None:
    eur_usd = Instrument(base_currency="EUR", quote_currency="USD")

    price = await adapter.get_price(eur_usd)

    assert price.bid > 0
    assert price.ask >= price.bid

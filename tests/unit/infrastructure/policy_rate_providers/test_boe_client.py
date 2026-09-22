from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from forex_agent.application.ports.policy_rate_history_provider import (
    PolicyRateProviderUnavailableError,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.policy_rate_providers.boe_client import (
    BoePolicyRateHistoryProvider,
)


def _ts(*args: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(*args, tzinfo=UTC))


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> BoePolicyRateHistoryProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://www.bankofengland.co.uk"
    )
    return BoePolicyRateHistoryProvider(client=client)


@pytest.mark.asyncio
async def test_parses_daily_series_and_sends_correct_request_date_format() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/boeapps/database/_iadb-fromshowcolumns.asp"
        assert request.url.params["SeriesCodes"] == "IUDBEDR"
        assert request.url.params["Datefrom"] == "02/Jan/2020"
        assert request.url.params["Dateto"] == "10/Jan/2020"
        return httpx.Response(
            200, text="DATE,IUDBEDR\n02 Jan 2020,0.75\n03 Jan 2020,0.75\n06 Jan 2020,0.75\n"
        )

    result = await _provider(handler).fetch_daily_series(
        "IUDBEDR", _ts(2020, 1, 2), _ts(2020, 1, 10)
    )

    assert result == [
        (_ts(2020, 1, 2), Decimal("0.75")),
        (_ts(2020, 1, 3), Decimal("0.75")),
        (_ts(2020, 1, 6), Decimal("0.75")),
    ]


@pytest.mark.asyncio
async def test_raises_on_non_2xx_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    with pytest.raises(PolicyRateProviderUnavailableError, match="503"):
        await _provider(handler).fetch_daily_series("IUDBEDR", _ts(2020, 1, 1), _ts(2020, 1, 2))


@pytest.mark.asyncio
async def test_raises_on_unexpected_csv_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="WRONG_COLUMN\nvalue\n")

    with pytest.raises(PolicyRateProviderUnavailableError):
        await _provider(handler).fetch_daily_series("IUDBEDR", _ts(2020, 1, 1), _ts(2020, 1, 2))


@pytest.mark.asyncio
async def test_default_client_sends_a_non_library_user_agent() -> None:
    # Regression case found running FX-43's real backfill script live: the
    # BoE's WAF returns 403 for httpx's own default User-Agent, even though
    # an otherwise-identical request succeeds with any other string. Only
    # meaningful for the SELF-CONSTRUCTED client -- a caller-supplied
    # client (as every other test in this file uses) is trusted as-is.
    provider = BoePolicyRateHistoryProvider()
    try:
        user_agent = provider._client.headers["user-agent"]
        assert "python-httpx" not in user_agent.lower()
    finally:
        await provider.aclose()

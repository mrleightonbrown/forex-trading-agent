from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from forex_agent.application.ports.policy_rate_history_provider import (
    PolicyRateProviderUnavailableError,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.policy_rate_providers.fred_client import (
    FredPolicyRateHistoryProvider,
)


def _ts(*args: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(*args, tzinfo=UTC))


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> FredPolicyRateHistoryProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://fred.stlouisfed.org"
    )
    return FredPolicyRateHistoryProvider(client=client)


@pytest.mark.asyncio
async def test_parses_daily_series_and_sends_correct_params() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/graph/fredgraph.csv"
        assert request.url.params["id"] == "DFEDTARU"
        assert request.url.params["cosd"] == "2020-01-01"
        assert request.url.params["coed"] == "2020-01-03"
        return httpx.Response(
            200,
            text="observation_date,DFEDTARU\n2020-01-01,1.75\n2020-01-02,1.75\n2020-01-03,2.00\n",
        )

    result = await _provider(handler).fetch_daily_series(
        "DFEDTARU", _ts(2020, 1, 1), _ts(2020, 1, 3)
    )

    assert result == [
        (_ts(2020, 1, 1), Decimal("1.75")),
        (_ts(2020, 1, 2), Decimal("1.75")),
        (_ts(2020, 1, 3), Decimal("2.00")),
    ]


@pytest.mark.asyncio
async def test_skips_missing_value_marker_not_fabricated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="observation_date,DFEDTARU\n2020-01-01,1.75\n2020-01-02,.\n2020-01-03,2.00\n"
        )

    result = await _provider(handler).fetch_daily_series(
        "DFEDTARU", _ts(2020, 1, 1), _ts(2020, 1, 3)
    )

    assert result == [
        (_ts(2020, 1, 1), Decimal("1.75")),
        (_ts(2020, 1, 3), Decimal("2.00")),
    ]


@pytest.mark.asyncio
async def test_raises_on_non_2xx_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    with pytest.raises(PolicyRateProviderUnavailableError, match="500"):
        await _provider(handler).fetch_daily_series("DFEDTARU", _ts(2020, 1, 1), _ts(2020, 1, 3))


@pytest.mark.asyncio
async def test_raises_on_unexpected_csv_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not,the,expected,columns\n1,2,3,4\n")

    with pytest.raises(PolicyRateProviderUnavailableError):
        await _provider(handler).fetch_daily_series("DFEDTARU", _ts(2020, 1, 1), _ts(2020, 1, 3))


@pytest.mark.asyncio
async def test_raises_on_network_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(PolicyRateProviderUnavailableError):
        await _provider(handler).fetch_daily_series("DFEDTARU", _ts(2020, 1, 1), _ts(2020, 1, 3))

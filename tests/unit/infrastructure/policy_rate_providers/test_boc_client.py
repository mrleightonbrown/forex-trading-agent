import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from forex_agent.application.ports.policy_rate_history_provider import (
    PolicyRateProviderUnavailableError,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.policy_rate_providers.boc_client import (
    BocPolicyRateHistoryProvider,
)


def _ts(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    microsecond: int = 0,
) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, minute, second, microsecond, tzinfo=UTC))


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> BocPolicyRateHistoryProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://www.bankofcanada.ca"
    )
    return BocPolicyRateHistoryProvider(client=client)


@pytest.mark.asyncio
async def test_parses_daily_series_and_sends_correct_params() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/valet/observations/V39079/json"
        assert request.url.params["start_date"] == "2020-01-01"
        assert request.url.params["end_date"] == "2020-01-02"
        body = {
            "observations": [
                {"d": "2020-01-01", "V39079": {"v": "1.75"}},
                {"d": "2020-01-02", "V39079": {"v": "1.75"}},
            ]
        }
        return httpx.Response(200, text=json.dumps(body))

    result = await _provider(handler).fetch_daily_series("V39079", _ts(2020, 1, 1), _ts(2020, 1, 2))

    assert result == [
        (_ts(2020, 1, 1), Decimal("1.75")),
        (_ts(2020, 1, 2), Decimal("1.75")),
    ]


@pytest.mark.asyncio
async def test_raises_on_non_2xx_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    with pytest.raises(PolicyRateProviderUnavailableError, match="500"):
        await _provider(handler).fetch_daily_series("V39079", _ts(2020, 1, 1), _ts(2020, 1, 2))


@pytest.mark.asyncio
async def test_raises_on_unexpected_json_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=json.dumps({"not_observations": []}))

    with pytest.raises(PolicyRateProviderUnavailableError):
        await _provider(handler).fetch_daily_series("V39079", _ts(2020, 1, 1), _ts(2020, 1, 2))

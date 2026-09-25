from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from forex_agent.application.ports.policy_rate_history_provider import (
    PolicyRateProviderUnavailableError,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.policy_rate_providers.ecb_client import (
    EcbPolicyRateHistoryProvider,
)

_HEADER = (
    "KEY,FREQ,REF_AREA,CURRENCY,PROVIDER_FM,INSTRUMENT_FM,PROVIDER_FM_ID,DATA_TYPE_FM,"
    "TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
)


def _row(date: str, value: str) -> str:
    return f"FM.D.U2.EUR.4F.KR.MRR_RT.LEV,D,U2,EUR,4F,KR,MRR_RT,LEV,{date},{value},A\n"


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


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> EcbPolicyRateHistoryProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://data-api.ecb.europa.eu"
    )
    return EcbPolicyRateHistoryProvider(client=client)


@pytest.mark.asyncio
async def test_parses_daily_series_by_column_name_not_position() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/service/data/FM/D.U2.EUR.4F.KR.MRR_RT.LEV"
        assert request.url.params["format"] == "csvdata"
        assert request.url.params["startPeriod"] == "2020-01-01"
        assert request.url.params["endPeriod"] == "2020-01-02"
        return httpx.Response(
            200, text=_HEADER + _row("2020-01-01", "0") + _row("2020-01-02", "0.25")
        )

    result = await _provider(handler).fetch_daily_series(
        "FM.D.U2.EUR.4F.KR.MRR_RT.LEV", _ts(2020, 1, 1), _ts(2020, 1, 2)
    )

    assert result == [
        (_ts(2020, 1, 1), Decimal("0")),
        (_ts(2020, 1, 2), Decimal("0.25")),
    ]


@pytest.mark.asyncio
async def test_leading_fm_prefix_is_not_doubled_in_the_request_path() -> None:
    # Regression case found running FX-43's real backfill script live: the
    # registry stores the FULL key including the "FM." dataflow prefix (as
    # ECB itself cites it), but the REST path already names "FM" as its own
    # segment -- passing the prefixed key through unmodified produces
    # /service/data/FM/FM.D.U2... , which the live API 400s on.
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/service/data/FM/D.U2.EUR.4F.KR.MRR_RT.LEV"
        return httpx.Response(200, text=_HEADER + _row("2020-01-01", "0"))

    await _provider(handler).fetch_daily_series(
        "FM.D.U2.EUR.4F.KR.MRR_RT.LEV", _ts(2020, 1, 1), _ts(2020, 1, 1)
    )


@pytest.mark.asyncio
async def test_empty_200_response_is_zero_observations_not_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="")

    result = await _provider(handler).fetch_daily_series(
        "FM.D.U2.EUR.4F.KR.MRR_RT.LEV", _ts(1990, 1, 1), _ts(1990, 1, 10)
    )

    assert result == []


@pytest.mark.asyncio
async def test_raises_on_404_invalid_series_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text='{"title":"Not Found","status":404}')

    with pytest.raises(PolicyRateProviderUnavailableError, match="404"):
        await _provider(handler).fetch_daily_series(
            "FM.D.U2.EUR.4F.KR.NOT_REAL.LEV", _ts(2020, 1, 1), _ts(2020, 1, 2)
        )


@pytest.mark.asyncio
async def test_raises_on_unexpected_csv_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not,the,expected,columns\n1,2,3,4\n")

    with pytest.raises(PolicyRateProviderUnavailableError):
        await _provider(handler).fetch_daily_series(
            "FM.D.U2.EUR.4F.KR.MRR_RT.LEV", _ts(2020, 1, 1), _ts(2020, 1, 2)
        )

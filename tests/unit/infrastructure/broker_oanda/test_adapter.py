from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest

from forex_agent.application.ports.exceptions import (
    BrokerUnavailableError,
    InstrumentNotAvailableError,
)
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.money import Money
from forex_agent.domain.price import Price
from forex_agent.infrastructure.broker_oanda.adapter import NonPracticeHostError, OandaBrokerAdapter

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
ACCOUNT_ID = "001-001-1-001"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api-fxpractice.oanda.com",
    )


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response], account_id: str = ACCOUNT_ID
) -> OandaBrokerAdapter:
    return OandaBrokerAdapter(
        api_key="secret-token", account_id=account_id, client=_client(handler)
    )


# --- Practice-host guard ----------------------------------------------------


def test_rejects_non_practice_host() -> None:
    with pytest.raises(NonPracticeHostError):
        OandaBrokerAdapter(
            api_key="x", account_id=ACCOUNT_ID, base_url="https://api-fxtrade.oanda.com"
        )


def test_accepts_practice_host() -> None:
    OandaBrokerAdapter(
        api_key="x", account_id=ACCOUNT_ID, base_url="https://api-fxpractice.oanda.com"
    )


# --- get_price ---------------------------------------------------------


@pytest.mark.asyncio
async def test_get_price_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v3/accounts/{ACCOUNT_ID}/pricing"
        assert request.url.params["instruments"] == "EUR_USD"
        assert request.headers["Authorization"] == "Bearer secret-token"
        return httpx.Response(
            200,
            json={
                "prices": [
                    {
                        "instrument": "EUR_USD",
                        "bids": [{"price": "1.10000"}],
                        "asks": [{"price": "1.10020"}],
                    }
                ]
            },
        )

    price = await _adapter(handler).get_price(EUR_USD)

    assert price == Price(bid=Decimal("1.10000"), ask=Decimal("1.10020"))


@pytest.mark.asyncio
async def test_get_price_uses_only_top_of_book() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "prices": [
                    {
                        "instrument": "EUR_USD",
                        "bids": [{"price": "1.10000"}, {"price": "1.09999"}],
                        "asks": [{"price": "1.10020"}, {"price": "1.10025"}],
                    }
                ]
            },
        )

    price = await _adapter(handler).get_price(EUR_USD)

    assert price == Price(bid=Decimal("1.10000"), ask=Decimal("1.10020"))


@pytest.mark.asyncio
async def test_get_price_400_is_instrument_not_available() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"errorMessage": "Invalid value specified for 'instruments'"}
        )

    with pytest.raises(InstrumentNotAvailableError):
        await _adapter(handler).get_price(EUR_USD)


@pytest.mark.asyncio
async def test_get_price_instrument_missing_from_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"prices": []})

    with pytest.raises(InstrumentNotAvailableError):
        await _adapter(handler).get_price(EUR_USD)


@pytest.mark.asyncio
async def test_get_price_empty_bids_or_asks_is_instrument_not_available() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"prices": [{"instrument": "EUR_USD", "bids": [], "asks": []}]},
        )

    with pytest.raises(InstrumentNotAvailableError):
        await _adapter(handler).get_price(EUR_USD)


@pytest.mark.asyncio
async def test_get_price_auth_failure_is_broker_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errorMessage": "Insufficient authorization"})

    with pytest.raises(BrokerUnavailableError):
        await _adapter(handler).get_price(EUR_USD)


@pytest.mark.asyncio
async def test_get_price_server_error_is_broker_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    with pytest.raises(BrokerUnavailableError):
        await _adapter(handler).get_price(EUR_USD)


@pytest.mark.asyncio
async def test_get_price_network_error_is_broker_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(BrokerUnavailableError):
        await _adapter(handler).get_price(EUR_USD)


@pytest.mark.asyncio
async def test_get_price_missing_prices_key_is_broker_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    with pytest.raises(BrokerUnavailableError):
        await _adapter(handler).get_price(EUR_USD)


@pytest.mark.asyncio
async def test_get_price_malformed_price_entry_is_broker_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "prices": [
                    {"instrument": "EUR_USD", "bids": [{"nope": "?"}], "asks": [{"price": "1.1"}]}
                ]
            },
        )

    with pytest.raises(BrokerUnavailableError):
        await _adapter(handler).get_price(EUR_USD)


# --- get_account_balance ------------------------------------------------


@pytest.mark.asyncio
async def test_get_account_balance_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v3/accounts/{ACCOUNT_ID}/summary"
        return httpx.Response(200, json={"account": {"balance": "100000.0000", "currency": "CAD"}})

    balance = await _adapter(handler).get_account_balance()

    assert balance == Money(Decimal("100000.0000"), "CAD")


@pytest.mark.asyncio
async def test_get_account_balance_auth_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errorMessage": "nope"})

    with pytest.raises(BrokerUnavailableError):
        await _adapter(handler).get_account_balance()


@pytest.mark.asyncio
async def test_get_account_balance_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(BrokerUnavailableError):
        await _adapter(handler).get_account_balance()


@pytest.mark.asyncio
async def test_get_account_balance_missing_account_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    with pytest.raises(BrokerUnavailableError):
        await _adapter(handler).get_account_balance()


@pytest.mark.asyncio
async def test_get_account_balance_malformed_account_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"account": {"currency": "CAD"}})

    with pytest.raises(BrokerUnavailableError):
        await _adapter(handler).get_account_balance()


# --- lifecycle -----------------------------------------------------------


@pytest.mark.asyncio
async def test_aclose_closes_self_created_client() -> None:
    adapter = OandaBrokerAdapter(api_key="x", account_id=ACCOUNT_ID)

    await adapter.aclose()

    assert adapter._client.is_closed


@pytest.mark.asyncio
async def test_aclose_does_not_close_injected_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"account": {"balance": "1", "currency": "USD"}})

    client = _client(handler)
    adapter = OandaBrokerAdapter(api_key="x", account_id=ACCOUNT_ID, client=client)

    await adapter.aclose()

    assert not client.is_closed

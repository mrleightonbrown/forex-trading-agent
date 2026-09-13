"""Plumbing shared by every OANDA adapter in this package (FX-4's
`OandaBrokerAdapter`, FX-6's `OandaMarketDataAdapter`): the practice-host
safety guard and JSON response parsing.
"""

from typing import Any
from urllib.parse import urlsplit

import httpx

from forex_agent.application.ports.exceptions import BrokerPortError, BrokerUnavailableError

PRACTICE_HOST = "api-fxpractice.oanda.com"
DEFAULT_BASE_URL = f"https://{PRACTICE_HOST}"


class NonPracticeHostError(BrokerPortError):
    """Raised when configured with anything other than OANDA's practice
    host. Independent of `Settings`' own PAPER/PRACTICE validation, since
    `OANDA_API_BASE_URL` is a separately-configurable value."""


def require_practice_host(base_url: str) -> None:
    host = urlsplit(base_url).hostname
    if host != PRACTICE_HOST:
        raise NonPracticeHostError(
            f"refuses to operate against host {host!r}; "
            f"only {PRACTICE_HOST!r} (practice) is permitted in V1"
        )


def parse_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = response.json()
    except ValueError as exc:
        raise BrokerUnavailableError(f"OANDA returned a non-JSON response: {exc}") from exc
    return payload


def error_message(response: httpx.Response) -> str:
    """OANDA's `errorMessage` field, falling back to the raw body."""
    try:
        payload = response.json()
    except ValueError:
        return response.text
    message = payload.get("errorMessage")
    return message if isinstance(message, str) else response.text

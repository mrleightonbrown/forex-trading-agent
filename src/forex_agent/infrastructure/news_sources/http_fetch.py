"""FX-57A: provider-neutral HTTP transport for news-source polling.

Deliberately the SMALLEST shared piece every RSS/Atom-based news
adapter needs (FX-57A Section 8): perform one GET, with conservative
bounded retry for transport failures/HTTP 429/HTTP 5xx only (never for
an ordinary 4xx, never for a parse failure -- parsing happens strictly
AFTER this module returns), and capture FTA's own retrieval instant
EXACTLY ONCE, immediately after a response body is actually received,
BEFORE any parsing is attempted. This module knows nothing about RSS,
Fed, or any other provider's schema -- it only moves bytes and reports
when FTA received them.

**The non-negotiable PIT rule this module exists to protect (FX-57A
Section 3/4)**: `retrieved_at` is FTA's own observation time for every
item in the response, NEVER any provider-supplied publish timestamp.
The `clock` parameter exists so a deterministic test can control this
instant exactly -- nothing in this module ever calls `datetime.now()`
more than once per successful response, and nothing downstream may
call it again for the same response.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from forex_agent.application.ports.news_source import NewsSourceUnavailableError
from forex_agent.domain.timestamps import UtcTimestamp

ClockFn = Callable[[], UtcTimestamp]
SleepFn = Callable[[float], Awaitable[None]]


def default_clock() -> UtcTimestamp:
    return UtcTimestamp(datetime.now(UTC))


async def _default_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


@dataclass(frozen=True, slots=True)
class FetchedResponse:
    """One successfully-retrieved HTTP response, plus FTA's own
    retrieval instant for it. `text`/`retrieved_at` are shared,
    unchanged, by every item a parser later extracts from this SAME
    response (FX-57A Section 4) -- a parser must never call its own
    clock."""

    text: str
    retrieved_at: UtcTimestamp
    status_code: int
    content_type: str | None


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    if seconds < 0:
        return None
    return seconds


async def fetch_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    clock: ClockFn = default_clock,
    max_attempts: int = 3,
    backoff_seconds: Callable[[int], float] = lambda attempt: 2.0 * attempt,
    sleep: SleepFn = _default_sleep,
) -> FetchedResponse:
    """GET `url`, retrying only a transport failure, HTTP 429, or HTTP
    5xx, up to `max_attempts` total attempts. An ordinary 4xx (other
    than 429) never retries. `retrieved_at` is captured exactly once,
    immediately after the attempt that actually succeeds -- never at
    the start of the loop, and never per subsequent parsed item."""
    last_error: str = "no attempt was made"
    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.get(url)
        except httpx.RequestError as exc:
            last_error = f"transport error reaching {url}: {exc}"
            if attempt < max_attempts:
                await sleep(backoff_seconds(attempt))
                continue
            raise NewsSourceUnavailableError(
                f"{last_error} (giving up after {attempt} attempts)"
            ) from exc

        if response.status_code == 429 or response.status_code >= 500:
            last_error = f"{url} returned HTTP {response.status_code}"
            if attempt < max_attempts:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                await sleep(retry_after if retry_after is not None else backoff_seconds(attempt))
                continue
            raise NewsSourceUnavailableError(f"{last_error} (giving up after {attempt} attempts)")

        if response.status_code >= 400:
            raise NewsSourceUnavailableError(
                f"{url} returned HTTP {response.status_code} -- not retried"
            )

        retrieved_at = clock()
        return FetchedResponse(
            text=response.text,
            retrieved_at=retrieved_at,
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
        )

    raise NewsSourceUnavailableError(last_error)

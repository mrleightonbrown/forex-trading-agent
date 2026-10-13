"""FX-57A: `fetch_text` transport retry/timeout/clock-injection tests
-- no real network access."""

from datetime import UTC, datetime

import httpx
import pytest

from forex_agent.application.ports.news_source import NewsSourceUnavailableError
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.news_sources.http_fetch import (
    FetchAttemptOutcome,
    FetchAttemptOutcomeKind,
    fetch_text,
)


class _ObservationPersistenceError(Exception):
    """Simulates a telemetry/database write failure inside `on_attempt`."""


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url="https://example.test")


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.asyncio
async def test_successful_response_captures_clock_exactly_once() -> None:
    calls = {"count": 0}

    def clock() -> UtcTimestamp:
        calls["count"] += 1
        return UtcTimestamp(datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<rss/>", headers={"content-type": "text/xml"})

    client = _client(httpx.MockTransport(handler))
    result = await fetch_text(client, "/feed.xml", clock=clock, sleep=_no_sleep)
    await client.aclose()

    assert calls["count"] == 1
    assert result.text == "<rss/>"
    assert result.retrieved_at.value == datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)
    assert result.status_code == 200
    assert result.content_type == "text/xml"


@pytest.mark.asyncio
async def test_transport_error_retries_then_succeeds() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, text="ok")

    client = _client(httpx.MockTransport(handler))
    result = await fetch_text(client, "/feed.xml", sleep=_no_sleep, max_attempts=3)
    await client.aclose()

    assert attempts["count"] == 2
    assert result.text == "ok"


@pytest.mark.asyncio
async def test_transport_error_exhausting_retries_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(NewsSourceUnavailableError):
        await fetch_text(client, "/feed.xml", sleep=_no_sleep, max_attempts=3)
    await client.aclose()


@pytest.mark.asyncio
async def test_429_retries_then_succeeds() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 2:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, text="ok")

    client = _client(httpx.MockTransport(handler))
    result = await fetch_text(client, "/feed.xml", sleep=_no_sleep, max_attempts=3)
    await client.aclose()

    assert attempts["count"] == 2
    assert result.text == "ok"


@pytest.mark.asyncio
async def test_500_retries_then_succeeds() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 2:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, text="ok")

    client = _client(httpx.MockTransport(handler))
    result = await fetch_text(client, "/feed.xml", sleep=_no_sleep, max_attempts=3)
    await client.aclose()

    assert attempts["count"] == 2
    assert result.text == "ok"


@pytest.mark.asyncio
async def test_ordinary_4xx_does_not_retry() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(404, text="not found")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(NewsSourceUnavailableError):
        await fetch_text(client, "/feed.xml", sleep=_no_sleep, max_attempts=3)
    await client.aclose()

    assert attempts["count"] == 1


@pytest.mark.asyncio
async def test_5xx_exhausting_retries_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="error")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(NewsSourceUnavailableError):
        await fetch_text(client, "/feed.xml", sleep=_no_sleep, max_attempts=3)
    await client.aclose()


@pytest.mark.asyncio
async def test_before_attempt_hook_runs_on_every_attempt_including_retries() -> None:
    # FX-57E Section 23: a source with its own robots.txt Crawl-delay
    # (Statistics Canada) needs its pacing hook invoked before EVERY
    # attempt this loop makes, including retries -- not just once
    # per outer call.
    attempts = {"count": 0}
    before_attempt_calls = {"count": 0}

    async def before_attempt() -> None:
        before_attempt_calls["count"] += 1

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, text="ok")

    client = _client(httpx.MockTransport(handler))
    await fetch_text(
        client, "/feed.xml", sleep=_no_sleep, max_attempts=3, before_attempt=before_attempt
    )
    await client.aclose()

    assert attempts["count"] == 3
    assert before_attempt_calls["count"] == 3


@pytest.mark.asyncio
async def test_no_before_attempt_hook_is_a_no_op() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    client = _client(httpx.MockTransport(handler))
    result = await fetch_text(client, "/feed.xml", sleep=_no_sleep)
    await client.aclose()

    assert result.text == "ok"


@pytest.mark.asyncio
async def test_on_attempt_hook_reports_each_retry_then_success() -> None:
    # FX-63: every transport-level attempt inside this loop must be
    # individually observable, including ones later retried.
    attempts = {"count": 0}
    observed: list[FetchAttemptOutcome] = []

    async def on_attempt(outcome: FetchAttemptOutcome) -> None:
        observed.append(outcome)

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, text="ok")

    client = _client(httpx.MockTransport(handler))
    await fetch_text(client, "/feed.xml", sleep=_no_sleep, max_attempts=3, on_attempt=on_attempt)
    await client.aclose()

    assert [o.attempt_number for o in observed] == [1, 2, 3]
    assert [o.outcome_kind for o in observed] == [
        FetchAttemptOutcomeKind.HTTP_FAILURE,
        FetchAttemptOutcomeKind.HTTP_FAILURE,
        FetchAttemptOutcomeKind.SUCCESS,
    ]
    assert observed[0].http_status == 503
    assert observed[2].http_status == 200


@pytest.mark.asyncio
async def test_on_attempt_hook_distinguishes_timeout_from_network_failure() -> None:
    timeout_observed: list[FetchAttemptOutcome] = []

    async def on_attempt(outcome: FetchAttemptOutcome) -> None:
        timeout_observed.append(outcome)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(NewsSourceUnavailableError):
        await fetch_text(
            client, "/feed.xml", sleep=_no_sleep, max_attempts=2, on_attempt=on_attempt
        )
    await client.aclose()

    assert len(timeout_observed) == 2
    assert all(o.outcome_kind is FetchAttemptOutcomeKind.TIMEOUT for o in timeout_observed)

    network_observed: list[FetchAttemptOutcome] = []

    async def on_attempt_network(outcome: FetchAttemptOutcome) -> None:
        network_observed.append(outcome)

    def network_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    network_client = _client(httpx.MockTransport(network_handler))
    with pytest.raises(NewsSourceUnavailableError):
        await fetch_text(
            network_client,
            "/feed.xml",
            sleep=_no_sleep,
            max_attempts=2,
            on_attempt=on_attempt_network,
        )
    await network_client.aclose()

    assert len(network_observed) == 2
    assert all(o.outcome_kind is FetchAttemptOutcomeKind.NETWORK_FAILURE for o in network_observed)


@pytest.mark.asyncio
async def test_on_attempt_hook_reports_unretried_ordinary_4xx() -> None:
    observed: list[FetchAttemptOutcome] = []

    async def on_attempt(outcome: FetchAttemptOutcome) -> None:
        observed.append(outcome)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(NewsSourceUnavailableError):
        await fetch_text(
            client, "/feed.xml", sleep=_no_sleep, max_attempts=3, on_attempt=on_attempt
        )
    await client.aclose()

    assert len(observed) == 1
    assert observed[0].outcome_kind is FetchAttemptOutcomeKind.HTTP_FAILURE
    assert observed[0].http_status == 404


@pytest.mark.asyncio
async def test_no_on_attempt_hook_is_a_no_op() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    client = _client(httpx.MockTransport(handler))
    result = await fetch_text(client, "/feed.xml", sleep=_no_sleep)
    await client.aclose()

    assert result.text == "ok"


# --- FX-63H: observation-persistence failure isolation ----------------------


@pytest.mark.asyncio
async def test_successful_fetch_survives_a_failing_on_attempt_hook() -> None:
    async def failing_on_attempt(outcome: FetchAttemptOutcome) -> None:
        raise _ObservationPersistenceError("db write failed")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    client = _client(httpx.MockTransport(handler))
    result = await fetch_text(
        client,
        "/feed.xml",
        sleep=_no_sleep,
        on_attempt=failing_on_attempt,
        on_attempt_error=lambda exc, outcome: None,
    )
    await client.aclose()

    assert result.text == "ok"


@pytest.mark.asyncio
async def test_genuine_http_failure_keeps_its_own_category_despite_failing_hook() -> None:
    async def failing_on_attempt(outcome: FetchAttemptOutcome) -> None:
        raise _ObservationPersistenceError("db write failed")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(NewsSourceUnavailableError):
        await fetch_text(
            client,
            "/feed.xml",
            sleep=_no_sleep,
            max_attempts=3,
            on_attempt=failing_on_attempt,
            on_attempt_error=lambda exc, outcome: None,
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_internal_retries_unaffected_by_a_failing_on_attempt_hook() -> None:
    attempts = {"count": 0}

    async def failing_on_attempt(outcome: FetchAttemptOutcome) -> None:
        raise _ObservationPersistenceError("db write failed")

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, text="ok")

    client = _client(httpx.MockTransport(handler))
    result = await fetch_text(
        client,
        "/feed.xml",
        sleep=_no_sleep,
        max_attempts=3,
        on_attempt=failing_on_attempt,
        on_attempt_error=lambda exc, outcome: None,
    )
    await client.aclose()

    # Exactly 3 real HTTP attempts -- the failing hook never caused an
    # extra retry, and never suppressed one either.
    assert attempts["count"] == 3
    assert result.text == "ok"


@pytest.mark.asyncio
async def test_on_attempt_error_is_invoked_with_the_exception_and_outcome() -> None:
    observed: list[tuple[Exception, FetchAttemptOutcome]] = []

    async def failing_on_attempt(outcome: FetchAttemptOutcome) -> None:
        raise _ObservationPersistenceError("db write failed")

    def on_attempt_error(exc: Exception, outcome: FetchAttemptOutcome) -> None:
        observed.append((exc, outcome))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    client = _client(httpx.MockTransport(handler))
    await fetch_text(
        client,
        "/feed.xml",
        sleep=_no_sleep,
        on_attempt=failing_on_attempt,
        on_attempt_error=on_attempt_error,
    )
    await client.aclose()

    assert len(observed) == 1
    exc, outcome = observed[0]
    assert isinstance(exc, _ObservationPersistenceError)
    assert outcome.outcome_kind is FetchAttemptOutcomeKind.SUCCESS


@pytest.mark.asyncio
async def test_default_on_attempt_error_prints_a_visible_diagnostic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def failing_on_attempt(outcome: FetchAttemptOutcome) -> None:
        raise _ObservationPersistenceError("db write failed")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    client = _client(httpx.MockTransport(handler))
    await fetch_text(client, "/feed.xml", sleep=_no_sleep, on_attempt=failing_on_attempt)
    await client.aclose()

    captured = capsys.readouterr()
    assert "operational observation persistence failed" in captured.err
    assert "_ObservationPersistenceError" in captured.err or "db write failed" in captured.err


@pytest.mark.asyncio
async def test_retry_after_header_is_respected() -> None:
    attempts = {"count": 0}
    slept: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        slept.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 2:
            return httpx.Response(429, text="slow down", headers={"Retry-After": "5"})
        return httpx.Response(200, text="ok")

    client = _client(httpx.MockTransport(handler))
    await fetch_text(client, "/feed.xml", sleep=recording_sleep, max_attempts=3)
    await client.aclose()

    assert slept == [5.0]

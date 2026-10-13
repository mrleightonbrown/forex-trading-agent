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
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

import httpx

from forex_agent.application.ports.news_source import NewsSourceUnavailableError
from forex_agent.domain.timestamps import UtcTimestamp

ClockFn = Callable[[], UtcTimestamp]
SleepFn = Callable[[float], Awaitable[None]]
BeforeAttemptFn = Callable[[], Awaitable[None]]


class FetchAttemptOutcomeKind(Enum):
    """FX-63: what happened on ONE transport-level attempt inside
    `fetch_text`'s own retry loop -- deliberately narrow and honestly
    distinguishable from the information this function already has at
    each decision point, never guessed from a string message.
    `TIMEOUT` is `httpx.TimeoutException` specifically (a subclass of
    `httpx.RequestError`); any OTHER `httpx.RequestError` is
    `NETWORK_FAILURE`. A retried HTTP 429/5xx is `HTTP_FAILURE` with
    its own `http_status`; an un-retried ordinary 4xx is also
    `HTTP_FAILURE` (one single attempt, no retry)."""

    SUCCESS = "SUCCESS"
    HTTP_FAILURE = "HTTP_FAILURE"
    TIMEOUT = "TIMEOUT"
    NETWORK_FAILURE = "NETWORK_FAILURE"


@dataclass(frozen=True, slots=True)
class FetchAttemptOutcome:
    """FX-63: one observed transport-level attempt, reported to an
    optional caller-supplied `on_attempt` hook -- see `fetch_text`'s
    own docstring. `attempt_number` is 1-based and counts EVERY
    attempt this call makes, including ones that are later retried;
    `observed_at` is this exact attempt's own instant, captured via
    the SAME injected `clock` as a successful response's own
    `retrieved_at` (never a second, independent clock read)."""

    attempt_number: int
    outcome_kind: FetchAttemptOutcomeKind
    http_status: int | None
    observed_at: UtcTimestamp


OnAttemptFn = Callable[[FetchAttemptOutcome], Awaitable[None]]

OnAttemptErrorFn = Callable[[Exception, FetchAttemptOutcome], None]
"""FX-63H: diagnostic sink for a failure WITHIN the optional `on_
attempt` hook itself -- see `fetch_text`'s own docstring for the
isolation guarantee this exists to support. Synchronous and
deliberately minimal: this is a diagnostic reporting step, never
itself part of the acquisition decision path, so it must never be
awaited in a way that could introduce a second place for a failure to
propagate from."""


def _default_on_attempt_error(exc: Exception, outcome: FetchAttemptOutcome) -> None:
    print(
        f"WARNING: operational observation persistence failed for attempt "
        f"{outcome.attempt_number} ({outcome.outcome_kind.value}): {exc!r} -- "
        "the underlying fetch outcome is unaffected and was NOT durably recorded "
        "for this attempt",
        file=sys.stderr,
    )


async def _report_attempt(
    on_attempt: OnAttemptFn,
    on_attempt_error: OnAttemptErrorFn,
    outcome: FetchAttemptOutcome,
) -> None:
    """FX-63H: the ONE narrow failure boundary around the optional
    `on_attempt` hook -- a telemetry/observation-persistence failure
    must never change an otherwise successful (or failed) fetch
    outcome, corrupt this call's own retry/raise/return decision, or
    be silently swallowed with no diagnostic. Any exception `on_
    attempt` itself raises is caught HERE, reported via `on_attempt_
    error`, and then dropped for THIS attempt -- never retried (which
    could duplicate the underlying HTTP attempt itself) and never
    re-raised. This is the ONLY `try/except` in this module that
    catches a bare `Exception`; every other exception in `fetch_text`
    (a genuine transport/HTTP failure) is handled by its own existing,
    narrower logic, completely unaffected by this one."""
    try:
        await on_attempt(outcome)
    except Exception as exc:  # deliberate: see docstring above
        on_attempt_error(exc, outcome)


AcquisitionAttemptRecorder = Callable[[str, str, str, FetchAttemptOutcome], Awaitable[None]]
"""FX-63: the shape every adapter's own optional `on_acquisition_
attempt` constructor parameter takes -- `(source_key, source_channel,
run_id, outcome)`. `fetch_text` itself knows nothing about a channel,
a source_key, or a logical "run" (it is provider-neutral, per the
module docstring); an adapter's own `fetch_feed`-equivalent method
mints a fresh `run_id` for EACH call and wraps this recorder into a
bare `OnAttemptFn` closure before passing it to `fetch_text` as
`on_attempt` -- see any adapter's own `fetch_feed` for the exact
pattern. `None` (the default on every adapter) preserves existing
behavior exactly; this is purely additive instrumentation consumed by
`scripts/ingest_*.py` to record FX-63 operational observations."""


def bind_acquisition_recorder(
    recorder: AcquisitionAttemptRecorder | None, source_key: str, source_channel: str
) -> OnAttemptFn | None:
    """FX-63: the one mechanical step every adapter's own `fetch_feed`
    -- equivalent method repeats verbatim -- mint a fresh `run_id` for
    THIS call, and wrap `recorder` into a bare `OnAttemptFn` closure
    `fetch_text` can call with no further context. Returns `None`
    unchanged when `recorder` is `None`, so `fetch_text` sees no hook
    at all and every existing caller's behavior is completely
    unaffected."""
    if recorder is None:
        return None
    run_id = str(uuid4())

    async def _on_attempt(outcome: FetchAttemptOutcome) -> None:
        await recorder(source_key, source_channel, run_id, outcome)

    return _on_attempt


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
    before_attempt: BeforeAttemptFn | None = None,
    on_attempt: OnAttemptFn | None = None,
    on_attempt_error: OnAttemptErrorFn = _default_on_attempt_error,
) -> FetchedResponse:
    """GET `url`, retrying only a transport failure, HTTP 429, or HTTP
    5xx, up to `max_attempts` total attempts. An ordinary 4xx (other
    than 429) never retries. `retrieved_at` is captured exactly once,
    immediately after the attempt that actually succeeds -- never at
    the start of the loop, and never per subsequent parsed item.

    **FX-57E Section 23**: `before_attempt`, when given, is awaited
    immediately before EVERY attempt this call makes, including
    retries -- the hook a source whose own `robots.txt` sets a
    `Crawl-delay` (Statistics Canada) uses to enforce a minimum
    inter-request interval that a bare per-call pacer (one that only
    wraps the OUTER call, not this loop's own internal retries) could
    otherwise violate. `None` (the default) preserves every existing
    caller's behavior exactly -- Fed/ECB/BoE/GOV.UK pass nothing here
    and are entirely unaffected.

    **FX-63: `on_attempt`, when given, is awaited immediately AFTER
    EVERY attempt this call makes resolves** (success, a retried
    failure, or the final failure that raises) -- additive, mirroring
    `before_attempt`'s own precedent exactly. `None` (the default)
    preserves every existing caller's behavior byte-for-byte; no
    existing adapter is required to pass this. This is the ONLY place
    `fetch_text`'s own internal retry attempts are individually
    observable -- a caller that wants durable, forward-looking
    acquisition-attempt evidence (FX-63) supplies this hook; one that
    does not is completely unaffected.

    **FX-63H: `on_attempt` is isolated from this call's own
    acquisition decision path.** Any exception `on_attempt` itself
    raises (e.g. a database write failing) is caught via `_report_
    attempt`, reported through `on_attempt_error` (default: a visible
    stderr diagnostic), and dropped for that one attempt -- it NEVER
    propagates into the retry/raise/return logic below, so a
    successful fetch stays successful, and a genuine HTTP/transport
    failure keeps its own original category, regardless of whether
    the optional telemetry write for that attempt succeeded."""
    last_error: str = "no attempt was made"
    for attempt in range(1, max_attempts + 1):
        if before_attempt is not None:
            await before_attempt()
        try:
            response = await client.get(url)
        except httpx.RequestError as exc:
            last_error = f"transport error reaching {url}: {exc}"
            if on_attempt is not None:
                kind = (
                    FetchAttemptOutcomeKind.TIMEOUT
                    if isinstance(exc, httpx.TimeoutException)
                    else FetchAttemptOutcomeKind.NETWORK_FAILURE
                )
                await _report_attempt(
                    on_attempt,
                    on_attempt_error,
                    FetchAttemptOutcome(attempt, kind, None, clock()),
                )
            if attempt < max_attempts:
                await sleep(backoff_seconds(attempt))
                continue
            raise NewsSourceUnavailableError(
                f"{last_error} (giving up after {attempt} attempts)"
            ) from exc

        if response.status_code == 429 or response.status_code >= 500:
            last_error = f"{url} returned HTTP {response.status_code}"
            if on_attempt is not None:
                await _report_attempt(
                    on_attempt,
                    on_attempt_error,
                    FetchAttemptOutcome(
                        attempt,
                        FetchAttemptOutcomeKind.HTTP_FAILURE,
                        response.status_code,
                        clock(),
                    ),
                )
            if attempt < max_attempts:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                await sleep(retry_after if retry_after is not None else backoff_seconds(attempt))
                continue
            raise NewsSourceUnavailableError(f"{last_error} (giving up after {attempt} attempts)")

        if response.status_code >= 400:
            if on_attempt is not None:
                await _report_attempt(
                    on_attempt,
                    on_attempt_error,
                    FetchAttemptOutcome(
                        attempt,
                        FetchAttemptOutcomeKind.HTTP_FAILURE,
                        response.status_code,
                        clock(),
                    ),
                )
            raise NewsSourceUnavailableError(
                f"{url} returned HTTP {response.status_code} -- not retried"
            )

        retrieved_at = clock()
        if on_attempt is not None:
            await _report_attempt(
                on_attempt,
                on_attempt_error,
                FetchAttemptOutcome(
                    attempt,
                    FetchAttemptOutcomeKind.SUCCESS,
                    response.status_code,
                    retrieved_at,
                ),
            )
        return FetchedResponse(
            text=response.text,
            retrieved_at=retrieved_at,
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
        )

    raise NewsSourceUnavailableError(last_error)

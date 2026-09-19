"""FX-26: BackfillCandles use case tests, using in-memory fakes for fast,
deterministic coverage of the watermark branching logic (fresh, forward
extension, backward extension, both, disjoint-rejection, no-op) and a
genuine mid-backfill interruption/resume proof. The live-Postgres version
of the interruption test lives in tests/integration (real persistence,
still a fake MarketDataPort — a real provider failure can't be
deterministically triggered).
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_agent.application.ports.exceptions import BrokerUnavailableError
from forex_agent.application.use_cases.backfill_candles import BackfillCandles
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.candle_repository import FakeCandleRepository
from tests.fakes.ingestion_watermark_repository import FakeIngestionWatermarkRepository
from tests.fakes.market_data_port import FakeMarketDataPort

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
_EPOCH = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _ts(minute: int) -> UtcTimestamp:
    return UtcTimestamp(_EPOCH + timedelta(minutes=minute))


def _dense_candles(count: int) -> list[Candle]:
    flat = Ohlc(open=Decimal("1.1"), high=Decimal("1.1"), low=Decimal("1.1"), close=Decimal("1.1"))
    return [
        Candle(
            instrument=EUR_USD,
            granularity=Granularity.M1,
            start_time=_ts(m),
            bid=flat,
            ask=flat,
            volume=1,
            is_finalized=True,
        )
        for m in range(count)
    ]


def _use_case(
    candles: list[Candle],
    max_candles_per_page: int = 5,
    fail_on: Callable[[UtcTimestamp, UtcTimestamp], bool] | None = None,
) -> tuple[
    BackfillCandles, FakeMarketDataPort, FakeCandleRepository, FakeIngestionWatermarkRepository
]:
    market_data = FakeMarketDataPort(candles, fail_on=fail_on)
    repo = FakeCandleRepository()
    watermarks = FakeIngestionWatermarkRepository()
    use_case = BackfillCandles(
        market_data=market_data,
        candles=repo,
        watermarks=watermarks,
        max_candles_per_page=max_candles_per_page,
    )
    return use_case, market_data, repo, watermarks


# --- validation -------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejects_end_not_after_start() -> None:
    use_case, _, _, _ = _use_case(_dense_candles(10))

    with pytest.raises(ValueError, match="end must be after start"):
        await use_case(EUR_USD, Granularity.M1, _ts(5), _ts(5))


# --- fresh backfill -----------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_backfill_pages_and_persists_the_whole_range() -> None:
    use_case, market_data, repo, watermarks = _use_case(_dense_candles(23), max_candles_per_page=5)

    result = await use_case(EUR_USD, Granularity.M1, _ts(0), _ts(23))

    assert result.pages_fetched == 5  # 23 candles / 5 per page -> 5 pages
    assert result.candles_written == 23
    assert result.earliest_ingested == _ts(0)
    assert result.latest_ingested == _ts(23)
    assert await watermarks.get_watermark(EUR_USD, Granularity.M1) == (_ts(0), _ts(23))
    stored = await repo.get_range(EUR_USD, Granularity.M1, _ts(0), _ts(23))
    assert len(stored) == 23
    assert len(market_data.requests) == 5


# --- watermark boundary alignment (FX-30) --------------------------------


@pytest.mark.asyncio
async def test_watermark_bounds_are_floored_to_candle_boundaries_on_fresh_backfill() -> None:
    """Regression: found live while gap-checking the FX-27 research
    dataset -- a wall-clock `start`/`end` (e.g. a script's own
    `datetime.now()`, essentially never exactly on a candle boundary)
    must not leak into the watermark verbatim. `earliest_ingested` must
    floor to the boundary at or before the requested `start`;
    `latest_ingested` must floor to the boundary at or before the
    requested `end` (not round up -- the candle containing a mid-candle
    `end` may still be forming and must not be claimed as covered)."""
    use_case, _market_data, _repo, watermarks = _use_case(
        _dense_candles(23), max_candles_per_page=5
    )
    misaligned_start = UtcTimestamp(_ts(0).value + timedelta(seconds=14, microseconds=34))
    misaligned_end = UtcTimestamp(_ts(23).value + timedelta(seconds=45))

    result = await use_case(EUR_USD, Granularity.M1, misaligned_start, misaligned_end)

    assert result.earliest_ingested == _ts(0)  # floored down from :14.000034
    assert result.latest_ingested == _ts(23)  # floored down from :45, NOT rounded up to _ts(24)
    assert await watermarks.get_watermark(EUR_USD, Granularity.M1) == (_ts(0), _ts(23))


@pytest.mark.asyncio
async def test_watermark_latest_is_not_rounded_up_into_a_still_forming_candle() -> None:
    """The specific risk a naive "round to nearest boundary" fix would
    reintroduce: requesting up to a mid-candle `end` must never claim
    the *next* candle (which might not exist/be finalized yet) as
    covered."""
    use_case, _market_data, _repo, _watermarks = _use_case(
        _dense_candles(23), max_candles_per_page=5
    )
    # 30 seconds into what would be candle 23 -- that candle isn't even
    # in the fixture (_dense_candles(23) only has candles 0..22).
    end_mid_candle_23 = UtcTimestamp(_ts(23).value + timedelta(seconds=30))

    result = await use_case(EUR_USD, Granularity.M1, _ts(0), end_mid_candle_23)

    assert result.latest_ingested == _ts(23)  # NOT _ts(24)


# --- forward extension ----------------------------------------------------


@pytest.mark.asyncio
async def test_forward_extension_only_fetches_the_new_portion() -> None:
    use_case, market_data, repo, _watermarks = _use_case(_dense_candles(30), max_candles_per_page=5)
    await use_case(EUR_USD, Granularity.M1, _ts(0), _ts(10))
    market_data.requests.clear()

    result = await use_case(EUR_USD, Granularity.M1, _ts(0), _ts(30))

    assert result.earliest_ingested == _ts(0)
    assert result.latest_ingested == _ts(30)
    # Only the new [10, 30) portion was requested, not [0, 10) again.
    for req_start, _req_end in market_data.requests:
        assert req_start.value >= _ts(10).value
    stored = await repo.get_range(EUR_USD, Granularity.M1, _ts(0), _ts(30))
    assert len(stored) == 30


# --- backward extension ----------------------------------------------------


@pytest.mark.asyncio
async def test_backward_extension_only_fetches_the_new_portion() -> None:
    use_case, market_data, repo, _watermarks = _use_case(_dense_candles(30), max_candles_per_page=5)
    await use_case(EUR_USD, Granularity.M1, _ts(10), _ts(30))
    market_data.requests.clear()

    result = await use_case(EUR_USD, Granularity.M1, _ts(0), _ts(30))

    assert result.earliest_ingested == _ts(0)
    assert result.latest_ingested == _ts(30)
    for _req_start, req_end in market_data.requests:
        assert req_end.value <= _ts(10).value
    stored = await repo.get_range(EUR_USD, Granularity.M1, _ts(0), _ts(30))
    assert len(stored) == 30


@pytest.mark.asyncio
async def test_backward_extension_pages_are_requested_in_descending_order() -> None:
    """The specific reason backward extension is safe under interruption:
    it must process pages closest to the existing coverage FIRST, so a
    crash never leaves a gap between newly-fetched data and the
    pre-existing watermark."""
    use_case, market_data, _, _ = _use_case(_dense_candles(30), max_candles_per_page=5)
    await use_case(EUR_USD, Granularity.M1, _ts(20), _ts(30))
    market_data.requests.clear()

    await use_case(EUR_USD, Granularity.M1, _ts(0), _ts(30))

    starts = [req_start.value for req_start, _ in market_data.requests]
    assert starts == sorted(starts, reverse=True)


# --- both directions ---------------------------------------------------


@pytest.mark.asyncio
async def test_extends_both_backward_and_forward_in_one_call() -> None:
    use_case, _, repo, _ = _use_case(_dense_candles(30), max_candles_per_page=5)
    await use_case(EUR_USD, Granularity.M1, _ts(10), _ts(20))

    result = await use_case(EUR_USD, Granularity.M1, _ts(0), _ts(30))

    assert result.earliest_ingested == _ts(0)
    assert result.latest_ingested == _ts(30)
    stored = await repo.get_range(EUR_USD, Granularity.M1, _ts(0), _ts(30))
    assert len(stored) == 30


# --- no-op / already covered ------------------------------------------------


@pytest.mark.asyncio
async def test_fully_covered_request_fetches_nothing() -> None:
    use_case, market_data, _, watermarks = _use_case(_dense_candles(30), max_candles_per_page=5)
    await use_case(EUR_USD, Granularity.M1, _ts(0), _ts(30))
    market_data.requests.clear()

    result = await use_case(EUR_USD, Granularity.M1, _ts(5), _ts(15))

    assert result.pages_fetched == 0
    assert result.candles_written == 0
    assert market_data.requests == []
    assert await watermarks.get_watermark(EUR_USD, Granularity.M1) == (_ts(0), _ts(30))


# --- disjoint range rejection -----------------------------------------------


@pytest.mark.asyncio
async def test_rejects_a_disjoint_request() -> None:
    use_case, _, _, _ = _use_case(_dense_candles(100), max_candles_per_page=5)
    await use_case(EUR_USD, Granularity.M1, _ts(0), _ts(10))

    with pytest.raises(ValueError, match="does not overlap or touch"):
        await use_case(EUR_USD, Granularity.M1, _ts(50), _ts(60))


@pytest.mark.asyncio
async def test_accepts_a_request_exactly_adjacent_to_existing_coverage() -> None:
    # Touching (not overlapping) at exactly the boundary must NOT count
    # as disjoint.
    use_case, _, repo, _watermarks = _use_case(_dense_candles(30), max_candles_per_page=5)
    await use_case(EUR_USD, Granularity.M1, _ts(0), _ts(10))

    result = await use_case(EUR_USD, Granularity.M1, _ts(10), _ts(20))

    assert result.earliest_ingested == _ts(0)
    assert result.latest_ingested == _ts(20)
    stored = await repo.get_range(EUR_USD, Granularity.M1, _ts(0), _ts(20))
    assert len(stored) == 20


# --- interruption and resume (in-memory) ------------------------------------


@pytest.mark.asyncio
async def test_interrupted_backfill_resumes_without_refetching_or_duplicating() -> None:
    candles = _dense_candles(25)

    def fail_on_third_page(req_start: UtcTimestamp, _req_end: UtcTimestamp) -> bool:
        return req_start.value == _ts(10).value  # the 3rd page (0-4,5-9,10-14,...)

    market_data = FakeMarketDataPort(candles, fail_on=fail_on_third_page)
    repo = FakeCandleRepository()
    watermarks = FakeIngestionWatermarkRepository()
    use_case = BackfillCandles(
        market_data=market_data, candles=repo, watermarks=watermarks, max_candles_per_page=5
    )

    with pytest.raises(BrokerUnavailableError):
        await use_case(EUR_USD, Granularity.M1, _ts(0), _ts(25))

    # Exactly the first two pages succeeded before the simulated failure.
    assert await watermarks.get_watermark(EUR_USD, Granularity.M1) == (_ts(0), _ts(10))
    stored_before = await repo.get_range(EUR_USD, Granularity.M1, _ts(0), _ts(25))
    assert len(stored_before) == 10
    requests_before_resume = list(market_data.requests)

    # Remove the failure and resume with the SAME request.
    market_data.set_fail_on(None)
    result = await use_case(EUR_USD, Granularity.M1, _ts(0), _ts(25))

    assert result.earliest_ingested == _ts(0)
    assert result.latest_ingested == _ts(25)
    stored_after = await repo.get_range(EUR_USD, Granularity.M1, _ts(0), _ts(25))
    assert len(stored_after) == 25  # no duplicates, nothing missing

    # The already-completed [0, 10) pages were never re-requested.
    resumed_requests = market_data.requests[len(requests_before_resume) :]
    for req_start, _req_end in resumed_requests:
        assert req_start.value >= _ts(10).value

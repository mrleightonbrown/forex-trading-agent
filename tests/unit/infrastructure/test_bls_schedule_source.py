"""FX-52A: unit tests for `BlsScheduleSource` against a mocked HTTP
transport -- no real network access (see tests/integration/
test_bls_schedule_source_live.py for the live-feed validation)."""

from datetime import date, time

import httpx
import pytest

from forex_agent.application.ports.economic_calendar_source import (
    EconomicCalendarSourceUnavailableError,
)
from forex_agent.infrastructure.economic_calendar_sources.bls_schedule_source import (
    BlsScheduleSource,
)

_SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:3a09855e-d5c6-45b2-a74f-2429f44d0418
DTSTART;TZID=US-Eastern:20261210T083000
SUMMARY:Employment Situation
END:VEVENT
BEGIN:VEVENT
UID:6f82e6b8-8b66-4da2-a29c-72643b3440bb
DTSTART;TZID=US-Eastern:20261215T083000
SUMMARY:Consumer Price Index
END:VEVENT
BEGIN:VEVENT
UID:00000000-0000-0000-0000-000000000000
DTSTART;TZID=US-Eastern:20261220T100000
SUMMARY:Productivity and Costs
END:VEVENT
END:VCALENDAR
"""


def _client_returning(status_code: int, text: str) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=text)

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    )


@pytest.mark.asyncio
async def test_employment_situation_splits_into_two_indicators() -> None:
    source = BlsScheduleSource(client=_client_returning(200, _SAMPLE_ICS))
    observations = await source.fetch_schedule()
    await source.aclose()

    employment = next(o for o in observations if "Employment" in o.raw_title)
    assert employment.indicator_keys == ("US_NONFARM_PAYROLLS", "US_UNEMPLOYMENT_RATE")
    assert employment.scheduled_date == date(2026, 12, 10)
    assert employment.scheduled_time == time(8, 30)
    assert employment.schedule_timezone == "America/New_York"


@pytest.mark.asyncio
async def test_cpi_maps_to_single_indicator() -> None:
    source = BlsScheduleSource(client=_client_returning(200, _SAMPLE_ICS))
    observations = await source.fetch_schedule()
    await source.aclose()

    cpi = next(o for o in observations if "Consumer Price" in o.raw_title)
    assert cpi.indicator_keys == ("US_CPI_YOY",)


@pytest.mark.asyncio
async def test_unrecognized_release_title_is_unmapped_and_omitted() -> None:
    source = BlsScheduleSource(client=_client_returning(200, _SAMPLE_ICS))
    observations = await source.fetch_schedule()
    await source.aclose()

    assert all("Productivity" not in o.raw_title for o in observations)
    assert len(observations) == 2


@pytest.mark.asyncio
async def test_http_error_status_raises_unavailable() -> None:
    source = BlsScheduleSource(client=_client_returning(503, "service unavailable"))
    with pytest.raises(EconomicCalendarSourceUnavailableError):
        await source.fetch_schedule()
    await source.aclose()


@pytest.mark.asyncio
async def test_network_failure_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    )
    source = BlsScheduleSource(client=client)
    with pytest.raises(EconomicCalendarSourceUnavailableError):
        await source.fetch_schedule()
    await source.aclose()


@pytest.mark.asyncio
async def test_malformed_ics_yields_empty_result_not_a_crash() -> None:
    source = BlsScheduleSource(client=_client_returning(200, "not a valid ics document"))
    observations = await source.fetch_schedule()
    await source.aclose()
    assert observations == ()

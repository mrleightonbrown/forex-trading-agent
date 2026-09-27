"""FX-52A: unit tests for `BocScheduleSource` against a mocked HTTP
transport."""

from datetime import date, time

import httpx
import pytest

from forex_agent.infrastructure.economic_calendar_sources.boc_schedule_source import (
    BocScheduleSource,
)

_SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:247309@bank-banque-canada.ca
DTSTART:20261028T134500Z
DTEND:20261028T141500Z
SUMMARY:Interest Rate Announcement and Monetary Policy Report
END:VEVENT
BEGIN:VEVENT
UID:217030@bank-banque-canada.ca
DTSTART:20261012T160100Z
SUMMARY:Thanksgiving Day
DESCRIPTION:National holiday
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
async def test_rate_announcement_mapped() -> None:
    source = BocScheduleSource(client=_client_returning(200, _SAMPLE_ICS))
    observations = await source.fetch_schedule()
    await source.aclose()

    assert len(observations) == 1
    obs = observations[0]
    assert obs.indicator_keys == ("CAD_POLICY_RATE_DECISION",)
    assert obs.scheduled_date == date(2026, 10, 28)
    assert obs.scheduled_time == time(13, 45)
    assert obs.schedule_timezone == "UTC"
    assert obs.external_event_id == "247309@bank-banque-canada.ca"


@pytest.mark.asyncio
async def test_holiday_is_unmapped() -> None:
    source = BocScheduleSource(client=_client_returning(200, _SAMPLE_ICS))
    observations = await source.fetch_schedule()
    await source.aclose()

    assert all("Thanksgiving" not in o.raw_title for o in observations)

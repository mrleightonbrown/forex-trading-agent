"""FX-52A: unit tests for `OnsScheduleSource` against a mocked HTTP
transport."""

from datetime import UTC, date, datetime, time

import httpx
import pytest

from forex_agent.application.ports.economic_calendar_source import (
    EconomicCalendarSourceUnavailableError,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.economic_calendar_sources.ons_schedule_source import (
    OnsScheduleSource,
    reference_period_from_title,
)

_SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
<title>GDP quarterly national accounts, UK: April to June 2026</title>
<link>https://www.ons.gov.uk/economy/grossdomesticproductgdp/bulletins/quarterlynationalaccounts/apriltojune2026</link>
<guid>https://www.ons.gov.uk/economy/grossdomesticproductgdp/bulletins/quarterlynationalaccounts/apriltojune2026</guid>
<pubDate>Wed, 30 Sep 2026 06:00:00 +0000</pubDate>
</item>
<item>
<title>Consumer trends, UK: April to June 2026</title>
<link>https://www.ons.gov.uk/economy/nationalaccounts/satelliteaccounts/bulletins/consumertrends/apriltojune2026</link>
<guid>https://www.ons.gov.uk/economy/nationalaccounts/satelliteaccounts/bulletins/consumertrends/apriltojune2026</guid>
<pubDate>Wed, 30 Sep 2026 08:30:00 +0000</pubDate>
</item>
</channel></rss>
"""


def _client_returning(status_code: int, text: str) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=text)

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    )


@pytest.mark.asyncio
async def test_gdp_bulletin_mapped_with_reference_period() -> None:
    source = OnsScheduleSource(client=_client_returning(200, _SAMPLE_RSS))
    observations = await source.fetch_schedule()
    await source.aclose()

    assert len(observations) == 1
    gdp = observations[0]
    assert gdp.indicator_keys == ("GBP_GDP_QOQ",)
    assert gdp.scheduled_date == date(2026, 9, 30)
    assert gdp.scheduled_time == time(6, 0)
    assert gdp.schedule_timezone == "Europe/London"
    assert gdp.reference_period == UtcTimestamp(datetime(2026, 4, 1, tzinfo=UTC))


@pytest.mark.asyncio
async def test_consumer_trends_is_unmapped() -> None:
    source = OnsScheduleSource(client=_client_returning(200, _SAMPLE_RSS))
    observations = await source.fetch_schedule()
    await source.aclose()

    assert all("Consumer trends" not in o.raw_title for o in observations)


@pytest.mark.asyncio
async def test_http_error_status_raises_unavailable() -> None:
    source = OnsScheduleSource(client=_client_returning(500, "error"))
    with pytest.raises(EconomicCalendarSourceUnavailableError):
        await source.fetch_schedule()
    await source.aclose()


def test_reference_period_from_title_matches_known_pattern() -> None:
    period = reference_period_from_title("GDP quarterly national accounts, UK: April to June 2026")
    assert period == UtcTimestamp(datetime(2026, 4, 1, tzinfo=UTC))


def test_reference_period_from_title_returns_none_for_unmatched_text() -> None:
    assert reference_period_from_title("Some unrelated title with no period") is None

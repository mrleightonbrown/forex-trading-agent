"""FX-52A: unit tests for `OnsScheduleSource` against a mocked HTTP
transport. FX-52AH.1 adds BST/GMT timezone-conversion regression
coverage -- see the adapter's own module docstring for the bug this
guards against."""

from datetime import UTC, date, datetime, time, timedelta

import httpx
import pytest

from forex_agent.application.ports.economic_calendar_source import (
    EconomicCalendarSourceUnavailableError,
    RawScheduleObservation,
)
from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
from forex_agent.domain.economic_event_state import schedule_within_window
from forex_agent.domain.economic_event_status import EconomicEventStatus
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
    result = await source.fetch_schedule()
    await source.aclose()

    assert len(result.observations) == 1
    gdp = result.observations[0]
    assert gdp.indicator_keys == ("GBP_GDP_QOQ",)
    # 06:00 UTC on 2026-09-30 falls during BST (UTC+1) -- correct London
    # local wall-clock time is 07:00, not a naive copy of the UTC value.
    assert gdp.scheduled_date == date(2026, 9, 30)
    assert gdp.scheduled_time == time(7, 0)
    assert gdp.schedule_timezone == "Europe/London"
    assert gdp.reference_period == UtcTimestamp(datetime(2026, 4, 1, tzinfo=UTC))


@pytest.mark.asyncio
async def test_consumer_trends_is_unmapped_and_counted() -> None:
    source = OnsScheduleSource(client=_client_returning(200, _SAMPLE_RSS))
    result = await source.fetch_schedule()
    await source.aclose()

    assert all("Consumer trends" not in o.raw_title for o in result.observations)
    assert result.mapped_count == 1
    assert result.unmapped_count == 1


@pytest.mark.asyncio
async def test_http_error_status_raises_unavailable() -> None:
    source = OnsScheduleSource(client=_client_returning(500, "error"))
    with pytest.raises(EconomicCalendarSourceUnavailableError):
        await source.fetch_schedule()
    await source.aclose()


@pytest.mark.asyncio
async def test_malformed_response_raises_unavailable_not_empty_result() -> None:
    source = OnsScheduleSource(client=_client_returning(200, "not xml at all"))
    with pytest.raises(EconomicCalendarSourceUnavailableError):
        await source.fetch_schedule()
    await source.aclose()


def test_reference_period_from_title_matches_known_pattern() -> None:
    period = reference_period_from_title("GDP quarterly national accounts, UK: April to June 2026")
    assert period == UtcTimestamp(datetime(2026, 4, 1, tzinfo=UTC))


# --- FX-52AH.1: BST/GMT timezone-conversion regression coverage --------------


def _rss_with_pub_date(pub_date_rfc2822: str) -> str:
    return f"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
<title>GDP quarterly national accounts, UK: April to June 2026</title>
<link>https://www.ons.gov.uk/economy/grossdomesticproductgdp/bulletins/quarterlynationalaccounts/apriltojune2026</link>
<guid>https://www.ons.gov.uk/economy/grossdomesticproductgdp/bulletins/quarterlynationalaccounts/apriltojune2026</guid>
<pubDate>{pub_date_rfc2822}</pubDate>
</item>
</channel></rss>
"""


def _assert_round_trips_to_same_utc_instant(
    obs: RawScheduleObservation, utc_instant: datetime
) -> None:
    """Rebuilds the exact `EconomicEventScheduleVintage` a real ingestion
    poll would persist from `obs`, then proves `schedule_within_window`
    resolves it back to `utc_instant` -- the same real UTC moment ONS's
    own `pubDate` claimed -- regardless of London's DST offset at the
    time. This is the actual failure mode the pre-fix adapter produced:
    a plausible-looking `scheduled_date`/`scheduled_time` that resolves
    to the WRONG UTC instant once genuinely interpreted in
    `schedule_timezone`."""
    schedule = EconomicEventScheduleVintage(
        occurrence_key="GBP_GDP_QOQ:test",
        revision_sequence=0,
        scheduled_date=obs.scheduled_date,
        scheduled_time=obs.scheduled_time,
        schedule_timezone=obs.schedule_timezone,
        status=EconomicEventStatus.SCHEDULED,
        availability=UtcTimestamp(utc_instant),
        availability_confidence=AvailabilityConfidence.VERIFIED,
        source="test",
    )
    containing_window = (
        UtcTimestamp(utc_instant - timedelta(minutes=1)),
        UtcTimestamp(utc_instant + timedelta(minutes=1)),
    )
    excluding_window = (
        UtcTimestamp(utc_instant + timedelta(minutes=1)),
        UtcTimestamp(utc_instant + timedelta(minutes=2)),
    )
    assert schedule_within_window(schedule, *containing_window) is True
    assert schedule_within_window(schedule, *excluding_window) is False


@pytest.mark.asyncio
async def test_bst_pub_date_converted_to_london_local_time_and_round_trips() -> None:
    # 09:15 UTC on 2026-06-17 falls during British Summer Time
    # (UTC+1) -- correct London local wall-clock time is 10:15, not a
    # naive copy of the UTC value the pre-fix adapter produced.
    utc_instant = datetime(2026, 6, 17, 9, 15, tzinfo=UTC)
    source = OnsScheduleSource(
        client=_client_returning(200, _rss_with_pub_date("Wed, 17 Jun 2026 09:15:00 +0000"))
    )
    result = await source.fetch_schedule()
    await source.aclose()

    obs = result.observations[0]
    assert obs.scheduled_date == date(2026, 6, 17)
    assert obs.scheduled_time == time(10, 15)
    assert obs.schedule_timezone == "Europe/London"
    _assert_round_trips_to_same_utc_instant(obs, utc_instant)


@pytest.mark.asyncio
async def test_gmt_pub_date_converted_to_london_local_time_and_round_trips() -> None:
    # 09:15 UTC on 2026-12-17 falls during GMT (UTC+0) -- London local
    # wall-clock time happens to equal the UTC value here, unlike the
    # BST case above; the conversion must still be applied explicitly
    # rather than skipped for "already correct" values.
    utc_instant = datetime(2026, 12, 17, 9, 15, tzinfo=UTC)
    source = OnsScheduleSource(
        client=_client_returning(200, _rss_with_pub_date("Thu, 17 Dec 2026 09:15:00 +0000"))
    )
    result = await source.fetch_schedule()
    await source.aclose()

    obs = result.observations[0]
    assert obs.scheduled_date == date(2026, 12, 17)
    assert obs.scheduled_time == time(9, 15)
    assert obs.schedule_timezone == "Europe/London"
    _assert_round_trips_to_same_utc_instant(obs, utc_instant)


def test_reference_period_from_title_returns_none_for_unmatched_text() -> None:
    assert reference_period_from_title("Some unrelated title with no period") is None

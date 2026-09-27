"""FX-52A: unit tests for `BocReleaseSource` against a mocked HTTP
transport. FX-52AH corrects released_time semantics: `released_time`
is now always `None` (never promoted from `dc:date`), `released_date`
prefers `cb:occurrenceDate` when present, and `dc:date` is preserved
separately as `source_published_at`.
"""

from datetime import UTC, date, datetime

import httpx
import pytest

from forex_agent.application.ports.economic_calendar_source import (
    EconomicCalendarSourceUnavailableError,
)
from forex_agent.infrastructure.economic_calendar_sources.boc_release_source import (
    BocReleaseSource,
)

_SAMPLE_RDF = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<item rdf:about="https://www.bankofcanada.ca/2026/09/rate-announcement/">
<title>Bank of Canada maintains the policy rate at 2&#188;%</title>
<link>https://www.bankofcanada.ca/2026/09/rate-announcement/</link>
<dc:date>2026-09-02T09:47:53+00:00</dc:date>
</item>
<item rdf:about="https://www.bankofcanada.ca/2026/09/new-banknote/">
<title>Bank of Canada unveils new vertical $20 bank note</title>
<link>https://www.bankofcanada.ca/2026/09/new-banknote/</link>
<dc:date>2026-09-03T13:20:16+00:00</dc:date>
</item>
</rdf:RDF>
"""

_CB_NS = "http://www.cbwiki.net/wiki/index.php/Specification_1.2/"
_SAMPLE_RDF_WITH_CB_NEWS = f"""<?xml version="1.0"?>
<rdf:RDF
    xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns="http://purl.org/rss/1.0/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:cb="{_CB_NS}">
<item rdf:about="https://www.bankofcanada.ca/2026/09/rate-announcement/">
<title>Bank of Canada maintains the policy rate at 2&#188;%</title>
<link>https://www.bankofcanada.ca/2026/09/rate-announcement/</link>
<dc:date>2026-09-02T09:47:53+00:00</dc:date>
<cb:news rdf:parseType="Resource">
<cb:occurrenceDate>2026-09-02</cb:occurrenceDate>
</cb:news>
</item>
</rdf:RDF>
"""


def _client_returning(status_code: int, text: str) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=text)

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    )


@pytest.mark.asyncio
async def test_rate_announcement_press_release_mapped_without_cb_news() -> None:
    # No cb:news/cb:occurrenceDate in this feed -- released_date falls
    # back to dc:date's own calendar date, released_time stays None.
    source = BocReleaseSource(client=_client_returning(200, _SAMPLE_RDF))
    result = await source.fetch_releases()
    await source.aclose()

    assert len(result.observations) == 1
    obs = result.observations[0]
    assert obs.indicator_keys == ("CAD_POLICY_RATE_DECISION",)
    assert obs.released_date == date(2026, 9, 2)
    assert obs.released_time is None
    assert obs.released_timezone == "UTC"
    assert obs.source_published_at is not None
    assert obs.source_published_at.value == datetime(2026, 9, 2, 9, 47, 53, tzinfo=UTC)


@pytest.mark.asyncio
async def test_rate_announcement_prefers_cb_occurrence_date() -> None:
    source = BocReleaseSource(client=_client_returning(200, _SAMPLE_RDF_WITH_CB_NEWS))
    result = await source.fetch_releases()
    await source.aclose()

    assert len(result.observations) == 1
    obs = result.observations[0]
    assert obs.released_date == date(2026, 9, 2)
    assert obs.released_time is None
    # dc:date is still preserved as provenance even when cb:occurrenceDate exists.
    assert obs.source_published_at is not None
    assert obs.source_published_at.value == datetime(2026, 9, 2, 9, 47, 53, tzinfo=UTC)


@pytest.mark.asyncio
async def test_unrelated_press_release_is_unmapped_and_counted() -> None:
    source = BocReleaseSource(client=_client_returning(200, _SAMPLE_RDF))
    result = await source.fetch_releases()
    await source.aclose()

    assert all("banknote" not in o.raw_title for o in result.observations)
    assert result.mapped_count == 1
    assert result.unmapped_count == 1


@pytest.mark.asyncio
async def test_observed_at_is_set_at_fetch_time() -> None:
    before = datetime.now(UTC)
    source = BocReleaseSource(client=_client_returning(200, _SAMPLE_RDF))
    result = await source.fetch_releases()
    await source.aclose()
    after = datetime.now(UTC)

    assert len(result.observations) == 1
    assert before <= result.observations[0].observed_at.value <= after


@pytest.mark.asyncio
async def test_malformed_response_raises_unavailable_not_empty_result() -> None:
    source = BocReleaseSource(client=_client_returning(200, "not rss at all"))
    with pytest.raises(EconomicCalendarSourceUnavailableError):
        await source.fetch_releases()
    await source.aclose()

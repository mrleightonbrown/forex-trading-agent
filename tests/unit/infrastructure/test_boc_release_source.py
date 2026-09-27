"""FX-52A: unit tests for `BocReleaseSource` against a mocked HTTP
transport."""

from datetime import UTC, date, datetime, time

import httpx
import pytest

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


def _client_returning(status_code: int, text: str) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=text)

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    )


@pytest.mark.asyncio
async def test_rate_announcement_press_release_mapped() -> None:
    source = BocReleaseSource(client=_client_returning(200, _SAMPLE_RDF))
    observations = await source.fetch_releases()
    await source.aclose()

    assert len(observations) == 1
    obs = observations[0]
    assert obs.indicator_keys == ("CAD_POLICY_RATE_DECISION",)
    assert obs.released_date == date(2026, 9, 2)
    assert obs.released_time == time(9, 47, 53)
    assert obs.released_timezone == "UTC"


@pytest.mark.asyncio
async def test_unrelated_press_release_is_unmapped() -> None:
    source = BocReleaseSource(client=_client_returning(200, _SAMPLE_RDF))
    observations = await source.fetch_releases()
    await source.aclose()

    assert all("banknote" not in o.raw_title for o in observations)


@pytest.mark.asyncio
async def test_observed_at_is_set_at_fetch_time() -> None:
    before = datetime.now(UTC)
    source = BocReleaseSource(client=_client_returning(200, _SAMPLE_RDF))
    observations = await source.fetch_releases()
    await source.aclose()
    after = datetime.now(UTC)

    assert len(observations) == 1
    assert before <= observations[0].observed_at.value <= after

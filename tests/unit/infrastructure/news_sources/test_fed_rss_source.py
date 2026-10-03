"""FX-57A: `FedRssSource` field-mapping tests against a mocked HTTP
transport -- no real network access (see tests/integration/
test_fed_rss_source_live.py for live-feed validation)."""

from datetime import UTC, datetime

import httpx
import pytest

from forex_agent.application.ports.news_source import NewsSourceUnavailableError
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.news_sources.fed_rss_source import (
    FED_FEEDS,
    SOURCE_KEY,
    FedFeedDefinition,
    FedRssSource,
)

_RETRIEVED_AT = UtcTimestamp(datetime(2026, 9, 16, 18, 0, 7, tzinfo=UTC))

_PRESS_MONETARY_FEED = next(f for f in FED_FEEDS if f.channel == "press_monetary")


def _source_returning(status_code: int, text: str) -> FedRssSource:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=text, headers={"content-type": "text/xml"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://www.federalreserve.gov"
    )
    return FedRssSource(client=client, clock=lambda: _RETRIEVED_AT)


def _feed_xml(*items_xml: str) -> str:
    body = "".join(items_xml)
    return f"<rss version='2.0'><channel><title>t</title>{body}</channel></rss>"


def _item_xml(
    guid: str = "https://www.federalreserve.gov/newsevents/pressreleases/item.htm",
    title: str = "FOMC Statement",
    link: str | None = None,
    description: str | None = "The FOMC decided to maintain rates.",
    pub_date: str | None = "Wed, 16 Sep 2026 18:00:00 GMT",
) -> str:
    link = link or guid
    parts = [f"<guid>{guid}</guid>", f"<title>{title}</title>", f"<link>{link}</link>"]
    if description is not None:
        parts.append(f"<description>{description}</description>")
    if pub_date is not None:
        parts.append(f"<pubDate>{pub_date}</pubDate>")
    return f"<item>{''.join(parts)}</item>"


@pytest.mark.asyncio
async def test_guid_maps_to_external_item_id_and_source_key_is_fed() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(guid="g-123")))
    outcome = await source.fetch_feed(_PRESS_MONETARY_FEED)
    await source.aclose()

    assert len(outcome.observations) == 1
    observation = outcome.observations[0]
    assert observation.external_item_id == "g-123"
    assert observation.source_key == SOURCE_KEY == "FED"


@pytest.mark.asyncio
async def test_title_maps_to_headline_link_maps_to_canonical_url() -> None:
    source = _source_returning(
        200,
        _feed_xml(_item_xml(title="Powell Speech", link="https://www.federalreserve.gov/x.htm")),
    )
    outcome = await source.fetch_feed(_PRESS_MONETARY_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.headline == "Powell Speech"
    assert observation.canonical_url == "https://www.federalreserve.gov/x.htm"


@pytest.mark.asyncio
async def test_description_maps_to_summary_when_present() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(description="A snippet.")))
    outcome = await source.fetch_feed(_PRESS_MONETARY_FEED)
    await source.aclose()

    assert outcome.observations[0].summary == "A snippet."
    assert outcome.observations[0].body_text is None


@pytest.mark.asyncio
async def test_retrieved_at_becomes_observed_at_exactly_not_pub_date() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(pub_date="Wed, 16 Sep 2026 18:00:00 GMT")))
    outcome = await source.fetch_feed(_PRESS_MONETARY_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.observed_at == _RETRIEVED_AT
    assert observation.observed_at.value != observation.source_published_at.value  # type: ignore[union-attr]
    assert outcome.retrieved_at == _RETRIEVED_AT


@pytest.mark.asyncio
async def test_valid_pub_date_produces_source_published_at_and_provenance() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(pub_date="Wed, 16 Sep 2026 18:00:00 GMT")))
    outcome = await source.fetch_feed(_PRESS_MONETARY_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_published_at == UtcTimestamp(
        datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)
    )
    assert len(observation.source_timestamp_provenance) == 1
    provenance = observation.source_timestamp_provenance[0]
    assert provenance.field_name == "pubDate"
    assert provenance.raw_value == "Wed, 16 Sep 2026 18:00:00 GMT"
    assert provenance.normalized_at == observation.source_published_at


@pytest.mark.asyncio
async def test_malformed_pub_date_keeps_raw_value_but_no_published_at() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(pub_date="not a date")))
    outcome = await source.fetch_feed(_PRESS_MONETARY_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_published_at is None
    provenance = observation.source_timestamp_provenance[0]
    assert provenance.raw_value == "not a date"
    assert provenance.normalized_at is None
    assert provenance.normalization_note is not None


@pytest.mark.asyncio
async def test_sentinel_pub_date_1899_keeps_raw_value_but_no_published_at() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(pub_date="Sat, 30 Dec 1899 15:00:00 GMT")))
    outcome = await source.fetch_feed(_PRESS_MONETARY_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_published_at is None
    provenance = observation.source_timestamp_provenance[0]
    assert provenance.raw_value == "Sat, 30 Dec 1899 15:00:00 GMT"
    assert provenance.normalized_at is None


@pytest.mark.asyncio
async def test_missing_guid_item_is_skipped_as_invalid() -> None:
    xml = _feed_xml("<item><title>No Guid</title></item>", _item_xml(guid="g-ok"))
    source = _source_returning(200, xml)
    outcome = await source.fetch_feed(_PRESS_MONETARY_FEED)
    await source.aclose()

    assert outcome.items_invalid == 1
    assert len(outcome.observations) == 1
    assert outcome.observations[0].external_item_id == "g-ok"


@pytest.mark.asyncio
async def test_missing_title_item_is_skipped_as_invalid() -> None:
    xml = _feed_xml("<item><guid>g1</guid></item>")
    source = _source_returning(200, xml)
    outcome = await source.fetch_feed(_PRESS_MONETARY_FEED)
    await source.aclose()

    assert outcome.items_invalid == 1
    assert len(outcome.observations) == 0


@pytest.mark.asyncio
async def test_content_type_and_channel_per_feed() -> None:
    source = _source_returning(200, _feed_xml(_item_xml()))

    for feed, expected_content_type in (
        (FED_FEEDS[0], "monetary_policy_release"),
        (FED_FEEDS[1], "speech"),
        (FED_FEEDS[2], "testimony"),
    ):
        outcome = await source.fetch_feed(feed)
        assert outcome.source_channel == feed.channel
        assert outcome.observations[0].source_content_type == expected_content_type
    await source.aclose()


@pytest.mark.asyncio
async def test_authors_always_empty_language_is_en() -> None:
    source = _source_returning(200, _feed_xml(_item_xml()))
    outcome = await source.fetch_feed(_PRESS_MONETARY_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.authors == ()
    assert observation.language == "en"


@pytest.mark.asyncio
async def test_source_updated_at_always_none() -> None:
    source = _source_returning(200, _feed_xml(_item_xml()))
    outcome = await source.fetch_feed(_PRESS_MONETARY_FEED)
    await source.aclose()

    assert outcome.observations[0].source_updated_at is None


@pytest.mark.asyncio
async def test_disposition_and_status_always_eligible_active() -> None:
    source = _source_returning(200, _feed_xml(_item_xml()))
    outcome = await source.fetch_feed(_PRESS_MONETARY_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_status == NewsSourceStatus.ACTIVE
    assert observation.evidence_disposition == NewsEvidenceDisposition.EVIDENCE_ELIGIBLE
    assert observation.quarantine_reason is None
    assert observation.observation_mode == NewsObservationMode.PROSPECTIVE


@pytest.mark.asyncio
async def test_valid_empty_feed_returns_zero_observations_no_error() -> None:
    source = _source_returning(200, _feed_xml())
    outcome = await source.fetch_feed(_PRESS_MONETARY_FEED)
    await source.aclose()

    assert outcome.observations == ()
    assert outcome.items_invalid == 0


@pytest.mark.asyncio
async def test_html_masquerading_as_200_raises_unavailable() -> None:
    source = _source_returning(200, "<html><body>blocked</body></html>")
    with pytest.raises(NewsSourceUnavailableError):
        await source.fetch_feed(_PRESS_MONETARY_FEED)
    await source.aclose()


@pytest.mark.asyncio
async def test_http_500_raises_unavailable() -> None:
    source = _source_returning(500, "error")
    with pytest.raises(NewsSourceUnavailableError):
        await source.fetch_feed(_PRESS_MONETARY_FEED)
    await source.aclose()


def test_fed_feeds_use_the_registered_source_key_and_exact_paths() -> None:
    assert SOURCE_KEY == "FED"
    paths = {f.path for f in FED_FEEDS}
    assert paths == {
        "/feeds/press_monetary.xml",
        "/feeds/speeches.xml",
        "/feeds/testimony.xml",
    }
    assert isinstance(FED_FEEDS[0], FedFeedDefinition)

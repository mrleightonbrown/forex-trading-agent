"""FX-57C: `BoeRssSource` field-mapping tests against a mocked HTTP
transport -- no real network access (see tests/integration/
test_boe_rss_source_live.py for live-feed validation)."""

from datetime import UTC, datetime

import httpx
import pytest

from forex_agent.application.ports.news_source import NewsSourceUnavailableError
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.news_sources.boe_rss_source import (
    BOE_FEEDS,
    SOURCE_KEY,
    BoeFeedDefinition,
    BoeRssSource,
)

_RETRIEVED_AT = UtcTimestamp(datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC))
_NEWS_FEED = next(f for f in BOE_FEEDS if f.channel == "boe_news")
_SPEECHES_FEED = next(f for f in BOE_FEEDS if f.channel == "boe_speeches")
_PUBLICATIONS_FEED = next(f for f in BOE_FEEDS if f.channel == "boe_publications")

_OPAQUE_GUID = "{B641CC4F-0AD7-46E2-9965-B44629C6E93E}"
_LINK = "https://www.bankofengland.co.uk/news/2026/october/appointment-of-members"


def _source_returning(status_code: int, text: str) -> BoeRssSource:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=text, headers={"content-type": "text/xml"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://www.bankofengland.co.uk"
    )
    return BoeRssSource(client=client, clock=lambda: _RETRIEVED_AT)


def _feed_xml(*items_xml: str) -> str:
    body = "".join(items_xml)
    return (
        f"<rss version='2.0'><channel><title>t</title><language>en</language>{body}</channel></rss>"
    )


def _item_xml(
    guid: str = _OPAQUE_GUID,
    title: str = "Appointment of members of the EDMC",
    link: str = _LINK,
    description: str | None = "A genuine summary of the item.",
    pub_date: str | None = "Fri, 02 Oct 2026 09:00:00 +0100",
    is_perma_link: str | None = "false",
) -> str:
    guid_attr = f' isPermaLink="{is_perma_link}"' if is_perma_link is not None else ""
    parts = [
        f"<title>{title}</title>",
        f"<link>{link}</link>",
        f"<guid{guid_attr}>{guid}</guid>",
    ]
    if description is not None:
        parts.append(f"<description>{description}</description>")
    if pub_date is not None:
        parts.append(f"<pubDate>{pub_date}</pubDate>")
    return f"<item>{''.join(parts)}</item>"


@pytest.mark.asyncio
async def test_guid_maps_to_external_item_id_and_source_key_is_boe() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(guid=_OPAQUE_GUID)))
    outcome = await source.fetch_feed(_NEWS_FEED)
    await source.aclose()

    assert len(outcome.observations) == 1
    observation = outcome.observations[0]
    assert observation.external_item_id == _OPAQUE_GUID
    assert observation.source_key == SOURCE_KEY == "BOE"


@pytest.mark.asyncio
async def test_opaque_guid_is_distinct_from_link_never_url_derived() -> None:
    source = _source_returning(
        200, _feed_xml(_item_xml(guid=_OPAQUE_GUID, link="https://www.bankofengland.co.uk/x"))
    )
    outcome = await source.fetch_feed(_NEWS_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.external_item_id == _OPAQUE_GUID
    assert observation.canonical_url == "https://www.bankofengland.co.uk/x"
    assert observation.external_item_id != observation.canonical_url


@pytest.mark.asyncio
async def test_title_maps_to_headline_description_maps_to_summary() -> None:
    source = _source_returning(
        200,
        _feed_xml(_item_xml(title="Financial Policy Committee Record", description="FPC summary.")),
    )
    outcome = await source.fetch_feed(_NEWS_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.headline == "Financial Policy Committee Record"
    assert observation.summary == "FPC summary."
    assert observation.body_text is None


@pytest.mark.asyncio
async def test_content_type_and_channel_per_feed() -> None:
    source = _source_returning(200, _feed_xml(_item_xml()))

    for feed, expected_content_type in (
        (_NEWS_FEED, "news"),
        (_SPEECHES_FEED, "speech"),
        (_PUBLICATIONS_FEED, "publication"),
    ):
        outcome = await source.fetch_feed(feed)
        assert outcome.source_channel == feed.channel
        assert outcome.observations[0].source_content_type == expected_content_type
        assert outcome.observations[0].source_channel == feed.channel
    await source.aclose()


@pytest.mark.asyncio
async def test_retrieved_at_becomes_observed_at_exactly_not_pub_date() -> None:
    source = _source_returning(
        200, _feed_xml(_item_xml(pub_date="Fri, 02 Oct 2026 09:00:00 +0100"))
    )
    outcome = await source.fetch_feed(_NEWS_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.observed_at == _RETRIEVED_AT
    assert observation.source_published_at is not None
    assert observation.observed_at.value != observation.source_published_at.value


@pytest.mark.asyncio
async def test_bst_plus_0100_pubdate_normalizes_to_utc() -> None:
    source = _source_returning(
        200, _feed_xml(_item_xml(pub_date="Fri, 02 Oct 2026 09:00:00 +0100"))
    )
    outcome = await source.fetch_feed(_NEWS_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_published_at == UtcTimestamp(
        datetime(2026, 10, 2, 8, 0, 0, tzinfo=UTC)
    )
    provenance = observation.source_timestamp_provenance[0]
    assert provenance.raw_value == "Fri, 02 Oct 2026 09:00:00 +0100"
    assert provenance.normalized_at == observation.source_published_at


@pytest.mark.asyncio
async def test_gmt_z_pubdate_normalizes_to_utc() -> None:
    # Live-confirmed BoE caveat: the speeches feed uses the bare
    # military-zone "Z" form during GMT season.
    source = _source_returning(200, _feed_xml(_item_xml(pub_date="Thu, 26 Mar 2026 16:00:00 Z")))
    outcome = await source.fetch_feed(_SPEECHES_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_published_at == UtcTimestamp(
        datetime(2026, 3, 26, 16, 0, 0, tzinfo=UTC)
    )
    provenance = observation.source_timestamp_provenance[0]
    assert provenance.raw_value == "Thu, 26 Mar 2026 16:00:00 Z"
    assert provenance.normalized_at == observation.source_published_at


@pytest.mark.asyncio
async def test_malformed_pub_date_keeps_raw_value_but_no_published_at() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(pub_date="not a date")))
    outcome = await source.fetch_feed(_NEWS_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_published_at is None
    provenance = observation.source_timestamp_provenance[0]
    assert provenance.raw_value == "not a date"
    assert provenance.normalized_at is None


@pytest.mark.asyncio
async def test_missing_guid_item_is_skipped_as_invalid() -> None:
    xml = _feed_xml(
        "<item><title>No Guid</title><link>https://x</link></item>",
        _item_xml(guid="{OK-GUID}"),
    )
    source = _source_returning(200, xml)
    outcome = await source.fetch_feed(_NEWS_FEED)
    await source.aclose()

    assert outcome.items_invalid == 1
    assert len(outcome.observations) == 1
    assert outcome.observations[0].external_item_id == "{OK-GUID}"


@pytest.mark.asyncio
async def test_missing_description_is_none_not_invalid() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(description=None)))
    outcome = await source.fetch_feed(_NEWS_FEED)
    await source.aclose()

    assert outcome.items_invalid == 0
    assert outcome.observations[0].summary is None


@pytest.mark.asyncio
async def test_missing_title_item_is_skipped_as_invalid() -> None:
    xml = _feed_xml("<item><guid>{G}</guid><link>https://x</link></item>")
    source = _source_returning(200, xml)
    outcome = await source.fetch_feed(_NEWS_FEED)
    await source.aclose()

    assert outcome.items_invalid == 1
    assert len(outcome.observations) == 0


@pytest.mark.asyncio
async def test_authors_always_empty_language_is_en_source_updated_at_none() -> None:
    source = _source_returning(200, _feed_xml(_item_xml()))
    outcome = await source.fetch_feed(_NEWS_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.authors == ()
    assert observation.language == "en"
    assert observation.source_updated_at is None


@pytest.mark.asyncio
async def test_disposition_and_status_always_eligible_active_prospective() -> None:
    source = _source_returning(200, _feed_xml(_item_xml()))
    outcome = await source.fetch_feed(_NEWS_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_status == NewsSourceStatus.ACTIVE
    assert observation.evidence_disposition == NewsEvidenceDisposition.EVIDENCE_ELIGIBLE
    assert observation.quarantine_reason is None
    assert observation.observation_mode == NewsObservationMode.PROSPECTIVE


@pytest.mark.asyncio
async def test_valid_empty_feed_returns_zero_observations_no_error() -> None:
    source = _source_returning(200, _feed_xml())
    outcome = await source.fetch_feed(_NEWS_FEED)
    await source.aclose()

    assert outcome.observations == ()
    assert outcome.items_invalid == 0
    assert outcome.source_channel == "boe_news"


@pytest.mark.asyncio
async def test_html_masquerading_as_200_raises_unavailable() -> None:
    source = _source_returning(200, "<html><body>blocked</body></html>")
    with pytest.raises(NewsSourceUnavailableError):
        await source.fetch_feed(_NEWS_FEED)
    await source.aclose()


@pytest.mark.asyncio
async def test_http_500_raises_unavailable() -> None:
    source = _source_returning(500, "error")
    with pytest.raises(NewsSourceUnavailableError):
        await source.fetch_feed(_NEWS_FEED)
    await source.aclose()


def test_boe_feeds_use_the_registered_source_key_and_exact_paths() -> None:
    assert SOURCE_KEY == "BOE"
    paths = {f.path for f in BOE_FEEDS}
    assert paths == {"/rss/news", "/rss/speeches", "/rss/publications"}
    assert isinstance(BOE_FEEDS[0], BoeFeedDefinition)

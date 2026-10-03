"""FX-57B: `EcbRssSource` field-mapping tests against a mocked HTTP
transport -- no real network access (see tests/integration/
test_ecb_rss_source_live.py for live-feed validation)."""

from datetime import UTC, datetime

import httpx
import pytest

from forex_agent.application.ports.news_source import NewsSourceUnavailableError
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.news_sources.ecb_rss_source import (
    ECB_FEEDS,
    SOURCE_KEY,
    EcbFeedDefinition,
    EcbRssSource,
)

_RETRIEVED_AT = UtcTimestamp(datetime(2026, 10, 2, 13, 30, 0, tzinfo=UTC))
_PRESS_FEED = ECB_FEEDS[0]


def _source_returning(status_code: int, text: str) -> EcbRssSource:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code, text=text, headers={"content-type": "application/rss+xml"}
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://www.ecb.europa.eu"
    )
    return EcbRssSource(client=client, clock=lambda: _RETRIEVED_AT)


def _feed_xml(*items_xml: str) -> str:
    body = "".join(items_xml)
    return (
        "<rss version='2.0'><channel><title>ECB - European Central Bank</title>"
        f"<language>en</language>{body}</channel></rss>"
    )


def _item_xml(
    url: str = "https://www.ecb.europa.eu//press/pr/date/2026/html/ecb.pr261002~abc123.en.html",
    title: str = "ECB amends monetary policy implementation guidelines",
    pub_date: str | None = "Fri, 02 Oct 2026 15:00:00 +0200",
    guid: str | None = None,
) -> str:
    guid = guid or url
    parts = [f"<title>{title}</title>", f"<link>{url}</link>", f"<guid>{guid}</guid>"]
    if pub_date is not None:
        parts.append(f"<pubDate>{pub_date}</pubDate>")
    return f"<item>{''.join(parts)}</item>"


_PR_URL = "https://www.ecb.europa.eu//press/pr/date/2026/html/ecb.pr261002~abc123.en.html"
_SP_URL = "https://www.ecb.europa.eu//press/key/date/2026/html/ecb.sp261002_1~def456.en.html"
_IN_URL = "https://www.ecb.europa.eu//press/inter/date/2026/html/ecb.in260930~ghi789.en.html"
_GC_URL = "https://www.ecb.europa.eu//press/govcdec/otherdec/2026/html/ecb.gc261002~jkl012.en.html"
_UNKNOWN_URL = "https://www.ecb.europa.eu//press/wp/date/2026/html/ecb.wp261002~mno345.en.pdf"


@pytest.mark.asyncio
async def test_guid_maps_to_external_item_id_and_source_key_is_ecb() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(url=_PR_URL)))
    outcome = await source.fetch_feed(_PRESS_FEED)
    await source.aclose()

    assert len(outcome.observations) == 1
    observation = outcome.observations[0]
    assert observation.external_item_id == _PR_URL
    assert observation.source_key == SOURCE_KEY == "ECB"


@pytest.mark.asyncio
async def test_title_maps_to_headline_link_maps_to_canonical_url() -> None:
    source = _source_returning(
        200, _feed_xml(_item_xml(title="Christine Lagarde: Where AI risks meet"))
    )
    outcome = await source.fetch_feed(_PRESS_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.headline == "Christine Lagarde: Where AI risks meet"
    assert observation.canonical_url == _PR_URL


@pytest.mark.asyncio
async def test_pr_sp_in_gc_content_classes_map_correctly_same_channel() -> None:
    source = _source_returning(
        200,
        _feed_xml(
            _item_xml(url=_PR_URL, guid=_PR_URL),
            _item_xml(url=_SP_URL, guid=_SP_URL),
            _item_xml(url=_IN_URL, guid=_IN_URL),
            _item_xml(url=_GC_URL, guid=_GC_URL),
        ),
    )
    outcome = await source.fetch_feed(_PRESS_FEED)
    await source.aclose()

    assert outcome.items_invalid == 0
    by_url = {o.canonical_url: o for o in outcome.observations}
    assert by_url[_PR_URL].source_content_type == "press_release"
    assert by_url[_SP_URL].source_content_type == "speech"
    assert by_url[_IN_URL].source_content_type == "interview"
    assert by_url[_GC_URL].source_content_type == "press_release"
    # Section 10/41: ALL share the same channel regardless of content type.
    assert all(o.source_channel == "ecb_press" for o in outcome.observations)
    assert all(o.source_key == "ECB" for o in outcome.observations)
    # Separate GUID identities.
    assert len({o.external_item_id for o in outcome.observations}) == 4


@pytest.mark.asyncio
async def test_unknown_content_class_is_invalid_not_guessed() -> None:
    source = _source_returning(
        200,
        _feed_xml(
            _item_xml(url=_UNKNOWN_URL, guid=_UNKNOWN_URL), _item_xml(url=_PR_URL, guid=_PR_URL)
        ),
    )
    outcome = await source.fetch_feed(_PRESS_FEED)
    await source.aclose()

    assert outcome.items_invalid == 1
    assert len(outcome.observations) == 1
    assert outcome.observations[0].canonical_url == _PR_URL
    assert "unrecognized" in outcome.invalid_reasons[0].lower()


@pytest.mark.asyncio
async def test_retrieved_at_becomes_observed_at_exactly_not_pub_date() -> None:
    source = _source_returning(
        200, _feed_xml(_item_xml(pub_date="Fri, 02 Oct 2026 15:00:00 +0200"))
    )
    outcome = await source.fetch_feed(_PRESS_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.observed_at == _RETRIEVED_AT
    assert observation.source_published_at is not None
    assert observation.observed_at.value != observation.source_published_at.value


@pytest.mark.asyncio
async def test_valid_pub_date_with_plus_0200_offset_normalizes_to_utc() -> None:
    source = _source_returning(
        200, _feed_xml(_item_xml(pub_date="Fri, 02 Oct 2026 15:00:00 +0200"))
    )
    outcome = await source.fetch_feed(_PRESS_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_published_at == UtcTimestamp(
        datetime(2026, 10, 2, 13, 0, 0, tzinfo=UTC)
    )
    provenance = observation.source_timestamp_provenance[0]
    assert provenance.raw_value == "Fri, 02 Oct 2026 15:00:00 +0200"
    assert provenance.normalized_at == observation.source_published_at


@pytest.mark.asyncio
async def test_malformed_pub_date_keeps_raw_value_but_no_published_at() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(pub_date="not a date")))
    outcome = await source.fetch_feed(_PRESS_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_published_at is None
    provenance = observation.source_timestamp_provenance[0]
    assert provenance.raw_value == "not a date"
    assert provenance.normalized_at is None


@pytest.mark.asyncio
async def test_missing_guid_item_is_skipped_as_invalid() -> None:
    xml = _feed_xml(
        f"<item><title>No Guid</title><link>{_PR_URL}</link></item>",
        _item_xml(url=_SP_URL, guid=_SP_URL),
    )
    source = _source_returning(200, xml)
    outcome = await source.fetch_feed(_PRESS_FEED)
    await source.aclose()

    assert outcome.items_invalid == 1
    assert len(outcome.observations) == 1
    assert outcome.observations[0].canonical_url == _SP_URL


@pytest.mark.asyncio
async def test_missing_title_item_is_skipped_as_invalid() -> None:
    xml = _feed_xml(f"<item><guid>{_PR_URL}</guid><link>{_PR_URL}</link></item>")
    source = _source_returning(200, xml)
    outcome = await source.fetch_feed(_PRESS_FEED)
    await source.aclose()

    assert outcome.items_invalid == 1
    assert len(outcome.observations) == 0


@pytest.mark.asyncio
async def test_no_description_no_author_authors_empty_summary_none() -> None:
    source = _source_returning(200, _feed_xml(_item_xml()))
    outcome = await source.fetch_feed(_PRESS_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.authors == ()
    assert observation.summary is None
    assert observation.body_text is None


@pytest.mark.asyncio
async def test_language_is_en_source_updated_at_always_none() -> None:
    source = _source_returning(200, _feed_xml(_item_xml()))
    outcome = await source.fetch_feed(_PRESS_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.language == "en"
    assert observation.source_updated_at is None


@pytest.mark.asyncio
async def test_disposition_and_status_always_eligible_active_prospective() -> None:
    source = _source_returning(200, _feed_xml(_item_xml()))
    outcome = await source.fetch_feed(_PRESS_FEED)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_status == NewsSourceStatus.ACTIVE
    assert observation.evidence_disposition == NewsEvidenceDisposition.EVIDENCE_ELIGIBLE
    assert observation.quarantine_reason is None
    assert observation.observation_mode == NewsObservationMode.PROSPECTIVE


@pytest.mark.asyncio
async def test_valid_empty_feed_returns_zero_observations_no_error() -> None:
    source = _source_returning(200, _feed_xml())
    outcome = await source.fetch_feed(_PRESS_FEED)
    await source.aclose()

    assert outcome.observations == ()
    assert outcome.items_invalid == 0


@pytest.mark.asyncio
async def test_html_masquerading_as_200_raises_unavailable() -> None:
    source = _source_returning(200, "<html><body>blocked</body></html>")
    with pytest.raises(NewsSourceUnavailableError):
        await source.fetch_feed(_PRESS_FEED)
    await source.aclose()


@pytest.mark.asyncio
async def test_http_500_raises_unavailable() -> None:
    source = _source_returning(500, "error")
    with pytest.raises(NewsSourceUnavailableError):
        await source.fetch_feed(_PRESS_FEED)
    await source.aclose()


def test_ecb_feed_uses_the_registered_source_key_and_exact_path() -> None:
    assert SOURCE_KEY == "ECB"
    assert len(ECB_FEEDS) == 1
    assert ECB_FEEDS[0].path == "/rss/press.html"
    assert ECB_FEEDS[0].channel == "ecb_press"
    assert isinstance(ECB_FEEDS[0], EcbFeedDefinition)

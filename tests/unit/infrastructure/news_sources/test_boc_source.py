"""FX-57F: `BocSource` field-mapping tests against a mocked HTTP
transport -- no real network access (see tests/integration/
test_boc_source_live.py for live-feed validation)."""

from datetime import UTC, datetime

import httpx
import pytest

from forex_agent.application.ports.news_source import NewsSourceUnavailableError
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.news_sources.boc_source import CHANNEL, SOURCE_KEY, BocSource

_RETRIEVED_AT = UtcTimestamp(datetime(2026, 10, 10, 20, 22, 50, tzinfo=UTC))
_HOST = "https://www.bankofcanada.ca"
_PATH = "/2026/09/fad-press-release-2026-09-02/"


def _source_returning(status_code: int, text: str) -> BocSource:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code, text=text, headers={"content-type": "application/rdf+xml"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=_HOST)
    return BocSource(client=client, clock=lambda: _RETRIEVED_AT)


def _feed_xml(*items_xml: str) -> str:
    body = "".join(items_xml)
    ns = (
        "xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#' "
        "xmlns='http://purl.org/rss/1.0/' xmlns:dc='http://purl.org/dc/elements/1.1/'"
    )
    return (
        f"<rdf:RDF {ns}>"
        f"<channel rdf:about='{_HOST}/content_type/press-releases/feed/'>"
        "<title>Press Releases - Bank of Canada</title>"
        "</channel>"
        f"{body}</rdf:RDF>"
    )


def _item_xml(
    about: str = f"{_HOST}{_PATH}",
    title: str = "Bank of Canada increases its policy rate",
    link: str | None = None,
    description: str | None = "The Bank of Canada today increased its policy rate.",
    dc_date: str | None = "2026-09-02T09:47:53+00:00",
    language: str | None = "en",
) -> str:
    link = link or about
    parts = [f"<title>{title}</title>", f"<link>{link}</link>"]
    if description is not None:
        parts.append(f"<description>{description}</description>")
    if dc_date is not None:
        parts.append(f"<dc:date>{dc_date}</dc:date>")
    if language is not None:
        parts.append(f"<dc:language>{language}</dc:language>")
    return f"<item rdf:about='{about}'>{''.join(parts)}</item>"


@pytest.mark.asyncio
async def test_rdf_about_maps_to_external_item_id_and_source_key_is_boc() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(about=f"{_HOST}{_PATH}")))
    outcome = await source.fetch_press_releases()
    await source.aclose()

    assert len(outcome.observations) == 1
    observation = outcome.observations[0]
    assert observation.external_item_id == f"{_HOST}{_PATH}"
    assert observation.source_key == SOURCE_KEY == "BOC"
    assert observation.source_channel == CHANNEL == "boc_press_releases"


@pytest.mark.asyncio
async def test_title_maps_to_headline_link_maps_to_canonical_url() -> None:
    source = _source_returning(
        200,
        _feed_xml(_item_xml(title="Bank of Canada maintains policy rate", link=f"{_HOST}{_PATH}")),
    )
    outcome = await source.fetch_press_releases()
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.headline == "Bank of Canada maintains policy rate"
    assert observation.canonical_url == f"{_HOST}{_PATH}"


@pytest.mark.asyncio
async def test_description_maps_to_summary_when_present() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(description="A snippet.")))
    outcome = await source.fetch_press_releases()
    await source.aclose()

    assert outcome.observations[0].summary == "A snippet."
    assert outcome.observations[0].body_text is None


@pytest.mark.asyncio
async def test_source_content_type_is_always_press_release() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(title="Bank of Canada unveils new note")))
    outcome = await source.fetch_press_releases()
    await source.aclose()

    # Section 9: never inferred more granularly from title wording,
    # even for a title that reads nothing like a rate decision.
    assert outcome.observations[0].source_content_type == "press_release"


@pytest.mark.asyncio
async def test_retrieved_at_becomes_observed_at_exactly_never_dc_date() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(dc_date="2026-09-02T09:47:53+00:00")))
    outcome = await source.fetch_press_releases()
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.observed_at == _RETRIEVED_AT
    assert observation.observed_at.value != observation.source_published_at.value  # type: ignore[union-attr]
    assert outcome.retrieved_at == _RETRIEVED_AT


@pytest.mark.asyncio
async def test_malformed_dc_date_shape_reinterprets_as_toronto_local() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(dc_date="2026-09-02T09:47:53+00:00")))
    outcome = await source.fetch_press_releases()
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_published_at == UtcTimestamp(
        datetime(2026, 9, 2, 13, 47, 53, tzinfo=UTC)
    )
    assert len(observation.source_timestamp_provenance) == 1
    provenance = observation.source_timestamp_provenance[0]
    assert provenance.field_name == "dc:date"
    assert provenance.raw_value == "2026-09-02T09:47:53+00:00"
    assert provenance.normalized_at == observation.source_published_at


@pytest.mark.asyncio
async def test_dst_ambiguous_dc_date_keeps_raw_value_but_no_published_at() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(dc_date="2026-11-01T01:30:00+00:00")))
    outcome = await source.fetch_press_releases()
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_published_at is None
    provenance = observation.source_timestamp_provenance[0]
    assert provenance.raw_value == "2026-11-01T01:30:00+00:00"
    assert provenance.normalized_at is None
    assert provenance.normalization_note is not None


@pytest.mark.asyncio
async def test_missing_dc_date_produces_no_timestamp_provenance_at_all() -> None:
    # Section 31: absent, not malformed -- no provenance entry exists,
    # rather than one with a None normalized_at.
    source = _source_returning(200, _feed_xml(_item_xml(dc_date=None)))
    outcome = await source.fetch_press_releases()
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_published_at is None
    assert observation.source_timestamp_provenance == ()


@pytest.mark.asyncio
async def test_missing_identity_item_is_skipped_as_invalid() -> None:
    xml = _feed_xml(
        "<item><title>No identity</title><link>x</link></item>",
        _item_xml(about=f"{_HOST}{_PATH}"),
    )
    source = _source_returning(200, xml)
    outcome = await source.fetch_press_releases()
    await source.aclose()

    assert outcome.items_invalid == 1
    assert len(outcome.observations) == 1
    assert outcome.observations[0].external_item_id == f"{_HOST}{_PATH}"


@pytest.mark.asyncio
async def test_malformed_feed_raises_news_source_unavailable() -> None:
    source = _source_returning(200, "<html><body>Access Denied</body></html>")
    with pytest.raises(NewsSourceUnavailableError):
        await source.fetch_press_releases()
    await source.aclose()


@pytest.mark.asyncio
async def test_observation_mode_is_always_prospective() -> None:
    source = _source_returning(200, _feed_xml(_item_xml()))
    outcome = await source.fetch_press_releases()
    await source.aclose()

    assert outcome.observations[0].observation_mode == NewsObservationMode.PROSPECTIVE


@pytest.mark.asyncio
async def test_source_status_active_and_evidence_eligible() -> None:
    source = _source_returning(200, _feed_xml(_item_xml()))
    outcome = await source.fetch_press_releases()
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_status == NewsSourceStatus.ACTIVE
    assert observation.evidence_disposition == NewsEvidenceDisposition.EVIDENCE_ELIGIBLE


@pytest.mark.asyncio
async def test_authors_always_empty_body_text_always_none() -> None:
    source = _source_returning(200, _feed_xml(_item_xml()))
    outcome = await source.fetch_press_releases()
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.authors == ()
    assert observation.body_text is None


# --- FX-57FH Section 5/6: dc:date raw preservation through the full adapter


@pytest.mark.asyncio
async def test_dc_date_raw_value_preserves_whitespace_through_full_adapter() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(dc_date="  2026-09-02T09:47:53+00:00  ")))
    outcome = await source.fetch_press_releases()
    await source.aclose()

    observation = outcome.observations[0]
    provenance = observation.source_timestamp_provenance[0]
    assert provenance.raw_value == "  2026-09-02T09:47:53+00:00  "
    assert observation.source_published_at == UtcTimestamp(
        datetime(2026, 9, 2, 13, 47, 53, tzinfo=UTC)
    )


# --- FX-57FH Section 7: language comes from the parsed source field -------


@pytest.mark.asyncio
async def test_language_is_the_parsed_dc_language_value_not_a_hardcoded_constant() -> None:
    source = _source_returning(200, _feed_xml(_item_xml(language="en")))
    outcome = await source.fetch_press_releases()
    await source.aclose()

    assert outcome.observations[0].language == "en"


@pytest.mark.asyncio
async def test_unexpected_language_item_is_skipped_as_invalid_not_ingested() -> None:
    xml = _feed_xml(_item_xml(language="fr"), _item_xml(about=f"{_HOST}{_PATH}#ok", language="en"))
    source = _source_returning(200, xml)
    outcome = await source.fetch_press_releases()
    await source.aclose()

    assert outcome.items_invalid == 1
    assert len(outcome.observations) == 1
    assert outcome.observations[0].external_item_id == f"{_HOST}{_PATH}#ok"


# --- FX-57FH Section 3/4: future-dated remediated observation fails closed


@pytest.mark.asyncio
async def test_future_dated_remediated_source_published_at_raises_and_returns_no_outcome() -> None:
    # _RETRIEVED_AT is 2026-10-10T20:22:50 UTC; this dc:date remediates
    # (October, EDT, UTC-4) to 2026-10-11T13:47:53 UTC -- strictly AFTER
    # retrieved_at, so the whole response must fail closed.
    source = _source_returning(200, _feed_xml(_item_xml(dc_date="2026-10-11T09:47:53+00:00")))
    with pytest.raises(NewsSourceUnavailableError) as exc_info:
        await source.fetch_press_releases()
    await source.aclose()

    message = str(exc_info.value)
    assert f"{_HOST}{_PATH}" in message
    assert "2026-10-11T09:47:53+00:00" in message
    assert "retrieved_at" in message


@pytest.mark.asyncio
async def test_source_published_at_exactly_equal_to_retrieved_at_does_not_raise() -> None:
    # _RETRIEVED_AT is 2026-10-10T20:22:50 UTC; 16:22:50 Toronto-local
    # (EDT, UTC-4) remediates to EXACTLY that instant -- Section 3's
    # own "<= retrieved_at, no tolerance" must accept equality.
    source = _source_returning(200, _feed_xml(_item_xml(dc_date="2026-10-10T16:22:50+00:00")))
    outcome = await source.fetch_press_releases()
    await source.aclose()

    assert outcome.observations[0].source_published_at == _RETRIEVED_AT


@pytest.mark.asyncio
async def test_future_dated_item_among_other_valid_items_discards_the_whole_response() -> None:
    # Section 4: no partial persistence -- a single future-dated item
    # must take the ENTIRE response down, including otherwise-valid
    # sibling items in the same response.
    xml = _feed_xml(
        _item_xml(about=f"{_HOST}{_PATH}#good", dc_date="2026-09-02T09:47:53+00:00"),
        _item_xml(about=f"{_HOST}{_PATH}#future", dc_date="2026-10-11T09:47:53+00:00"),
    )
    source = _source_returning(200, xml)
    with pytest.raises(NewsSourceUnavailableError):
        await source.fetch_press_releases()
    await source.aclose()


@pytest.mark.asyncio
async def test_on_acquisition_attempt_hook_is_invoked_with_source_key_and_channel() -> None:
    observed: list[tuple[str, str]] = []

    async def on_acquisition_attempt(
        source_key: str, channel: str, run_id: str, outcome: object
    ) -> None:
        observed.append((source_key, channel))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=_feed_xml(_item_xml()), headers={"content-type": "application/rdf+xml"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=_HOST)
    source = BocSource(
        client=client, clock=lambda: _RETRIEVED_AT, on_acquisition_attempt=on_acquisition_attempt
    )
    await source.fetch_press_releases()
    await source.aclose()

    assert observed == [(SOURCE_KEY, CHANNEL)]

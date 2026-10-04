"""FX-57D: deterministic fixture tests for `parse_content_api_item`
and `GovUkHmtSource` against a mocked HTTP transport -- no real
network access (see tests/integration/test_govuk_hmt_source_live.py
for live-feed validation)."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from forex_agent.application.ports.news_source import NewsSourceUnavailableError
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_revision_fact import NewsSourceRevisionKind
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.news_sources.govuk_content_api import (
    CHANNEL,
    SOURCE_KEY,
    GovUkHmtSource,
    MalformedContentApiResponseError,
    parse_content_api_item,
)

_RETRIEVED_AT = UtcTimestamp(datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC))
_HMT_ORG = {
    "base_path": "/government/organisations/hm-treasury",
    "title": "HM Treasury",
}
_NON_HMT_ORG = {
    "base_path": "/government/organisations/cabinet-office",
    "title": "Cabinet Office",
}


def _content_json(
    content_id: str = "fd408444-8375-4485-90d3-8fb2c57d54c4",
    base_path: str = "/government/news/example-item",
    title: str = "Example item",
    description: str | None = "A genuine summary.",
    document_type: str = "news_story",
    locale: str = "en",
    body: str | None = "<p>Body text.</p>",
    first_published_at: str | None = "2026-10-01T09:24:06+01:00",
    public_updated_at: str | None = "2026-10-01T09:24:06+01:00",
    updated_at: str | None = "2026-10-01T09:24:06+01:00",
    publishing_scheduled_at: str | None = None,
    change_history: list[dict[str, str]] | None = None,
    withdrawn_notice: dict[str, str] | None = None,
    organisations: list[dict[str, str]] | None = None,
) -> str:
    data = {
        "content_id": content_id,
        "base_path": base_path,
        "title": title,
        "description": description,
        "document_type": document_type,
        "locale": locale,
        "first_published_at": first_published_at,
        "public_updated_at": public_updated_at,
        "updated_at": updated_at,
        "publishing_scheduled_at": publishing_scheduled_at,
        "withdrawn_notice": withdrawn_notice if withdrawn_notice is not None else {},
        "details": {
            "body": body,
            "change_history": (
                change_history
                if change_history is not None
                else [{"note": "First published.", "public_timestamp": "2026-10-01T08:24:06Z"}]
            ),
        },
        "links": {
            "organisations": organisations if organisations is not None else [_HMT_ORG],
        },
    }
    return json.dumps(data)


# --- parse_content_api_item -------------------------------------------------


def test_normal_active_item_parses() -> None:
    item = parse_content_api_item(_content_json())
    assert item.content_id == "fd408444-8375-4485-90d3-8fb2c57d54c4"
    assert item.base_path == "/government/news/example-item"
    assert item.title == "Example item"
    assert item.document_type == "news_story"
    assert item.locale == "en"
    assert item.withdrawn is False
    assert item.organisation_base_paths == ("/government/organisations/hm-treasury",)


def test_missing_title_raises() -> None:
    with pytest.raises(MalformedContentApiResponseError, match="title"):
        parse_content_api_item(_content_json(title=""))


def test_missing_content_id_raises() -> None:
    with pytest.raises(MalformedContentApiResponseError, match="content_id"):
        parse_content_api_item(_content_json(content_id=""))


def test_missing_optional_description_is_none() -> None:
    item = parse_content_api_item(_content_json(description=None))
    assert item.description is None


def test_body_present() -> None:
    item = parse_content_api_item(_content_json(body="<p>Hello</p>"))
    assert item.body == "<p>Hello</p>"


def test_body_absent_is_none() -> None:
    item = parse_content_api_item(_content_json(body=None))
    assert item.body is None


def test_malformed_json_raises() -> None:
    with pytest.raises(MalformedContentApiResponseError):
        parse_content_api_item("{not valid json")


def test_non_object_top_level_raises() -> None:
    with pytest.raises(MalformedContentApiResponseError):
        parse_content_api_item("[1, 2, 3]")


def test_html_masquerading_as_200_raises() -> None:
    with pytest.raises(MalformedContentApiResponseError):
        parse_content_api_item("<html><body>Not JSON</body></html>")


# --- Timestamp test matrix (Section 76) -------------------------------------


def test_a_first_published_at_raw_preserved() -> None:
    item = parse_content_api_item(_content_json(first_published_at="2026-10-01T09:24:06+01:00"))
    assert item.first_published_at_raw == "2026-10-01T09:24:06+01:00"


def test_b_public_updated_at_raw_preserved() -> None:
    item = parse_content_api_item(_content_json(public_updated_at="2026-10-01T10:00:00+01:00"))
    assert item.public_updated_at_raw == "2026-10-01T10:00:00+01:00"


def test_c_updated_at_raw_preserved_independently() -> None:
    item = parse_content_api_item(
        _content_json(
            public_updated_at="2026-10-01T09:24:06+01:00",
            updated_at="2026-10-01T09:24:44+01:00",
        )
    )
    assert item.public_updated_at_raw == "2026-10-01T09:24:06+01:00"
    assert item.updated_at_raw == "2026-10-01T09:24:44+01:00"
    assert item.updated_at_raw != item.public_updated_at_raw


def test_d_publishing_scheduled_at_preserved_only_if_present() -> None:
    item_absent = parse_content_api_item(_content_json(publishing_scheduled_at=None))
    assert item_absent.publishing_scheduled_at_raw is None

    item_present = parse_content_api_item(
        _content_json(publishing_scheduled_at="2026-10-01T09:24:06+01:00")
    )
    assert item_present.publishing_scheduled_at_raw == "2026-10-01T09:24:06+01:00"


def test_malformed_timestamp_preserved_raw_but_not_normalized() -> None:
    item = parse_content_api_item(_content_json(first_published_at="not-a-timestamp"))
    assert item.first_published_at_raw == "not-a-timestamp"


# --- Change-history test matrix (Section 77) --------------------------------


def test_zero_change_history_entries() -> None:
    item = parse_content_api_item(_content_json(change_history=[]))
    assert item.change_history == ()


def test_one_change_history_entry() -> None:
    item = parse_content_api_item(
        _content_json(
            change_history=[
                {"note": "First published.", "public_timestamp": "2026-10-01T08:24:06Z"}
            ]
        )
    )
    assert len(item.change_history) == 1
    assert item.change_history[0].note == "First published."
    assert item.change_history[0].public_timestamp_raw == "2026-10-01T08:24:06Z"


def test_several_change_history_entries_deterministic_order() -> None:
    item = parse_content_api_item(
        _content_json(
            change_history=[
                {
                    "note": "Updated with new information.",
                    "public_timestamp": "2026-09-07T11:42:27Z",
                },
                {"note": "First published.", "public_timestamp": "2025-06-19T09:26:00Z"},
            ]
        )
    )
    assert len(item.change_history) == 2
    assert item.change_history[0].note == "Updated with new information."
    assert item.change_history[1].note == "First published."


def test_malformed_change_history_entry_timestamp_preserved_raw() -> None:
    item = parse_content_api_item(
        _content_json(change_history=[{"note": "Odd entry.", "public_timestamp": "garbage"}])
    )
    assert item.change_history[0].public_timestamp_raw == "garbage"


# --- Withdrawal mapping ------------------------------------------------------


def test_empty_withdrawn_notice_is_active() -> None:
    item = parse_content_api_item(_content_json(withdrawn_notice={}))
    assert item.withdrawn is False


def test_populated_withdrawn_notice_is_withdrawn() -> None:
    item = parse_content_api_item(
        _content_json(
            withdrawn_notice={
                "explanation": "This page is withdrawn because it is no longer current.",
                "withdrawn_at": "2026-10-02T10:00:00+01:00",
            }
        )
    )
    assert item.withdrawn is True
    assert item.withdrawn_explanation == "This page is withdrawn because it is no longer current."
    assert item.withdrawn_at_raw == "2026-10-02T10:00:00+01:00"


# --- GovUkHmtSource: fetch_content_item mapping -----------------------------


def _source_returning(
    status_code: int, text: str, clock: UtcTimestamp = _RETRIEVED_AT
) -> GovUkHmtSource:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=text, headers={"content-type": "application/json"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://www.gov.uk"
    )
    return GovUkHmtSource(client=client, clock=lambda: clock, pace_seconds=0.0)


@pytest.mark.asyncio
async def test_source_key_and_channel() -> None:
    source = _source_returning(200, _content_json())
    outcome = await source.fetch_content_item("/government/news/example-item")
    await source.aclose()

    assert outcome.source_channel == CHANNEL == "hmt_news_and_communications"
    assert len(outcome.observations) == 1
    observation = outcome.observations[0]
    assert observation.source_key == SOURCE_KEY == "GOVUK_HMT"


@pytest.mark.asyncio
async def test_content_id_is_external_identity() -> None:
    source = _source_returning(200, _content_json(content_id="abc-123"))
    outcome = await source.fetch_content_item("/government/news/x")
    await source.aclose()

    assert outcome.observations[0].external_item_id == "abc-123"


@pytest.mark.asyncio
async def test_canonical_url_built_from_base_path_not_discovery_path() -> None:
    source = _source_returning(200, _content_json(base_path="/government/news/canonical-slug"))
    outcome = await source.fetch_content_item("/government/news/different-discovery-path")
    await source.aclose()

    assert (
        outcome.observations[0].canonical_url == "https://www.gov.uk/government/news/canonical-slug"
    )


@pytest.mark.asyncio
async def test_e_observed_at_is_retrieved_at_never_source_timestamp() -> None:
    source = _source_returning(200, _content_json(first_published_at="2026-10-01T09:24:06+01:00"))
    outcome = await source.fetch_content_item("/government/news/x")
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.observed_at == _RETRIEVED_AT
    assert observation.source_published_at is not None
    assert observation.observed_at.value != observation.source_published_at.value


@pytest.mark.asyncio
async def test_first_published_at_maps_to_source_published_at() -> None:
    source = _source_returning(200, _content_json(first_published_at="2026-10-01T09:24:06+01:00"))
    outcome = await source.fetch_content_item("/government/news/x")
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_published_at == UtcTimestamp(
        datetime(2026, 10, 1, 8, 24, 6, tzinfo=UTC)
    )
    provenance_fields = {p.field_name: p for p in observation.source_timestamp_provenance}
    assert provenance_fields["first_published_at"].raw_value == "2026-10-01T09:24:06+01:00"


@pytest.mark.asyncio
async def test_public_updated_at_maps_to_source_updated_at_not_updated_at() -> None:
    source = _source_returning(
        200,
        _content_json(
            public_updated_at="2026-10-01T09:24:06+01:00",
            updated_at="2026-10-01T09:24:44+01:00",
        ),
    )
    outcome = await source.fetch_content_item("/government/news/x")
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_updated_at == UtcTimestamp(
        datetime(2026, 10, 1, 8, 24, 6, tzinfo=UTC)
    )
    provenance_fields = {p.field_name: p for p in observation.source_timestamp_provenance}
    assert provenance_fields["updated_at"].raw_value == "2026-10-01T09:24:44+01:00"
    assert provenance_fields["public_updated_at"].raw_value == "2026-10-01T09:24:06+01:00"
    # updated_at is preserved as its OWN provenance entry with its OWN
    # raw value, never collapsed into / substituted for public_updated_at.
    assert provenance_fields["updated_at"].normalized_at != observation.source_updated_at


@pytest.mark.asyncio
async def test_change_history_maps_to_update_kind_revision_facts() -> None:
    source = _source_returning(
        200,
        _content_json(
            change_history=[
                {"note": "Updated with new info.", "public_timestamp": "2026-09-07T11:42:27Z"},
                {"note": "First published.", "public_timestamp": "2025-06-19T09:26:00Z"},
            ]
        ),
    )
    outcome = await source.fetch_content_item("/government/news/x")
    await source.aclose()

    revision_metadata = outcome.observations[0].source_revision_metadata
    assert len(revision_metadata) == 2
    assert all(fact.kind is NewsSourceRevisionKind.UPDATE for fact in revision_metadata)
    assert revision_metadata[0].note == "Updated with new info."
    assert revision_metadata[1].note == "First published."


@pytest.mark.asyncio
async def test_withdrawn_notice_maps_to_withdrawn_status_and_revision_fact() -> None:
    source = _source_returning(
        200,
        _content_json(
            withdrawn_notice={
                "explanation": "No longer current.",
                "withdrawn_at": "2026-10-02T10:00:00+01:00",
            }
        ),
    )
    outcome = await source.fetch_content_item("/government/news/x")
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_status == NewsSourceStatus.WITHDRAWN
    assert observation.evidence_disposition == NewsEvidenceDisposition.EVIDENCE_ELIGIBLE
    withdrawal_facts = [
        f
        for f in observation.source_revision_metadata
        if f.kind is NewsSourceRevisionKind.WITHDRAWAL
    ]
    assert len(withdrawal_facts) == 1
    assert withdrawal_facts[0].note == "No longer current."


@pytest.mark.asyncio
async def test_active_item_status_and_disposition() -> None:
    source = _source_returning(200, _content_json())
    outcome = await source.fetch_content_item("/government/news/x")
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_status == NewsSourceStatus.ACTIVE
    assert observation.evidence_disposition == NewsEvidenceDisposition.EVIDENCE_ELIGIBLE
    assert observation.quarantine_reason is None
    assert observation.observation_mode == NewsObservationMode.PROSPECTIVE
    assert observation.authors == ()


@pytest.mark.asyncio
async def test_non_hm_treasury_item_is_invalid_not_ingested() -> None:
    source = _source_returning(200, _content_json(organisations=[_NON_HMT_ORG]))
    outcome = await source.fetch_content_item("/government/news/x")
    await source.aclose()

    assert outcome.observations == ()
    assert outcome.items_invalid == 1
    assert "not HM-Treasury-associated" in outcome.invalid_reasons[0]


@pytest.mark.asyncio
async def test_co_published_item_with_hmt_among_organisations_is_valid() -> None:
    source = _source_returning(200, _content_json(organisations=[_NON_HMT_ORG, _HMT_ORG]))
    outcome = await source.fetch_content_item("/government/news/x")
    await source.aclose()

    assert len(outcome.observations) == 1
    assert outcome.items_invalid == 0


@pytest.mark.asyncio
async def test_404_raises_unavailable() -> None:
    source = _source_returning(404, "")
    with pytest.raises(NewsSourceUnavailableError):
        await source.fetch_content_item("/government/news/gone")
    await source.aclose()


@pytest.mark.asyncio
async def test_410_raises_unavailable() -> None:
    source = _source_returning(410, "")
    with pytest.raises(NewsSourceUnavailableError):
        await source.fetch_content_item("/government/news/gone")
    await source.aclose()


@pytest.mark.asyncio
async def test_malformed_json_response_raises_unavailable() -> None:
    source = _source_returning(200, "{not valid json")
    with pytest.raises(NewsSourceUnavailableError):
        await source.fetch_content_item("/government/news/x")
    await source.aclose()


@pytest.mark.asyncio
async def test_html_200_response_raises_unavailable() -> None:
    source = _source_returning(200, "<html><body>blocked</body></html>")
    with pytest.raises(NewsSourceUnavailableError):
        await source.fetch_content_item("/government/news/x")
    await source.aclose()


@pytest.mark.asyncio
async def test_discover_current_paths_dedupes_and_validates() -> None:
    atom = (
        "<feed xmlns='http://www.w3.org/2005/Atom'><title>t</title>"
        "<entry><id>tag:a</id><updated>2026-10-01T09:00:00+01:00</updated>"
        "<link rel='alternate' href='https://www.gov.uk/government/news/a'/>"
        "<title>A</title></entry>"
        "</feed>"
    )
    source = _source_returning(200, atom)
    paths = await source.discover_current_paths()
    await source.aclose()
    assert paths == ("/government/news/a",)


@pytest.mark.asyncio
async def test_malformed_discovery_feed_raises_unavailable() -> None:
    source = _source_returning(200, "<html><body>blocked</body></html>")
    with pytest.raises(NewsSourceUnavailableError):
        await source.discover_current_paths()
    await source.aclose()


# --- Rate pacing (Section 19/79) --------------------------------------------


@pytest.mark.asyncio
async def test_pacing_sleeps_the_remaining_time_between_requests() -> None:
    clock_values = iter([0.0, 0.03, 0.03, 0.2])
    monotonic_calls: list[float] = []

    def fake_monotonic() -> float:
        value = next(clock_values)
        monotonic_calls.append(value)
        return value

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=_content_json(), headers={"content-type": "application/json"}
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://www.gov.uk"
    )
    source = GovUkHmtSource(
        client=client,
        clock=lambda: _RETRIEVED_AT,
        pace_seconds=0.15,
        sleep=fake_sleep,
        monotonic=fake_monotonic,
    )

    await source.fetch_content_item("/government/news/a")
    await source.fetch_content_item("/government/news/b")
    await source.aclose()

    # First call: no prior request, no sleep. Second call: only 0.03s
    # elapsed since the first (monotonic 0.0 -> 0.03), so it must wait
    # the REMAINING 0.12s to respect the configured 0.15s pace.
    assert sleeps == [0.12]


@pytest.mark.asyncio
async def test_pacing_does_not_sleep_if_enough_time_already_elapsed() -> None:
    clock_values = iter([0.0, 1.0])

    def fake_monotonic() -> float:
        return next(clock_values)

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=_content_json(), headers={"content-type": "application/json"}
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://www.gov.uk"
    )
    source = GovUkHmtSource(
        client=client,
        clock=lambda: _RETRIEVED_AT,
        pace_seconds=0.15,
        sleep=fake_sleep,
        monotonic=fake_monotonic,
    )

    await source.fetch_content_item("/government/news/a")
    await source.fetch_content_item("/government/news/b")
    await source.aclose()

    assert sleeps == []

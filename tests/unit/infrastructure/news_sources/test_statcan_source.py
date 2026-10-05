"""FX-57E: deterministic fixture tests for `StatCanSource` against a
mocked HTTP transport -- no real network access (see
tests/integration/test_statcan_source_live.py for live-feed
validation)."""

from datetime import UTC, datetime

import httpx
import pytest

from forex_agent.application.ports.news_source import NewsSourceUnavailableError
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.news_sources.statcan_source import (
    SOURCE_KEY,
    STATCAN_FEEDS,
    StatCanSource,
)

_HOST = "https://www150.statcan.gc.ca"
_RETRIEVED_AT = UtcTimestamp(datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC))


def _feed_xml(
    *,
    entry_id: str = "https://www.statcan.gc.ca/daily-quotidien/261002/dq261002b-eng.htm",
    title: str = "Example item",
    updated: str = "2026-10-02T08:30:00-04:00",
    summary: str | None = "Example summary.",
) -> str:
    summary_xml = (
        f"<summary type='xhtml'><div xmlns='http://www.w3.org/1999/xhtml'>{summary}</div></summary>"
        if summary is not None
        else ""
    )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<feed xmlns='http://www.w3.org/2005/Atom'>"
        "<title>Statistics Canada, The Daily: Prices and price indexes</title>"
        "<entry>"
        f"<id>{entry_id}</id>"
        f"<title type='xhtml'><div xmlns='http://www.w3.org/1999/xhtml'>{title}</div></title>"
        f"<link href='{entry_id}'></link>"
        f"<updated>{updated}</updated>"
        f"{summary_xml}"
        "</entry>"
        "</feed>"
    )


def _source_returning(
    status_code: int,
    text: str,
    *,
    clock: UtcTimestamp = _RETRIEVED_AT,
    pace_seconds: float = 0.0,
) -> StatCanSource:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code, text=text, headers={"content-type": "application/atom+xml"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=_HOST)
    return StatCanSource(client=client, clock=lambda: clock, crawl_delay_seconds=pace_seconds)


# --- feed definitions --------------------------------------------------------


def test_exactly_four_feeds_configured() -> None:
    assert len(STATCAN_FEEDS) == 4
    assert {f.channel for f in STATCAN_FEEDS} == {
        "statcan_prices",
        "statcan_labour",
        "statcan_economic_accounts",
        "statcan_international_trade",
    }


def test_feed_paths_match_exact_adopted_endpoints() -> None:
    by_channel = {f.channel: f.path for f in STATCAN_FEEDS}
    assert by_channel["statcan_prices"] == "/n1/rss/dai-quo/18-eng.atom"
    assert by_channel["statcan_labour"] == "/n1/rss/dai-quo/14-eng.atom"
    assert by_channel["statcan_economic_accounts"] == "/n1/rss/dai-quo/36-eng.atom"
    assert by_channel["statcan_international_trade"] == "/n1/rss/dai-quo/12-eng.atom"


def test_all_subjects_feed_is_never_configured() -> None:
    assert all("0-eng.atom" not in f.path for f in STATCAN_FEEDS)


# --- field mapping -----------------------------------------------------------


@pytest.mark.asyncio
async def test_source_key_and_channel() -> None:
    feed = STATCAN_FEEDS[0]
    source = _source_returning(200, _feed_xml())
    outcome = await source.fetch_feed(feed)
    await source.aclose()

    assert outcome.source_channel == feed.channel
    assert len(outcome.observations) == 1
    observation = outcome.observations[0]
    assert observation.source_key == SOURCE_KEY == "STATCAN"
    assert observation.source_channel == feed.channel


@pytest.mark.asyncio
async def test_entry_id_is_external_identity() -> None:
    feed = STATCAN_FEEDS[0]
    source = _source_returning(
        200,
        _feed_xml(entry_id="https://www.statcan.gc.ca/daily-quotidien/261002/dq261002z-eng.htm"),
    )
    outcome = await source.fetch_feed(feed)
    await source.aclose()

    assert (
        outcome.observations[0].external_item_id
        == "https://www.statcan.gc.ca/daily-quotidien/261002/dq261002z-eng.htm"
    )


@pytest.mark.asyncio
async def test_canonical_url_separate_fact_from_identity() -> None:
    feed = STATCAN_FEEDS[0]
    entry_id = "https://www.statcan.gc.ca/daily-quotidien/261002/dq261002b-eng.htm"
    source = _source_returning(200, _feed_xml(entry_id=entry_id))
    outcome = await source.fetch_feed(feed)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.canonical_url == entry_id
    # Identity and canonical URL happen to coincide for StatCan, but
    # are mapped from genuinely separate parsed fields.
    assert observation.external_item_id == observation.canonical_url


@pytest.mark.asyncio
async def test_content_type_is_constant_daily_release_for_every_feed() -> None:
    # Section 31: content_type never varies by channel for StatCan --
    # the channel itself already preserves the subject taxonomy. This
    # constancy is exactly what lets a genuine cross-subject release
    # merge cleanly as additional provenance rather than conflicting.
    for feed in STATCAN_FEEDS:
        source = _source_returning(200, _feed_xml())
        outcome = await source.fetch_feed(feed)
        await source.aclose()
        assert outcome.observations[0].source_content_type == "daily_release"


@pytest.mark.asyncio
async def test_language_is_en() -> None:
    feed = STATCAN_FEEDS[0]
    source = _source_returning(200, _feed_xml())
    outcome = await source.fetch_feed(feed)
    await source.aclose()
    assert outcome.observations[0].language == "en"


@pytest.mark.asyncio
async def test_authors_always_empty() -> None:
    feed = STATCAN_FEEDS[0]
    source = _source_returning(200, _feed_xml())
    outcome = await source.fetch_feed(feed)
    await source.aclose()
    assert outcome.observations[0].authors == ()


@pytest.mark.asyncio
async def test_body_text_always_none_no_content_field_exists() -> None:
    feed = STATCAN_FEEDS[0]
    source = _source_returning(200, _feed_xml())
    outcome = await source.fetch_feed(feed)
    await source.aclose()
    assert outcome.observations[0].body_text is None


@pytest.mark.asyncio
async def test_summary_mapped_when_present() -> None:
    feed = STATCAN_FEEDS[0]
    source = _source_returning(200, _feed_xml(summary="Real summary text."))
    outcome = await source.fetch_feed(feed)
    await source.aclose()
    assert outcome.observations[0].summary == "Real summary text."


@pytest.mark.asyncio
async def test_summary_absent_is_none() -> None:
    feed = STATCAN_FEEDS[0]
    source = _source_returning(200, _feed_xml(summary=None))
    outcome = await source.fetch_feed(feed)
    await source.aclose()
    assert outcome.observations[0].summary is None


@pytest.mark.asyncio
async def test_source_status_always_active() -> None:
    feed = STATCAN_FEEDS[0]
    source = _source_returning(200, _feed_xml())
    outcome = await source.fetch_feed(feed)
    await source.aclose()
    assert outcome.observations[0].source_status is NewsSourceStatus.ACTIVE


@pytest.mark.asyncio
async def test_no_revision_metadata_fabricated() -> None:
    feed = STATCAN_FEEDS[0]
    source = _source_returning(200, _feed_xml())
    outcome = await source.fetch_feed(feed)
    await source.aclose()
    assert outcome.observations[0].source_revision_metadata == ()


# --- timestamp semantics (Section 17/19/20/66) ------------------------------


@pytest.mark.asyncio
async def test_e_observed_at_is_retrieved_at_never_source_timestamp() -> None:
    feed = STATCAN_FEEDS[0]
    source = _source_returning(200, _feed_xml(updated="2026-10-02T08:30:00-04:00"))
    outcome = await source.fetch_feed(feed)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.observed_at == _RETRIEVED_AT
    assert observation.source_published_at is not None
    assert observation.observed_at.value != observation.source_published_at.value


@pytest.mark.asyncio
async def test_updated_maps_to_source_published_at_never_source_updated_at() -> None:
    feed = STATCAN_FEEDS[0]
    source = _source_returning(200, _feed_xml(updated="2026-10-02T08:30:00-04:00"))
    outcome = await source.fetch_feed(feed)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_published_at == UtcTimestamp(
        datetime(2026, 10, 2, 12, 30, 0, tzinfo=UTC)
    )
    assert observation.source_updated_at is None
    provenance = observation.source_timestamp_provenance
    assert len(provenance) == 1
    assert provenance[0].field_name == "updated"
    assert provenance[0].raw_value == "2026-10-02T08:30:00-04:00"


@pytest.mark.asyncio
async def test_minus_05_00_offset_handled_numerically_no_toronto_hardcoding() -> None:
    # Section 19: a valid -05:00 (EST/winter) offset must normalize
    # correctly via ordinary ISO-8601 parsing, with no special-cased
    # Toronto-local reinterpretation (that is the Bank of Canada
    # story's own defect; StatCan does not inherit it).
    feed = STATCAN_FEEDS[0]
    source = _source_returning(200, _feed_xml(updated="2026-01-15T08:30:00-05:00"))
    outcome = await source.fetch_feed(feed)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_published_at == UtcTimestamp(
        datetime(2026, 1, 15, 13, 30, 0, tzinfo=UTC)
    )


@pytest.mark.asyncio
async def test_malformed_updated_preserves_raw_but_normalizes_to_none() -> None:
    feed = STATCAN_FEEDS[0]
    source = _source_returning(200, _feed_xml(updated="not-a-timestamp"))
    outcome = await source.fetch_feed(feed)
    await source.aclose()

    observation = outcome.observations[0]
    assert observation.source_published_at is None
    provenance = observation.source_timestamp_provenance
    assert provenance[0].raw_value == "not-a-timestamp"
    assert provenance[0].normalized_at is None


# --- sequence-id fixture (Section 67) ---------------------------------------


@pytest.mark.asyncio
async def test_sequence_letter_entries_are_distinct_identities_same_timestamp() -> None:
    feed = STATCAN_FEEDS[0]
    source_a = _source_returning(
        200,
        _feed_xml(
            entry_id="https://www.statcan.gc.ca/daily-quotidien/261005/dq261005a-eng.htm",
            updated="2026-10-05T08:30:00-04:00",
        ),
    )
    outcome_a = await source_a.fetch_feed(feed)
    await source_a.aclose()

    source_g = _source_returning(
        200,
        _feed_xml(
            entry_id="https://www.statcan.gc.ca/daily-quotidien/261005/dq261005g-eng.htm",
            updated="2026-10-05T08:30:00-04:00",
        ),
    )
    outcome_g = await source_g.fetch_feed(feed)
    await source_g.aclose()

    obs_a = outcome_a.observations[0]
    obs_g = outcome_g.observations[0]
    assert obs_a.external_item_id != obs_g.external_item_id
    # The sequence letter never fabricates distinct timing -- both
    # share the identical source-side publication instant.
    assert obs_a.source_published_at == obs_g.source_published_at
    assert obs_a.observed_at == obs_g.observed_at  # same injected clock


# --- source-level failures ---------------------------------------------------


@pytest.mark.asyncio
async def test_404_raises_unavailable() -> None:
    feed = STATCAN_FEEDS[0]
    source = _source_returning(404, "")
    with pytest.raises(NewsSourceUnavailableError):
        await source.fetch_feed(feed)
    await source.aclose()


@pytest.mark.asyncio
async def test_malformed_xml_raises_unavailable() -> None:
    feed = STATCAN_FEEDS[0]
    source = _source_returning(200, "<feed><entry>unterminated")
    with pytest.raises(NewsSourceUnavailableError):
        await source.fetch_feed(feed)
    await source.aclose()


@pytest.mark.asyncio
async def test_html_200_masquerading_raises_unavailable() -> None:
    feed = STATCAN_FEEDS[0]
    source = _source_returning(200, "<html><body>blocked</body></html>")
    with pytest.raises(NewsSourceUnavailableError):
        await source.fetch_feed(feed)
    await source.aclose()


@pytest.mark.asyncio
async def test_items_invalid_passthrough_from_parser() -> None:
    feed = STATCAN_FEEDS[0]
    atom = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<feed xmlns='http://www.w3.org/2005/Atom'><title>t</title>"
        "<entry><id>https://www.statcan.gc.ca/cgi-bin/IPS/display?cat_num=18-001-X</id>"
        "<title type='xhtml'><div xmlns='http://www.w3.org/1999/xhtml'>Catalogue</div></title>"
        "<link href='https://www.statcan.gc.ca/cgi-bin/IPS/display?cat_num=18-001-X'></link>"
        "<updated>2026-10-02T08:30:00-04:00</updated></entry>"
        "</feed>"
    )
    source = _source_returning(200, atom)
    outcome = await source.fetch_feed(feed)
    await source.aclose()

    assert outcome.observations == ()
    assert outcome.items_invalid == 1
    assert (
        "known recurring StatCan Product/Study catalogue-reference shape"
        in (outcome.invalid_reasons[0])
    )


# --- robots/rate pacing matrix (Section 19/48/79) ---------------------------


@pytest.mark.asyncio
async def test_a_first_request_proceeds_immediately() -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    clock_values = iter([0.0])

    def fake_monotonic() -> float:
        return next(clock_values)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=_feed_xml(), headers={"content-type": "application/atom+xml"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=_HOST)
    source = StatCanSource(
        client=client,
        clock=lambda: _RETRIEVED_AT,
        crawl_delay_seconds=2.0,
        sleep=fake_sleep,
        monotonic=fake_monotonic,
    )
    await source.fetch_feed(STATCAN_FEEDS[0])
    await source.aclose()

    assert sleeps == []


@pytest.mark.asyncio
async def test_b_second_top_level_feed_request_is_delayed_sufficiently() -> None:
    clock_values = iter([0.0, 0.3, 0.3])
    sleeps: list[float] = []

    def fake_monotonic() -> float:
        return next(clock_values)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=_feed_xml(), headers={"content-type": "application/atom+xml"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=_HOST)
    source = StatCanSource(
        client=client,
        clock=lambda: _RETRIEVED_AT,
        crawl_delay_seconds=2.0,
        sleep=fake_sleep,
        monotonic=fake_monotonic,
    )
    await source.fetch_feed(STATCAN_FEEDS[0])
    await source.fetch_feed(STATCAN_FEEDS[1])
    await source.aclose()

    assert sleeps == [1.7]


@pytest.mark.asyncio
async def test_c_retry_attempt_is_also_delayed_sufficiently() -> None:
    # Section 22/23/48.C: a retry attempt inside fetch_text's own
    # retry loop must ALSO respect the crawl delay, not just the
    # outer per-feed call.
    clock_values = iter([0.0, 0.1, 0.1])
    sleeps: list[float] = []

    def fake_monotonic() -> float:
        return next(clock_values)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 2:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(
            200, text=_feed_xml(), headers={"content-type": "application/atom+xml"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=_HOST)
    source = StatCanSource(
        client=client,
        clock=lambda: _RETRIEVED_AT,
        crawl_delay_seconds=2.0,
        sleep=fake_sleep,
        monotonic=fake_monotonic,
    )
    outcome = await source.fetch_feed(STATCAN_FEEDS[0])
    await source.aclose()

    assert attempts["count"] == 2
    assert len(outcome.observations) == 1
    # fetch_text's own 5xx backoff (2.0s) AND the crawl-delay pacer's
    # own remaining-time sleep before attempt 2 (1.9s at t=0.1) both
    # go through the SAME injected sleep -- both honored, zero real
    # wall-clock wait.
    assert sleeps == [2.0, 1.9]


@pytest.mark.asyncio
async def test_e_pacing_uses_injected_clock_no_real_wall_clock_wait() -> None:
    import time as time_module

    started = time_module.monotonic()
    clock_values = iter([0.0, 0.0, 0.0])

    def fake_monotonic() -> float:
        return next(clock_values)

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=_feed_xml(), headers={"content-type": "application/atom+xml"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=_HOST)
    source = StatCanSource(
        client=client,
        clock=lambda: _RETRIEVED_AT,
        crawl_delay_seconds=2.0,
        sleep=fake_sleep,
        monotonic=fake_monotonic,
    )
    await source.fetch_feed(STATCAN_FEEDS[0])
    await source.fetch_feed(STATCAN_FEEDS[1])
    await source.aclose()

    elapsed = time_module.monotonic() - started
    assert elapsed < 1.0  # never actually waited 2 real seconds
    assert sleep_calls == [2.0]

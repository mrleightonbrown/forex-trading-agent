"""FX-57F: end-to-end deterministic test exercising the FULL chain --
a fixture BoC RSS 1.0/RDF response -> `BocSource` ->
`NormalizedNewsObservation` -> `IngestNewsSourceOnce` ->
`RecordNewsObservation` -> `SqlAlchemyNewsRepository` -> live
Postgres -- mirrors FX-57A/B/C/D/E's own equivalent suites.

Requires a live Postgres with migrations applied -- run
`docker compose up -d db && alembic upgrade head` first. Uses the REAL
`source_key="BOC"` -- cleanup therefore filters by a distinguishing,
never-real `external_item_id` prefix, never by `source_key`, so
genuine BoC rows ingested by `scripts/ingest_boc_news.py` against this
same database are never at risk of being deleted by this suite.

**One genuine channel, by construction (Section 6)**: unlike StatCan's
own genuine cross-channel merge finding, BoC is adopted as exactly one
channel -- every vintage here is expected to carry
`observed_source_channels == ("boc_press_releases",)` throughout; the
multi-channel machinery (FX-57E0/ADR 0006) is exercised as a no-op,
never special-cased away, exactly as the story's own spec requires.

**dc:date remediation worked examples (Sections 61/62/63/64)**: the
PIT tests below cover both a summer (EDT) and a winter (EST) malformed
`dc:date` -- proving `ZoneInfo`-driven DST resolution end-to-end
through the full persisted chain, not just the remediation helper's
own unit tests. `test_raw_dc_date_only_change_creates_a_second_vintage`
covers Section 64: a second poll where ONLY the raw `dc:date` string
changes (not the headline/summary/link) must still be treated as a
genuine content revision, producing a new vintage.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.ports.news_source import (
    NewsSourceChannelFetcher,
    NewsSourceFetchOutcome,
)
from forex_agent.application.use_cases.ingest_news_source_once import IngestNewsSourceOnce
from forex_agent.application.use_cases.record_news_observation import RecordNewsObservation
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.news_sources.boc_source import CHANNEL, SOURCE_KEY, BocSource

_HOST = "https://www.bankofcanada.ca"
_TEST_ID_PREFIX = f"{_HOST}/9999/"


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        mapping_rows = (
            (
                await cleanup_session.execute(
                    delete(NewsSourceMappingRow)
                    .where(
                        NewsSourceMappingRow.source_key == SOURCE_KEY,
                        NewsSourceMappingRow.external_item_id.startswith(_TEST_ID_PREFIX),
                    )
                    .returning(NewsSourceMappingRow.news_item_key)
                )
            )
            .scalars()
            .all()
        )
        for news_item_key in mapping_rows:
            await cleanup_session.execute(
                delete(NewsItemVintageRow).where(NewsItemVintageRow.news_item_key == news_item_key)
            )
            await cleanup_session.execute(
                delete(NewsItemRow).where(NewsItemRow.news_item_key == news_item_key)
            )
        await cleanup_session.commit()


def _entry_id(suffix: str) -> str:
    return f"{_TEST_ID_PREFIX}{suffix}/"


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
    suffix: str,
    title: str = "Example press release",
    dc_date: str | None = "2026-10-05T09:47:00+00:00",
    summary: str = "Example summary.",
) -> str:
    entry_id = _entry_id(suffix)
    parts = [f"<title>{title}</title>", f"<link>{entry_id}</link>"]
    if dc_date is not None:
        parts.append(f"<dc:date>{dc_date}</dc:date>")
    parts.append(f"<description>{summary}</description>")
    return f"<item rdf:about='{entry_id}'>{''.join(parts)}</item>"


def _fetcher(
    body: str, retrieved_at: UtcTimestamp, *, status_code: int = 200
) -> NewsSourceChannelFetcher:
    async def _fetch() -> NewsSourceFetchOutcome:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code, text=body, headers={"content-type": "application/rdf+xml"}
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=_HOST)
        source = BocSource(client=client, clock=lambda: retrieved_at)
        try:
            return await source.fetch_press_releases()
        finally:
            await source.aclose()

    return _fetch


def _ts(hour: int, minute: int = 0, second: int = 0, day: int = 5) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 10, day, hour % 24, minute, second, tzinfo=UTC))


@pytest.mark.asyncio
async def test_single_poll_persists_item_and_first_vintage(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    body = _feed_xml(_item_xml("single-poll", title="Bank of Canada increases its policy rate"))
    result = await ingest((_fetcher(body, _ts(10)),))
    await session.commit()

    assert result.created == 1
    assert result.items_processed == 1
    assert result.source_channels == (CHANNEL,)

    identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("single-poll"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = await repository.list_vintages(item.news_item_key)
    assert len(vintages) == 1
    vintage = vintages[0]
    assert vintage.headline == "Bank of Canada increases its policy rate"
    assert vintage.availability == _ts(10)
    assert vintage.source_channel == CHANNEL
    assert vintage.observed_source_channels == (CHANNEL,)
    assert vintage.source_content_type == "press_release"
    assert vintage.language == "en"
    assert vintage.authors == ()
    assert vintage.body_text is None
    assert vintage.summary == "Example summary."
    assert vintage.canonical_url == _entry_id("single-poll")
    assert vintage.source_updated_at is None
    assert len(vintage.source_timestamp_provenance) == 1
    assert vintage.source_timestamp_provenance[0].field_name == "dc:date"
    # Section 10: identity is NOT availability's own observation time.
    assert vintage.availability.value != vintage.source_published_at.value  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_repeated_identical_poll_creates_no_new_vintage(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    body = _feed_xml(_item_xml("idempotent"))
    first = await ingest((_fetcher(body, _ts(11)),))
    second = await ingest((_fetcher(body, _ts(12)),))
    await session.commit()

    assert first.created == 1
    assert second.created == 0
    assert second.unchanged == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("idempotent"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    assert len(await repository.list_vintages(item.news_item_key)) == 1


@pytest.mark.asyncio
async def test_title_change_creates_a_second_vintage(session: AsyncSession) -> None:
    # Section 63: same-ID content update.
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    first_body = _feed_xml(_item_xml("revised", title="Original title"))
    second_body = _feed_xml(_item_xml("revised", title="Updated title"))

    first = await ingest((_fetcher(first_body, _ts(12)),))
    second = await ingest((_fetcher(second_body, _ts(13)),))
    await session.commit()

    assert first.created == 1
    assert second.revisions_added == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("revised"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = sorted(
        await repository.list_vintages(item.news_item_key), key=lambda v: v.revision_sequence
    )
    assert len(vintages) == 2
    assert vintages[0].headline == "Original title"
    assert vintages[1].headline == "Updated title"


@pytest.mark.asyncio
async def test_raw_dc_date_only_change_creates_a_second_vintage(session: AsyncSession) -> None:
    # Section 64: ONLY the raw dc:date string changes between polls --
    # must still be treated as a genuine content revision.
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    first_body = _feed_xml(_item_xml("timestamp-only-change", dc_date="2026-10-05T09:47:00+00:00"))
    second_body = _feed_xml(_item_xml("timestamp-only-change", dc_date="2026-10-05T09:52:00+00:00"))

    first = await ingest((_fetcher(first_body, _ts(14)),))
    second = await ingest((_fetcher(second_body, _ts(15)),))
    await session.commit()

    assert first.created == 1
    assert second.revisions_added == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("timestamp-only-change"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = sorted(
        await repository.list_vintages(item.news_item_key), key=lambda v: v.revision_sequence
    )
    assert len(vintages) == 2
    assert vintages[0].source_timestamp_provenance[0].raw_value == "2026-10-05T09:47:00+00:00"
    assert vintages[1].source_timestamp_provenance[0].raw_value == "2026-10-05T09:52:00+00:00"


@pytest.mark.asyncio
async def test_two_different_ids_same_headline_remain_distinct_items(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    body = _feed_xml(
        _item_xml("twin-a", title="Same headline text"),
        _item_xml("twin-b", title="Same headline text"),
    )
    result = await ingest((_fetcher(body, _ts(16)),))
    await session.commit()

    assert result.created == 2

    item_a = await repository.get_item_by_source_identity(
        NewsSourceIdentity(SOURCE_KEY, _entry_id("twin-a"))
    )
    item_b = await repository.get_item_by_source_identity(
        NewsSourceIdentity(SOURCE_KEY, _entry_id("twin-b"))
    )
    assert item_a is not None
    assert item_b is not None
    assert item_a.news_item_key != item_b.news_item_key


@pytest.mark.asyncio
async def test_old_source_dated_first_poll_item_remains_prospective(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    body = _feed_xml(_item_xml("old-release", dc_date="2026-01-28T09:47:00+00:00"))
    await ingest((_fetcher(body, _ts(17)),))
    await session.commit()

    identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("old-release"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    assert item.first_observation_mode is NewsObservationMode.PROSPECTIVE
    assert item.first_seen_at == _ts(17)
    vintages = await repository.list_vintages(item.news_item_key)
    assert vintages[0].observation_mode is NewsObservationMode.PROSPECTIVE


@pytest.mark.asyncio
async def test_one_malformed_response_writes_zero_news_evidence(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    result = await ingest((_fetcher("<html><body>blocked</body></html>", _ts(18)),))
    await session.commit()

    assert result.created == 0
    assert result.items_processed == 0
    assert len(result.errors) == 1


@pytest.mark.asyncio
async def test_dst_ambiguous_dc_date_item_persists_with_no_source_published_at(
    session: AsyncSession,
) -> None:
    # Section 29: a DST-ambiguous raw dc:date must persist cleanly
    # (no crash, no guessed value) -- source_published_at stays None,
    # the raw string is preserved, availability is unaffected.
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    body = _feed_xml(_item_xml("dst-ambiguous", dc_date="2026-11-01T01:30:00+00:00"))
    result = await ingest((_fetcher(body, _ts(19)),))
    await session.commit()

    assert result.created == 1
    identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("dst-ambiguous"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintage = (await repository.list_vintages(item.news_item_key))[0]
    assert vintage.source_published_at is None
    assert vintage.source_timestamp_provenance[0].raw_value == "2026-11-01T01:30:00+00:00"
    assert vintage.availability == _ts(19)


# --- PIT worked examples, both DST seasons (Sections 61/62) ----------------


@pytest.mark.asyncio
async def test_pit_summer_edt_query_between_source_published_at_and_fta_retrieval(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    # Malformed raw dc:date 09:47:53+00:00 remediates to 13:47:53 UTC
    # (09:47:53 EDT). FTA's own retrieval lands a few seconds later.
    t0 = UtcTimestamp(datetime(2026, 9, 2, 13, 47, 53, tzinfo=UTC))
    t1 = UtcTimestamp(datetime(2026, 9, 2, 13, 48, 1, tzinfo=UTC))

    body = _feed_xml(_item_xml("pit-summer", dc_date="2026-09-02T09:47:53+00:00"))
    await ingest((_fetcher(body, t1),))
    await session.commit()

    identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("pit-summer"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None

    between_t0_and_t1 = UtcTimestamp(datetime(2026, 9, 2, 13, 47, 57, tzinfo=UTC))
    assert t0.value < between_t0_and_t1.value < t1.value
    assert await repository.latest_vintage_as_of(item.news_item_key, between_t0_and_t1) is None

    at_t1 = await repository.latest_vintage_as_of(item.news_item_key, t1)
    assert at_t1 is not None
    assert at_t1.source_published_at == t0


@pytest.mark.asyncio
async def test_pit_winter_est_query_between_source_published_at_and_fta_retrieval(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    # Malformed raw dc:date 09:47:00+00:00 remediates to 14:47:00 UTC
    # (09:47:00 EST). FTA's own retrieval lands a few seconds later.
    t0 = UtcTimestamp(datetime(2026, 1, 28, 14, 47, 0, tzinfo=UTC))
    t1 = UtcTimestamp(datetime(2026, 1, 28, 14, 47, 9, tzinfo=UTC))

    body = _feed_xml(_item_xml("pit-winter", dc_date="2026-01-28T09:47:00+00:00"))
    await ingest((_fetcher(body, t1),))
    await session.commit()

    identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("pit-winter"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None

    between_t0_and_t1 = UtcTimestamp(datetime(2026, 1, 28, 14, 47, 4, tzinfo=UTC))
    assert t0.value < between_t0_and_t1.value < t1.value
    assert await repository.latest_vintage_as_of(item.news_item_key, between_t0_and_t1) is None

    at_t1 = await repository.latest_vintage_as_of(item.news_item_key, t1)
    assert at_t1 is not None
    assert at_t1.source_published_at == t0

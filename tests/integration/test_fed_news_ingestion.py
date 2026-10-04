"""FX-57A: end-to-end deterministic test exercising the FULL chain --
a fixture Fed RSS response -> `FedRssSource` -> `NormalizedNewsObser
vation` -> `IngestNewsSourceOnce` -> `RecordNewsObservation` ->
`SqlAlchemyNewsRepository` -> live Postgres -- verifying actual
persisted rows, not just in-memory DTOs (FX-57A Section 28/54: "this
is MORE important than testing the parser only").

Requires a live Postgres with the FX-56 migration applied -- run
`docker compose up -d db && alembic upgrade head` first. Uses the
REAL `source_key="FED"` (the registered identity this story requires
throughout) -- cleanup therefore filters by a distinguishing,
never-real `external_item_id` prefix, never by `source_key`, so a
genuine Fed row ingested by `scripts/ingest_fed_news.py` against this
same database is never at risk of being deleted by this suite.
"""

import functools
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
from forex_agent.application.use_cases.ingest_news_source_once import (
    CrossChannelIdentityCollisionError,
    IngestNewsSourceOnce,
)
from forex_agent.application.use_cases.record_news_observation import RecordNewsObservation
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.news_sources.fed_rss_source import (
    FED_FEEDS,
    SOURCE_KEY,
    FedRssSource,
)

_TEST_GUID_PREFIX = "https://www.federalreserve.gov/fx57a-integration-test/"
_PRESS_MONETARY_FEED = next(f for f in FED_FEEDS if f.channel == "press_monetary")


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
                        NewsSourceMappingRow.external_item_id.startswith(_TEST_GUID_PREFIX),
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


def _feed_xml(*items_xml: str) -> str:
    body = "".join(items_xml)
    return f"<rss version='2.0'><channel><title>t</title>{body}</channel></rss>"


def _item_xml(guid: str, title: str, pub_date: str = "Wed, 16 Sep 2026 18:00:00 GMT") -> str:
    return (
        f"<item><guid>{_TEST_GUID_PREFIX}{guid}</guid><title>{title}</title>"
        f"<link>{_TEST_GUID_PREFIX}{guid}</link><description>A test description.</description>"
        f"<pubDate>{pub_date}</pubDate></item>"
    )


class _ScriptedFedSource:
    """Wraps `FedRssSource` so each poll's HTTP body AND clock value
    can be scripted independently, driving two sequential polls
    through the same adapter instance without a second fixture file."""

    def __init__(self) -> None:
        self._responses: list[tuple[str, UtcTimestamp]] = []
        self._client: httpx.AsyncClient | None = None
        self._source: FedRssSource | None = None

    def script(self, body: str, retrieved_at: UtcTimestamp) -> None:
        self._responses.append((body, retrieved_at))

    def fetcher(self) -> NewsSourceChannelFetcher:
        async def _fetch() -> NewsSourceFetchOutcome:
            body, retrieved_at = self._responses.pop(0)

            def handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, text=body, headers={"content-type": "text/xml"})

            client = httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="https://www.federalreserve.gov",
            )
            source = FedRssSource(client=client, clock=lambda: retrieved_at)
            try:
                return await source.fetch_feed(_PRESS_MONETARY_FEED)
            finally:
                await source.aclose()

        return _fetch


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 10, 3, hour, 0, 0, tzinfo=UTC))


@pytest.mark.asyncio
async def test_single_poll_persists_item_and_first_vintage(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    scripted = _ScriptedFedSource()
    scripted.script(_feed_xml(_item_xml("single-poll", "FOMC Statement")), _ts(10))

    result = await ingest((scripted.fetcher(),))
    await session.commit()

    assert result.created == 1
    assert result.items_processed == 1

    identity = NewsSourceIdentity(SOURCE_KEY, f"{_TEST_GUID_PREFIX}single-poll")
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = await repository.list_vintages(item.news_item_key)
    assert len(vintages) == 1
    assert vintages[0].headline == "FOMC Statement"
    assert vintages[0].availability == _ts(10)
    assert vintages[0].source_published_at == UtcTimestamp(
        datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)
    )
    assert vintages[0].source_content_type == "monetary_policy_release"


@pytest.mark.asyncio
async def test_repeated_identical_poll_creates_no_new_vintage(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    feed_body = _feed_xml(_item_xml("idempotent", "Unchanged Speech"))
    scripted = _ScriptedFedSource()
    scripted.script(feed_body, _ts(11))
    scripted.script(feed_body, _ts(12))

    first = await ingest((scripted.fetcher(),))
    second = await ingest((scripted.fetcher(),))
    await session.commit()

    assert first.created == 1
    assert second.created == 0
    assert second.unchanged == 1

    identity = NewsSourceIdentity(SOURCE_KEY, f"{_TEST_GUID_PREFIX}idempotent")
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = await repository.list_vintages(item.news_item_key)
    assert len(vintages) == 1


@pytest.mark.asyncio
async def test_same_guid_changed_content_creates_a_second_vintage(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    scripted = _ScriptedFedSource()
    scripted.script(_feed_xml(_item_xml("revised", "Original Title")), _ts(12))
    scripted.script(_feed_xml(_item_xml("revised", "Updated Title")), _ts(13))

    first = await ingest((scripted.fetcher(),))
    second = await ingest((scripted.fetcher(),))
    await session.commit()

    assert first.created == 1
    assert second.revisions_added == 1

    identity = NewsSourceIdentity(SOURCE_KEY, f"{_TEST_GUID_PREFIX}revised")
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = sorted(
        await repository.list_vintages(item.news_item_key), key=lambda v: v.revision_sequence
    )
    assert len(vintages) == 2
    assert vintages[0].headline == "Original Title"
    assert vintages[0].revision_sequence == 0
    assert vintages[1].headline == "Updated Title"
    assert vintages[1].revision_sequence == 1
    assert vintages[1].availability == _ts(13)


@pytest.mark.asyncio
async def test_one_malformed_response_writes_zero_news_evidence(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    scripted = _ScriptedFedSource()
    scripted.script("<html><body>blocked</body></html>", _ts(14))

    result = await ingest((scripted.fetcher(),))
    await session.commit()

    assert result.created == 0
    assert result.items_processed == 0
    assert len(result.errors) == 1

    identity = NewsSourceIdentity(SOURCE_KEY, f"{_TEST_GUID_PREFIX}single-poll")
    assert await repository.get_item_by_source_identity(identity) is None


@pytest.mark.asyncio
async def test_duplicate_guid_across_two_channels_fails_closed(
    session: AsyncSession,
) -> None:
    # FX-57CH correction: source_key+guid is identity, so the SAME
    # guid observed through two DIFFERENT Fed channels WITHIN ONE
    # ingestion run is ambiguous simultaneous membership, not a
    # sequential provenance change -- `IngestNewsSourceOnce` must fail
    # the whole run closed (`CrossChannelIdentityCollisionError`)
    # rather than inventing a false "revision 0 channel=speeches,
    # revision 1 channel=testimony" history. (The original version of
    # this test pinned exactly that unsafe fallback -- corrected here,
    # mirroring the same correction made to BoE's own equivalent test.)
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    speeches_feed = next(f for f in FED_FEEDS if f.channel == "speeches")
    testimony_feed = next(f for f in FED_FEEDS if f.channel == "testimony")
    shared_guid = f"{_TEST_GUID_PREFIX}shared-across-channels"
    retrieved_at = _ts(15)

    def handler(request: httpx.Request) -> httpx.Response:
        text = _feed_xml(_item_xml("shared-across-channels", "Cross-channel item"))
        return httpx.Response(200, text=text, headers={"content-type": "text/xml"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://www.federalreserve.gov"
    )
    source = FedRssSource(client=client, clock=lambda: retrieved_at)

    with pytest.raises(CrossChannelIdentityCollisionError) as exc_info:
        await ingest(
            (
                functools.partial(source.fetch_feed, speeches_feed),
                functools.partial(source.fetch_feed, testimony_feed),
            )
        )
    await source.aclose()
    await session.commit()

    assert exc_info.value.external_item_id == shared_guid
    assert exc_info.value.channels == frozenset({"speeches", "testimony"})

    identity = NewsSourceIdentity(SOURCE_KEY, shared_guid)
    assert await repository.get_item_by_source_identity(identity) is None

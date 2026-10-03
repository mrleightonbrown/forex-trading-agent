"""FX-57B: end-to-end deterministic test exercising the FULL chain --
a fixture ECB RSS response -> `EcbRssSource` -> `NormalizedNewsObser
vation` -> `IngestNewsSourceOnce` -> `RecordNewsObservation` ->
`SqlAlchemyNewsRepository` -> live Postgres -- verifying actual
persisted rows, not just in-memory DTOs (mirrors FX-57A's own
`test_fed_news_ingestion.py`).

Requires a live Postgres with the FX-57B migration (`a95058f88727`)
applied -- run `docker compose up -d db && alembic upgrade head`
first. Uses the REAL `source_key="ECB"` -- cleanup therefore filters
by a distinguishing, never-real `external_item_id` prefix, never by
`source_key`, so the genuine ECB rows ingested by `scripts/
ingest_ecb_news.py` against this same database are never at risk of
being deleted by this suite.
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
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.news_sources.ecb_rss_source import (
    ECB_FEEDS,
    SOURCE_KEY,
    EcbRssSource,
)

_TEST_URL_PREFIX = "https://www.ecb.europa.eu//press/fx57b-integration-test"
_PRESS_FEED = ECB_FEEDS[0]


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
                        NewsSourceMappingRow.external_item_id.startswith(_TEST_URL_PREFIX),
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


def _item_xml(
    code: str,
    guid_suffix: str,
    title: str,
    pub_date: str = "Fri, 02 Oct 2026 15:00:00 +0200",
) -> str:
    url = f"{_TEST_URL_PREFIX}/ecb.{code}261002~{guid_suffix}.en.html"
    return (
        f"<item><title>{title}</title><link>{url}</link><guid>{url}</guid>"
        f"<pubDate>{pub_date}</pubDate></item>"
    )


def _url_for(code: str, guid_suffix: str) -> str:
    return f"{_TEST_URL_PREFIX}/ecb.{code}261002~{guid_suffix}.en.html"


class _ScriptedEcbSource:
    """Scripts each poll's HTTP body AND clock value independently --
    mirrors FX-57A's own `_ScriptedFedSource`."""

    def __init__(self) -> None:
        self._responses: list[tuple[str, UtcTimestamp]] = []

    def script(self, body: str, retrieved_at: UtcTimestamp) -> None:
        self._responses.append((body, retrieved_at))

    def fetcher(self) -> NewsSourceChannelFetcher:
        async def _fetch() -> NewsSourceFetchOutcome:
            body, retrieved_at = self._responses.pop(0)

            def handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    200, text=body, headers={"content-type": "application/rss+xml"}
                )

            client = httpx.AsyncClient(
                transport=httpx.MockTransport(handler), base_url="https://www.ecb.europa.eu"
            )
            source = EcbRssSource(client=client, clock=lambda: retrieved_at)
            try:
                return await source.fetch_feed(_PRESS_FEED)
            finally:
                await source.aclose()

        return _fetch


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 10, 2, hour, 0, 0, tzinfo=UTC))


@pytest.mark.asyncio
async def test_single_poll_persists_item_and_first_vintage(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    scripted = _ScriptedEcbSource()
    scripted.script(
        _feed_xml(
            _item_xml("pr", "single-poll", "ECB amends monetary policy implementation guidelines")
        ),
        _ts(10),
    )

    result = await ingest((scripted.fetcher(),))
    await session.commit()

    assert result.created == 1
    assert result.items_processed == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _url_for("pr", "single-poll"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = await repository.list_vintages(item.news_item_key)
    assert len(vintages) == 1
    assert vintages[0].headline == "ECB amends monetary policy implementation guidelines"
    assert vintages[0].availability == _ts(10)
    assert vintages[0].source_channel == "ecb_press"
    assert vintages[0].source_content_type == "press_release"
    assert vintages[0].summary is None
    assert vintages[0].source_updated_at is None
    assert vintages[0].source_published_at == UtcTimestamp(
        datetime(2026, 10, 2, 13, 0, 0, tzinfo=UTC)
    )
    assert len(vintages[0].source_timestamp_provenance) == 1
    assert vintages[0].source_timestamp_provenance[0].raw_value == (
        "Fri, 02 Oct 2026 15:00:00 +0200"
    )


@pytest.mark.asyncio
async def test_repeated_identical_poll_creates_no_new_vintage(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    feed_body = _feed_xml(_item_xml("sp", "idempotent", "Isabel Schnabel: Central banks on-chain"))
    scripted = _ScriptedEcbSource()
    scripted.script(feed_body, _ts(11))
    scripted.script(feed_body, _ts(12))

    first = await ingest((scripted.fetcher(),))
    second = await ingest((scripted.fetcher(),))
    await session.commit()

    assert first.created == 1
    assert second.created == 0
    assert second.unchanged == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _url_for("sp", "idempotent"))
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

    scripted = _ScriptedEcbSource()
    scripted.script(_feed_xml(_item_xml("in", "revised", "Original Title")), _ts(12))
    scripted.script(_feed_xml(_item_xml("in", "revised", "Updated Title")), _ts(13))

    first = await ingest((scripted.fetcher(),))
    second = await ingest((scripted.fetcher(),))
    await session.commit()

    assert first.created == 1
    assert second.revisions_added == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _url_for("in", "revised"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = sorted(
        await repository.list_vintages(item.news_item_key), key=lambda v: v.revision_sequence
    )
    assert len(vintages) == 2
    assert vintages[0].headline == "Original Title"
    assert vintages[0].source_content_type == "interview"
    assert vintages[1].headline == "Updated Title"
    assert vintages[1].availability == _ts(13)


@pytest.mark.asyncio
async def test_different_guid_same_headline_remains_separate_item(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    scripted = _ScriptedEcbSource()
    scripted.script(
        _feed_xml(
            _item_xml("sp", "twin-a", "The outlook for the euro area economy"),
            _item_xml("sp", "twin-b", "The outlook for the euro area economy"),
        ),
        _ts(14),
    )
    result = await ingest((scripted.fetcher(),))
    await session.commit()

    assert result.created == 2

    item_a = await repository.get_item_by_source_identity(
        NewsSourceIdentity(SOURCE_KEY, _url_for("sp", "twin-a"))
    )
    item_b = await repository.get_item_by_source_identity(
        NewsSourceIdentity(SOURCE_KEY, _url_for("sp", "twin-b"))
    )
    assert item_a is not None
    assert item_b is not None
    assert item_a.news_item_key != item_b.news_item_key


@pytest.mark.asyncio
async def test_channel_vs_content_type_matrix_same_channel_distinct_types(
    session: AsyncSession,
) -> None:
    # Section 41: three synthetic items in the SAME response, all
    # sharing the SAME channel, with distinct content types and
    # distinct GUID identities -- the model distinction ECB proves.
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    scripted = _ScriptedEcbSource()
    scripted.script(
        _feed_xml(
            _item_xml("pr", "matrix-pr", "A press release"),
            _item_xml("sp", "matrix-sp", "A speech"),
            _item_xml("in", "matrix-in", "An interview"),
        ),
        _ts(15),
    )
    result = await ingest((scripted.fetcher(),))
    await session.commit()

    assert result.created == 3

    expectations = {
        "pr": ("matrix-pr", "press_release"),
        "sp": ("matrix-sp", "speech"),
        "in": ("matrix-in", "interview"),
    }
    news_item_keys = set()
    for code, (suffix, expected_content_type) in expectations.items():
        identity = NewsSourceIdentity(SOURCE_KEY, _url_for(code, suffix))
        item = await repository.get_item_by_source_identity(identity)
        assert item is not None
        news_item_keys.add(item.news_item_key)
        vintages = await repository.list_vintages(item.news_item_key)
        assert len(vintages) == 1
        assert vintages[0].source_channel == "ecb_press"
        assert vintages[0].source_content_type == expected_content_type

    # All three remain separate NewsItems despite sharing one channel.
    assert len(news_item_keys) == 3

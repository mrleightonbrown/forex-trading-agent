"""FX-57C: end-to-end deterministic test exercising the FULL chain --
a fixture BoE RSS response -> `BoeRssSource` -> `NormalizedNewsObser
vation` -> `IngestNewsSourceOnce` -> `RecordNewsObservation` ->
`SqlAlchemyNewsRepository` -> live Postgres -- mirrors FX-57A/FX-57B's
own `test_fed_news_ingestion.py`/`test_ecb_news_ingestion.py`.

Requires a live Postgres with migration `a95058f88727` applied -- run
`docker compose up -d db && alembic upgrade head` first. Uses the REAL
`source_key="BOE"` -- cleanup therefore filters by a distinguishing,
never-real `external_item_id` prefix (BoE's own GUIDs are opaque, not
URL-shaped, so the test fixtures use an opaque-looking but clearly
fake, prefixed GUID of their own), never by `source_key`, so genuine
BoE rows ingested by `scripts/ingest_boe_news.py` against this same
database are never at risk of being deleted by this suite.
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
from forex_agent.application.use_cases.ingest_news_source_once import IngestNewsSourceOnce
from forex_agent.application.use_cases.record_news_observation import RecordNewsObservation
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.news_sources.boe_rss_source import (
    BOE_FEEDS,
    SOURCE_KEY,
    BoeRssSource,
)

_TEST_GUID_PREFIX = "{FX57C-TEST-"
_NEWS_FEED = next(f for f in BOE_FEEDS if f.channel == "boe_news")


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


def _item_xml(
    guid_suffix: str,
    title: str,
    link: str = "https://www.bankofengland.co.uk/news/fx57c-test",
    pub_date: str = "Fri, 02 Oct 2026 09:00:00 +0100",
) -> str:
    guid = f"{_TEST_GUID_PREFIX}{guid_suffix}}}"
    return (
        f"<item><guid isPermaLink='false'>{guid}</guid><title>{title}</title>"
        f"<link>{link}</link><description>A test description.</description>"
        f"<pubDate>{pub_date}</pubDate></item>"
    )


def _guid_for(suffix: str) -> str:
    return f"{_TEST_GUID_PREFIX}{suffix}}}"


class _ScriptedBoeSource:
    """Wraps `BoeRssSource` so each poll's HTTP body AND clock value
    can be scripted independently -- mirrors FX-57A/FX-57B's own
    `_ScriptedFedSource`/`_ScriptedEcbSource`."""

    def __init__(self) -> None:
        self._responses: list[tuple[str, UtcTimestamp]] = []

    def script(self, body: str, retrieved_at: UtcTimestamp) -> None:
        self._responses.append((body, retrieved_at))

    def fetcher(self) -> NewsSourceChannelFetcher:
        async def _fetch() -> NewsSourceFetchOutcome:
            body, retrieved_at = self._responses.pop(0)

            def handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, text=body, headers={"content-type": "text/xml"})

            client = httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="https://www.bankofengland.co.uk",
            )
            source = BoeRssSource(client=client, clock=lambda: retrieved_at)
            try:
                return await source.fetch_feed(_NEWS_FEED)
            finally:
                await source.aclose()

        return _fetch


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 10, 2, hour, 0, 0, tzinfo=UTC))


@pytest.mark.asyncio
async def test_single_poll_persists_item_and_first_vintage(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    scripted = _ScriptedBoeSource()
    scripted.script(
        _feed_xml(_item_xml("single-poll", "Appointment of members of the EDMC")), _ts(10)
    )

    result = await ingest((scripted.fetcher(),))
    await session.commit()

    assert result.created == 1
    assert result.items_processed == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _guid_for("single-poll"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = await repository.list_vintages(item.news_item_key)
    assert len(vintages) == 1
    assert vintages[0].headline == "Appointment of members of the EDMC"
    assert vintages[0].availability == _ts(10)
    assert vintages[0].source_channel == "boe_news"
    assert vintages[0].source_content_type == "news"
    assert vintages[0].source_updated_at is None
    assert vintages[0].source_published_at == UtcTimestamp(
        datetime(2026, 10, 2, 8, 0, 0, tzinfo=UTC)
    )
    assert len(vintages[0].source_timestamp_provenance) == 1
    assert vintages[0].source_timestamp_provenance[0].raw_value == (
        "Fri, 02 Oct 2026 09:00:00 +0100"
    )
    # Section 10/11: opaque GUID identity, independent of the link --
    # the identity used to resolve this item is NOT the canonical_url
    # persisted alongside it.
    assert identity.external_item_id != vintages[0].canonical_url


@pytest.mark.asyncio
async def test_repeated_identical_poll_creates_no_new_vintage(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    feed_body = _feed_xml(_item_xml("idempotent", "Unchanged Speech"))
    scripted = _ScriptedBoeSource()
    scripted.script(feed_body, _ts(11))
    scripted.script(feed_body, _ts(12))

    first = await ingest((scripted.fetcher(),))
    second = await ingest((scripted.fetcher(),))
    await session.commit()

    assert first.created == 1
    assert second.created == 0
    assert second.unchanged == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _guid_for("idempotent"))
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

    scripted = _ScriptedBoeSource()
    scripted.script(_feed_xml(_item_xml("revised", "Original Title")), _ts(12))
    scripted.script(_feed_xml(_item_xml("revised", "Updated Title")), _ts(13))

    first = await ingest((scripted.fetcher(),))
    second = await ingest((scripted.fetcher(),))
    await session.commit()

    assert first.created == 1
    assert second.revisions_added == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _guid_for("revised"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = sorted(
        await repository.list_vintages(item.news_item_key), key=lambda v: v.revision_sequence
    )
    assert len(vintages) == 2
    assert vintages[0].headline == "Original Title"
    assert vintages[1].headline == "Updated Title"
    assert vintages[1].availability == _ts(13)


@pytest.mark.asyncio
async def test_different_guid_same_headline_remains_separate_item(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    scripted = _ScriptedBoeSource()
    scripted.script(
        _feed_xml(
            _item_xml("twin-a", "Minutes of the Court of Directors"),
            _item_xml("twin-b", "Minutes of the Court of Directors"),
        ),
        _ts(14),
    )
    result = await ingest((scripted.fetcher(),))
    await session.commit()

    assert result.created == 2

    item_a = await repository.get_item_by_source_identity(
        NewsSourceIdentity(SOURCE_KEY, _guid_for("twin-a"))
    )
    item_b = await repository.get_item_by_source_identity(
        NewsSourceIdentity(SOURCE_KEY, _guid_for("twin-b"))
    )
    assert item_a is not None
    assert item_b is not None
    assert item_a.news_item_key != item_b.news_item_key


@pytest.mark.asyncio
async def test_one_malformed_response_writes_zero_news_evidence(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    scripted = _ScriptedBoeSource()
    scripted.script("<html><body>blocked</body></html>", _ts(15))

    result = await ingest((scripted.fetcher(),))
    await session.commit()

    assert result.created == 0
    assert result.items_processed == 0
    assert len(result.errors) == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _guid_for("single-poll"))
    assert await repository.get_item_by_source_identity(identity) is None


@pytest.mark.asyncio
async def test_same_guid_across_two_boe_channels_resolves_to_one_item(
    session: AsyncSession,
) -> None:
    # FX-57C Section 9/40/56: live validation found ZERO cross-channel
    # GUID overlap across all 150 sampled BoE items (50 per feed x 3
    # feeds) -- this test pins the FALLBACK model behavior in case
    # that ever changes, it does not claim BoE actually does this
    # today. source_key+guid is identity, so the SAME guid observed
    # through two different BoE channels must resolve to exactly ONE
    # NewsItem -- never two; since source_channel participates in
    # modeled-fact equality, the second channel's observation is a
    # genuine, deliberate provenance change (a new vintage), not a
    # silently-discarded duplicate and not a fabricated second item.
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    news_feed = next(f for f in BOE_FEEDS if f.channel == "boe_news")
    speeches_feed = next(f for f in BOE_FEEDS if f.channel == "boe_speeches")
    shared_guid_suffix = "shared-across-channels"
    retrieved_at = _ts(16)

    def handler(request: httpx.Request) -> httpx.Response:
        text = _feed_xml(_item_xml(shared_guid_suffix, "Cross-channel item"))
        return httpx.Response(200, text=text, headers={"content-type": "text/xml"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://www.bankofengland.co.uk"
    )
    source = BoeRssSource(client=client, clock=lambda: retrieved_at)

    result = await ingest(
        (
            functools.partial(source.fetch_feed, news_feed),
            functools.partial(source.fetch_feed, speeches_feed),
        )
    )
    await source.aclose()
    await session.commit()

    assert result.created == 1
    assert result.revisions_added == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _guid_for(shared_guid_suffix))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = await repository.list_vintages(item.news_item_key)
    assert len(vintages) == 2


@pytest.mark.asyncio
async def test_pit_query_between_source_pubdate_and_fta_retrieval_sees_nothing(
    session: AsyncSession,
) -> None:
    # FX-57C Section 12/58's own worked example, pinned exactly:
    # source pubDate = T0 (09:00:00 +0100 = 08:00:00 UTC); FTA
    # retrieval T1 is strictly LATER than T0. A PIT query for any
    # as_of strictly between T0 and T1 must see NOTHING -- FTA did
    # not yet know this item existed at that instant, regardless of
    # what the source itself claims about when it was published.
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    t0 = UtcTimestamp(datetime(2026, 10, 2, 8, 0, 0, tzinfo=UTC))  # pubDate, in UTC
    t1 = UtcTimestamp(datetime(2026, 10, 2, 8, 0, 7, tzinfo=UTC))  # FTA's own retrieval

    scripted = _ScriptedBoeSource()
    scripted.script(
        _feed_xml(
            _item_xml(
                "pit-example", "PIT worked example", pub_date="Fri, 02 Oct 2026 09:00:00 +0100"
            )
        ),
        t1,
    )
    await ingest((scripted.fetcher(),))
    await session.commit()

    identity = NewsSourceIdentity(SOURCE_KEY, _guid_for("pit-example"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None

    between_t0_and_t1 = UtcTimestamp(datetime(2026, 10, 2, 8, 0, 3, tzinfo=UTC))
    assert t0.value < between_t0_and_t1.value < t1.value
    assert await repository.latest_vintage_as_of(item.news_item_key, between_t0_and_t1) is None

    at_or_after_t1 = await repository.latest_vintage_as_of(item.news_item_key, t1)
    assert at_or_after_t1 is not None
    assert at_or_after_t1.headline == "PIT worked example"

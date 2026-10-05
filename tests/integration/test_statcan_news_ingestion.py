"""FX-57E: end-to-end deterministic test exercising the FULL chain --
a fixture StatCan Atom response -> `StatCanSource` ->
`NormalizedNewsObservation` -> `IngestNewsSourceOnce` ->
`RecordNewsObservation` -> `SqlAlchemyNewsRepository` -> live
Postgres -- mirrors FX-57A/B/C/D's own
`test_fed_news_ingestion.py`/`test_ecb_news_ingestion.py`/
`test_boe_news_ingestion.py`/`test_govuk_hmt_news_ingestion.py`.

Requires a live Postgres with migrations applied -- run
`docker compose up -d db && alembic upgrade head` first. Uses the REAL
`source_key="STATCAN"` -- cleanup therefore filters by a
distinguishing, never-real `external_item_id` prefix, never by
`source_key`, so genuine StatCan rows ingested by
`scripts/ingest_statcan_news.py` against this same database are never
at risk of being deleted by this suite.

**The genuine cross-subject multi-channel merge (FX-57E0/ADR 0006)**
is this file's own most important addition over every prior FX-57
adapter's own equivalent suite: live research found Statistics Canada
legitimately cross-lists the SAME Daily release under more than one
subject feed simultaneously. `test_same_release_cross_listed_under_
two_channels_merges_into_one_item` pins that exact shape end-to-end
against real Postgres, not just the generic common-layer tests already
covering this in `test_ingest_news_source_once.py`.
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
from forex_agent.application.use_cases.ingest_news_source_once import (
    ConflictingDuplicateExternalIdError,
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
from forex_agent.infrastructure.news_sources.statcan_source import (
    SOURCE_KEY,
    STATCAN_FEEDS,
    StatCanSource,
)

_TEST_ID_PREFIX = "https://www.statcan.gc.ca/daily-quotidien/9"
_PRICES_FEED = next(f for f in STATCAN_FEEDS if f.channel == "statcan_prices")
_LABOUR_FEED = next(f for f in STATCAN_FEEDS if f.channel == "statcan_labour")
_TRADE_FEED = next(f for f in STATCAN_FEEDS if f.channel == "statcan_international_trade")


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


_SUFFIX_CODES: dict[str, str] = {}
_NEXT_CODE = [900001]


def _code_for(suffix: str) -> str:
    # Every real StatCan date-folder/dq-token is exactly 6 digits
    # (`YYMMDD`) followed by one-or-more lowercase letters -- this
    # generates a distinct, VALID-shaped, but clearly-impossible
    # ("9...") 6-digit code per test suffix, so test fixtures satisfy
    # the parser's own Daily-release URL-shape validation while never
    # colliding with a genuine StatCan date.
    if suffix not in _SUFFIX_CODES:
        _SUFFIX_CODES[suffix] = str(_NEXT_CODE[0])
        _NEXT_CODE[0] += 1
    return _SUFFIX_CODES[suffix]


def _entry_id(suffix: str) -> str:
    code = _code_for(suffix)
    return f"https://www.statcan.gc.ca/daily-quotidien/{code}/dq{code}z-eng.htm"


def _feed_xml(*entries_xml: str) -> str:
    body = "".join(entries_xml)
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<feed xmlns='http://www.w3.org/2005/Atom'><title>t</title>"
        f"{body}</feed>"
    )


def _entry_xml(
    suffix: str,
    title: str = "Example Daily release",
    updated: str = "2026-10-05T08:30:00-04:00",
    summary: str = "Example summary.",
) -> str:
    entry_id = _entry_id(suffix)
    return (
        "<entry>"
        f"<id>{entry_id}</id>"
        f"<title type='xhtml'><div xmlns='http://www.w3.org/1999/xhtml'>{title}</div></title>"
        f"<link href='{entry_id}'></link>"
        f"<updated>{updated}</updated>"
        f"<summary type='xhtml'><div xmlns='http://www.w3.org/1999/xhtml'>{summary}</div></summary>"
        "</entry>"
    )


def _fetcher(
    feed: object, body: str, retrieved_at: UtcTimestamp, *, status_code: int = 200
) -> NewsSourceChannelFetcher:
    async def _fetch() -> NewsSourceFetchOutcome:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code, text=body, headers={"content-type": "application/atom+xml"}
            )

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://www150.statcan.gc.ca"
        )
        source = StatCanSource(client=client, clock=lambda: retrieved_at, crawl_delay_seconds=0.0)
        try:
            return await source.fetch_feed(feed)  # type: ignore[arg-type]
        finally:
            await source.aclose()

    return _fetch


def _ts(hour: int, minute: int = 0, second: int = 0) -> UtcTimestamp:
    day = 5 + hour // 24
    return UtcTimestamp(datetime(2026, 10, day, hour % 24, minute, second, tzinfo=UTC))


@pytest.mark.asyncio
async def test_single_poll_persists_item_and_first_vintage(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    body = _feed_xml(_entry_xml("single-poll", title="Treasury-adjacent Daily release"))
    result = await ingest((_fetcher(_PRICES_FEED, body, _ts(10)),))
    await session.commit()

    assert result.created == 1
    assert result.items_processed == 1
    assert result.source_channels == ("statcan_prices",)

    identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("single-poll"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = await repository.list_vintages(item.news_item_key)
    assert len(vintages) == 1
    vintage = vintages[0]
    assert vintage.headline == "Treasury-adjacent Daily release"
    assert vintage.availability == _ts(10)
    assert vintage.source_channel == "statcan_prices"
    assert vintage.observed_source_channels == ("statcan_prices",)
    assert vintage.source_content_type == "daily_release"
    assert vintage.language == "en"
    assert vintage.authors == ()
    assert vintage.body_text is None
    assert vintage.summary == "Example summary."
    assert vintage.canonical_url == _entry_id("single-poll")
    assert vintage.source_published_at == UtcTimestamp(datetime(2026, 10, 5, 12, 30, 0, tzinfo=UTC))
    assert vintage.source_updated_at is None
    assert len(vintage.source_timestamp_provenance) == 1
    assert vintage.source_timestamp_provenance[0].field_name == "updated"
    # Section 10: identity is NOT availability's own observation time.
    assert vintage.availability.value != vintage.source_published_at.value


@pytest.mark.asyncio
async def test_repeated_identical_poll_creates_no_new_vintage(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    body = _feed_xml(_entry_xml("idempotent"))
    first = await ingest((_fetcher(_PRICES_FEED, body, _ts(11)),))
    second = await ingest((_fetcher(_PRICES_FEED, body, _ts(12)),))
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
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    first_body = _feed_xml(_entry_xml("revised", title="Original title"))
    second_body = _feed_xml(_entry_xml("revised", title="Updated title"))

    first = await ingest((_fetcher(_PRICES_FEED, first_body, _ts(12)),))
    second = await ingest((_fetcher(_PRICES_FEED, second_body, _ts(13)),))
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
async def test_two_different_ids_same_headline_remain_distinct_items(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    body = _feed_xml(
        _entry_xml("twin-a", title="Same headline text"),
        _entry_xml("twin-b", title="Same headline text"),
    )
    result = await ingest((_fetcher(_PRICES_FEED, body, _ts(14)),))
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
    # Section 36/40: an item whose source release date is far in the
    # past relative to FTA's own FIRST retrieval is still PROSPECTIVE,
    # never BACKFILL -- first-seen is this retrieval, not the source's
    # own June release date.
    from forex_agent.domain.news_observation_mode import NewsObservationMode

    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    body = _feed_xml(_entry_xml("old-release", updated="2026-06-15T08:30:00-04:00"))
    await ingest((_fetcher(_PRICES_FEED, body, _ts(15)),))
    await session.commit()

    identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("old-release"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    assert item.first_observation_mode is NewsObservationMode.PROSPECTIVE
    assert item.first_seen_at == _ts(15)
    vintages = await repository.list_vintages(item.news_item_key)
    assert vintages[0].observation_mode is NewsObservationMode.PROSPECTIVE


@pytest.mark.asyncio
async def test_one_malformed_response_writes_zero_news_evidence(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    result = await ingest((_fetcher(_PRICES_FEED, "<html><body>blocked</body></html>", _ts(16)),))
    await session.commit()

    assert result.created == 0
    assert result.items_processed == 0
    assert len(result.errors) == 1


# --- The genuine cross-subject multi-channel merge (FX-57E0/ADR 0006) ------


@pytest.mark.asyncio
async def test_same_release_cross_listed_under_two_channels_merges_into_one_item(
    session: AsyncSession,
) -> None:
    # Live-confirmed shape: the SAME Daily release id, with IDENTICAL
    # content, appears in both the prices and international_trade
    # feeds within one poll. Both observations must survive and merge
    # into ONE item's own cumulative observed_source_channels -- never
    # two items, never a fabricated content-change revision.
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    shared_body = _feed_xml(
        _entry_xml("cross-listed", title="Canadian international merchandise trade, July 2026")
    )
    result = await ingest(
        (
            _fetcher(_PRICES_FEED, shared_body, _ts(17)),
            _fetcher(_TRADE_FEED, shared_body, _ts(17)),
        )
    )
    await session.commit()

    assert result.created == 1
    assert result.revisions_added == 1
    assert result.channel_memberships_added == 1
    assert result.errors == ()

    identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("cross-listed"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = sorted(
        await repository.list_vintages(item.news_item_key), key=lambda v: v.revision_sequence
    )
    assert len(vintages) == 2
    assert vintages[0].observed_source_channels == ("statcan_prices",)
    assert vintages[1].observed_source_channels == ("statcan_international_trade", "statcan_prices")
    # The headline never actually changed -- both vintages agree.
    assert vintages[0].headline == vintages[1].headline


@pytest.mark.asyncio
async def test_three_channel_cross_listing_merges_cumulatively(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    shared_body = _feed_xml(_entry_xml("triple-listed", title="A triple-subject release"))
    result = await ingest(
        (
            _fetcher(_PRICES_FEED, shared_body, _ts(18)),
            _fetcher(_LABOUR_FEED, shared_body, _ts(18)),
            _fetcher(_TRADE_FEED, shared_body, _ts(18)),
        )
    )
    await session.commit()

    assert result.created == 1
    assert result.revisions_added == 2
    assert result.channel_memberships_added == 2

    identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("triple-listed"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = sorted(
        await repository.list_vintages(item.news_item_key), key=lambda v: v.revision_sequence
    )
    assert len(vintages) == 3
    assert vintages[-1].observed_source_channels == (
        "statcan_international_trade",
        "statcan_labour",
        "statcan_prices",
    )


@pytest.mark.asyncio
async def test_cross_subject_genuine_conflict_fails_whole_run_closed(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    prices_body = _feed_xml(_entry_xml("conflicting", title="Headline from prices"))
    trade_body = _feed_xml(_entry_xml("conflicting", title="Conflicting headline from trade"))
    unrelated_body = _feed_xml(_entry_xml("unrelated-good-item", title="A perfectly good item"))

    with pytest.raises(ConflictingDuplicateExternalIdError):
        await ingest(
            (
                _fetcher(_PRICES_FEED, prices_body, _ts(19)),
                _fetcher(_TRADE_FEED, trade_body, _ts(19)),
                _fetcher(_LABOUR_FEED, unrelated_body, _ts(19)),
            )
        )
    await session.commit()

    colliding_identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("conflicting"))
    assert await repository.get_item_by_source_identity(colliding_identity) is None
    unrelated_identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("unrelated-good-item"))
    assert await repository.get_item_by_source_identity(unrelated_identity) is None


@pytest.mark.asyncio
async def test_same_headline_but_differing_summary_across_channels_still_conflicts(
    session: AsyncSession,
) -> None:
    # FX-57EH Section 6: headline equality ALONE is not sufficient to
    # call a cross-subject overlap benign -- the SAME non-channel-
    # fact rule IngestNewsSourceOnce actually uses compares every
    # non-channel field, including summary. Two observations sharing
    # an identical headline but differing summary across channels
    # must still fail the whole run closed.
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    prices_body = _feed_xml(
        _entry_xml(
            "same-headline-diff-summary",
            title="Identical headline across both channels",
            summary="Summary as reported by the prices subject feed.",
        )
    )
    trade_body = _feed_xml(
        _entry_xml(
            "same-headline-diff-summary",
            title="Identical headline across both channels",
            summary="A genuinely DIFFERENT summary as reported by trade.",
        )
    )

    with pytest.raises(ConflictingDuplicateExternalIdError):
        await ingest(
            (
                _fetcher(_PRICES_FEED, prices_body, _ts(20)),
                _fetcher(_TRADE_FEED, trade_body, _ts(20)),
            )
        )
    await session.commit()

    identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("same-headline-diff-summary"))
    assert await repository.get_item_by_source_identity(identity) is None


# --- PIT worked example (Section 70) ----------------------------------------


@pytest.mark.asyncio
async def test_pit_query_between_source_published_at_and_fta_retrieval_sees_nothing(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    t0 = UtcTimestamp(datetime(2026, 10, 5, 12, 30, 0, tzinfo=UTC))  # 08:30 EDT in UTC
    t1 = UtcTimestamp(datetime(2026, 10, 5, 12, 30, 7, tzinfo=UTC))  # FTA's own retrieval

    body = _feed_xml(_entry_xml("pit-example", title="PIT worked example"))
    await ingest((_fetcher(_PRICES_FEED, body, t1),))
    await session.commit()

    identity = NewsSourceIdentity(SOURCE_KEY, _entry_id("pit-example"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None

    between_t0_and_t1 = UtcTimestamp(datetime(2026, 10, 5, 12, 30, 3, tzinfo=UTC))
    assert t0.value < between_t0_and_t1.value < t1.value
    assert await repository.latest_vintage_as_of(item.news_item_key, between_t0_and_t1) is None

    at_t1 = await repository.latest_vintage_as_of(item.news_item_key, t1)
    assert at_t1 is not None
    assert at_t1.headline == "PIT worked example"
    # The sequence letter embedded in the id has no influence on this
    # PIT result -- it is the id, not a timestamp.

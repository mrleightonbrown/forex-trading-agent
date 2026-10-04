"""FX-57D: end-to-end deterministic test exercising the FULL chain --
a fixture GOV.UK Content API response -> `GovUkHmtSource` ->
`NormalizedNewsObservation` -> `IngestNewsSourceOnce` ->
`RecordNewsObservation` -> `SqlAlchemyNewsRepository` -> live
Postgres -- mirrors FX-57A/FX-57B/FX-57C's own
`test_fed_news_ingestion.py`/`test_ecb_news_ingestion.py`/
`test_boe_news_ingestion.py`.

Requires a live Postgres with migrations applied -- run
`docker compose up -d db && alembic upgrade head` first. Uses the REAL
`source_key="GOVUK_HMT"` -- cleanup therefore filters by a
distinguishing, never-real `external_item_id` prefix, never by
`source_key`, so genuine HMT rows ingested by
`scripts/ingest_govuk_hmt_news.py` against this same database are
never at risk of being deleted by this suite.

**No discovery-stage parsing here.** This file hydrates each
discovered PATH directly through `GovUkHmtSource.fetch_content_item`
-- `govuk_discovery.py`'s own parser has its own dedicated unit tests
(`tests/unit/infrastructure/news_sources/test_govuk_discovery.py`);
this file's job is the Content-API-to-stored-evidence chain and the
common orchestration's own behaviors as GOV.UK actually exercises
them (Section 14/55's whole-run same-channel dedupe/collision guard,
withdrawal, PIT, change_history)."""

import json
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
from forex_agent.domain.news_source_revision_fact import NewsSourceRevisionKind
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.news_sources.govuk_content_api import (
    CHANNEL,
    SOURCE_KEY,
    GovUkHmtSource,
)

_TEST_ID_PREFIX = "FX57D-TEST-"
_HMT_ORG = {"base_path": "/government/organisations/hm-treasury", "title": "HM Treasury"}
_NON_HMT_ORG = {"base_path": "/government/organisations/cabinet-office", "title": "Cabinet Office"}


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


def _content_id(suffix: str) -> str:
    return f"{_TEST_ID_PREFIX}{suffix}"


def _content_json(
    suffix: str,
    title: str = "Example item",
    base_path: str | None = None,
    description: str | None = "A genuine summary.",
    document_type: str = "news_story",
    body: str = "<p>Body text.</p>",
    first_published_at: str = "2026-10-01T09:24:06+01:00",
    public_updated_at: str = "2026-10-01T09:24:06+01:00",
    updated_at: str = "2026-10-01T09:24:06+01:00",
    change_history: list[dict[str, str]] | None = None,
    withdrawn_notice: dict[str, str] | None = None,
    organisations: list[dict[str, str]] | None = None,
) -> str:
    data = {
        "content_id": _content_id(suffix),
        "base_path": base_path if base_path is not None else f"/government/news/{suffix}",
        "title": title,
        "description": description,
        "document_type": document_type,
        "locale": "en",
        "first_published_at": first_published_at,
        "public_updated_at": public_updated_at,
        "updated_at": updated_at,
        "publishing_scheduled_at": None,
        "withdrawn_notice": withdrawn_notice if withdrawn_notice is not None else {},
        "details": {
            "body": body,
            "change_history": (
                change_history
                if change_history is not None
                else [{"note": "First published.", "public_timestamp": "2026-10-01T08:24:06Z"}]
            ),
        },
        "links": {"organisations": organisations if organisations is not None else [_HMT_ORG]},
    }
    return json.dumps(data)


def _fetcher(
    path: str, body: str, retrieved_at: UtcTimestamp, *, status_code: int = 200
) -> NewsSourceChannelFetcher:
    async def _fetch() -> NewsSourceFetchOutcome:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code, text=body, headers={"content-type": "application/json"}
            )

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://www.gov.uk"
        )
        source = GovUkHmtSource(client=client, clock=lambda: retrieved_at, pace_seconds=0.0)
        try:
            return await source.fetch_content_item(path)
        finally:
            await source.aclose()

    return _fetch


def _ts(hour: int, minute: int = 0, second: int = 0) -> UtcTimestamp:
    day = 3 + hour // 24
    return UtcTimestamp(datetime(2026, 10, day, hour % 24, minute, second, tzinfo=UTC))


@pytest.mark.asyncio
async def test_single_poll_persists_item_and_first_vintage(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    body = _content_json("single-poll", title="Treasury announces new scheme")
    result = await ingest((_fetcher("/government/news/single-poll", body, _ts(10)),))
    await session.commit()

    assert result.created == 1
    assert result.items_processed == 1
    assert result.source_channels == (CHANNEL,)

    identity = NewsSourceIdentity(SOURCE_KEY, _content_id("single-poll"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = await repository.list_vintages(item.news_item_key)
    assert len(vintages) == 1
    vintage = vintages[0]
    assert vintage.headline == "Treasury announces new scheme"
    assert vintage.availability == _ts(10)
    assert vintage.source_channel == "hmt_news_and_communications"
    assert vintage.source_content_type == "news_story"
    assert vintage.language == "en"
    assert vintage.authors == ()
    assert vintage.canonical_url == "https://www.gov.uk/government/news/single-poll"
    assert vintage.body_text == "<p>Body text.</p>"
    assert vintage.summary == "A genuine summary."
    assert vintage.source_status is NewsSourceStatus.ACTIVE
    assert vintage.source_published_at == UtcTimestamp(datetime(2026, 10, 1, 8, 24, 6, tzinfo=UTC))
    assert vintage.source_updated_at == UtcTimestamp(datetime(2026, 10, 1, 8, 24, 6, tzinfo=UTC))

    provenance_fields = {p.field_name for p in vintage.source_timestamp_provenance}
    assert provenance_fields == {"first_published_at", "public_updated_at", "updated_at"}

    assert len(vintage.source_revision_metadata) == 1
    assert vintage.source_revision_metadata[0].kind is NewsSourceRevisionKind.UPDATE
    assert vintage.source_revision_metadata[0].note == "First published."

    # Section 10: content_id identity is NOT the canonical URL.
    assert identity.external_item_id != vintage.canonical_url


@pytest.mark.asyncio
async def test_repeated_identical_poll_creates_no_new_vintage(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    body = _content_json("idempotent", title="Unchanged item")
    first = await ingest((_fetcher("/government/news/idempotent", body, _ts(11)),))
    second = await ingest((_fetcher("/government/news/idempotent", body, _ts(12)),))
    await session.commit()

    assert first.created == 1
    assert second.created == 0
    assert second.unchanged == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _content_id("idempotent"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    assert len(await repository.list_vintages(item.news_item_key)) == 1


@pytest.mark.asyncio
async def test_title_change_creates_a_second_vintage(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    first_body = _content_json("revised", title="Original title")
    second_body = _content_json("revised", title="Updated title")

    first = await ingest((_fetcher("/government/news/revised", first_body, _ts(12)),))
    second = await ingest((_fetcher("/government/news/revised", second_body, _ts(13)),))
    await session.commit()

    assert first.created == 1
    assert second.revisions_added == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _content_id("revised"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = sorted(
        await repository.list_vintages(item.news_item_key), key=lambda v: v.revision_sequence
    )
    assert len(vintages) == 2
    assert vintages[0].headline == "Original title"
    assert vintages[1].headline == "Updated title"
    assert vintages[1].availability == _ts(13)


@pytest.mark.asyncio
async def test_updated_at_only_change_still_creates_a_new_vintage(session: AsyncSession) -> None:
    # `updated_at` is persisted ONLY as its own provenance entry (never
    # mapped to source_updated_at), but that provenance tuple
    # participates in modeled-fact equality (FX-56's general
    # invariant) -- so a genuine change in `updated_at` ALONE, with
    # everything else held fixed, must still mint a new revision.
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    first_body = _content_json("updated-at-only", updated_at="2026-10-01T09:24:06+01:00")
    second_body = _content_json("updated-at-only", updated_at="2026-10-01T09:24:44+01:00")

    first = await ingest((_fetcher("/government/news/updated-at-only", first_body, _ts(14)),))
    second = await ingest((_fetcher("/government/news/updated-at-only", second_body, _ts(15)),))
    await session.commit()

    assert first.created == 1
    assert second.revisions_added == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _content_id("updated-at-only"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = await repository.list_vintages(item.news_item_key)
    assert len(vintages) == 2


@pytest.mark.asyncio
async def test_first_poll_with_preexisting_multi_entry_change_history_is_one_revision(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    body = _content_json(
        "history-on-first-poll",
        change_history=[
            {"note": "Updated with new information.", "public_timestamp": "2026-09-07T11:42:27Z"},
            {"note": "First published.", "public_timestamp": "2025-06-19T09:26:00Z"},
        ],
    )
    result = await ingest((_fetcher("/government/news/history-on-first-poll", body, _ts(16)),))
    await session.commit()

    assert result.created == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _content_id("history-on-first-poll"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = await repository.list_vintages(item.news_item_key)
    assert len(vintages) == 1
    assert vintages[0].revision_sequence == 0
    assert len(vintages[0].source_revision_metadata) == 2
    assert [f.note for f in vintages[0].source_revision_metadata] == [
        "Updated with new information.",
        "First published.",
    ]
    assert all(
        f.kind is NewsSourceRevisionKind.UPDATE for f in vintages[0].source_revision_metadata
    )


@pytest.mark.asyncio
async def test_withdrawal_becomes_visible_at_fta_observation_time_not_source_withdrawn_at(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    active_body = _content_json("withdrawal-example", title="Live scheme details")
    withdrawn_body = _content_json(
        "withdrawal-example",
        title="Live scheme details",
        withdrawn_notice={
            "explanation": "This scheme has ended.",
            # Deliberately earlier than the FIRST poll, to prove the
            # source's own claimed withdrawal time is irrelevant to
            # when FTA itself may treat the item as withdrawn.
            "withdrawn_at": "2026-09-01T00:00:00+01:00",
        },
    )

    t_active = _ts(17)
    t_withdrawn = _ts(18)
    first = await ingest((_fetcher("/government/news/withdrawal-example", active_body, t_active),))
    second = await ingest(
        (_fetcher("/government/news/withdrawal-example", withdrawn_body, t_withdrawn),)
    )
    await session.commit()

    assert first.created == 1
    assert second.revisions_added == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _content_id("withdrawal-example"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = sorted(
        await repository.list_vintages(item.news_item_key), key=lambda v: v.revision_sequence
    )
    assert vintages[0].source_status is NewsSourceStatus.ACTIVE
    assert vintages[1].source_status is NewsSourceStatus.WITHDRAWN
    withdrawal_facts = [
        f
        for f in vintages[1].source_revision_metadata
        if f.kind is NewsSourceRevisionKind.WITHDRAWAL
    ]
    assert len(withdrawal_facts) == 1

    just_before_withdrawn_observation = _ts(17, 30)
    assert t_active.value < just_before_withdrawn_observation.value < t_withdrawn.value
    still_active = await repository.latest_vintage_as_of(
        item.news_item_key, just_before_withdrawn_observation
    )
    assert still_active is not None
    assert still_active.source_status is NewsSourceStatus.ACTIVE

    now_withdrawn = await repository.latest_vintage_as_of(item.news_item_key, t_withdrawn)
    assert now_withdrawn is not None
    assert now_withdrawn.source_status is NewsSourceStatus.WITHDRAWN


@pytest.mark.asyncio
async def test_two_discovered_paths_hydrating_to_identical_content_id_dedupes(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    # Two DIFFERENT discovery paths both hydrate, through the Content
    # API, to the SAME content_id and the SAME canonical base_path --
    # a benign alias (Section 14/55); genuinely identical modeled
    # facts must collapse to ONE stored observation, never two.
    shared_base_path = "/government/news/canonical-alias-target"
    body = _content_json("aliased", title="Aliased item", base_path=shared_base_path)

    result = await ingest(
        (
            _fetcher("/government/news/alias-a", body, _ts(19)),
            _fetcher("/government/news/alias-b", body, _ts(20)),
        )
    )
    await session.commit()

    assert result.created == 1
    assert result.items_processed == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _content_id("aliased"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None
    vintages = await repository.list_vintages(item.news_item_key)
    assert len(vintages) == 1
    assert vintages[0].canonical_url == f"https://www.gov.uk{shared_base_path}"


@pytest.mark.asyncio
async def test_two_discovered_paths_hydrating_to_conflicting_content_id_fails_closed(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    body_a = _content_json("colliding", title="Version seen via path A")
    body_b = _content_json("colliding", title="Version seen via path B")
    unrelated_body = _content_json("unrelated-good-item", title="An unrelated, perfectly good item")

    with pytest.raises(ConflictingDuplicateExternalIdError) as exc_info:
        await ingest(
            (
                _fetcher("/government/news/colliding-a", body_a, _ts(21)),
                _fetcher("/government/news/colliding-b", body_b, _ts(22)),
                _fetcher("/government/news/unrelated", unrelated_body, _ts(23)),
            )
        )
    await session.commit()

    assert exc_info.value.external_item_id == _content_id("colliding")

    colliding_identity = NewsSourceIdentity(SOURCE_KEY, _content_id("colliding"))
    assert await repository.get_item_by_source_identity(colliding_identity) is None
    unrelated_identity = NewsSourceIdentity(SOURCE_KEY, _content_id("unrelated-good-item"))
    assert await repository.get_item_by_source_identity(unrelated_identity) is None


@pytest.mark.asyncio
async def test_404_response_is_an_ordinary_fetch_error_not_a_withdrawal(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    result = await ingest((_fetcher("/government/news/gone", "", _ts(24), status_code=404),))
    await session.commit()

    assert result.created == 0
    assert result.items_processed == 0
    assert len(result.errors) == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _content_id("gone"))
    assert await repository.get_item_by_source_identity(identity) is None


@pytest.mark.asyncio
async def test_non_hm_treasury_item_is_invalid_and_not_ingested(session: AsyncSession) -> None:
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    body = _content_json("not-hmt", organisations=[_NON_HMT_ORG])
    result = await ingest((_fetcher("/government/news/not-hmt", body, _ts(25)),))
    await session.commit()

    assert result.created == 0
    assert result.items_invalid == 1

    identity = NewsSourceIdentity(SOURCE_KEY, _content_id("not-hmt"))
    assert await repository.get_item_by_source_identity(identity) is None


@pytest.mark.asyncio
async def test_pit_query_between_source_published_at_and_fta_retrieval_sees_nothing(
    session: AsyncSession,
) -> None:
    # FX-57D Section 58-style worked example, mirroring FX-57C's own:
    # source first_published_at = T0 (09:24:06+01:00 = 08:24:06 UTC);
    # FTA retrieval T1 is strictly LATER than T0. A PIT query for any
    # as_of strictly between T0 and T1 must see NOTHING.
    repository = SqlAlchemyNewsRepository(session)
    ingest = IngestNewsSourceOnce(SOURCE_KEY, RecordNewsObservation(repository))

    t0 = UtcTimestamp(datetime(2026, 10, 1, 8, 24, 6, tzinfo=UTC))
    t1 = UtcTimestamp(datetime(2026, 10, 1, 8, 24, 13, tzinfo=UTC))

    body = _content_json("pit-example", title="PIT worked example")
    await ingest((_fetcher("/government/news/pit-example", body, t1),))
    await session.commit()

    identity = NewsSourceIdentity(SOURCE_KEY, _content_id("pit-example"))
    item = await repository.get_item_by_source_identity(identity)
    assert item is not None

    between_t0_and_t1 = UtcTimestamp(datetime(2026, 10, 1, 8, 24, 10, tzinfo=UTC))
    assert t0.value < between_t0_and_t1.value < t1.value
    assert await repository.latest_vintage_as_of(item.news_item_key, between_t0_and_t1) is None

    at_t1 = await repository.latest_vintage_as_of(item.news_item_key, t1)
    assert at_t1 is not None
    assert at_t1.headline == "PIT worked example"

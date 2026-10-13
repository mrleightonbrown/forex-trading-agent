"""FX-63H Section H1: real-Postgres integration tests for `infra
structure.news_sources.acquisition_observation_wiring.make_acquisition_
recorder` -- proves the recorder's own observation write uses a
genuinely INDEPENDENT session/transaction, never the caller's own
session used for NewsItem persistence. A caller's pending, uncommitted
NewsItem write must remain uncommitted (invisible to any other
session) after the recorder's own commit -- the exact invariant that
would be violated if the recorder shared a session with the caller.

Requires a live Postgres with migration `d8995cb04276` applied (the
current head)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.source_acquisition_outcome import SourceAcquisitionOutcome
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.models.source_operational_observation import (
    SourceOperationalObservationRow,
)
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.news_sources.acquisition_observation_wiring import (
    make_acquisition_recorder,
)
from forex_agent.infrastructure.news_sources.http_fetch import (
    FetchAttemptOutcome,
    FetchAttemptOutcomeKind,
)

TEST_SOURCE_KEY = "__fx63h_wiring_test__"
TEST_NEWS_SOURCE_KEY = "__fx63h_wiring_test_news__"


def _ts(hour: int, minute: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, minute, tzinfo=UTC))


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    yield factory

    async with factory() as cleanup_session:
        await cleanup_session.execute(
            delete(SourceOperationalObservationRow).where(
                SourceOperationalObservationRow.source_key == TEST_SOURCE_KEY
            )
        )
        item_keys = (
            (
                await cleanup_session.execute(
                    delete(NewsSourceMappingRow)
                    .where(NewsSourceMappingRow.source_key == TEST_NEWS_SOURCE_KEY)
                    .returning(NewsSourceMappingRow.news_item_key)
                )
            )
            .scalars()
            .all()
        )
        for key in item_keys:
            await cleanup_session.execute(
                delete(NewsItemVintageRow).where(NewsItemVintageRow.news_item_key == key)
            )
            await cleanup_session.execute(
                delete(NewsItemRow).where(NewsItemRow.news_item_key == key)
            )
        await cleanup_session.commit()


async def test_recorder_commit_does_not_commit_unrelated_pending_news_item_write(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as outer_session:
        news_repo = SqlAlchemyNewsRepository(outer_session)
        registration = await news_repo._register_source_item_for_test_setup(
            NewsSourceIdentity(source_key=TEST_NEWS_SOURCE_KEY, external_item_id="item1"),
            _ts(8),
            NewsObservationMode.PROSPECTIVE,
        )
        # A SECOND, deliberately UNCOMMITTED vintage insert on the SAME
        # outer session -- `_register_source_item_for_test_setup` above
        # already committed the item+mapping; this vintage insert is
        # issued directly (bypassing `add_vintage`'s own auto-commit)
        # so it stays genuinely pending on `outer_session`.
        vintage = NewsItemVintage(
            news_item_key=registration.news_item_key,
            revision_sequence=0,
            availability=_ts(8),
            observation_mode=NewsObservationMode.PROSPECTIVE,
            headline="pending, never committed",
            source_channel="test_channel",
            observed_source_channels=("test_channel",),
            source_status=NewsSourceStatus.ACTIVE,
            evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        )
        outer_session.add(
            NewsItemVintageRow(
                news_item_key=vintage.news_item_key,
                revision_sequence=vintage.revision_sequence,
                availability=vintage.availability.value,
                observation_mode=vintage.observation_mode.value,
                headline=vintage.headline,
                source_channel=vintage.source_channel,
                observed_source_channels=list(vintage.observed_source_channels),
                source_status=vintage.source_status.value,
                evidence_disposition=vintage.evidence_disposition.value,
            )
        )
        await outer_session.flush()  # visible within this session, still UNCOMMITTED

        recorder = make_acquisition_recorder(session_factory)
        await recorder(
            TEST_SOURCE_KEY,
            "test_channel",
            "run-isolation-1",
            FetchAttemptOutcome(1, FetchAttemptOutcomeKind.SUCCESS, 200, _ts(9)),
        )

        async with session_factory() as check_session:
            observation_rows = (
                (
                    await check_session.execute(
                        select(SourceOperationalObservationRow).where(
                            SourceOperationalObservationRow.source_key == TEST_SOURCE_KEY
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(observation_rows) == 1  # the recorder's own write IS durably committed

            pending_vintage_rows = (
                (
                    await check_session.execute(
                        select(NewsItemVintageRow).where(
                            NewsItemVintageRow.news_item_key == registration.news_item_key,
                            NewsItemVintageRow.revision_sequence == 0,
                        )
                    )
                )
                .scalars()
                .all()
            )
            # The pending vintage insert on `outer_session` was NEVER
            # committed -- a shared-session bug would have let the
            # recorder's own commit() durably commit this too.
            assert len(pending_vintage_rows) == 0

        await outer_session.rollback()


async def test_recorder_write_succeeds_through_the_real_stack(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    recorder = make_acquisition_recorder(session_factory)

    await recorder(
        TEST_SOURCE_KEY,
        "test_channel",
        "run-real-stack",
        FetchAttemptOutcome(1, FetchAttemptOutcomeKind.HTTP_FAILURE, 503, _ts(9)),
    )

    async with session_factory() as check_session:
        rows = (
            (
                await check_session.execute(
                    select(SourceOperationalObservationRow).where(
                        SourceOperationalObservationRow.source_key == TEST_SOURCE_KEY
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].outcome == SourceAcquisitionOutcome.HTTP_FAILURE.value

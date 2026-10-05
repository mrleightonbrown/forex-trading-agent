"""FX-56: `SqlAlchemyNewsRepository` round-trip, point-in-time query,
and atomic-registration tests against live Postgres.

Requires a live Postgres with the FX-56 migration applied -- run
`docker compose up -d db && alembic upgrade head` first.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.ports.news_repository import (
    NewsItemRegistrationOutcome,
    NewsVintageConflictError,
    NewsVintageWriteOutcome,
)
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.news_source_revision_fact import (
    NewsSourceRevisionFact,
    NewsSourceRevisionKind,
)
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.news_source_timestamp_provenance import NewsSourceTimestampProvenance
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine

TEST_SOURCE_KEY = "__test_source__"
# `mint_news_item_key` always prefixes with the registering identity's
# own `source_key` (see `domain.news_item_identity`), so every item
# minted by this test module's own identities starts with this same
# prefix -- NOT a separately-invented one, which would silently leave
# every test item/vintage row behind forever (caught by inspecting the
# dev DB directly after a full test run).
TEST_ITEM_PREFIX = TEST_SOURCE_KEY


def _ts(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, minute, second, tzinfo=UTC))


def _identity(external_item_id: str) -> NewsSourceIdentity:
    return NewsSourceIdentity(source_key=TEST_SOURCE_KEY, external_item_id=external_item_id)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        await cleanup_session.execute(
            delete(NewsItemVintageRow).where(
                NewsItemVintageRow.news_item_key.startswith(TEST_ITEM_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(NewsSourceMappingRow).where(
                NewsSourceMappingRow.source_key.startswith(TEST_SOURCE_KEY)
            )
        )
        await cleanup_session.execute(
            delete(NewsItemRow).where(NewsItemRow.news_item_key.startswith(TEST_ITEM_PREFIX))
        )
        await cleanup_session.commit()


@pytest.fixture
def repo(session: AsyncSession) -> SqlAlchemyNewsRepository:
    return SqlAlchemyNewsRepository(session)


# --- Registration / identity ------------------------------------------------
#
# FX-56H.1: every call below goes through `_register_source_item_for_
# test_setup`, a PRIVATE, test-only helper -- NOT a public operation
# on the `NewsRepository` port. These tests exercise bare identity
# resolution (item+mapping, no vintage) as a repository-level unit in
# its own right (in particular the identity-race handling shared with
# the real public creating operation); they deliberately do NOT
# represent a state any production code path can produce, since
# `RecordNewsObservation` only ever creates an item together with its
# own revision 0, via `register_source_item_with_first_vintage`.


async def test_bare_identity_registration_creates_new_item_and_mapping(
    repo: SqlAlchemyNewsRepository,
) -> None:
    observed_at = _ts(2026, 9, 29, 9, 2)
    result = await repo._register_source_item_for_test_setup(
        _identity("fed-001"), observed_at, NewsObservationMode.PROSPECTIVE
    )
    assert result.outcome is NewsItemRegistrationOutcome.CREATED
    assert result.first_seen_at == observed_at
    assert result.news_item_key.startswith(TEST_SOURCE_KEY)

    item = await repo.get_item(result.news_item_key)
    assert item is not None
    assert item.first_seen_at == observed_at
    assert item.first_observation_mode is NewsObservationMode.PROSPECTIVE


async def test_bare_identity_registration_is_idempotent_for_repeat_call(
    repo: SqlAlchemyNewsRepository,
) -> None:
    first_observed = _ts(2026, 9, 29, 9, 2)
    first = await repo._register_source_item_for_test_setup(
        _identity("fed-002"), first_observed, NewsObservationMode.PROSPECTIVE
    )

    later_poll = _ts(2026, 9, 29, 9, 5)
    second = await repo._register_source_item_for_test_setup(
        _identity("fed-002"), later_poll, NewsObservationMode.PROSPECTIVE
    )

    assert second.outcome is NewsItemRegistrationOutcome.ALREADY_EXISTS
    assert second.news_item_key == first.news_item_key
    # The item's real first_seen_at is the FIRST observation, never the
    # later poll's own observed_at (FX-56 Section 33).
    assert second.first_seen_at == first_observed


async def test_different_source_keys_never_collapse_identity(
    repo: SqlAlchemyNewsRepository,
) -> None:
    # FX-56 Section 36: same external ID under two different sources
    # must resolve to two different items.
    observed_at = _ts(2026, 9, 29, 9, 2)
    a = await repo._register_source_item_for_test_setup(
        NewsSourceIdentity(source_key=TEST_SOURCE_KEY, external_item_id="shared-id"),
        observed_at,
        NewsObservationMode.PROSPECTIVE,
    )
    b = await repo._register_source_item_for_test_setup(
        NewsSourceIdentity(source_key=f"{TEST_SOURCE_KEY}_other", external_item_id="shared-id"),
        observed_at,
        NewsObservationMode.PROSPECTIVE,
    )
    assert a.news_item_key != b.news_item_key


async def test_get_item_by_source_identity_returns_none_when_unregistered(
    repo: SqlAlchemyNewsRepository,
) -> None:
    assert await repo.get_item_by_source_identity(_identity("never-seen")) is None


async def test_get_item_by_source_identity_resolves_after_registration(
    repo: SqlAlchemyNewsRepository,
) -> None:
    observed_at = _ts(2026, 9, 29, 9, 2)
    registration = await repo._register_source_item_for_test_setup(
        _identity("fed-003"), observed_at, NewsObservationMode.PROSPECTIVE
    )
    item = await repo.get_item_by_source_identity(_identity("fed-003"))
    assert item is not None
    assert item.news_item_key == registration.news_item_key


async def test_concurrent_first_registration_resolves_to_one_item() -> None:
    """FX-56 Section 11/71, strengthened by FX-56H Section 5: two
    sessions racing to register the SAME, never-before-seen external
    identity must resolve to exactly ONE durable `NewsItem`, with NO
    orphan item -- not merely "the winning key's own row count is 1,"
    but "no second candidate item, under ANY key, survived the race
    at all." Uses a dedicated `source_key` (not shared with any other
    test in this module) so the orphan check below can safely count
    every `news_items` row under that prefix without risking a false
    pass/fail from unrelated test data. Uses two real, independent
    connections against live Postgres -- Postgres's own row lock on
    the mapping table's unique index serializes the two transactions
    correctly regardless of exact timing, so this is deterministic in
    OUTCOME even though which session "wins" is not.

    Deliberately exercises the PRIVATE `_register_source_item_for_
    test_setup` helper, in isolation from vintage concerns, to pin the
    identity-race handling (`_insert_item_and_mapping`) that the real
    public creating operation, `register_source_item_with_first_
    vintage`, shares with it (FX-56H.1) -- see `test_record_news_
    observation.py::test_concurrent_complete_first_observations_
    leave_exactly_one_of_each` for the equivalent proof through the
    actual production path."""
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    race_source_key = f"{TEST_SOURCE_KEY}_race1"
    identity = NewsSourceIdentity(source_key=race_source_key, external_item_id="race-item")
    observed_at = _ts(2026, 9, 29, 9, 2)

    async def _register() -> str:
        async with session_factory() as own_session:
            repo = SqlAlchemyNewsRepository(own_session)
            result = await repo._register_source_item_for_test_setup(
                identity, observed_at, NewsObservationMode.PROSPECTIVE
            )
            return result.news_item_key

    try:
        key_a, key_b = await asyncio.gather(_register(), _register())
        assert key_a == key_b

        async with session_factory() as check_session:
            # Every `news_items` row ever minted under THIS test's own
            # dedicated source_key prefix -- not just a count filtered
            # to the winning key -- so a surviving orphan candidate
            # (under a DIFFERENT, losing uuid suffix) cannot hide from
            # this assertion the way a `WHERE news_item_key = :key`
            # count would let it.
            all_items_under_prefix: Sequence[object] = (
                (
                    await check_session.execute(
                        text(
                            "SELECT news_item_key FROM news_items WHERE news_item_key LIKE :pattern"
                        ),
                        {"pattern": f"{race_source_key}:%"},
                    )
                )
                .scalars()
                .all()
            )
            mapping_count: int = (
                await check_session.execute(
                    text(
                        "SELECT COUNT(*) FROM news_source_mappings "
                        "WHERE source_key = :source_key AND external_item_id = :external_item_id"
                    ),
                    {
                        "source_key": identity.source_key,
                        "external_item_id": identity.external_item_id,
                    },
                )
            ).scalar_one()
            assert all_items_under_prefix == [key_a]
            assert mapping_count == 1
    finally:
        async with session_factory() as cleanup_session:
            await cleanup_session.execute(
                delete(NewsSourceMappingRow).where(
                    NewsSourceMappingRow.source_key == race_source_key
                )
            )
            await cleanup_session.execute(
                delete(NewsItemRow).where(NewsItemRow.news_item_key.startswith(race_source_key))
            )
            await cleanup_session.commit()


# --- Vintages / round-trip --------------------------------------------------


async def test_add_vintage_round_trip_with_full_fields(
    repo: SqlAlchemyNewsRepository,
) -> None:
    registration = await repo._register_source_item_for_test_setup(
        _identity("fed-004"), _ts(2026, 9, 29, 9, 2), NewsObservationMode.PROSPECTIVE
    )
    provenance = NewsSourceTimestampProvenance(
        field_name="dc:date",
        raw_value="2026-09-02T09:45:53+00:00",
        normalized_at=_ts(2026, 9, 2, 13, 45, 53),
        normalization_note="raw value mislabels America/Toronto local time as +00:00",
    )
    revision_fact = NewsSourceRevisionFact(
        kind=NewsSourceRevisionKind.UPDATE,
        source_timestamp=_ts(2026, 9, 28, 15, 56, 37),
        raw_timestamp="2026-09-28T15:56:37Z",
        note="First published.",
    )
    vintage = NewsItemVintage(
        news_item_key=registration.news_item_key,
        revision_sequence=0,
        availability=_ts(2026, 9, 29, 9, 2),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="Federal Reserve issues FOMC statement",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        summary="The Committee decided to maintain the target range.",
        body_text="Full statement text here.",
        canonical_url="https://www.federalreserve.gov/newsevents/pressreleases/monetary20260929a.htm",
        authors=("Board of Governors",),
        language="en",
        source_content_type="press_release",
        source_published_at=_ts(2026, 9, 29, 9, 0),
        source_updated_at=None,
        source_timestamp_provenance=(provenance,),
        source_revision_metadata=(revision_fact,),
    )
    outcome = await repo.add_vintage(vintage)
    assert outcome is NewsVintageWriteOutcome.INSERTED

    vintages = await repo.list_vintages(registration.news_item_key)
    assert len(vintages) == 1
    round_tripped = vintages[0]
    assert round_tripped == vintage


async def test_add_vintage_is_idempotent_for_exact_duplicate(
    repo: SqlAlchemyNewsRepository,
) -> None:
    registration = await repo._register_source_item_for_test_setup(
        _identity("fed-005"), _ts(2026, 9, 29, 9, 2), NewsObservationMode.PROSPECTIVE
    )
    vintage = NewsItemVintage(
        news_item_key=registration.news_item_key,
        revision_sequence=0,
        availability=_ts(2026, 9, 29, 9, 2),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="Same headline",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    )
    assert await repo.add_vintage(vintage) is NewsVintageWriteOutcome.INSERTED
    assert await repo.add_vintage(vintage) is NewsVintageWriteOutcome.ALREADY_PRESENT

    vintages = await repo.list_vintages(registration.news_item_key)
    assert len(vintages) == 1


async def test_add_vintage_conflict_raises_on_different_payload_same_identity(
    repo: SqlAlchemyNewsRepository,
) -> None:
    registration = await repo._register_source_item_for_test_setup(
        _identity("fed-006"), _ts(2026, 9, 29, 9, 2), NewsObservationMode.PROSPECTIVE
    )
    first = NewsItemVintage(
        news_item_key=registration.news_item_key,
        revision_sequence=0,
        availability=_ts(2026, 9, 29, 9, 2),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="Headline A",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    )
    conflicting = NewsItemVintage(
        news_item_key=registration.news_item_key,
        revision_sequence=0,
        availability=_ts(2026, 9, 29, 9, 2),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="Headline B",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    )
    await repo.add_vintage(first)
    with pytest.raises(NewsVintageConflictError):
        await repo.add_vintage(conflicting)


async def test_vintage_requires_an_existing_item_fk(repo: SqlAlchemyNewsRepository) -> None:
    orphan_vintage = NewsItemVintage(
        news_item_key=f"{TEST_ITEM_PREFIX}:does-not-exist",
        revision_sequence=0,
        availability=_ts(2026, 9, 29, 9, 2),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="Orphan",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    )
    with pytest.raises(IntegrityError):
        await repo.add_vintage(orphan_vintage)


# --- Point-in-time queries ---------------------------------------------------


async def test_correction_pit_example(repo: SqlAlchemyNewsRepository) -> None:
    # FX-56 Section 48's own worked example.
    registration = await repo._register_source_item_for_test_setup(
        _identity("fed-007"), _ts(2026, 9, 29, 9, 0), NewsObservationMode.PROSPECTIVE
    )
    news_item_key = registration.news_item_key
    revision_0 = NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=0,
        availability=_ts(2026, 9, 29, 9, 0),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="Original headline",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        source_updated_at=_ts(2026, 9, 29, 9, 10),
    )
    await repo.add_vintage(revision_0)

    revision_1 = NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=1,
        availability=_ts(2026, 9, 29, 9, 14),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="Corrected headline",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        source_updated_at=_ts(2026, 9, 29, 9, 10),
    )
    await repo.add_vintage(revision_1)

    as_of_before = _ts(2026, 9, 29, 9, 12)
    result_before = await repo.latest_vintage_as_of(news_item_key, as_of_before)
    assert result_before is not None
    assert result_before.headline == "Original headline"

    as_of_after = _ts(2026, 9, 29, 9, 15)
    result_after = await repo.latest_vintage_as_of(news_item_key, as_of_after)
    assert result_after is not None
    assert result_after.headline == "Corrected headline"


async def test_latest_vintage_as_of_returns_none_before_first_seen(
    repo: SqlAlchemyNewsRepository,
) -> None:
    registration = await repo._register_source_item_for_test_setup(
        _identity("fed-008"), _ts(2026, 9, 29, 9, 2), NewsObservationMode.PROSPECTIVE
    )
    vintage = NewsItemVintage(
        news_item_key=registration.news_item_key,
        revision_sequence=0,
        availability=_ts(2026, 9, 29, 9, 2),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="Headline",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    )
    await repo.add_vintage(vintage)

    result = await repo.latest_vintage_as_of(registration.news_item_key, _ts(2026, 9, 29, 9, 1))
    assert result is None


async def test_withdrawal_pit_example(repo: SqlAlchemyNewsRepository) -> None:
    # FX-56 Section 47's own worked example.
    registration = await repo._register_source_item_for_test_setup(
        _identity("boc-001"), _ts(2026, 9, 29, 10, 0), NewsObservationMode.PROSPECTIVE
    )
    news_item_key = registration.news_item_key
    active = NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=0,
        availability=_ts(2026, 9, 29, 10, 0),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="Policy statement",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    )
    await repo.add_vintage(active)

    withdrawn = NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=1,
        availability=_ts(2026, 9, 29, 10, 8),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="Policy statement",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.WITHDRAWN,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        source_revision_metadata=(
            NewsSourceRevisionFact(
                kind=NewsSourceRevisionKind.WITHDRAWAL,
                source_timestamp=_ts(2026, 9, 29, 10, 5),
            ),
        ),
    )
    await repo.add_vintage(withdrawn)

    before = await repo.latest_vintage_as_of(news_item_key, _ts(2026, 9, 29, 10, 6))
    assert before is not None
    assert before.source_status is NewsSourceStatus.ACTIVE

    after = await repo.latest_vintage_as_of(news_item_key, _ts(2026, 9, 29, 10, 9))
    assert after is not None
    assert after.source_status is NewsSourceStatus.WITHDRAWN
    # The withdrawal must never be backdated to the source's own claim.
    assert after.availability == _ts(2026, 9, 29, 10, 8)


async def test_evidence_eligible_query_excludes_quarantined(
    repo: SqlAlchemyNewsRepository,
) -> None:
    # FX-56 Section 46's own worked example.
    registration = await repo._register_source_item_for_test_setup(
        _identity("boc-002"), _ts(2026, 9, 29, 10, 0), NewsObservationMode.PROSPECTIVE
    )
    news_item_key = registration.news_item_key
    quarantined = NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=0,
        availability=_ts(2026, 9, 29, 10, 0),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="Suspicious speech listing",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.QUARANTINED,
        quarantine_reason="future_source_timestamp",
    )
    await repo.add_vintage(quarantined)

    eligible = NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=1,
        availability=_ts(2026, 9, 29, 10, 20),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="Speech transcript",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    )
    await repo.add_vintage(eligible)

    as_of_10_10 = _ts(2026, 9, 29, 10, 10)
    assert (await repo.latest_vintage_as_of(news_item_key, as_of_10_10)) is not None
    assert (await repo.latest_evidence_eligible_vintage_as_of(news_item_key, as_of_10_10)) is None

    as_of_10_30 = _ts(2026, 9, 29, 10, 30)
    generic_result = await repo.latest_vintage_as_of(news_item_key, as_of_10_30)
    eligible_result = await repo.latest_evidence_eligible_vintage_as_of(news_item_key, as_of_10_30)
    assert generic_result is not None
    assert eligible_result is not None
    assert generic_result.revision_sequence == eligible_result.revision_sequence == 1


async def test_evidence_eligible_query_excludes_backfill_by_default(
    repo: SqlAlchemyNewsRepository,
) -> None:
    # FX-56 Section 28/50/74's own guardrail -- no backfill adapter
    # exists yet, but the structural capability must already work.
    registration = await repo._register_source_item_for_test_setup(
        _identity("boc-003"), _ts(2027, 1, 10, 0, 0), NewsObservationMode.BACKFILL
    )
    news_item_key = registration.news_item_key
    backfilled = NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=0,
        availability=_ts(2027, 1, 10, 0, 0),
        observation_mode=NewsObservationMode.BACKFILL,
        headline="Historically-imported article",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        source_published_at=_ts(2023, 4, 1),
    )
    await repo.add_vintage(backfilled)

    historical_as_of = _ts(2023, 4, 2)
    assert (await repo.latest_vintage_as_of(news_item_key, historical_as_of)) is None

    prospective_only = await repo.latest_evidence_eligible_vintage_as_of(
        news_item_key, _ts(2027, 1, 11, 0, 0), include_backfill=False
    )
    assert prospective_only is None

    including_backfill = await repo.latest_evidence_eligible_vintage_as_of(
        news_item_key, _ts(2027, 1, 11, 0, 0), include_backfill=True
    )
    assert including_backfill is not None
    assert including_backfill.observation_mode is NewsObservationMode.BACKFILL


async def test_first_poll_after_corrections_creates_only_one_revision(
    repo: SqlAlchemyNewsRepository,
) -> None:
    # FX-56 Section 49's own worked example: a source's own correction
    # history must never fabricate FTA vintages FTA did not observe.
    registration = await repo._register_source_item_for_test_setup(
        _identity("govuk-001"), _ts(2026, 9, 29, 9, 15), NewsObservationMode.PROSPECTIVE
    )
    news_item_key = registration.news_item_key
    only_observation = NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=0,
        availability=_ts(2026, 9, 29, 9, 15),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="News story",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        source_revision_metadata=(
            NewsSourceRevisionFact(kind=NewsSourceRevisionKind.OTHER, note="First published."),
            NewsSourceRevisionFact(
                kind=NewsSourceRevisionKind.CORRECTION, note="08:30 correction."
            ),
            NewsSourceRevisionFact(
                kind=NewsSourceRevisionKind.CORRECTION, note="09:00 correction."
            ),
        ),
    )
    await repo.add_vintage(only_observation)

    vintages = await repo.list_vintages(news_item_key)
    assert len(vintages) == 1
    assert vintages[0].revision_sequence == 0
    assert vintages[0].availability == _ts(2026, 9, 29, 9, 15)
    assert len(vintages[0].source_revision_metadata) == 3


async def test_malformed_authors_json_fails_loudly_on_read(
    repo: SqlAlchemyNewsRepository, session: AsyncSession
) -> None:
    from forex_agent.infrastructure.db.news_repository import MalformedNewsVintageRowError

    registration = await repo._register_source_item_for_test_setup(
        _identity("fed-malformed"), _ts(2026, 9, 29, 9, 2), NewsObservationMode.PROSPECTIVE
    )
    vintage = NewsItemVintage(
        news_item_key=registration.news_item_key,
        revision_sequence=0,
        availability=_ts(2026, 9, 29, 9, 2),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="Headline",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    )
    await repo.add_vintage(vintage)

    # Bypass the domain constructor entirely to simulate a corrupted
    # row -- this must be caught on READ, not silently coerced.
    await session.execute(
        text(
            "UPDATE news_item_vintages SET authors = '\"not-a-list\"'::jsonb "
            "WHERE news_item_key = :key"
        ),
        {"key": registration.news_item_key},
    )
    await session.commit()

    with pytest.raises(MalformedNewsVintageRowError):
        await repo.list_vintages(registration.news_item_key)


# --- DB constraint hardening (FX-56H Section 8/11) --------------------------


async def test_db_rejects_negative_revision_sequence_via_raw_sql(
    repo: SqlAlchemyNewsRepository, session: AsyncSession
) -> None:
    registration = await repo._register_source_item_for_test_setup(
        _identity("constraint-revseq"), _ts(2026, 9, 29, 9, 2), NewsObservationMode.PROSPECTIVE
    )
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO news_item_vintages "
                "(news_item_key, revision_sequence, availability, observation_mode, "
                "headline, source_status, evidence_disposition) "
                "VALUES (:key, -1, now(), 'PROSPECTIVE', 'x', 'ACTIVE', 'EVIDENCE_ELIGIBLE')"
            ),
            {"key": registration.news_item_key},
        )
    await session.rollback()


async def test_db_rejects_invalid_observation_mode_via_raw_sql(
    repo: SqlAlchemyNewsRepository, session: AsyncSession
) -> None:
    registration = await repo._register_source_item_for_test_setup(
        _identity("constraint-obsmode"), _ts(2026, 9, 29, 9, 2), NewsObservationMode.PROSPECTIVE
    )
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO news_item_vintages "
                "(news_item_key, revision_sequence, availability, observation_mode, "
                "headline, source_status, evidence_disposition) "
                "VALUES (:key, 0, now(), 'BOGUS_MODE', 'x', 'ACTIVE', 'EVIDENCE_ELIGIBLE')"
            ),
            {"key": registration.news_item_key},
        )
    await session.rollback()


async def test_db_rejects_invalid_source_status_via_raw_sql(
    repo: SqlAlchemyNewsRepository, session: AsyncSession
) -> None:
    registration = await repo._register_source_item_for_test_setup(
        _identity("constraint-sourcestatus"),
        _ts(2026, 9, 29, 9, 2),
        NewsObservationMode.PROSPECTIVE,
    )
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO news_item_vintages "
                "(news_item_key, revision_sequence, availability, observation_mode, "
                "headline, source_status, evidence_disposition) "
                "VALUES (:key, 0, now(), 'PROSPECTIVE', 'x', 'BOGUS_STATUS', 'EVIDENCE_ELIGIBLE')"
            ),
            {"key": registration.news_item_key},
        )
    await session.rollback()


async def test_db_rejects_invalid_evidence_disposition_via_raw_sql(
    repo: SqlAlchemyNewsRepository, session: AsyncSession
) -> None:
    registration = await repo._register_source_item_for_test_setup(
        _identity("constraint-disposition"),
        _ts(2026, 9, 29, 9, 2),
        NewsObservationMode.PROSPECTIVE,
    )
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO news_item_vintages "
                "(news_item_key, revision_sequence, availability, observation_mode, "
                "headline, source_status, evidence_disposition) "
                "VALUES (:key, 0, now(), 'PROSPECTIVE', 'x', 'ACTIVE', 'BOGUS_DISPOSITION')"
            ),
            {"key": registration.news_item_key},
        )
    await session.rollback()


async def test_db_rejects_invalid_first_observation_mode_via_raw_sql(
    session: AsyncSession,
) -> None:
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO news_items (news_item_key, first_seen_at, first_observation_mode) "
                "VALUES (:key, now(), 'BOGUS_MODE')"
            ),
            {"key": f"{TEST_SOURCE_KEY}:constraint-item-mode"},
        )
    await session.rollback()

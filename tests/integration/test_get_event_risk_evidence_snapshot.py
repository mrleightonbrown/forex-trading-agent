"""FX-54: end-to-end integration tests for `GetEventRiskEvidenceSnapshot`
against live Postgres, using `SqlAlchemyEconomicEventRepository` and
real canonical indicator registry entries (GBP_GDP_QOQ,
US_NONFARM_PAYROLLS, US_UNEMPLOYMENT_RATE, CAD_POLICY_RATE_DECISION,
US_CPI_YOY) -- pair-relevance filtering depends on genuine registry
resolution, so a fake/unrecognized indicator key would not exercise it.

No live network calls are made anywhere in this file -- all event data
is persisted directly via the repository, exactly like every other
FX-51/FX-52A integration test in this project; `tests/integration/
test_*_source_live.py` (marked `live_source`) remain the only tests in
this project that touch a real external calendar feed.

Requires a live Postgres with the FX-54 schema applied — run
`docker compose up -d db && uv run alembic upgrade head` first.
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.get_event_risk_evidence_snapshot import (
    GetEventRiskEvidenceSnapshot,
)
from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_occurrence import EconomicEventOccurrence
from forex_agent.domain.economic_event_release_vintage import EconomicEventReleaseVintage
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.event_risk_evidence_snapshot import EventRiskEvidenceSnapshot
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.pair_currency_role import PairCurrencyRole
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.economic_event_repository import (
    SqlAlchemyEconomicEventRepository,
)
from forex_agent.infrastructure.db.models.economic_event_actual_value_vintage import (
    EconomicEventActualValueVintageRow,
)
from forex_agent.infrastructure.db.models.economic_event_consensus_vintage import (
    EconomicEventConsensusVintageRow,
)
from forex_agent.infrastructure.db.models.economic_event_occurrence import (
    EconomicEventOccurrenceRow,
)
from forex_agent.infrastructure.db.models.economic_event_release_vintage import (
    EconomicEventReleaseVintageRow,
)
from forex_agent.infrastructure.db.models.economic_event_schedule_vintage import (
    EconomicEventScheduleVintageRow,
)
from forex_agent.infrastructure.db.session import get_engine

TEST_OCCURRENCE_PREFIX = "__fx54_test_occ__"


def _ts(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, minute, tzinfo=UTC))


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        for row_type in (
            EconomicEventScheduleVintageRow,
            EconomicEventConsensusVintageRow,
            EconomicEventActualValueVintageRow,
            EconomicEventReleaseVintageRow,
        ):
            await cleanup_session.execute(
                delete(row_type).where(row_type.occurrence_key.startswith(TEST_OCCURRENCE_PREFIX))
            )
        await cleanup_session.execute(
            delete(EconomicEventOccurrenceRow).where(
                EconomicEventOccurrenceRow.occurrence_key.startswith(TEST_OCCURRENCE_PREFIX)
            )
        )
        await cleanup_session.commit()


def _occurrence(
    key: str, indicator_key: str, release_group_key: str | None = None
) -> EconomicEventOccurrence:
    return EconomicEventOccurrence(
        occurrence_key=key, indicator_key=indicator_key, release_group_key=release_group_key
    )


def _schedule(
    key: str,
    revision_sequence: int,
    scheduled_date: date,
    availability: UtcTimestamp,
    scheduled_time: time | None = time(9, 0),
    timezone: str = "UTC",
    status: EconomicEventStatus = EconomicEventStatus.SCHEDULED,
) -> EconomicEventScheduleVintage:
    return EconomicEventScheduleVintage(
        occurrence_key=key,
        revision_sequence=revision_sequence,
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        schedule_timezone=timezone,
        status=status,
        availability=availability,
        availability_confidence=AvailabilityConfidence.VERIFIED,
        source="test",
    )


def _release(
    key: str,
    revision_sequence: int,
    released_date: date,
    availability: UtcTimestamp,
    released_time: time | None = time(9, 0),
    timezone: str = "UTC",
    source_published_at: UtcTimestamp | None = None,
) -> EconomicEventReleaseVintage:
    return EconomicEventReleaseVintage(
        occurrence_key=key,
        revision_sequence=revision_sequence,
        released_date=released_date,
        released_time=released_time,
        released_timezone=timezone,
        availability=availability,
        availability_confidence=AvailabilityConfidence.VERIFIED,
        source="test",
        source_published_at=source_published_at,
    )


# ---------------------------------------------------------------------------
# Pair filtering (FX-54 Section 5/38)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gbp_usd_shows_gbp_as_base_and_excludes_cad(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEventRiskEvidenceSnapshot(repo)
    gbp_key = f"{TEST_OCCURRENCE_PREFIX}GBP1"
    cad_key = f"{TEST_OCCURRENCE_PREFIX}CAD1"
    as_of = _ts(2026, 12, 1)
    await repo.add_occurrence(_occurrence(gbp_key, "GBP_GDP_QOQ"))
    await repo.add_occurrence(_occurrence(cad_key, "CAD_POLICY_RATE_DECISION"))
    await repo.add_schedule_vintage(_schedule(gbp_key, 0, date(2026, 12, 10), as_of))
    await repo.add_schedule_vintage(_schedule(cad_key, 0, date(2026, 12, 10), as_of))

    snapshot = await use_case(
        Instrument(base_currency="GBP", quote_currency="USD"),
        as_of,
        lookahead=timedelta(days=30),
        lookback=timedelta(0),
    )

    all_keys = {m.occurrence_key for g in snapshot.upcoming_schedule_groups for m in g.members}
    assert gbp_key in all_keys
    assert cad_key not in all_keys
    gbp_evidence = next(
        m
        for g in snapshot.upcoming_schedule_groups
        for m in g.members
        if m.occurrence_key == gbp_key
    )
    assert gbp_evidence.pair_role is PairCurrencyRole.BASE
    assert gbp_evidence.currency == "GBP"


@pytest.mark.asyncio
async def test_usd_cad_shows_cad_as_quote_and_excludes_gbp(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEventRiskEvidenceSnapshot(repo)
    cad_key = f"{TEST_OCCURRENCE_PREFIX}CAD2"
    gbp_key = f"{TEST_OCCURRENCE_PREFIX}GBP2"
    as_of = _ts(2026, 12, 1)
    await repo.add_occurrence(_occurrence(cad_key, "CAD_POLICY_RATE_DECISION"))
    await repo.add_occurrence(_occurrence(gbp_key, "GBP_GDP_QOQ"))
    await repo.add_schedule_vintage(_schedule(cad_key, 0, date(2026, 12, 10), as_of))
    await repo.add_schedule_vintage(_schedule(gbp_key, 0, date(2026, 12, 10), as_of))

    snapshot = await use_case(
        Instrument(base_currency="USD", quote_currency="CAD"),
        as_of,
        lookahead=timedelta(days=30),
        lookback=timedelta(0),
    )

    all_keys = {m.occurrence_key for g in snapshot.upcoming_schedule_groups for m in g.members}
    assert cad_key in all_keys
    assert gbp_key not in all_keys
    cad_evidence = next(
        m
        for g in snapshot.upcoming_schedule_groups
        for m in g.members
        if m.occurrence_key == cad_key
    )
    assert cad_evidence.pair_role is PairCurrencyRole.QUOTE


@pytest.mark.asyncio
async def test_eur_usd_reports_structural_incompleteness_but_still_returns_usd_evidence(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEventRiskEvidenceSnapshot(repo)
    usd_key = f"{TEST_OCCURRENCE_PREFIX}USD1"
    as_of = _ts(2026, 12, 1)
    await repo.add_occurrence(_occurrence(usd_key, "US_CPI_YOY"))
    await repo.add_schedule_vintage(_schedule(usd_key, 0, date(2026, 12, 10), as_of))

    snapshot = await use_case(
        Instrument(base_currency="EUR", quote_currency="USD"),
        as_of,
        lookahead=timedelta(days=30),
        lookback=timedelta(0),
    )

    assert snapshot.coverage.untracked_pair_currencies == ("EUR",)
    all_keys = {m.occurrence_key for g in snapshot.upcoming_schedule_groups for m in g.members}
    assert usd_key in all_keys


# ---------------------------------------------------------------------------
# PIT semantics (FX-54 Section 7/35/36)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reschedule_does_not_leak_backward_in_time(session: AsyncSession) -> None:
    # FX-54 Section 35's own worked example.
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEventRiskEvidenceSnapshot(repo)
    key = f"{TEST_OCCURRENCE_PREFIX}RESCHED1"
    await repo.add_occurrence(_occurrence(key, "GBP_GDP_QOQ"))
    await repo.add_schedule_vintage(_schedule(key, 0, date(2026, 10, 10), _ts(2026, 9, 1)))
    await repo.add_schedule_vintage(_schedule(key, 1, date(2026, 10, 12), _ts(2026, 9, 5)))

    instrument = Instrument(base_currency="GBP", quote_currency="USD")
    before_reschedule_known = await use_case(
        instrument, _ts(2026, 9, 3), lookahead=timedelta(days=60), lookback=timedelta(0)
    )
    after_reschedule_known = await use_case(
        instrument, _ts(2026, 9, 6), lookahead=timedelta(days=60), lookback=timedelta(0)
    )

    def _scheduled_date_for(snapshot: EventRiskEvidenceSnapshot) -> date:
        member = next(
            m
            for g in snapshot.upcoming_schedule_groups
            for m in g.members
            if m.occurrence_key == key
        )
        return member.scheduled_date

    assert _scheduled_date_for(before_reschedule_known) == date(2026, 10, 10)
    assert _scheduled_date_for(after_reschedule_known) == date(2026, 10, 12)


@pytest.mark.asyncio
async def test_cancellation_does_not_leak_backward_and_is_not_removed(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEventRiskEvidenceSnapshot(repo)
    key = f"{TEST_OCCURRENCE_PREFIX}CANCEL1"
    await repo.add_occurrence(_occurrence(key, "GBP_GDP_QOQ"))
    await repo.add_schedule_vintage(_schedule(key, 0, date(2026, 10, 10), _ts(2026, 9, 1)))
    await repo.add_schedule_vintage(
        _schedule(
            key,
            1,
            date(2026, 10, 10),
            _ts(2026, 9, 5),
            status=EconomicEventStatus.CANCELLED,
        )
    )

    instrument = Instrument(base_currency="GBP", quote_currency="USD")
    before_cancellation = await use_case(
        instrument, _ts(2026, 9, 3), lookahead=timedelta(days=60), lookback=timedelta(0)
    )
    after_cancellation = await use_case(
        instrument, _ts(2026, 9, 6), lookahead=timedelta(days=60), lookback=timedelta(0)
    )

    def _status_for(snapshot: EventRiskEvidenceSnapshot) -> EconomicEventStatus:
        member = next(
            m
            for g in snapshot.upcoming_schedule_groups
            for m in g.members
            if m.occurrence_key == key
        )
        return member.status

    assert _status_for(before_cancellation) is EconomicEventStatus.SCHEDULED
    assert _status_for(after_cancellation) is EconomicEventStatus.CANCELLED


# ---------------------------------------------------------------------------
# Exact vs date-only timing (FX-54 Section 9/10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exact_time_schedule_computes_time_until_event(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEventRiskEvidenceSnapshot(repo)
    key = f"{TEST_OCCURRENCE_PREFIX}EXACT1"
    as_of = _ts(2026, 12, 10, 5, 0)
    await repo.add_occurrence(_occurrence(key, "GBP_GDP_QOQ"))
    await repo.add_schedule_vintage(
        _schedule(key, 0, date(2026, 12, 10), as_of, scheduled_time=time(7, 0))
    )

    snapshot = await use_case(
        Instrument(base_currency="GBP", quote_currency="USD"),
        as_of,
        lookahead=timedelta(hours=24),
        lookback=timedelta(0),
    )

    member = next(
        m for g in snapshot.upcoming_schedule_groups for m in g.members if m.occurrence_key == key
    )
    assert member.exact_scheduled_at_utc == _ts(2026, 12, 10, 7, 0)
    assert member.time_until_event == timedelta(hours=2)


@pytest.mark.asyncio
async def test_date_only_schedule_never_fabricates_instant_but_still_appears(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEventRiskEvidenceSnapshot(repo)
    key = f"{TEST_OCCURRENCE_PREFIX}TBD1"
    as_of = _ts(2026, 12, 1)
    await repo.add_occurrence(_occurrence(key, "GBP_GDP_QOQ"))
    await repo.add_schedule_vintage(
        _schedule(key, 0, date(2026, 12, 10), as_of, scheduled_time=None)
    )

    snapshot = await use_case(
        Instrument(base_currency="GBP", quote_currency="USD"),
        as_of,
        lookahead=timedelta(days=30),
        lookback=timedelta(0),
    )

    member = next(
        m for g in snapshot.upcoming_schedule_groups for m in g.members if m.occurrence_key == key
    )
    assert member.scheduled_time is None
    assert member.exact_scheduled_at_utc is None
    assert member.time_until_event is None


# ---------------------------------------------------------------------------
# Release evidence PIT semantics (FX-54 Section 13/34)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_pit_example_source_published_at_does_not_override_availability(
    session: AsyncSession,
) -> None:
    # FX-54 Section 34's own worked example, exactly: official event
    # date Sep 2; source published 09:47; this system first retrieved
    # it (availability) 09:50. as_of=09:48 must NOT show the release;
    # as_of=09:51 may.
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEventRiskEvidenceSnapshot(repo)
    key = f"{TEST_OCCURRENCE_PREFIX}RELPIT1"
    await repo.add_occurrence(_occurrence(key, "CAD_POLICY_RATE_DECISION"))
    await repo.add_release_vintage(
        _release(
            key,
            0,
            date(2026, 9, 2),
            _ts(2026, 9, 2, 9, 50),
            released_time=None,
            source_published_at=_ts(2026, 9, 2, 9, 47),
        )
    )

    instrument = Instrument(base_currency="USD", quote_currency="CAD")
    at_09_48 = await use_case(
        instrument, _ts(2026, 9, 2, 9, 48), lookahead=timedelta(0), lookback=timedelta(hours=1)
    )
    at_09_51 = await use_case(
        instrument, _ts(2026, 9, 2, 9, 51), lookahead=timedelta(0), lookback=timedelta(hours=1)
    )

    keys_at_09_48 = {m.occurrence_key for g in at_09_48.recent_release_groups for m in g.members}
    keys_at_09_51 = {m.occurrence_key for g in at_09_51.recent_release_groups for m in g.members}
    assert key not in keys_at_09_48
    assert key in keys_at_09_51
    released_member = next(
        m for g in at_09_51.recent_release_groups for m in g.members if m.occurrence_key == key
    )
    assert released_member.source_published_at == _ts(2026, 9, 2, 9, 47)
    assert released_member.exact_released_at_utc is None
    assert released_member.elapsed_since_release is None


@pytest.mark.asyncio
async def test_scheduled_time_passing_does_not_imply_release(session: AsyncSession) -> None:
    # FX-54 Section 12: a schedule with no corresponding release
    # vintage must never produce release evidence, even though its own
    # scheduled instant is in the past relative to as_of.
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEventRiskEvidenceSnapshot(repo)
    key = f"{TEST_OCCURRENCE_PREFIX}NORELEASE1"
    await repo.add_occurrence(_occurrence(key, "GBP_GDP_QOQ"))
    await repo.add_schedule_vintage(
        _schedule(key, 0, date(2026, 9, 1), _ts(2026, 8, 1), scheduled_time=time(9, 0))
    )

    snapshot = await use_case(
        Instrument(base_currency="GBP", quote_currency="USD"),
        _ts(2026, 9, 2),
        lookahead=timedelta(0),
        lookback=timedelta(days=10),
    )

    release_keys = {m.occurrence_key for g in snapshot.recent_release_groups for m in g.members}
    assert key not in release_keys


# ---------------------------------------------------------------------------
# Release groups (FX-54 Section 16/37)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_package_preserves_both_canonical_members(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEventRiskEvidenceSnapshot(repo)
    nfp_key = f"{TEST_OCCURRENCE_PREFIX}NFP1"
    unemployment_key = f"{TEST_OCCURRENCE_PREFIX}UNEMP1"
    group_key = f"{TEST_OCCURRENCE_PREFIX}GROUP1"
    await repo.add_occurrence(
        _occurrence(nfp_key, "US_NONFARM_PAYROLLS", release_group_key=group_key)
    )
    await repo.add_occurrence(
        _occurrence(unemployment_key, "US_UNEMPLOYMENT_RATE", release_group_key=group_key)
    )
    availability = _ts(2026, 9, 4, 8, 35)
    await repo.add_release_vintage(
        _release(nfp_key, 0, date(2026, 9, 4), availability, released_time=time(8, 30))
    )
    await repo.add_release_vintage(
        _release(unemployment_key, 0, date(2026, 9, 4), availability, released_time=time(8, 30))
    )

    snapshot = await use_case(
        Instrument(base_currency="USD", quote_currency="CAD"),
        _ts(2026, 9, 4, 9, 0),
        lookahead=timedelta(0),
        lookback=timedelta(hours=1),
    )

    matching_groups = [g for g in snapshot.recent_release_groups if g.group_key == group_key]
    assert len(matching_groups) == 1
    member_keys = {m.occurrence_key for m in matching_groups[0].members}
    assert member_keys == {nfp_key, unemployment_key}


# ---------------------------------------------------------------------------
# Ordering (FX-54 Section 18)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_groups_are_ordered_chronologically(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEventRiskEvidenceSnapshot(repo)
    later_key = f"{TEST_OCCURRENCE_PREFIX}ORDER_LATER"
    earlier_key = f"{TEST_OCCURRENCE_PREFIX}ORDER_EARLIER"
    as_of = _ts(2026, 12, 1)
    # Inserted out of chronological order deliberately.
    await repo.add_occurrence(_occurrence(later_key, "GBP_GDP_QOQ"))
    await repo.add_schedule_vintage(_schedule(later_key, 0, date(2026, 12, 20), as_of))
    await repo.add_occurrence(_occurrence(earlier_key, "GBP_GDP_QOQ"))
    await repo.add_schedule_vintage(_schedule(earlier_key, 0, date(2026, 12, 10), as_of))

    snapshot = await use_case(
        Instrument(base_currency="GBP", quote_currency="USD"),
        as_of,
        lookahead=timedelta(days=30),
        lookback=timedelta(0),
    )

    test_group_keys = [
        g.group_key
        for g in snapshot.upcoming_schedule_groups
        if g.group_key in (earlier_key, later_key)
    ]
    assert test_group_keys == [earlier_key, later_key]


# ---------------------------------------------------------------------------
# Coverage / absence-is-not-safe (FX-54 Section 19/20)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_evidence_still_carries_coverage_evidence(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEventRiskEvidenceSnapshot(repo)

    snapshot = await use_case(
        Instrument(base_currency="EUR", quote_currency="USD"),
        _ts(2026, 12, 1),
        lookahead=timedelta(hours=1),
        lookback=timedelta(hours=1),
    )

    assert snapshot.upcoming_schedule_groups == ()
    assert snapshot.recent_release_groups == ()
    assert snapshot.coverage.untracked_pair_currencies == ("EUR",)
    assert snapshot.coverage.tracked_indicator_keys_by_currency[1][0] == "USD"
    assert snapshot.coverage.tracked_indicator_keys_by_currency[1][1] != ()

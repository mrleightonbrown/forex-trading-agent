"""FX-54: unit tests for `EventScheduleEvidence`/`build_schedule_evidence`/
`group_schedule_evidence` -- pure domain-layer assembly, grouping, and
ordering, with no repository/database dependency at all."""

from datetime import UTC, date, datetime, time, timedelta

import pytest

from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_occurrence import EconomicEventOccurrence
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.economic_indicator_registry import (
    GBP_GDP_QOQ,
    US_NONFARM_PAYROLLS,
)
from forex_agent.domain.event_schedule_evidence import (
    EventScheduleEvidence,
    build_schedule_evidence,
    group_schedule_evidence,
)
from forex_agent.domain.pair_currency_role import PairCurrencyRole
from forex_agent.domain.timestamps import UtcTimestamp

_AS_OF = UtcTimestamp(datetime(2026, 9, 1, tzinfo=UTC))


def _occurrence(key: str, release_group_key: str | None = None) -> EconomicEventOccurrence:
    return EconomicEventOccurrence(
        occurrence_key=key, indicator_key=GBP_GDP_QOQ.key, release_group_key=release_group_key
    )


def _schedule(
    key: str,
    scheduled_date: date,
    scheduled_time: time | None,
    timezone: str = "Europe/London",
    status: EconomicEventStatus = EconomicEventStatus.SCHEDULED,
) -> EconomicEventScheduleVintage:
    return EconomicEventScheduleVintage(
        occurrence_key=key,
        revision_sequence=0,
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        schedule_timezone=timezone,
        status=status,
        availability=_AS_OF,
        availability_confidence=AvailabilityConfidence.VERIFIED,
        source="test",
    )


def test_exact_time_resolves_instant_and_time_until_event() -> None:
    occurrence = _occurrence("occ1")
    schedule = _schedule("occ1", date(2026, 12, 10), time(7, 0))
    as_of = UtcTimestamp(datetime(2026, 12, 10, 5, 0, tzinfo=UTC))

    evidence = build_schedule_evidence(
        occurrence, schedule, GBP_GDP_QOQ, PairCurrencyRole.BASE, as_of
    )

    # 07:00 Europe/London in December (GMT, UTC+0) == 07:00 UTC.
    assert evidence.exact_scheduled_at_utc == UtcTimestamp(datetime(2026, 12, 10, 7, 0, tzinfo=UTC))
    assert evidence.time_until_event == timedelta(hours=2)
    assert evidence.currency == "GBP"
    assert evidence.pair_role is PairCurrencyRole.BASE
    assert evidence.indicator_key == "GBP_GDP_QOQ"
    assert evidence.display_name == GBP_GDP_QOQ.name
    assert evidence.category == GBP_GDP_QOQ.category


def test_date_only_never_fabricates_instant_or_time_until() -> None:
    occurrence = _occurrence("occ2")
    schedule = _schedule("occ2", date(2026, 12, 10), None)

    evidence = build_schedule_evidence(
        occurrence, schedule, GBP_GDP_QOQ, PairCurrencyRole.QUOTE, _AS_OF
    )

    assert evidence.scheduled_time is None
    assert evidence.exact_scheduled_at_utc is None
    assert evidence.time_until_event is None


def test_cancelled_status_is_preserved_not_removed() -> None:
    occurrence = _occurrence("occ3")
    schedule = _schedule(
        "occ3", date(2026, 12, 10), time(7, 0), status=EconomicEventStatus.CANCELLED
    )

    evidence = build_schedule_evidence(
        occurrence, schedule, GBP_GDP_QOQ, PairCurrencyRole.BASE, _AS_OF
    )

    assert evidence.status is EconomicEventStatus.CANCELLED


def test_reference_period_and_release_group_key_pass_through() -> None:
    occurrence = EconomicEventOccurrence(
        occurrence_key="occ4",
        indicator_key=GBP_GDP_QOQ.key,
        reference_period=UtcTimestamp(datetime(2026, 4, 1, tzinfo=UTC)),
        release_group_key="grp-x",
    )
    schedule = _schedule("occ4", date(2026, 12, 10), time(7, 0))

    evidence = build_schedule_evidence(
        occurrence, schedule, GBP_GDP_QOQ, PairCurrencyRole.BASE, _AS_OF
    )

    assert evidence.reference_period == UtcTimestamp(datetime(2026, 4, 1, tzinfo=UTC))
    assert evidence.release_group_key == "grp-x"


def test_rejects_exact_instant_without_time_until() -> None:
    with pytest.raises(ValueError, match="both be None or both be set"):
        EventScheduleEvidence(
            occurrence_key="occ",
            indicator_key="K",
            display_name="d",
            economy="US",
            currency="USD",
            pair_role=PairCurrencyRole.BASE,
            category=GBP_GDP_QOQ.category,
            reference_period=None,
            release_group_key=None,
            status=EconomicEventStatus.SCHEDULED,
            scheduled_date=date(2026, 1, 1),
            scheduled_time=time(9, 0),
            schedule_timezone="UTC",
            exact_scheduled_at_utc=_AS_OF,
            time_until_event=None,
            availability=_AS_OF,
            availability_confidence=AvailabilityConfidence.VERIFIED,
            source="test",
        )


def test_rejects_exact_instant_when_scheduled_time_is_none() -> None:
    with pytest.raises(ValueError, match="never fabricate an exact instant"):
        EventScheduleEvidence(
            occurrence_key="occ",
            indicator_key="K",
            display_name="d",
            economy="US",
            currency="USD",
            pair_role=PairCurrencyRole.BASE,
            category=GBP_GDP_QOQ.category,
            reference_period=None,
            release_group_key=None,
            status=EconomicEventStatus.SCHEDULED,
            scheduled_date=date(2026, 1, 1),
            scheduled_time=None,
            schedule_timezone="UTC",
            exact_scheduled_at_utc=_AS_OF,
            time_until_event=timedelta(0),
            availability=_AS_OF,
            availability_confidence=AvailabilityConfidence.VERIFIED,
            source="test",
        )


def test_no_risk_or_policy_field_exists() -> None:
    # FX-54 Section 3/27: must never carry an importance/risk/veto field.
    forbidden = {
        "risk_score",
        "severity",
        "importance",
        "should_trade",
        "should_avoid",
        "blackout",
        "safe_to_trade",
    }
    fields = set(EventScheduleEvidence.__dataclass_fields__)
    assert fields.isdisjoint(forbidden)


# --- group_schedule_evidence ---------------------------------------------------


def _evidence(
    occurrence_key: str,
    indicator_key: str = "GBP_GDP_QOQ",
    release_group_key: str | None = None,
    scheduled_date: date = date(2026, 12, 10),
    scheduled_time: time | None = time(7, 0),
) -> EventScheduleEvidence:
    occurrence = EconomicEventOccurrence(
        occurrence_key=occurrence_key,
        indicator_key=indicator_key,
        release_group_key=release_group_key,
    )
    schedule = _schedule(occurrence_key, scheduled_date, scheduled_time)
    indicator = GBP_GDP_QOQ if indicator_key == "GBP_GDP_QOQ" else US_NONFARM_PAYROLLS
    return build_schedule_evidence(occurrence, schedule, indicator, PairCurrencyRole.BASE, _AS_OF)


def test_ungrouped_occurrence_is_its_own_one_member_group() -> None:
    evidence = _evidence("occ1")
    groups = group_schedule_evidence([evidence])

    assert len(groups) == 1
    assert groups[0].group_key == "occ1"
    assert groups[0].members == (evidence,)


def test_shared_release_group_key_produces_one_group_two_members() -> None:
    nfp = _evidence("occ_nfp", indicator_key="US_NONFARM_PAYROLLS", release_group_key="grp-emp")
    unemployment = _evidence(
        "occ_unemp", indicator_key="US_NONFARM_PAYROLLS", release_group_key="grp-emp"
    )

    groups = group_schedule_evidence([nfp, unemployment])

    assert len(groups) == 1
    assert groups[0].group_key == "grp-emp"
    assert len(groups[0].members) == 2
    # Both canonical members preserved individually -- never collapsed.
    assert {m.occurrence_key for m in groups[0].members} == {"occ_nfp", "occ_unemp"}


def test_same_timestamp_without_shared_group_key_does_not_merge() -> None:
    # FX-54 Section 16: grouping is by release_group_key ONLY, never by
    # coincidental matching timestamps.
    one = _evidence("occ1", scheduled_date=date(2026, 12, 10), scheduled_time=time(7, 0))
    two = _evidence("occ2", scheduled_date=date(2026, 12, 10), scheduled_time=time(7, 0))

    groups = group_schedule_evidence([one, two])

    assert len(groups) == 2
    assert {g.group_key for g in groups} == {"occ1", "occ2"}


def test_members_sorted_deterministically_never_by_a_chosen_primary() -> None:
    b_member = _evidence("occ_b", indicator_key="US_NONFARM_PAYROLLS", release_group_key="grp")
    a_member = _evidence("occ_a", indicator_key="US_NONFARM_PAYROLLS", release_group_key="grp")

    groups = group_schedule_evidence([b_member, a_member])

    assert groups[0].members[0].occurrence_key == "occ_a"
    assert groups[0].members[1].occurrence_key == "occ_b"


def test_groups_are_ordered_chronologically() -> None:
    later = _evidence("occ_later", scheduled_date=date(2026, 12, 12), scheduled_time=time(7, 0))
    earlier = _evidence("occ_earlier", scheduled_date=date(2026, 12, 10), scheduled_time=time(7, 0))

    groups = group_schedule_evidence([later, earlier])

    assert [g.group_key for g in groups] == ["occ_earlier", "occ_later"]


def test_date_only_group_orders_by_local_day_start_never_fabricating_an_instant() -> None:
    exact = _evidence("occ_exact", scheduled_date=date(2026, 12, 10), scheduled_time=time(23, 0))
    date_only_earlier_day = _evidence(
        "occ_date_only", scheduled_date=date(2026, 12, 10), scheduled_time=None
    )

    groups = group_schedule_evidence([exact, date_only_earlier_day])

    # Both share 2026-12-10 -- the date-only fact's own local-day START
    # (00:00 Europe/London) is earlier than the exact 23:00 instant, so
    # it sorts first, without ever exposing a fabricated instant on
    # either evidence object itself.
    assert [g.group_key for g in groups] == ["occ_date_only", "occ_exact"]
    assert groups[0].members[0].exact_scheduled_at_utc is None


def test_tie_broken_by_group_key_when_instants_are_equal() -> None:
    one = _evidence("occ_b", scheduled_date=date(2026, 12, 10), scheduled_time=time(7, 0))
    two = _evidence("occ_a", scheduled_date=date(2026, 12, 10), scheduled_time=time(7, 0))

    groups = group_schedule_evidence([one, two])

    assert [g.group_key for g in groups] == ["occ_a", "occ_b"]

"""FX-54V: unit tests for `build_events_view` -- pure, no I/O. Every
field asserted here must be a direct, renamed passthrough of FX-54's
own evidence; this view model must never interpret it."""

from datetime import UTC, date, datetime, time, timedelta

from forex_agent.apps.api.view_models.events_view_model import (
    EMPTY_RELEASE_WINDOW_MESSAGE,
    EMPTY_SCHEDULE_WINDOW_MESSAGE,
    SOURCE_HEALTH_NOTE,
    build_events_view,
)
from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_category import EconomicEventCategory
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.event_coverage_evidence import EventCoverageEvidence
from forex_agent.domain.event_evidence_group import EventEvidenceGroup
from forex_agent.domain.event_release_evidence import EventReleaseEvidence
from forex_agent.domain.event_risk_evidence_snapshot import EventRiskEvidenceSnapshot
from forex_agent.domain.event_schedule_evidence import EventScheduleEvidence
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.pair_currency_role import PairCurrencyRole
from forex_agent.domain.timestamps import UtcTimestamp

_AS_OF = UtcTimestamp(datetime(2026, 9, 1, tzinfo=UTC))
_COVERAGE = EventCoverageEvidence(
    base_currency="GBP",
    quote_currency="USD",
    tracked_indicator_keys_by_currency=(("GBP", ("GBP_GDP_QOQ",)), ("USD", ())),
    untracked_pair_currencies=("USD",),
)


def _schedule_evidence(
    scheduled_time: time | None, exact_utc: UtcTimestamp | None
) -> EventScheduleEvidence:
    return EventScheduleEvidence(
        occurrence_key="occ1",
        indicator_key="GBP_GDP_QOQ",
        display_name="UK GDP Quarterly National Accounts",
        economy="GB",
        currency="GBP",
        pair_role=PairCurrencyRole.BASE,
        category=EconomicEventCategory.GROWTH,
        reference_period=None,
        release_group_key=None,
        status=EconomicEventStatus.SCHEDULED,
        scheduled_date=date(2026, 9, 10),
        scheduled_time=scheduled_time,
        schedule_timezone="Europe/London",
        exact_scheduled_at_utc=exact_utc,
        time_until_event=(None if exact_utc is None else exact_utc.value - _AS_OF.value),
        availability=_AS_OF,
        availability_confidence=AvailabilityConfidence.VERIFIED,
        source="test",
    )


def _snapshot(
    schedule_groups: tuple[EventEvidenceGroup[EventScheduleEvidence], ...] = (),
    release_groups: tuple[EventEvidenceGroup[EventReleaseEvidence], ...] = (),
) -> EventRiskEvidenceSnapshot:
    return EventRiskEvidenceSnapshot(
        instrument=Instrument(base_currency="GBP", quote_currency="USD"),
        as_of=_AS_OF,
        lookahead=timedelta(hours=24),
        lookback=timedelta(hours=48),
        upcoming_schedule_groups=schedule_groups,
        recent_release_groups=release_groups,
        coverage=_COVERAGE,
    )


def test_date_only_event_renders_none_never_midnight() -> None:
    member = _schedule_evidence(scheduled_time=None, exact_utc=None)
    group = EventEvidenceGroup(group_key="occ1", members=(member,))

    view = build_events_view(_snapshot(schedule_groups=(group,)))

    rendered = view["upcoming_schedule_groups"][0]["members"][0]
    assert rendered["scheduled_time"] is None  # never "00:00:00"
    assert rendered["exact_scheduled_at_utc"] is None
    assert rendered["time_until_event_seconds"] is None


def test_exact_time_event_renders_instant_and_time_until() -> None:
    exact = UtcTimestamp(datetime(2026, 9, 10, 8, 0, tzinfo=UTC))
    member = _schedule_evidence(scheduled_time=time(8, 0), exact_utc=exact)
    group = EventEvidenceGroup(group_key="occ1", members=(member,))

    view = build_events_view(_snapshot(schedule_groups=(group,)))

    rendered = view["upcoming_schedule_groups"][0]["members"][0]
    assert rendered["exact_scheduled_at_utc"] == "2026-09-10T08:00:00+00:00"
    assert rendered["time_until_event_seconds"] == (exact.value - _AS_OF.value).total_seconds()


def test_release_package_is_marked_and_preserves_both_members() -> None:
    def _release(occurrence_key: str, indicator_key: str) -> EventReleaseEvidence:
        return EventReleaseEvidence(
            occurrence_key=occurrence_key,
            indicator_key=indicator_key,
            display_name=indicator_key,
            economy="US",
            currency="USD",
            pair_role=PairCurrencyRole.QUOTE,
            category=EconomicEventCategory.EMPLOYMENT,
            release_group_key="grp-emp",
            released_date=date(2026, 9, 4),
            released_time=time(13, 30),
            released_timezone="UTC",
            exact_released_at_utc=UtcTimestamp(datetime(2026, 9, 4, 13, 30, tzinfo=UTC)),
            elapsed_since_release=timedelta(hours=1),
            availability=_AS_OF,
            availability_confidence=AvailabilityConfidence.VERIFIED,
            source="test",
            source_published_at=None,
        )

    group = EventEvidenceGroup(
        group_key="grp-emp",
        members=(_release("nfp", "US_NONFARM_PAYROLLS"), _release("unemp", "US_UNEMPLOYMENT_RATE")),
    )

    view = build_events_view(_snapshot(release_groups=(group,)))

    rendered_group = view["recent_release_groups"][0]
    assert rendered_group["is_package"] is True
    assert len(rendered_group["members"]) == 2
    member_keys = {m["occurrence_key"] for m in rendered_group["members"]}
    assert member_keys == {"nfp", "unemp"}


def test_cancelled_status_is_preserved() -> None:
    member = EventScheduleEvidence(
        occurrence_key="occ1",
        indicator_key="GBP_GDP_QOQ",
        display_name="UK GDP",
        economy="GB",
        currency="GBP",
        pair_role=PairCurrencyRole.BASE,
        category=EconomicEventCategory.GROWTH,
        reference_period=None,
        release_group_key=None,
        status=EconomicEventStatus.CANCELLED,
        scheduled_date=date(2026, 9, 10),
        scheduled_time=time(8, 0),
        schedule_timezone="UTC",
        exact_scheduled_at_utc=UtcTimestamp(datetime(2026, 9, 10, 8, 0, tzinfo=UTC)),
        time_until_event=timedelta(hours=1),
        availability=_AS_OF,
        availability_confidence=AvailabilityConfidence.VERIFIED,
        source="test",
    )
    group = EventEvidenceGroup(group_key="occ1", members=(member,))

    view = build_events_view(_snapshot(schedule_groups=(group,)))

    assert view["upcoming_schedule_groups"][0]["members"][0]["status"] == "CANCELLED"


def test_empty_windows_use_the_restrained_message_never_all_clear() -> None:
    view = build_events_view(_snapshot())

    assert view["upcoming_schedule_groups"] == []
    assert view["recent_release_groups"] == []
    assert view["empty_schedule_window_message"] == EMPTY_SCHEDULE_WINDOW_MESSAGE
    assert view["empty_release_window_message"] == EMPTY_RELEASE_WINDOW_MESSAGE
    for forbidden in ("all clear", "safe", "no event risk", "nothing to worry"):
        assert forbidden not in EMPTY_SCHEDULE_WINDOW_MESSAGE.lower()
        assert forbidden not in EMPTY_RELEASE_WINDOW_MESSAGE.lower()


def test_coverage_reports_tracked_and_untracked_and_no_health_claim() -> None:
    view = build_events_view(_snapshot())

    coverage = view["coverage"]
    assert coverage["tracked_indicator_keys_by_currency"] == [
        {"currency": "GBP", "indicator_keys": ["GBP_GDP_QOQ"]},
        {"currency": "USD", "indicator_keys": []},
    ]
    assert coverage["untracked_pair_currencies"] == ["USD"]
    assert coverage["source_health_note"] == SOURCE_HEALTH_NOTE
    assert "not currently tracked" in SOURCE_HEALTH_NOTE

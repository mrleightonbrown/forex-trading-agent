"""FX-51: point-in-time economic-event state selection tests, including
the story's own worked examples A/B/C verbatim."""

from datetime import UTC, date, datetime, time
from decimal import Decimal

from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_actual_value_vintage import (
    EconomicEventActualValueVintage,
)
from forex_agent.domain.economic_event_consensus_vintage import EconomicEventConsensusVintage
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
from forex_agent.domain.economic_event_state import (
    first_release_as_of,
    latest_actual_as_of,
    latest_consensus_as_of,
    latest_schedule_as_of,
)
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.timestamps import UtcTimestamp

INDICATOR = "US_CPI_YOY"


def _ts(month: int, day: int, hour: int = 0, minute: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, month, day, hour, minute, tzinfo=UTC))


def _ref() -> UtcTimestamp:
    return _ts(1, 1)


def _schedule(
    revision_sequence: int,
    scheduled_date: date,
    availability: UtcTimestamp | None,
    status: EconomicEventStatus = EconomicEventStatus.SCHEDULED,
    confidence: AvailabilityConfidence = AvailabilityConfidence.VERIFIED,
) -> EconomicEventScheduleVintage:
    return EconomicEventScheduleVintage(
        indicator_key=INDICATOR,
        reference_period=_ref(),
        revision_sequence=revision_sequence,
        scheduled_date=scheduled_date,
        scheduled_time=time(8, 30),
        schedule_timezone="America/New_York",
        status=status,
        availability=availability,
        availability_confidence=confidence,
        source="test",
    )


def _consensus(
    revision_sequence: int, value: str, availability: UtcTimestamp | None
) -> EconomicEventConsensusVintage:
    return EconomicEventConsensusVintage(
        indicator_key=INDICATOR,
        reference_period=_ref(),
        revision_sequence=revision_sequence,
        consensus_value=Decimal(value),
        availability=availability,
        availability_confidence=(
            AvailabilityConfidence.VERIFIED if availability else AvailabilityConfidence.UNKNOWN
        ),
        source="test",
    )


def _actual(
    revision_sequence: int, value: str, availability: UtcTimestamp | None
) -> EconomicEventActualValueVintage:
    return EconomicEventActualValueVintage(
        indicator_key=INDICATOR,
        reference_period=_ref(),
        revision_sequence=revision_sequence,
        actual_value=Decimal(value),
        availability=availability,
        availability_confidence=(
            AvailabilityConfidence.VERIFIED if availability else AvailabilityConfidence.UNKNOWN
        ),
        source="test",
    )


# --- Worked example A: schedule history ------------------------------------


def test_worked_example_a_schedule_before_and_after_reschedule() -> None:
    initial = _schedule(0, date(2026, 10, 2), availability=_ts(1, 1))
    rescheduled = _schedule(1, date(2026, 10, 5), availability=_ts(1, 5))

    before = latest_schedule_as_of([initial, rescheduled], _ts(1, 3))
    after = latest_schedule_as_of([initial, rescheduled], _ts(1, 6))

    assert before is not None and before.scheduled_date == date(2026, 10, 2)
    assert after is not None and after.scheduled_date == date(2026, 10, 5)


def test_schedule_cancellation_then_reinstatement_recoverable() -> None:
    initial = _schedule(0, date(2026, 10, 2), availability=_ts(1, 1))
    cancelled = _schedule(
        1, date(2026, 10, 2), availability=_ts(1, 2), status=EconomicEventStatus.CANCELLED
    )
    reinstated = _schedule(2, date(2026, 10, 9), availability=_ts(1, 3))

    all_vintages = [initial, cancelled, reinstated]
    assert latest_schedule_as_of(all_vintages, _ts(1, 1, 12))
    at_cancel = latest_schedule_as_of(all_vintages, _ts(1, 2, 12))
    at_reinstate = latest_schedule_as_of(all_vintages, _ts(1, 3, 12))

    assert at_cancel is not None and at_cancel.status is EconomicEventStatus.CANCELLED
    assert at_reinstate is not None and at_reinstate.status is EconomicEventStatus.SCHEDULED
    assert at_reinstate.scheduled_date == date(2026, 10, 9)


def test_date_known_time_unknown_then_time_becomes_known() -> None:
    tbd = EconomicEventScheduleVintage(
        indicator_key=INDICATOR,
        reference_period=_ref(),
        revision_sequence=0,
        scheduled_date=date(2026, 10, 2),
        scheduled_time=None,
        schedule_timezone="America/New_York",
        status=EconomicEventStatus.SCHEDULED,
        availability=_ts(1, 1),
        availability_confidence=AvailabilityConfidence.VERIFIED,
        source="test",
    )
    time_known = _schedule(1, date(2026, 10, 2), availability=_ts(1, 2))

    before = latest_schedule_as_of([tbd, time_known], _ts(1, 1, 12))
    after = latest_schedule_as_of([tbd, time_known], _ts(1, 3))

    assert before is not None and before.scheduled_time is None
    assert after is not None and after.scheduled_time == time(8, 30)


# --- Worked example B: consensus ---------------------------------------------


def test_worked_example_b_consensus_revision_before_release() -> None:
    early = _consensus(0, "3.1", availability=_ts(1, 1, 9, 0))
    revised = _consensus(1, "3.0", availability=_ts(1, 1, 12, 0))

    at_1100 = latest_consensus_as_of([early, revised], _ts(1, 1, 11, 0))
    at_1300 = latest_consensus_as_of([early, revised], _ts(1, 1, 13, 0))

    assert at_1100 is not None and at_1100.consensus_value == Decimal("3.1")
    assert at_1300 is not None and at_1300.consensus_value == Decimal("3.0")


def test_post_release_consensus_update_does_not_rewrite_pre_release_state() -> None:
    pre_release = _consensus(0, "3.1", availability=_ts(1, 1, 9, 0))
    post_release_update = _consensus(1, "3.05", availability=_ts(1, 1, 14, 0))

    at_release_cutoff = latest_consensus_as_of(
        [pre_release, post_release_update], _ts(1, 1, 13, 30)
    )

    assert at_release_cutoff is not None
    assert at_release_cutoff.consensus_value == Decimal("3.1")


# --- Worked example C: actual values -----------------------------------------


def test_worked_example_c_first_release_then_revision() -> None:
    first = _actual(0, "150", availability=_ts(1, 1, 13, 30))
    revision = _actual(1, "140", availability=_ts(2, 1))

    at_release_day = latest_actual_as_of([first, revision], _ts(1, 1, 14, 0))
    after_revision = latest_actual_as_of([first, revision], _ts(2, 2))

    assert at_release_day is not None and at_release_day.actual_value == Decimal("150")
    assert after_revision is not None and after_revision.actual_value == Decimal("140")


def test_first_release_remains_recoverable_after_revision() -> None:
    first = _actual(0, "150", availability=_ts(1, 1, 13, 30))
    revision = _actual(1, "140", availability=_ts(2, 1))
    second_revision = _actual(2, "137", availability=_ts(3, 1))

    all_vintages = [first, revision, second_revision]

    assert first_release_as_of(all_vintages, _ts(3, 2)) is not None
    recovered = first_release_as_of(all_vintages, _ts(3, 2))
    assert recovered is not None and recovered.actual_value == Decimal("150")
    # Latest-known-as-of, queried at the same instant, is the SECOND
    # revision -- both remain simultaneously recoverable from the same
    # stored history.
    latest = latest_actual_as_of(all_vintages, _ts(3, 2))
    assert latest is not None and latest.actual_value == Decimal("137")


def test_first_release_not_visible_before_its_own_availability() -> None:
    first = _actual(0, "150", availability=_ts(1, 1, 13, 30))
    assert first_release_as_of([first], _ts(1, 1, 13, 0)) is None
    assert first_release_as_of([first], _ts(1, 1, 13, 30)) is not None


# --- Backfill / unknown availability ------------------------------------------


def test_unknown_availability_never_visible_at_any_as_of() -> None:
    backfilled = EconomicEventActualValueVintage(
        indicator_key=INDICATOR,
        reference_period=_ref(),
        revision_sequence=0,
        actual_value=Decimal("150"),
        availability=None,
        availability_confidence=AvailabilityConfidence.UNKNOWN,
        source="manual_backfill",
    )
    far_future = UtcTimestamp(datetime(2099, 1, 1, tzinfo=UTC))
    assert latest_actual_as_of([backfilled], far_future) is None
    assert first_release_as_of([backfilled], far_future) is None


def test_estimated_confidence_is_visible_like_verified() -> None:
    conservative = EconomicEventActualValueVintage(
        indicator_key=INDICATOR,
        reference_period=_ref(),
        revision_sequence=0,
        actual_value=Decimal("150"),
        availability=_ts(1, 1),
        availability_confidence=AvailabilityConfidence.ESTIMATED,
        source="manual_backfill",
    )
    result = latest_actual_as_of([conservative], _ts(1, 2))
    assert result is not None and result.actual_value == Decimal("150")


# --- Empty / edge cases -------------------------------------------------------


def test_empty_history_returns_none_everywhere() -> None:
    assert latest_schedule_as_of([], _ts(1, 1)) is None
    assert latest_consensus_as_of([], _ts(1, 1)) is None
    assert latest_actual_as_of([], _ts(1, 1)) is None
    assert first_release_as_of([], _ts(1, 1)) is None


def test_tie_break_by_revision_sequence_when_availability_matches() -> None:
    same_instant = _ts(1, 1)
    older_content = _consensus(0, "3.1", availability=same_instant)
    newer_content = _consensus(1, "3.0", availability=same_instant)
    result = latest_consensus_as_of([older_content, newer_content], same_instant)
    assert result is not None and result.consensus_value == Decimal("3.0")

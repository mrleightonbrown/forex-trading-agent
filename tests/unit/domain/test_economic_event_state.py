"""FX-51: point-in-time economic-event state selection tests, including
the story's own worked examples A/B/C verbatim. FX-51H adds
`latest_release_as_of` and `schedule_within_window` coverage."""

from datetime import UTC, date, datetime, time
from decimal import Decimal

from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_actual_value_vintage import (
    EconomicEventActualValueVintage,
)
from forex_agent.domain.economic_event_consensus_vintage import EconomicEventConsensusVintage
from forex_agent.domain.economic_event_release_vintage import EconomicEventReleaseVintage
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
from forex_agent.domain.economic_event_state import (
    first_release_as_of,
    latest_actual_as_of,
    latest_consensus_as_of,
    latest_release_as_of,
    latest_schedule_as_of,
    schedule_within_window,
)
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.timestamps import UtcTimestamp

OCCURRENCE_KEY = "US_CPI_2026_01"


def _ts(month: int, day: int, hour: int = 0, minute: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, month, day, hour, minute, tzinfo=UTC))


def _schedule(
    revision_sequence: int,
    scheduled_date: date,
    availability: UtcTimestamp | None,
    status: EconomicEventStatus = EconomicEventStatus.SCHEDULED,
    confidence: AvailabilityConfidence = AvailabilityConfidence.VERIFIED,
    scheduled_time: time | None = time(8, 30),
    schedule_timezone: str = "America/New_York",
) -> EconomicEventScheduleVintage:
    return EconomicEventScheduleVintage(
        occurrence_key=OCCURRENCE_KEY,
        revision_sequence=revision_sequence,
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        schedule_timezone=schedule_timezone,
        status=status,
        availability=availability,
        availability_confidence=confidence,
        source="test",
    )


def _consensus(
    revision_sequence: int, value: str, availability: UtcTimestamp | None
) -> EconomicEventConsensusVintage:
    return EconomicEventConsensusVintage(
        occurrence_key=OCCURRENCE_KEY,
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
        occurrence_key=OCCURRENCE_KEY,
        revision_sequence=revision_sequence,
        actual_value=Decimal(value),
        availability=availability,
        availability_confidence=(
            AvailabilityConfidence.VERIFIED if availability else AvailabilityConfidence.UNKNOWN
        ),
        source="test",
    )


def _release(
    revision_sequence: int,
    released_date: date,
    released_time: time | None,
    availability: UtcTimestamp | None,
    timezone: str = "UTC",
) -> EconomicEventReleaseVintage:
    return EconomicEventReleaseVintage(
        occurrence_key=OCCURRENCE_KEY,
        revision_sequence=revision_sequence,
        released_date=released_date,
        released_time=released_time,
        released_timezone=timezone,
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
    tbd = _schedule(0, date(2026, 10, 2), availability=_ts(1, 1), scheduled_time=None)
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


# --- Release-occurred state (FX-51H) ------------------------------------------


def test_release_time_is_independent_of_availability_time() -> None:
    # A statement released at 13:00 whose transcript is only published
    # (and thus knowable) two days later.
    release = _release(
        0, date(2026, 9, 4), time(13, 0), availability=_ts(9, 6, 9, 0), timezone="UTC"
    )
    assert release.released_time is not None
    assert release.availability is not None
    released_instant = datetime.combine(release.released_date, release.released_time, tzinfo=UTC)
    assert released_instant < release.availability.value

    before_availability = latest_release_as_of([release], _ts(9, 5))
    after_availability = latest_release_as_of([release], _ts(9, 6, 10, 0))
    assert before_availability is None
    assert after_availability is not None


def test_qualitative_event_release_recoverable_without_actual_value() -> None:
    release = _release(0, date(2026, 9, 10), time(14, 0), availability=_ts(9, 10, 14, 5))
    result = latest_release_as_of([release], _ts(9, 11))
    assert result is not None
    assert result.released_date == date(2026, 9, 10)


def test_release_unknown_time_remains_time_unknown() -> None:
    release = _release(0, date(2026, 9, 10), None, availability=_ts(9, 10, 15, 0))
    result = latest_release_as_of([release], _ts(9, 11))
    assert result is not None and result.released_time is None


def test_release_after_a_reschedule_is_still_recoverable() -> None:
    initial_schedule = _schedule(0, date(2026, 10, 2), availability=_ts(1, 1))
    rescheduled = _schedule(1, date(2026, 10, 5), availability=_ts(1, 4))
    release = _release(0, date(2026, 10, 5), time(8, 30), availability=_ts(10, 5, 8, 35))

    schedule_state = latest_schedule_as_of([initial_schedule, rescheduled], _ts(10, 6))
    release_state = latest_release_as_of([release], _ts(10, 6))

    assert schedule_state is not None and schedule_state.scheduled_date == date(2026, 10, 5)
    assert release_state is not None and release_state.released_date == date(2026, 10, 5)


# --- Backfill / unknown availability ------------------------------------------


def test_unknown_availability_never_visible_at_any_as_of() -> None:
    backfilled = EconomicEventActualValueVintage(
        occurrence_key=OCCURRENCE_KEY,
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
        occurrence_key=OCCURRENCE_KEY,
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
    assert latest_release_as_of([], _ts(1, 1)) is None


def test_tie_break_by_revision_sequence_when_availability_matches() -> None:
    same_instant = _ts(1, 1)
    older_content = _consensus(0, "3.1", availability=same_instant)
    newer_content = _consensus(1, "3.0", availability=same_instant)
    result = latest_consensus_as_of([older_content, newer_content], same_instant)
    assert result is not None and result.consensus_value == Decimal("3.0")


# --- schedule_within_window (FX-51H Section 4) -------------------------------


def test_known_time_exact_instant_membership() -> None:
    # 2026-09-04 08:30 America/New_York (EDT, UTC-4) == 12:30 UTC.
    schedule = _schedule(0, date(2026, 9, 4), availability=_ts(8, 1))
    window_start = UtcTimestamp(datetime(2026, 9, 4, 12, 0, tzinfo=UTC))
    window_end = UtcTimestamp(datetime(2026, 9, 4, 13, 0, tzinfo=UTC))
    outside_start = UtcTimestamp(datetime(2026, 9, 4, 13, 0, tzinfo=UTC))
    outside_end = UtcTimestamp(datetime(2026, 9, 4, 14, 0, tzinfo=UTC))

    assert schedule_within_window(schedule, window_start, window_end) is True
    assert schedule_within_window(schedule, outside_start, outside_end) is False


def test_known_time_dst_boundary_resolved_correctly() -> None:
    # 2026-01-15 08:30 America/New_York (EST, UTC-5) == 13:30 UTC -- a
    # naive "compare local date to UTC date" check would already agree
    # here, but a late-evening local time crossing midnight UTC is
    # where the old bug actually bit; test that specific case below.
    late_local = _schedule(0, date(2026, 1, 15), availability=_ts(1, 1), scheduled_time=time(23, 0))
    # 2026-01-15 23:00 America/New_York (EST, UTC-5) == 2026-01-16 04:00 UTC
    # -- a naive UTC-calendar-date comparison against a window ending
    # at [2026-01-15 00:00, 2026-01-16 00:00) UTC would (wrongly) call
    # this "within" the Jan 15 UTC window; the real instant is Jan 16.
    jan_15_utc_window_start = UtcTimestamp(datetime(2026, 1, 15, 0, 0, tzinfo=UTC))
    jan_15_utc_window_end = UtcTimestamp(datetime(2026, 1, 16, 0, 0, tzinfo=UTC))
    jan_16_utc_window_start = UtcTimestamp(datetime(2026, 1, 16, 0, 0, tzinfo=UTC))
    jan_16_utc_window_end = UtcTimestamp(datetime(2026, 1, 17, 0, 0, tzinfo=UTC))

    assert (
        schedule_within_window(late_local, jan_15_utc_window_start, jan_15_utc_window_end) is False
    )
    assert (
        schedule_within_window(late_local, jan_16_utc_window_start, jan_16_utc_window_end) is True
    )


def test_unknown_time_uses_local_day_overlap_never_a_fabricated_instant() -> None:
    tbd = _schedule(0, date(2026, 1, 15), availability=_ts(1, 1), scheduled_time=None)
    # The local day 2026-01-15 in America/New_York spans
    # [2026-01-15 05:00 UTC, 2026-01-16 05:00 UTC) (EST, UTC-5).
    overlapping_window = (
        UtcTimestamp(datetime(2026, 1, 16, 0, 0, tzinfo=UTC)),
        UtcTimestamp(datetime(2026, 1, 16, 6, 0, tzinfo=UTC)),
    )
    non_overlapping_window = (
        UtcTimestamp(datetime(2026, 1, 16, 6, 0, tzinfo=UTC)),
        UtcTimestamp(datetime(2026, 1, 17, 0, 0, tzinfo=UTC)),
    )

    assert schedule_within_window(tbd, *overlapping_window) is True
    assert schedule_within_window(tbd, *non_overlapping_window) is False

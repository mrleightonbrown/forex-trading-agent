"""FX-54V: pure builder converting an `EventRiskEvidenceSnapshot`
(FX-54, already fetched) into a JSON-safe dict for the "Market
Context" dashboard's Economic Events section -- timeline, upcoming/
recent cards, release groups, and coverage panel. No I/O, no
repository access, no interpretation: every field here is a direct,
renamed passthrough of FX-54's own evidence, never a risk/policy
judgment (FX-54V Section 33 forbids that here just as firmly as FX-54
Section 3 forbids it in the evidence layer itself).

Date-only facts render `scheduled_time`/`released_time` as `None` and
`exact_scheduled_at_utc`/`exact_released_at_utc` as `None` -- the HTML/
JS layer is responsible for rendering `None` as "Time TBD," never as
`00:00` (FX-54V Section 18: "For date-only: Time TBD, not 00:00").
"""

from typing import Any

from forex_agent.domain.event_evidence_group import EventEvidenceGroup
from forex_agent.domain.event_release_evidence import EventReleaseEvidence
from forex_agent.domain.event_risk_evidence_snapshot import EventRiskEvidenceSnapshot
from forex_agent.domain.event_schedule_evidence import EventScheduleEvidence

#: FX-54V Section 23: the exact, restrained wording an empty window
#: must use -- never "all clear"/"safe to trade"/"no event risk."
EMPTY_SCHEDULE_WINDOW_MESSAGE = "No tracked PIT-visible events in this window."
EMPTY_RELEASE_WINDOW_MESSAGE = "No tracked PIT-visible release evidence in this window."

#: FX-54V Section 24: source freshness/health is genuinely not tracked
#: anywhere in this repository for the economic-calendar subsystem --
#: stated once, here, rather than invented per-source.
SOURCE_HEALTH_NOTE = "Source freshness/health is not currently tracked by this view."


def _schedule_member_view(member: EventScheduleEvidence) -> dict[str, Any]:
    return {
        "occurrence_key": member.occurrence_key,
        "indicator_key": member.indicator_key,
        "display_name": member.display_name,
        "economy": member.economy,
        "currency": member.currency,
        "pair_role": member.pair_role.value,
        "category": member.category.value,
        "reference_period": (
            None if member.reference_period is None else member.reference_period.value.isoformat()
        ),
        "release_group_key": member.release_group_key,
        "status": member.status.value,
        "scheduled_date": member.scheduled_date.isoformat(),
        "scheduled_time": (
            None if member.scheduled_time is None else member.scheduled_time.isoformat()
        ),
        "schedule_timezone": member.schedule_timezone,
        "exact_scheduled_at_utc": (
            None
            if member.exact_scheduled_at_utc is None
            else member.exact_scheduled_at_utc.value.isoformat()
        ),
        "time_until_event_seconds": (
            None if member.time_until_event is None else member.time_until_event.total_seconds()
        ),
        "availability": (
            None if member.availability is None else member.availability.value.isoformat()
        ),
        "availability_confidence": member.availability_confidence.value,
        "source": member.source,
    }


def _release_member_view(member: EventReleaseEvidence) -> dict[str, Any]:
    return {
        "occurrence_key": member.occurrence_key,
        "indicator_key": member.indicator_key,
        "display_name": member.display_name,
        "economy": member.economy,
        "currency": member.currency,
        "pair_role": member.pair_role.value,
        "category": member.category.value,
        "release_group_key": member.release_group_key,
        "released_date": member.released_date.isoformat(),
        "released_time": (
            None if member.released_time is None else member.released_time.isoformat()
        ),
        "released_timezone": member.released_timezone,
        "exact_released_at_utc": (
            None
            if member.exact_released_at_utc is None
            else member.exact_released_at_utc.value.isoformat()
        ),
        "elapsed_since_release_seconds": (
            None
            if member.elapsed_since_release is None
            else member.elapsed_since_release.total_seconds()
        ),
        "availability": (
            None if member.availability is None else member.availability.value.isoformat()
        ),
        "availability_confidence": member.availability_confidence.value,
        "source": member.source,
        "source_published_at": (
            None
            if member.source_published_at is None
            else member.source_published_at.value.isoformat()
        ),
    }


def _schedule_group_view(group: EventEvidenceGroup[EventScheduleEvidence]) -> dict[str, Any]:
    return {
        "group_key": group.group_key,
        "is_package": len(group.members) > 1,
        "members": [_schedule_member_view(m) for m in group.members],
    }


def _release_group_view(group: EventEvidenceGroup[EventReleaseEvidence]) -> dict[str, Any]:
    return {
        "group_key": group.group_key,
        "is_package": len(group.members) > 1,
        "members": [_release_member_view(m) for m in group.members],
    }


def build_events_view(snapshot: EventRiskEvidenceSnapshot) -> dict[str, Any]:
    """The Economic Events section's own JSON-safe read model."""
    coverage = snapshot.coverage
    return {
        "instrument": {
            "base_currency": snapshot.instrument.base_currency,
            "quote_currency": snapshot.instrument.quote_currency,
            "symbol": snapshot.instrument.symbol,
        },
        "as_of": snapshot.as_of.value.isoformat(),
        "lookahead_seconds": snapshot.lookahead.total_seconds(),
        "lookback_seconds": snapshot.lookback.total_seconds(),
        "upcoming_schedule_groups": [
            _schedule_group_view(g) for g in snapshot.upcoming_schedule_groups
        ],
        "recent_release_groups": [_release_group_view(g) for g in snapshot.recent_release_groups],
        "empty_schedule_window_message": (
            EMPTY_SCHEDULE_WINDOW_MESSAGE if not snapshot.upcoming_schedule_groups else None
        ),
        "empty_release_window_message": (
            EMPTY_RELEASE_WINDOW_MESSAGE if not snapshot.recent_release_groups else None
        ),
        "coverage": {
            "base_currency": coverage.base_currency,
            "quote_currency": coverage.quote_currency,
            "tracked_indicator_keys_by_currency": [
                {"currency": currency, "indicator_keys": list(keys)}
                for currency, keys in coverage.tracked_indicator_keys_by_currency
            ],
            "untracked_pair_currencies": list(coverage.untracked_pair_currencies),
            "source_health_note": SOURCE_HEALTH_NOTE,
        },
    }

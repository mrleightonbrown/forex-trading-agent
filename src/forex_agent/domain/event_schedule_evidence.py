"""FX-54: one pair-relevant, PIT-visible forward-schedule fact --
"as of `as_of`, this canonical event is/was known to be scheduled for
this date[/time], with this status" -- the timing-only evidence unit
`GetEventRiskEvidenceSnapshot` exposes for the `[as_of, as_of +
lookahead)` window (see that use case's own module docstring).

Deliberately mirrors `EconomicEventScheduleVintage`'s own exact-time-
vs-date-only discipline: `exact_scheduled_at_utc`/`time_until_event`
are BOTH `None` whenever `scheduled_time` is `None` -- never a
fabricated midnight, never an invented "typical release hour," never
approximated from a previous occurrence's own time (FX-54 Section 9).
This type carries no risk/policy verdict of any kind (no importance,
no severity, no trade-veto field) -- it reports facts only (FX-54
Section 3).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time, timedelta

from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_category import EconomicEventCategory
from forex_agent.domain.economic_event_occurrence import EconomicEventOccurrence
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
from forex_agent.domain.economic_event_state import (
    resolve_exact_instant,
    resolve_local_day_utc_range,
)
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.economic_indicator_definition import EconomicIndicatorDefinition
from forex_agent.domain.event_evidence_group import EventEvidenceGroup
from forex_agent.domain.pair_currency_role import PairCurrencyRole
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class EventScheduleEvidence:
    """Fields:
    occurrence_key: this occurrence's own canonical identity --
        never a provider ID (FX-52AH's own correction applies
        unchanged; this is `EconomicEventOccurrence.occurrence_key`
        itself, not a source-mapping lookup key).
    indicator_key/display_name/economy/currency/category: the
        canonical `EconomicIndicatorDefinition` this occurrence is
        one instance of, verbatim from the registry.
    pair_role: whether `currency` is the requesting pair's BASE or
        QUOTE side (FX-54 Section 6) -- structural, non-
        directional.
    reference_period: the occurrence's own reference period, or
        `None` for a qualitative/irregular occurrence -- verbatim
        from `EconomicEventOccurrence.reference_period`.
    release_group_key: `EconomicEventOccurrence.release_group_key`
        verbatim, or `None` -- see `EventEvidenceGroup`'s own
        docstring for how grouping is exposed.
    status/scheduled_date/scheduled_time/schedule_timezone: the
        PIT-visible schedule vintage's own claim, verbatim.
    exact_scheduled_at_utc: `scheduled_date`+`scheduled_time`
        resolved to a single UTC instant via `schedule_timezone`,
        or `None` whenever `scheduled_time` is `None` -- NEVER
        fabricated.
    time_until_event: `exact_scheduled_at_utc - as_of`, or `None`
        whenever `exact_scheduled_at_utc` is `None`. Deliberately a
        `timedelta`, never a pre-rounded "minutes until" value
        (FX-54 Section 10) -- a caller wanting minutes must derive
        it explicitly under its own, tested rounding rule.
    availability/availability_confidence/source: the schedule
        vintage's own provenance, verbatim.
    """

    occurrence_key: str
    indicator_key: str
    display_name: str
    economy: str
    currency: str
    pair_role: PairCurrencyRole
    category: EconomicEventCategory
    reference_period: UtcTimestamp | None
    release_group_key: str | None
    status: EconomicEventStatus
    scheduled_date: date
    scheduled_time: time | None
    schedule_timezone: str
    exact_scheduled_at_utc: UtcTimestamp | None
    time_until_event: timedelta | None
    availability: UtcTimestamp | None
    availability_confidence: AvailabilityConfidence
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence_key, str) or not self.occurrence_key.strip():
            raise ValueError(
                f"occurrence_key must be a non-empty string, got {self.occurrence_key!r}"
            )
        if (self.exact_scheduled_at_utc is None) != (self.time_until_event is None):
            raise ValueError(
                "exact_scheduled_at_utc and time_until_event must both be None or both be "
                "set -- never fabricate one without the other"
            )
        if self.scheduled_time is None and self.exact_scheduled_at_utc is not None:
            raise ValueError(
                "exact_scheduled_at_utc must be None when scheduled_time is None -- "
                "never fabricate an exact instant for a date-only schedule"
            )


def build_schedule_evidence(
    occurrence: EconomicEventOccurrence,
    schedule: EconomicEventScheduleVintage,
    indicator: EconomicIndicatorDefinition,
    pair_role: PairCurrencyRole,
    as_of: UtcTimestamp,
) -> EventScheduleEvidence:
    """Assembles one `EventScheduleEvidence` from already-PIT-selected
    repository results -- this function does no PIT filtering itself
    (the caller must already have obtained `schedule` via a PIT-safe
    query, e.g. `known_events_in_window`); it only resolves the exact
    UTC instant (if any) and computes `time_until_event` relative to
    `as_of`."""
    exact_instant = resolve_exact_instant(
        schedule.scheduled_date, schedule.scheduled_time, schedule.schedule_timezone
    )
    time_until = None if exact_instant is None else exact_instant.value - as_of.value
    return EventScheduleEvidence(
        occurrence_key=occurrence.occurrence_key,
        indicator_key=indicator.key,
        display_name=indicator.name,
        economy=indicator.economy,
        currency=indicator.currency,
        pair_role=pair_role,
        category=indicator.category,
        reference_period=occurrence.reference_period,
        release_group_key=occurrence.release_group_key,
        status=schedule.status,
        scheduled_date=schedule.scheduled_date,
        scheduled_time=schedule.scheduled_time,
        schedule_timezone=schedule.schedule_timezone,
        exact_scheduled_at_utc=exact_instant,
        time_until_event=time_until,
        availability=schedule.availability,
        availability_confidence=schedule.availability_confidence,
        source=schedule.source,
    )


def _sort_instant(evidence: EventScheduleEvidence) -> UtcTimestamp:
    """The chronological ordering key (FX-54 Section 18) -- the exact
    instant when known, or otherwise the START of the date-only local
    day range. NEVER exposed on `EventScheduleEvidence` itself (that
    would be exactly the fabricated-instant mistake Section 9
    forbids) -- this exists only to give an otherwise-unorderable
    date-only fact a deterministic position among exact-time facts,
    derived purely from fields that are always genuinely known
    (`scheduled_date`/`schedule_timezone`)."""
    if evidence.exact_scheduled_at_utc is not None:
        return evidence.exact_scheduled_at_utc
    day_start, _ = resolve_local_day_utc_range(evidence.scheduled_date, evidence.schedule_timezone)
    return day_start


def group_schedule_evidence(
    items: Sequence[EventScheduleEvidence],
) -> tuple[EventEvidenceGroup[EventScheduleEvidence], ...]:
    """Groups `items` by `release_group_key` (falling back to each
    item's own `occurrence_key` when it has none -- see
    `EventEvidenceGroup`'s own docstring), then returns the groups in
    deterministic chronological order (FX-54 Section 18): by the
    EARLIEST member's own `_sort_instant`, tie-broken by `group_key`.
    Within each group, members are sorted by `(indicator_key,
    occurrence_key)` -- never by an invented "primary" member and
    never by timestamp (Section 17: members may genuinely disagree
    about timing; this ordering must not paper over that by picking
    one)."""
    grouped: dict[str, list[EventScheduleEvidence]] = {}
    for item in items:
        key = item.release_group_key or item.occurrence_key
        grouped.setdefault(key, []).append(item)

    groups = [
        EventEvidenceGroup(
            group_key=key,
            members=tuple(sorted(members, key=lambda m: (m.indicator_key, m.occurrence_key))),
        )
        for key, members in grouped.items()
    ]
    groups.sort(key=lambda g: (min(_sort_instant(m).value for m in g.members), g.group_key))
    return tuple(groups)

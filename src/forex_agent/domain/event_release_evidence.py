"""FX-54: one pair-relevant, PIT-visible release-occurrence fact --
"as of `as_of`, this canonical event is/was known to have actually
been released on this date[/time]" -- the timing-only evidence unit
`GetEventRiskEvidenceSnapshot` exposes for the `[as_of - lookback,
as_of)` window (see that use case's own module docstring).

Mirrors `EventScheduleEvidence`'s own exact-time-vs-date-only
discipline for release evidence: `exact_released_at_utc`/
`elapsed_since_release` are BOTH `None` whenever `released_time` is
`None` (e.g. Bank of Canada's own release evidence -- FX-52AH.1
Section 14). Keeps THREE genuinely distinct instants apart, per
FX-52AH.1's own hardening: `released_at` (the claimed occurrence,
possibly date-only), `source_published_at` (when the SOURCE says it
published this evidence -- provenance only, never promoted to
`released_time`), and `availability` (when THIS system could first
know the fact, which PIT-gates whether this evidence exists in the
snapshot at all). This type carries no risk/policy verdict of any kind
(FX-54 Section 3) and never reinterprets an absent release as "event
failed"/"cancelled"/"delayed" (FX-54 Section 12) -- release evidence
is reported only from genuine `EconomicEventReleaseVintage` facts,
never inferred from a schedule's own time having passed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time, timedelta

from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_category import EconomicEventCategory
from forex_agent.domain.economic_event_occurrence import EconomicEventOccurrence
from forex_agent.domain.economic_event_release_vintage import EconomicEventReleaseVintage
from forex_agent.domain.economic_event_state import (
    resolve_exact_instant,
    resolve_local_day_utc_range,
)
from forex_agent.domain.economic_indicator_definition import EconomicIndicatorDefinition
from forex_agent.domain.event_evidence_group import EventEvidenceGroup
from forex_agent.domain.pair_currency_role import PairCurrencyRole
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class EventReleaseEvidence:
    """Fields: see `EventScheduleEvidence` for the shared identity/
    provenance ones (`occurrence_key`, `indicator_key`, `display_name`,
    `economy`, `currency`, `pair_role`, `category`,
    `release_group_key`, `availability`, `availability_confidence`,
    `source`).
        released_date/released_time/released_timezone: the PIT-visible
            release vintage's own claim, verbatim.
        exact_released_at_utc: `released_date`+`released_time`
            resolved to a UTC instant via `released_timezone`, or
            `None` whenever `released_time` is `None` -- NEVER
            fabricated.
        elapsed_since_release: `as_of - exact_released_at_utc`, or
            `None` whenever `exact_released_at_utc` is `None`
            (FX-54 Section 13/14) -- never approximated from a
            date-only fact.
        source_published_at: the source's own claimed publication
            instant (FX-52AH.1), preserved independently of both
            `exact_released_at_utc` and `availability` -- never
            conflated with either.
    """

    occurrence_key: str
    indicator_key: str
    display_name: str
    economy: str
    currency: str
    pair_role: PairCurrencyRole
    category: EconomicEventCategory
    release_group_key: str | None
    released_date: date
    released_time: time | None
    released_timezone: str
    exact_released_at_utc: UtcTimestamp | None
    elapsed_since_release: timedelta | None
    availability: UtcTimestamp | None
    availability_confidence: AvailabilityConfidence
    source: str
    source_published_at: UtcTimestamp | None

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence_key, str) or not self.occurrence_key.strip():
            raise ValueError(
                f"occurrence_key must be a non-empty string, got {self.occurrence_key!r}"
            )
        if (self.exact_released_at_utc is None) != (self.elapsed_since_release is None):
            raise ValueError(
                "exact_released_at_utc and elapsed_since_release must both be None or both "
                "be set -- never fabricate one without the other"
            )
        if self.released_time is None and self.exact_released_at_utc is not None:
            raise ValueError(
                "exact_released_at_utc must be None when released_time is None -- never "
                "fabricate an exact instant for a date-only release"
            )


def build_release_evidence(
    occurrence: EconomicEventOccurrence,
    release: EconomicEventReleaseVintage,
    indicator: EconomicIndicatorDefinition,
    pair_role: PairCurrencyRole,
    as_of: UtcTimestamp,
) -> EventReleaseEvidence:
    """Assembles one `EventReleaseEvidence` from an already-PIT-
    selected repository result -- see `build_schedule_evidence` for
    the identical division of responsibility (no PIT filtering here;
    the caller must already have obtained `release` via a PIT-safe
    query, e.g. `known_releases_in_window`)."""
    exact_instant = resolve_exact_instant(
        release.released_date, release.released_time, release.released_timezone
    )
    elapsed = None if exact_instant is None else as_of.value - exact_instant.value
    return EventReleaseEvidence(
        occurrence_key=occurrence.occurrence_key,
        indicator_key=indicator.key,
        display_name=indicator.name,
        economy=indicator.economy,
        currency=indicator.currency,
        pair_role=pair_role,
        category=indicator.category,
        release_group_key=occurrence.release_group_key,
        released_date=release.released_date,
        released_time=release.released_time,
        released_timezone=release.released_timezone,
        exact_released_at_utc=exact_instant,
        elapsed_since_release=elapsed,
        availability=release.availability,
        availability_confidence=release.availability_confidence,
        source=release.source,
        source_published_at=release.source_published_at,
    )


def _sort_instant(evidence: EventReleaseEvidence) -> UtcTimestamp:
    """See `event_schedule_evidence._sort_instant`'s own docstring --
    identical purpose, never exposed on `EventReleaseEvidence` itself."""
    if evidence.exact_released_at_utc is not None:
        return evidence.exact_released_at_utc
    day_start, _ = resolve_local_day_utc_range(evidence.released_date, evidence.released_timezone)
    return day_start


def group_release_evidence(
    items: Sequence[EventReleaseEvidence],
) -> tuple[EventEvidenceGroup[EventReleaseEvidence], ...]:
    """See `event_schedule_evidence.group_schedule_evidence`'s own
    docstring -- identical grouping/sorting contract, applied to
    release evidence."""
    grouped: dict[str, list[EventReleaseEvidence]] = {}
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

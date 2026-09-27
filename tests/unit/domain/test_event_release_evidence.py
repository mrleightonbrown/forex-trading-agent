"""FX-54: unit tests for `EventReleaseEvidence`/`build_release_evidence`/
`group_release_evidence` -- pure domain-layer assembly, grouping, and
ordering, with no repository/database dependency at all."""

from datetime import UTC, date, datetime, time, timedelta

import pytest

from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_occurrence import EconomicEventOccurrence
from forex_agent.domain.economic_event_release_vintage import EconomicEventReleaseVintage
from forex_agent.domain.economic_indicator_registry import CAD_POLICY_RATE_DECISION
from forex_agent.domain.event_release_evidence import (
    EventReleaseEvidence,
    build_release_evidence,
    group_release_evidence,
)
from forex_agent.domain.pair_currency_role import PairCurrencyRole
from forex_agent.domain.timestamps import UtcTimestamp

_INDICATOR = CAD_POLICY_RATE_DECISION


def _occurrence(key: str, release_group_key: str | None = None) -> EconomicEventOccurrence:
    return EconomicEventOccurrence(
        occurrence_key=key, indicator_key=_INDICATOR.key, release_group_key=release_group_key
    )


def _release(
    key: str,
    released_date: date,
    released_time: time | None,
    timezone: str = "UTC",
    availability: UtcTimestamp | None = None,
    source_published_at: UtcTimestamp | None = None,
) -> EconomicEventReleaseVintage:
    return EconomicEventReleaseVintage(
        occurrence_key=key,
        revision_sequence=0,
        released_date=released_date,
        released_time=released_time,
        released_timezone=timezone,
        availability=availability or UtcTimestamp(datetime(2026, 9, 2, 9, 50, tzinfo=UTC)),
        availability_confidence=AvailabilityConfidence.VERIFIED,
        source="test",
        source_published_at=source_published_at,
    )


def test_exact_time_resolves_instant_and_elapsed_since_release() -> None:
    occurrence = _occurrence("occ1")
    release = _release("occ1", date(2026, 9, 2), time(13, 45))
    as_of = UtcTimestamp(datetime(2026, 9, 2, 14, 45, tzinfo=UTC))

    evidence = build_release_evidence(
        occurrence, release, _INDICATOR, PairCurrencyRole.QUOTE, as_of
    )

    assert evidence.exact_released_at_utc == UtcTimestamp(datetime(2026, 9, 2, 13, 45, tzinfo=UTC))
    assert evidence.elapsed_since_release == timedelta(hours=1)
    assert evidence.currency == "CAD"
    assert evidence.pair_role is PairCurrencyRole.QUOTE


def test_date_only_never_fabricates_instant_or_elapsed() -> None:
    # Bank of Canada-style release evidence (FX-52AH.1).
    occurrence = _occurrence("occ2")
    release = _release("occ2", date(2026, 9, 2), None)
    as_of = UtcTimestamp(datetime(2026, 9, 2, 10, 0, tzinfo=UTC))

    evidence = build_release_evidence(occurrence, release, _INDICATOR, PairCurrencyRole.BASE, as_of)

    assert evidence.released_time is None
    assert evidence.exact_released_at_utc is None
    assert evidence.elapsed_since_release is None


def test_source_published_at_preserved_independently_of_availability_and_released_at() -> None:
    occurrence = _occurrence("occ3")
    published_at = UtcTimestamp(datetime(2026, 9, 2, 9, 47, tzinfo=UTC))
    availability = UtcTimestamp(datetime(2026, 9, 2, 9, 50, tzinfo=UTC))
    release = _release(
        "occ3",
        date(2026, 9, 2),
        None,
        availability=availability,
        source_published_at=published_at,
    )
    as_of = UtcTimestamp(datetime(2026, 9, 2, 10, 0, tzinfo=UTC))

    evidence = build_release_evidence(occurrence, release, _INDICATOR, PairCurrencyRole.BASE, as_of)

    assert evidence.source_published_at == published_at
    assert evidence.availability == availability
    assert evidence.exact_released_at_utc is None
    # Three genuinely distinct instants -- none conflated with another.
    assert evidence.source_published_at != evidence.availability


def test_rejects_exact_instant_without_elapsed() -> None:
    with pytest.raises(ValueError, match="both be None or both be set"):
        EventReleaseEvidence(
            occurrence_key="occ",
            indicator_key="K",
            display_name="d",
            economy="CA",
            currency="CAD",
            pair_role=PairCurrencyRole.BASE,
            category=_INDICATOR.category,
            release_group_key=None,
            released_date=date(2026, 1, 1),
            released_time=time(9, 0),
            released_timezone="UTC",
            exact_released_at_utc=UtcTimestamp(datetime(2026, 1, 1, 9, 0, tzinfo=UTC)),
            elapsed_since_release=None,
            availability=UtcTimestamp(datetime(2026, 1, 1, 9, 0, tzinfo=UTC)),
            availability_confidence=AvailabilityConfidence.VERIFIED,
            source="test",
            source_published_at=None,
        )


def test_rejects_exact_instant_when_released_time_is_none() -> None:
    with pytest.raises(ValueError, match="never fabricate an exact instant"):
        EventReleaseEvidence(
            occurrence_key="occ",
            indicator_key="K",
            display_name="d",
            economy="CA",
            currency="CAD",
            pair_role=PairCurrencyRole.BASE,
            category=_INDICATOR.category,
            release_group_key=None,
            released_date=date(2026, 1, 1),
            released_time=None,
            released_timezone="UTC",
            exact_released_at_utc=UtcTimestamp(datetime(2026, 1, 1, 9, 0, tzinfo=UTC)),
            elapsed_since_release=timedelta(0),
            availability=UtcTimestamp(datetime(2026, 1, 1, 9, 0, tzinfo=UTC)),
            availability_confidence=AvailabilityConfidence.VERIFIED,
            source="test",
            source_published_at=None,
        )


def test_no_risk_consensus_or_surprise_field_exists() -> None:
    # FX-54 Section 3/25/26/27: must never carry a policy, consensus,
    # or surprise field.
    forbidden = {
        "risk_score",
        "importance",
        "consensus",
        "forecast",
        "actual_value",
        "surprise",
        "surprise_direction",
        "should_trade",
        "blackout",
    }
    fields = set(EventReleaseEvidence.__dataclass_fields__)
    assert fields.isdisjoint(forbidden)


# --- group_release_evidence ---------------------------------------------------


def _evidence(
    occurrence_key: str,
    release_group_key: str | None = None,
    released_date: date = date(2026, 9, 2),
    released_time: time | None = time(13, 45),
) -> EventReleaseEvidence:
    occurrence = EconomicEventOccurrence(
        occurrence_key=occurrence_key,
        indicator_key=_INDICATOR.key,
        release_group_key=release_group_key,
    )
    release = _release(occurrence_key, released_date, released_time)
    as_of = UtcTimestamp(datetime(2026, 9, 3, tzinfo=UTC))
    return build_release_evidence(occurrence, release, _INDICATOR, PairCurrencyRole.BASE, as_of)


def test_ungrouped_occurrence_is_its_own_one_member_group() -> None:
    evidence = _evidence("occ1")
    groups = group_release_evidence([evidence])

    assert len(groups) == 1
    assert groups[0].group_key == "occ1"
    assert groups[0].members == (evidence,)


def test_shared_release_group_key_produces_one_group_two_members() -> None:
    one = _evidence("occ_a", release_group_key="grp-emp")
    two = _evidence("occ_b", release_group_key="grp-emp")

    groups = group_release_evidence([one, two])

    assert len(groups) == 1
    assert groups[0].group_key == "grp-emp"
    assert {m.occurrence_key for m in groups[0].members} == {"occ_a", "occ_b"}


def test_same_timestamp_without_shared_group_key_does_not_merge() -> None:
    one = _evidence("occ1")
    two = _evidence("occ2")

    groups = group_release_evidence([one, two])

    assert len(groups) == 2
    assert {g.group_key for g in groups} == {"occ1", "occ2"}


def test_groups_are_ordered_chronologically() -> None:
    later = _evidence("occ_later", released_date=date(2026, 9, 3))
    earlier = _evidence("occ_earlier", released_date=date(2026, 9, 1))

    groups = group_release_evidence([later, earlier])

    assert [g.group_key for g in groups] == ["occ_earlier", "occ_later"]

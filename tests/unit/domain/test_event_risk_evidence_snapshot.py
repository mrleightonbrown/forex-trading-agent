"""FX-54: unit tests for `EventRiskEvidenceSnapshot`'s own construction-
time validation and its no-policy contract."""

from datetime import UTC, datetime, timedelta

import pytest

from forex_agent.domain.event_coverage_evidence import build_coverage_evidence
from forex_agent.domain.event_risk_evidence_snapshot import EventRiskEvidenceSnapshot
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp

_AS_OF = UtcTimestamp(datetime(2026, 9, 1, tzinfo=UTC))
_INSTRUMENT = Instrument(base_currency="GBP", quote_currency="USD")
_COVERAGE = build_coverage_evidence("GBP", "USD")


def _snapshot(lookahead: timedelta, lookback: timedelta) -> EventRiskEvidenceSnapshot:
    return EventRiskEvidenceSnapshot(
        instrument=_INSTRUMENT,
        as_of=_AS_OF,
        lookahead=lookahead,
        lookback=lookback,
        upcoming_schedule_groups=(),
        recent_release_groups=(),
        coverage=_COVERAGE,
    )


def test_accepts_zero_horizons() -> None:
    snapshot = _snapshot(timedelta(0), timedelta(0))
    assert snapshot.lookahead == timedelta(0)
    assert snapshot.lookback == timedelta(0)


def test_rejects_negative_lookahead() -> None:
    with pytest.raises(ValueError, match="lookahead"):
        _snapshot(timedelta(hours=-1), timedelta(0))


def test_rejects_negative_lookback() -> None:
    with pytest.raises(ValueError, match="lookback"):
        _snapshot(timedelta(0), timedelta(hours=-1))


def test_empty_evidence_is_a_valid_result_not_an_error() -> None:
    # FX-54 Section 19: an empty snapshot is a legitimate result --
    # never rejected, never substituted with a default.
    snapshot = _snapshot(timedelta(hours=24), timedelta(hours=2))
    assert snapshot.upcoming_schedule_groups == ()
    assert snapshot.recent_release_groups == ()


def test_no_risk_policy_or_all_clear_field_exists() -> None:
    # FX-54 Section 3/20/27: the snapshot itself must never carry a
    # risk/policy/all-clear field of any kind.
    forbidden = {
        "risk_score",
        "importance",
        "should_trade",
        "should_avoid",
        "blackout",
        "safe_to_trade",
        "clear_of_events",
        "no_event_risk",
        "event_risk_multiplier",
    }
    fields = set(EventRiskEvidenceSnapshot.__dataclass_fields__)
    assert fields.isdisjoint(forbidden)

"""FX-56H Section 3: `NormalizedNewsObservation` validates its own
headline/quarantine-reason invariants in `__post_init__`, so a
malformed observation never reaches `RecordNewsObservation`, let
alone any repository call."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.ports.news_source import NormalizedNewsObservation
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp

_T = UtcTimestamp(datetime(2026, 9, 29, 9, 2, tzinfo=UTC))


def _observation(**overrides: object) -> NormalizedNewsObservation:
    defaults: dict[str, object] = {
        "source_key": "FED",
        "external_item_id": "item-1",
        "observed_at": _T,
        "observation_mode": NewsObservationMode.PROSPECTIVE,
        "headline": "A valid headline",
        "source_status": NewsSourceStatus.ACTIVE,
        "evidence_disposition": NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    }
    defaults.update(overrides)
    return NormalizedNewsObservation(**defaults)  # type: ignore[arg-type]


def test_valid_observation_constructs() -> None:
    observation = _observation()
    assert observation.headline == "A valid headline"


def test_blank_headline_is_rejected() -> None:
    with pytest.raises(ValueError, match="headline"):
        _observation(headline="")


def test_whitespace_only_headline_is_rejected() -> None:
    with pytest.raises(ValueError, match="headline"):
        _observation(headline="   ")


def test_quarantined_without_reason_is_rejected() -> None:
    with pytest.raises(ValueError, match="quarantine_reason"):
        _observation(evidence_disposition=NewsEvidenceDisposition.QUARANTINED)


def test_quarantined_with_reason_is_valid() -> None:
    observation = _observation(
        evidence_disposition=NewsEvidenceDisposition.QUARANTINED,
        quarantine_reason="future_source_timestamp",
    )
    assert observation.quarantine_reason == "future_source_timestamp"


def test_eligible_with_a_quarantine_reason_is_rejected() -> None:
    with pytest.raises(ValueError, match="quarantine_reason"):
        _observation(
            evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
            quarantine_reason="should not be here",
        )

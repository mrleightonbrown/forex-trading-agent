from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_status import NewsSourceStatus


def test_observation_mode_has_exactly_prospective_and_backfill() -> None:
    assert {member.value for member in NewsObservationMode} == {"PROSPECTIVE", "BACKFILL"}


def test_evidence_disposition_has_exactly_eligible_and_quarantined() -> None:
    assert {member.value for member in NewsEvidenceDisposition} == {
        "EVIDENCE_ELIGIBLE",
        "QUARANTINED",
    }


def test_source_status_has_exactly_active_and_withdrawn() -> None:
    assert {member.value for member in NewsSourceStatus} == {"ACTIVE", "WITHDRAWN"}

from datetime import UTC, datetime

import pytest

from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_revision_fact import (
    NewsSourceRevisionFact,
    NewsSourceRevisionKind,
)
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.news_source_timestamp_provenance import NewsSourceTimestampProvenance
from forex_agent.domain.timestamps import UtcTimestamp

_T = UtcTimestamp(datetime(2026, 9, 29, 9, 2, tzinfo=UTC))


def _minimal_vintage(**overrides: object) -> NewsItemVintage:
    defaults: dict[str, object] = {
        "news_item_key": "FED:abc",
        "revision_sequence": 0,
        "availability": _T,
        "observation_mode": NewsObservationMode.PROSPECTIVE,
        "headline": "Federal Reserve issues FOMC statement",
        "source_channel": "press_monetary",
        "source_status": NewsSourceStatus.ACTIVE,
        "evidence_disposition": NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    }
    defaults.update(overrides)
    return NewsItemVintage(**defaults)  # type: ignore[arg-type]


def test_minimal_vintage_constructs() -> None:
    vintage = _minimal_vintage()
    assert vintage.summary is None
    assert vintage.body_text is None
    assert vintage.authors == ()
    assert vintage.source_timestamp_provenance == ()
    assert vintage.source_revision_metadata == ()
    assert vintage.quarantine_reason is None


def test_revision_sequence_must_be_non_negative() -> None:
    with pytest.raises(ValueError, match="revision_sequence"):
        _minimal_vintage(revision_sequence=-1)


def test_headline_is_required_non_empty() -> None:
    with pytest.raises(ValueError, match="headline"):
        _minimal_vintage(headline="")


def test_source_channel_is_required_non_empty() -> None:
    with pytest.raises(ValueError, match="source_channel"):
        _minimal_vintage(source_channel="")


def test_availability_must_be_a_utc_timestamp() -> None:
    with pytest.raises(TypeError, match="availability"):
        _minimal_vintage(availability=datetime(2026, 9, 29, tzinfo=UTC))


def test_authors_must_be_a_tuple_of_non_empty_strings() -> None:
    vintage = _minimal_vintage(authors=("Alan Taylor",))
    assert vintage.authors == ("Alan Taylor",)
    with pytest.raises(ValueError, match="author"):
        _minimal_vintage(authors=("",))
    with pytest.raises(TypeError, match="authors"):
        _minimal_vintage(authors=["Alan Taylor"])


def test_source_published_at_may_be_earlier_than_availability() -> None:
    # FX-56 Section 17: this is valid and expected, not an error.
    published = UtcTimestamp(datetime(2026, 9, 29, 9, 0, tzinfo=UTC))
    vintage = _minimal_vintage(availability=_T, source_published_at=published)
    assert vintage.source_published_at == published
    assert vintage.source_published_at.value < vintage.availability.value


def test_source_timestamp_provenance_entries_must_be_the_domain_type() -> None:
    provenance = NewsSourceTimestampProvenance(field_name="dc:date", raw_value="x")
    vintage = _minimal_vintage(source_timestamp_provenance=(provenance,))
    assert vintage.source_timestamp_provenance == (provenance,)
    with pytest.raises(TypeError, match="source_timestamp_provenance"):
        _minimal_vintage(source_timestamp_provenance=({"field_name": "dc:date"},))


def test_source_revision_metadata_entries_must_be_the_domain_type() -> None:
    fact = NewsSourceRevisionFact(kind=NewsSourceRevisionKind.CORRECTION)
    vintage = _minimal_vintage(source_revision_metadata=(fact,))
    assert vintage.source_revision_metadata == (fact,)
    with pytest.raises(TypeError, match="source_revision_metadata"):
        _minimal_vintage(source_revision_metadata=("not-a-fact",))


# --- Quarantine mutual exclusivity (FX-56 Section 25/65) -------------------


def test_quarantined_requires_a_reason() -> None:
    with pytest.raises(ValueError, match="quarantine_reason"):
        _minimal_vintage(evidence_disposition=NewsEvidenceDisposition.QUARANTINED)


def test_quarantined_with_reason_is_valid() -> None:
    vintage = _minimal_vintage(
        evidence_disposition=NewsEvidenceDisposition.QUARANTINED,
        quarantine_reason="future_source_timestamp",
    )
    assert vintage.quarantine_reason == "future_source_timestamp"


def test_eligible_forbids_a_quarantine_reason() -> None:
    with pytest.raises(ValueError, match="quarantine_reason"):
        _minimal_vintage(
            evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
            quarantine_reason="should not be here",
        )


def test_source_status_independent_of_quarantine() -> None:
    # An ACTIVE article can be quarantined; a WITHDRAWN article can be
    # evidence-eligible (FX-56 Section 65) -- neither implies the other.
    quarantined_active = _minimal_vintage(
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.QUARANTINED,
        quarantine_reason="anomalous timestamp",
    )
    assert quarantined_active.source_status is NewsSourceStatus.ACTIVE

    eligible_withdrawn = _minimal_vintage(source_status=NewsSourceStatus.WITHDRAWN)
    assert eligible_withdrawn.evidence_disposition is NewsEvidenceDisposition.EVIDENCE_ELIGIBLE

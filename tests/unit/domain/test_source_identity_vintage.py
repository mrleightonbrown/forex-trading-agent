"""FX-62 Section 12.A: domain tests for `SourceIdentityVintage` --
aliases/display-name vintages, deterministic ordering of aliases, and
invalid field rejection."""

from datetime import UTC, datetime

import pytest

from forex_agent.domain.source_evidence_kind import SourceEvidenceKind
from forex_agent.domain.source_identity_vintage import SourceIdentityVintage
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(hour: int = 9) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


def _evidence() -> SourceProvenanceEvidence:
    return SourceProvenanceEvidence(
        evidence_kind=SourceEvidenceKind.ADAPTER_CONFIGURATION, description="test evidence"
    )


def _vintage(**overrides: object) -> SourceIdentityVintage:
    defaults: dict[str, object] = {
        "source_key": "FEDERAL_RESERVE",
        "revision_sequence": 0,
        "availability": _ts(),
        "algorithm_version": "fx62_v1",
        "display_name": "Federal Reserve Board / FOMC",
        "aliases": (),
        "authoritative_identifier": None,
        "canonical_website": None,
        "evidence": _evidence(),
    }
    defaults.update(overrides)
    return SourceIdentityVintage(**defaults)  # type: ignore[arg-type]


def test_constructs_with_valid_fields() -> None:
    vintage = _vintage(aliases=("FOMC", "Fed"))  # already canonically sorted
    assert vintage.aliases == ("FOMC", "Fed")


def test_revision_sequence_must_not_be_negative() -> None:
    with pytest.raises(ValueError, match="revision_sequence"):
        _vintage(revision_sequence=-1)


def test_display_name_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="display_name"):
        _vintage(display_name="")


def test_aliases_must_be_sorted() -> None:
    with pytest.raises(ValueError, match="aliases"):
        SourceIdentityVintage(
            source_key="FEDERAL_RESERVE",
            revision_sequence=0,
            availability=_ts(),
            algorithm_version="fx62_v1",
            display_name="Federal Reserve",
            aliases=("Fed", "FOMC"),  # not sorted
            authoritative_identifier=None,
            canonical_website=None,
            evidence=_evidence(),
        )


def test_aliases_must_not_contain_duplicates() -> None:
    with pytest.raises(ValueError, match="aliases"):
        _vintage(aliases=("Fed", "Fed"))


def test_optional_fields_accept_none() -> None:
    vintage = _vintage(authoritative_identifier=None, canonical_website=None)
    assert vintage.authoritative_identifier is None
    assert vintage.canonical_website is None


def test_optional_fields_reject_empty_string() -> None:
    with pytest.raises(ValueError, match="authoritative_identifier"):
        _vintage(authoritative_identifier="")


def test_evidence_must_be_a_source_provenance_evidence() -> None:
    with pytest.raises(TypeError, match="evidence"):
        _vintage(evidence="not evidence")


def test_correction_reason_optional_and_informational_only() -> None:
    vintage = _vintage(correction_reason="fixed a typo in the display name")
    assert vintage.correction_reason == "fixed a typo in the display name"

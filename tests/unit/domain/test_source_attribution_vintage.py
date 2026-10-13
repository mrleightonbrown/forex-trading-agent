"""FX-62 Section 12.A: domain tests for `SourceAttributionVintage` --
confirmed vs. unresolved attribution, publisher distinct from quoted
individual (via role), and invalid status/attributed_source_key
combination rejection."""

from datetime import UTC, datetime

import pytest

from forex_agent.domain.source_attribution_role import SourceAttributionRole
from forex_agent.domain.source_attribution_status import SourceAttributionStatus
from forex_agent.domain.source_attribution_vintage import SourceAttributionVintage
from forex_agent.domain.source_evidence_kind import SourceEvidenceKind
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(hour: int = 9) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


def _evidence() -> SourceProvenanceEvidence:
    return SourceProvenanceEvidence(
        evidence_kind=SourceEvidenceKind.ADAPTER_CONFIGURATION, description="test evidence"
    )


def _vintage(**overrides: object) -> SourceAttributionVintage:
    defaults: dict[str, object] = {
        "news_item_key": "ITEM-1",
        "role": SourceAttributionRole.PUBLISHER,
        "revision_sequence": 0,
        "availability": _ts(),
        "algorithm_version": "fx62_v1",
        "status": SourceAttributionStatus.CONFIRMED,
        "attributed_source_key": "FEDERAL_RESERVE",
        "evidence_basis_revision_sequence": 0,
        "evidence": _evidence(),
    }
    defaults.update(overrides)
    return SourceAttributionVintage(**defaults)  # type: ignore[arg-type]


def test_confirmed_attribution_requires_attributed_source_key() -> None:
    with pytest.raises(ValueError, match="attributed_source_key"):
        _vintage(status=SourceAttributionStatus.CONFIRMED, attributed_source_key=None)


def test_unresolved_attribution_forbids_attributed_source_key() -> None:
    with pytest.raises(ValueError, match="attributed_source_key"):
        _vintage(status=SourceAttributionStatus.UNRESOLVED, attributed_source_key="FEDERAL_RESERVE")


def test_unresolved_attribution_with_none_is_valid() -> None:
    vintage = _vintage(status=SourceAttributionStatus.UNRESOLVED, attributed_source_key=None)
    assert vintage.status is SourceAttributionStatus.UNRESOLVED
    assert vintage.attributed_source_key is None


@pytest.mark.parametrize(
    "role",
    [
        SourceAttributionRole.PUBLISHER,
        SourceAttributionRole.ORIGINATING_CLAIMANT,
        SourceAttributionRole.QUOTED_ACTOR,
    ],
)
def test_every_role_constructs_successfully(role: SourceAttributionRole) -> None:
    vintage = _vintage(role=role)
    assert vintage.role is role


def test_publisher_and_quoted_actor_are_distinct_roles_for_the_same_item() -> None:
    """FX-62 Section 4.3: a source may publish a document containing a
    quotation without originating the quoted claim -- these are
    genuinely different `SourceAttributionVintage` rows, distinguished
    by `role` alone, for the SAME `news_item_key`."""
    publisher = _vintage(role=SourceAttributionRole.PUBLISHER, attributed_source_key="BOE")
    quoted = _vintage(role=SourceAttributionRole.QUOTED_ACTOR, attributed_source_key="SOME_PERSON")
    assert publisher.news_item_key == quoted.news_item_key
    assert publisher.role != quoted.role
    assert publisher.attributed_source_key != quoted.attributed_source_key


def test_news_item_key_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="news_item_key"):
        _vintage(news_item_key="")


def test_revision_sequence_must_not_be_negative() -> None:
    with pytest.raises(ValueError, match="revision_sequence"):
        _vintage(revision_sequence=-1)


def test_evidence_basis_revision_sequence_must_not_be_negative() -> None:
    with pytest.raises(ValueError, match="evidence_basis_revision_sequence"):
        _vintage(evidence_basis_revision_sequence=-1)


def test_corrects_revision_sequence_must_be_strictly_earlier() -> None:
    with pytest.raises(ValueError, match="corrects_revision_sequence"):
        _vintage(revision_sequence=1, corrects_revision_sequence=1)


def test_corrects_revision_sequence_accepts_a_valid_earlier_value() -> None:
    vintage = _vintage(revision_sequence=2, corrects_revision_sequence=1)
    assert vintage.corrects_revision_sequence == 1

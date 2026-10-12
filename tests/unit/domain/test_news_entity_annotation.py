import pytest

from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
from forex_agent.domain.news_entity_type import NewsEntityType


def test_valid_entity_annotation_constructs() -> None:
    annotation = NewsEntityAnnotation(
        entity_type=NewsEntityType.INSTITUTION,
        entity_key="FEDERAL_RESERVE",
        evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
    )
    assert annotation.entity_key == "FEDERAL_RESERVE"


def test_blank_entity_key_rejected() -> None:
    with pytest.raises(ValueError, match="entity_key"):
        NewsEntityAnnotation(
            entity_type=NewsEntityType.INSTITUTION,
            entity_key="   ",
            evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
        )


def test_wrong_entity_type_rejected() -> None:
    with pytest.raises(TypeError, match="entity_type"):
        NewsEntityAnnotation(
            entity_type="INSTITUTION",  # type: ignore[arg-type]
            entity_key="FEDERAL_RESERVE",
            evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
        )


def test_empty_evidence_rejected() -> None:
    with pytest.raises(ValueError, match="evidence"):
        NewsEntityAnnotation(
            entity_type=NewsEntityType.INSTITUTION, entity_key="FEDERAL_RESERVE", evidence=()
        )


def test_duplicate_evidence_rejected() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        NewsEntityAnnotation(
            entity_type=NewsEntityType.INSTITUTION,
            entity_key="FEDERAL_RESERVE",
            evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE, NewsEntityEvidenceKind.SOURCE_PROFILE),
        )


def test_noncanonical_evidence_order_rejected() -> None:
    # TEXT_ALIAS.value == "TEXT_ALIAS" sorts before "SOURCE_PROFILE"? No --
    # "SOURCE_PROFILE" < "TEXT_ALIAS" lexically, so this order is wrong.
    with pytest.raises(ValueError, match="canonical sorted order"):
        NewsEntityAnnotation(
            entity_type=NewsEntityType.INSTITUTION,
            entity_key="FEDERAL_RESERVE",
            evidence=(NewsEntityEvidenceKind.TEXT_ALIAS, NewsEntityEvidenceKind.SOURCE_PROFILE),
        )


def test_both_evidence_kinds_together_is_valid() -> None:
    annotation = NewsEntityAnnotation(
        entity_type=NewsEntityType.INSTITUTION,
        entity_key="FEDERAL_RESERVE",
        evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE, NewsEntityEvidenceKind.TEXT_ALIAS),
    )
    assert len(annotation.evidence) == 2

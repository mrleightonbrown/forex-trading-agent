"""FX-64 Section 6: tests for `ForecastEvidenceReference`."""

from datetime import UTC, datetime

import pytest

from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.timestamps import UtcTimestamp


def test_news_item_vintage_basis_valid() -> None:
    evidence = ForecastEvidenceReference(
        evidence_kind=ForecastEvidenceKind.NEWS_ITEM_VINTAGE_BASIS,
        description="Read directly from the stored article text.",
        news_item_key="ITEM-1",
        basis_revision_sequence=0,
    )
    assert evidence.news_item_key == "ITEM-1"


def test_news_item_vintage_basis_requires_news_item_key() -> None:
    with pytest.raises(ValueError, match="news_item_key"):
        ForecastEvidenceReference(
            evidence_kind=ForecastEvidenceKind.NEWS_ITEM_VINTAGE_BASIS,
            description="desc",
            basis_revision_sequence=0,
        )


def test_news_item_vintage_basis_requires_basis_revision_sequence() -> None:
    with pytest.raises(ValueError, match="basis_revision_sequence"):
        ForecastEvidenceReference(
            evidence_kind=ForecastEvidenceKind.NEWS_ITEM_VINTAGE_BASIS,
            description="desc",
            news_item_key="ITEM-1",
        )


def test_news_item_vintage_basis_rejects_document_identifier() -> None:
    with pytest.raises(ValueError, match="document_identifier"):
        ForecastEvidenceReference(
            evidence_kind=ForecastEvidenceKind.NEWS_ITEM_VINTAGE_BASIS,
            description="desc",
            news_item_key="ITEM-1",
            basis_revision_sequence=0,
            document_identifier="SPF-2025Q1",
        )


def test_external_document_reference_valid() -> None:
    evidence = ForecastEvidenceReference(
        evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        description="Read directly from the published survey results table.",
        document_identifier="ECB-SPF-2025Q1",
        document_locator="Table 1, row 'HICP inflation 2025'",
        official_reference_url="https://www.ecb.europa.eu/stats/ecb_surveys/survey_of_professional_forecasters/html/index.en.html",
        content_fingerprint="sha256:abc123",
        publisher_declared_publication_at=UtcTimestamp(datetime(2025, 1, 20, tzinfo=UTC)),
    )
    assert evidence.document_identifier == "ECB-SPF-2025Q1"


def test_external_document_reference_requires_document_identifier() -> None:
    with pytest.raises(ValueError, match="document_identifier"):
        ForecastEvidenceReference(
            evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
            description="desc",
        )


def test_external_document_reference_rejects_news_item_key() -> None:
    with pytest.raises(ValueError, match="news_item_key"):
        ForecastEvidenceReference(
            evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
            description="desc",
            document_identifier="ECB-SPF-2025Q1",
            news_item_key="ITEM-1",
        )


def test_empty_description_rejected() -> None:
    with pytest.raises(ValueError, match="description"):
        ForecastEvidenceReference(
            evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
            description="",
            document_identifier="ECB-SPF-2025Q1",
        )


def test_publisher_declared_publication_at_distinct_from_fta_availability() -> None:
    """Section 6/7: this field is purely descriptive, never promoted
    to anything resembling FTA's own availability -- proven here just
    by confirming it is a plain, independent field with no special
    coupling in the type itself."""
    published_at = UtcTimestamp(datetime(2023, 1, 1, tzinfo=UTC))
    evidence = ForecastEvidenceReference(
        evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        description="desc",
        document_identifier="DOC-1",
        publisher_declared_publication_at=published_at,
    )
    assert evidence.publisher_declared_publication_at == published_at


def test_missing_evidence_entirely_is_rejected_by_construction() -> None:
    """There is no way to construct a `ForecastEvidenceReference`
    satisfying neither evidence shape -- `evidence_kind` is required,
    and each kind has its own required field(s)."""
    with pytest.raises(TypeError, match="evidence_kind"):
        ForecastEvidenceReference(evidence_kind="NONE", description="desc")  # type: ignore[arg-type]

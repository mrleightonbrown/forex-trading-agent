"""FX-65 Section 8: tests for `EvidenceAuthenticationReview`."""

from datetime import UTC, datetime

import pytest

from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.timestamps import UtcTimestamp


def _ts() -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))


def test_valid_review() -> None:
    review = EvidenceAuthenticationReview(
        reviewed_by="FTA research operator",
        review_method="Cross-checked against the official press release",
        reviewed_at=_ts(),
        corroboration_reference="https://example.org/release",
    )
    assert review.corroboration_reference == "https://example.org/release"


def test_corroboration_reference_optional() -> None:
    review = EvidenceAuthenticationReview(
        reviewed_by="FTA research operator", review_method="Direct review", reviewed_at=_ts()
    )
    assert review.corroboration_reference is None


@pytest.mark.parametrize("reviewed_by", ["", "   "])
def test_empty_reviewed_by_rejected(reviewed_by: str) -> None:
    with pytest.raises(ValueError, match="reviewed_by"):
        EvidenceAuthenticationReview(
            reviewed_by=reviewed_by, review_method="Direct review", reviewed_at=_ts()
        )


def test_non_utc_timestamp_reviewed_at_rejected() -> None:
    with pytest.raises(TypeError, match="reviewed_at"):
        EvidenceAuthenticationReview(
            reviewed_by="FTA research operator",
            review_method="Direct review",
            reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),  # type: ignore[arg-type]
        )

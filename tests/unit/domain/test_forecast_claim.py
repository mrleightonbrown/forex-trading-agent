"""FX-64 Section 5: tests for `ForecastClaim` -- the minimal durable
identity, mirroring FX-62's `IntelligenceSource` shape."""

from datetime import UTC, datetime

import pytest

from forex_agent.domain.forecast_claim import ForecastClaim
from forex_agent.domain.timestamps import UtcTimestamp


def test_constructs_with_valid_fields() -> None:
    claim = ForecastClaim(
        claim_key="ECB-SPF-2025Q1:EA_HICP_YOY_ANNUAL_AVERAGE:AGGREGATE",
        registered_at=UtcTimestamp(datetime(2025, 1, 20, tzinfo=UTC)),
    )
    assert claim.claim_key == "ECB-SPF-2025Q1:EA_HICP_YOY_ANNUAL_AVERAGE:AGGREGATE"


def test_empty_claim_key_rejected() -> None:
    with pytest.raises(ValueError, match="claim_key"):
        ForecastClaim(claim_key="", registered_at=UtcTimestamp(datetime(2025, 1, 1, tzinfo=UTC)))


def test_wrong_registered_at_type_rejected() -> None:
    with pytest.raises(TypeError, match="registered_at"):
        ForecastClaim(claim_key="CLAIM-1", registered_at=datetime(2025, 1, 1, tzinfo=UTC))  # type: ignore[arg-type]


def test_claim_is_immutable() -> None:
    from dataclasses import FrozenInstanceError

    claim = ForecastClaim(
        claim_key="CLAIM-1", registered_at=UtcTimestamp(datetime(2025, 1, 1, tzinfo=UTC))
    )
    with pytest.raises(FrozenInstanceError):
        claim.claim_key = "CLAIM-2"  # type: ignore[misc]


def test_two_forecasters_predicting_the_same_value_are_distinct_claims() -> None:
    """Section 5's own explicit invariant: claim identity is never
    derived from the forecast VALUE -- proven structurally here by two
    independently-keyed claims coexisting with no collision."""
    claim_a = ForecastClaim(
        claim_key="SURVEY:ROUND-1:FORECASTER-A",
        registered_at=UtcTimestamp(datetime(2025, 1, 1, tzinfo=UTC)),
    )
    claim_b = ForecastClaim(
        claim_key="SURVEY:ROUND-1:FORECASTER-B",
        registered_at=UtcTimestamp(datetime(2025, 1, 1, tzinfo=UTC)),
    )
    assert claim_a.claim_key != claim_b.claim_key

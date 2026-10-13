"""FX-64: an in-memory fake implementing `StructuredForecastRepository`,
mirroring the real `SqlAlchemyStructuredForecastRepository`'s own
exact latest-by-(availability, revision_sequence) selection and
idempotent-write semantics -- including the production-vs-research
provenance filtering boundary (Section 7), so application-layer tests
exercise the SAME separation the real repository enforces."""

from forex_agent.application.ports.structured_forecast_repository import (
    ForecastClaimRegistrationResult,
    ForecastVintageWriteResult,
)
from forex_agent.domain.forecast_claim import ForecastClaim
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp


def _sort_key(vintage: StructuredForecastVintage) -> tuple[object, int]:
    return (vintage.availability.value, vintage.revision_sequence)


class FakeStructuredForecastRepository:
    def __init__(self) -> None:
        self.claims: dict[str, ForecastClaim] = {}
        self.vintages: dict[str, list[StructuredForecastVintage]] = {}

    async def get_claim(self, claim_key: str) -> ForecastClaim | None:
        return self.claims.get(claim_key)

    async def register_claim_with_first_vintage(
        self, claim: ForecastClaim, first_vintage: StructuredForecastVintage
    ) -> ForecastClaimRegistrationResult:
        if claim.claim_key in self.claims:
            return ForecastClaimRegistrationResult(created=False)
        self.claims[claim.claim_key] = claim
        self.vintages[claim.claim_key] = [first_vintage]
        return ForecastClaimRegistrationResult(created=True)

    async def add_vintage(self, vintage: StructuredForecastVintage) -> ForecastVintageWriteResult:
        existing = self.vintages.setdefault(vintage.claim_key, [])
        if any(v.revision_sequence == vintage.revision_sequence for v in existing):
            return ForecastVintageWriteResult(inserted=False)
        existing.append(vintage)
        return ForecastVintageWriteResult(inserted=True)

    async def list_vintages_for_claim(
        self, claim_key: str
    ) -> tuple[StructuredForecastVintage, ...]:
        return tuple(self.vintages.get(claim_key, ()))

    async def latest_vintage_for_claim(self, claim_key: str) -> StructuredForecastVintage | None:
        vintages = self.vintages.get(claim_key, ())
        if not vintages:
            return None
        return max(vintages, key=_sort_key)

    async def latest_production_observed_vintage_as_of(
        self, claim_key: str, as_of: UtcTimestamp
    ) -> StructuredForecastVintage | None:
        eligible = [
            v
            for v in self.vintages.get(claim_key, ())
            if v.provenance_mode is ForecastProvenanceMode.PRODUCTION_OBSERVED
            and v.availability.value <= as_of.value
        ]
        return max(eligible, key=_sort_key) if eligible else None

    async def list_production_observed_claims_as_of(
        self,
        as_of: UtcTimestamp,
        *,
        target_key: str | None = None,
        window_start: UtcTimestamp | None = None,
        window_end: UtcTimestamp | None = None,
    ) -> tuple[StructuredForecastVintage, ...]:
        results: list[StructuredForecastVintage] = []
        for claim_key in self.vintages:
            latest = await self.latest_production_observed_vintage_as_of(claim_key, as_of)
            if latest is None:
                continue
            if target_key is not None and latest.target_key != target_key:
                continue
            if window_start is not None and latest.availability.value < window_start.value:
                continue
            if window_end is not None and latest.availability.value > window_end.value:
                continue
            results.append(latest)
        return tuple(results)

    async def latest_vintage_as_of_for_research(
        self, claim_key: str, research_as_of: UtcTimestamp
    ) -> StructuredForecastVintage | None:
        eligible = [
            v
            for v in self.vintages.get(claim_key, ())
            if v.availability.value <= research_as_of.value
        ]
        return max(eligible, key=_sort_key) if eligible else None

"""FX-64: port for storing and point-in-time-querying FTA's own
structured forecast registry -- mirrors FX-62's `SourceRegistry
Repository` shape (minimal immutable `ForecastClaim` + append-only
`StructuredForecastVintage`) but with ONE additional, load-bearing
distinction Section 7 requires: an ordinary PRODUCTION read method and
a SEPARATE, differently-named RESEARCH read method, so a caller can
never accidentally receive a `RETROSPECTIVE_RESEARCH` vintage through
an ordinary `as_of` query. There is NO single method that silently
decides which provenance mode to include -- the caller's own choice
of method name is the only switch, and it is visible at every call
site."""

from dataclasses import dataclass
from typing import Protocol

from forex_agent.domain.forecast_claim import ForecastClaim
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastClaimRegistrationResult:
    created: bool


@dataclass(frozen=True, slots=True)
class ForecastVintageWriteResult:
    inserted: bool


class StructuredForecastRepository(Protocol):
    async def get_claim(self, claim_key: str) -> ForecastClaim | None: ...

    async def register_claim_with_first_vintage(
        self, claim: ForecastClaim, first_vintage: StructuredForecastVintage
    ) -> ForecastClaimRegistrationResult:
        """Atomically resolves `claim.claim_key` to a durable claim,
        together with its own revision-0 vintage -- mirrors FX-62's
        own `register_source_with_first_identity_vintage` exactly: no
        caller can ever observe a claim with zero vintages."""
        ...

    async def add_vintage(self, vintage: StructuredForecastVintage) -> ForecastVintageWriteResult:
        """Append-only insert keyed on `(claim_key, revision_
        sequence)` -- `ON CONFLICT DO NOTHING` semantics, mirroring
        every other FX-56/58/59/62 vintage repository."""
        ...

    async def list_vintages_for_claim(
        self, claim_key: str
    ) -> tuple[StructuredForecastVintage, ...]:
        """Every stored vintage of this claim, in no particular
        guaranteed order -- an administrative/audit read, used by the
        full-history determinism check (Section 13)."""
        ...

    async def latest_vintage_for_claim(self, claim_key: str) -> StructuredForecastVintage | None:
        """The claim's own latest vintage by `(availability, revision_
        sequence)`, REGARDLESS of `provenance_mode` -- an
        administrative read used only by the recording use case's own
        PIT-ordering/idempotency checks (which must see every vintage
        ever written, including retrospective ones, to correctly
        order a NEW retrospective vintage against an EARLIER
        retrospective one). Never used to answer a production or
        research QUERY -- see the two methods below for those."""
        ...

    async def latest_production_observed_vintage_as_of(
        self, claim_key: str, as_of: UtcTimestamp
    ) -> StructuredForecastVintage | None:
        """FX-64 Section 7: the ONLY production PIT read this port
        offers. Returns the latest vintage with `provenance_mode ==
        PRODUCTION_OBSERVED` and `availability <= as_of` -- a
        `RETROSPECTIVE_RESEARCH` vintage is NEVER returned here,
        regardless of its own `availability`. `None` if no such
        vintage exists (including when the claim has ONLY
        retrospective vintages)."""
        ...

    async def list_production_observed_claims_as_of(
        self,
        as_of: UtcTimestamp,
        *,
        target_key: str | None = None,
        window_start: UtcTimestamp | None = None,
        window_end: UtcTimestamp | None = None,
    ) -> tuple[StructuredForecastVintage, ...]:
        """FX-64 Section 14 (`ListForecastClaimsAsOf`): every claim's
        own latest `PRODUCTION_OBSERVED` vintage with `availability <=
        as_of`, one row per claim, optionally bounded by `target_key`
        and/or an inclusive `[window_start, window_end]` on
        `availability`. Never includes a `RETROSPECTIVE_RESEARCH`
        vintage."""
        ...

    async def latest_vintage_as_of_for_research(
        self, claim_key: str, research_as_of: UtcTimestamp
    ) -> StructuredForecastVintage | None:
        """FX-64 Section 7 (`GetRetrospectiveForecastResearchView`'s
        own read path): the latest vintage with `availability <=
        research_as_of`, of EITHER provenance mode -- deliberately
        named differently from every production method above so a
        caller can never reach this by accident. `research_as_of` is
        a SEPARATE dimension from any production `as_of` (Section 7's
        own explicit "historical retrospective inclusion and
        historical production knowledge are separate dimensions, not
        interchangeable timestamps") -- it still means "FTA's own
        knowledge as of this instant," just without excluding
        retrospective vintages."""
        ...

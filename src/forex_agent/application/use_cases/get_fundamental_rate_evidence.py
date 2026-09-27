"""FX-54V: the "Market Context" dashboard's own Fundamentals card --
`(instrument, as_of, rate_semantics)` -> a `FundamentalRateEvidence`
that reports each leg's current policy-rate state independently, never
requiring both to resolve (see that type's own docstring for why this
is deliberately NOT `ComputePolicyRateDifferential`/FX-45's own use
case: FX-45 gates its result behind `domain.research_readiness` --
correct for a differential-CHANGE research feature, wrong for
truthfully displaying today's already-known rate on a dashboard, since
a research-safety window failure there would blank out a factual,
already-known rate for no correctness reason).

Does no new PIT logic of its own -- pure orchestration over `domain.
policy_rate_state.announced_state_as_of`/`effective_state_as_of` and
`domain.policy_rate_differential.CurrencyRateState.from_vintage`/
`rate_differential`, exactly the same pure functions FX-45 itself is
built on, with no additional gate layered on top.
"""

from dataclasses import dataclass

from forex_agent.application.ports.macro_observation_repository import MacroObservationRepository
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.policy_rate_differential import (
    CurrencyRateState,
    FundamentalRateEvidence,
    RateSemantics,
    format_pair,
    rate_differential,
)
from forex_agent.domain.policy_rate_registry import canonical_series_for_currency
from forex_agent.domain.policy_rate_state import announced_state_as_of, effective_state_as_of
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class GetFundamentalRateEvidence:
    """See the module docstring."""

    repository: MacroObservationRepository

    async def __call__(
        self, instrument: Instrument, as_of: UtcTimestamp, rate_semantics: RateSemantics
    ) -> FundamentalRateEvidence:
        base, base_reason = await self._resolve(instrument.base_currency, as_of, rate_semantics)
        quote, quote_reason = await self._resolve(instrument.quote_currency, as_of, rate_semantics)
        differential = (
            rate_differential(base.rate, quote.rate)
            if base is not None and quote is not None
            else None
        )
        return FundamentalRateEvidence(
            pair=format_pair(instrument.base_currency, instrument.quote_currency),
            as_of=as_of,
            rate_semantics=rate_semantics,
            base_currency=instrument.base_currency,
            quote_currency=instrument.quote_currency,
            base=base,
            base_unavailable_reason=base_reason,
            quote=quote,
            quote_unavailable_reason=quote_reason,
            differential=differential,
        )

    async def _resolve(
        self, currency: str, as_of: UtcTimestamp, rate_semantics: RateSemantics
    ) -> tuple[CurrencyRateState | None, str | None]:
        series = canonical_series_for_currency(currency)
        if series is None:
            return None, f"{currency} has no canonical policy rate in this registry"

        history: tuple[MacroObservationVintage, ...] = await self.repository.list_all_for_series(
            series.key
        )
        state_as_of = (
            announced_state_as_of
            if rate_semantics is RateSemantics.ANNOUNCED
            else effective_state_as_of
        )
        vintage = state_as_of(history, as_of)
        if vintage is None:
            reason = (
                f"no {rate_semantics.value} policy-rate state is defensibly established for "
                f"{currency} as of {as_of.value.isoformat()}"
            )
            return None, reason
        return CurrencyRateState.from_vintage(currency, vintage), None

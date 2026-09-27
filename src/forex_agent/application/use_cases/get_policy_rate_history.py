"""FX-54V: the "Market Context" dashboard's policy-rate history chart
-- `(instrument, as_of, rate_semantics)` -> a `PolicyRateHistory`
giving both legs' full chronological rate path as currently knowable
at `as_of`, via `domain.policy_rate_state.announced_history_as_of`/
`effective_history_as_of`. No `domain.research_readiness` gate (see
that module's own docstring, and `get_fundamental_rate_evidence`'s,
for why a display-only history is a different question from a
research-safety requirement).
"""

from dataclasses import dataclass

from forex_agent.application.ports.macro_observation_repository import MacroObservationRepository
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.policy_rate_differential import PolicyRateHistory, RateSemantics
from forex_agent.domain.policy_rate_registry import canonical_series_for_currency
from forex_agent.domain.policy_rate_state import announced_history_as_of, effective_history_as_of
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class GetPolicyRateHistory:
    """See the module docstring."""

    repository: MacroObservationRepository

    async def __call__(
        self, instrument: Instrument, as_of: UtcTimestamp, rate_semantics: RateSemantics
    ) -> PolicyRateHistory:
        history_as_of = (
            announced_history_as_of
            if rate_semantics is RateSemantics.ANNOUNCED
            else effective_history_as_of
        )
        base_series = canonical_series_for_currency(instrument.base_currency)
        quote_series = canonical_series_for_currency(instrument.quote_currency)

        base_vintages = (
            await self.repository.list_all_for_series(base_series.key)
            if base_series is not None
            else ()
        )
        quote_vintages = (
            await self.repository.list_all_for_series(quote_series.key)
            if quote_series is not None
            else ()
        )

        return PolicyRateHistory(
            base_currency=instrument.base_currency,
            quote_currency=instrument.quote_currency,
            rate_semantics=rate_semantics,
            base_history=history_as_of(base_vintages, as_of),
            quote_history=history_as_of(quote_vintages, as_of),
        )

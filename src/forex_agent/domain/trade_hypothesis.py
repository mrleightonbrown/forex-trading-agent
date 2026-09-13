from dataclasses import dataclass

from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide


@dataclass(frozen=True, slots=True)
class TradeHypothesis:
    """The raw output of a `Strategy` — nothing more.

    Carries zero authority on its own. CLAUDE.md's execution pipeline is
    trade hypothesis -> risk decision -> approved execution intent -> order;
    this is only the first stage. No risk decision or execution intent type
    exists yet (Risk Engine / Paper Trading Execution aren't in the current
    phase), so nothing can legitimately turn this into an order yet.
    """

    instrument: Instrument
    side: TradeSide
    generated_at: UtcTimestamp
    rationale: str

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError(
                f"instrument must be an Instrument, got {type(self.instrument).__name__}"
            )
        if not isinstance(self.side, TradeSide):
            raise TypeError(f"side must be a TradeSide, got {type(self.side).__name__}")
        if not isinstance(self.generated_at, UtcTimestamp):
            raise TypeError(
                f"generated_at must be a UtcTimestamp, got {type(self.generated_at).__name__}"
            )
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("rationale must be a non-empty string")

from dataclasses import dataclass

from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class Candle:
    """One historical price bar for an instrument at a given granularity.

    `is_finalized` mirrors OANDA's `complete` flag under a name that states
    the rule directly — CLAUDE.md: "Strategies must only evaluate finalized
    candles."
    """

    instrument: Instrument
    granularity: Granularity
    start_time: UtcTimestamp
    bid: Ohlc
    ask: Ohlc
    volume: int
    is_finalized: bool

    def __post_init__(self) -> None:
        if not isinstance(self.granularity, Granularity):
            raise TypeError(
                f"granularity must be a Granularity, got {type(self.granularity).__name__}"
            )
        if not isinstance(self.start_time, UtcTimestamp):
            raise TypeError(
                f"start_time must be a UtcTimestamp, got {type(self.start_time).__name__}"
            )
        if not isinstance(self.bid, Ohlc):
            raise TypeError(f"bid must be an Ohlc, got {type(self.bid).__name__}")
        if not isinstance(self.ask, Ohlc):
            raise TypeError(f"ask must be an Ohlc, got {type(self.ask).__name__}")
        if self.volume < 0:
            raise ValueError(f"volume must not be negative, got {self.volume}")

        # At a given instant, ask >= bid always holds — open and close are
        # each a single instant (unlike high/low, which can occur at
        # different moments for each side), so this is safe to check
        # exactly. A violation means corrupt/crossed provider data.
        if self.ask.open < self.bid.open:
            raise ValueError(
                f"crossed market at open: ask ({self.ask.open}) < bid ({self.bid.open})"
            )
        if self.ask.close < self.bid.close:
            raise ValueError(
                f"crossed market at close: ask ({self.ask.close}) < bid ({self.bid.close})"
            )

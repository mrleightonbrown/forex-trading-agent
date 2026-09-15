from enum import Enum


class TargetPosition(Enum):
    """What a `Strategy` wants the position to be — `TradeHypothesis`'s
    directional field (FX-18). Distinct from `TradeSide`: `TradeSide` is
    execution-only (LONG/SHORT — what a fill or an open position actually
    is), while `TargetPosition` additionally carries FLAT, letting a
    strategy express "close out and stay out" as a real signal rather than
    an opposite-direction hypothesis abused to trigger a close.

    Carries no execution authority of its own — same as `TradeHypothesis`
    itself (see its docstring): nothing here can turn a FLAT/LONG/SHORT
    target into an order without the risk/execution pipeline CLAUDE.md
    requires.
    """

    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"

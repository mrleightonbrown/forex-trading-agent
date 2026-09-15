from dataclasses import dataclass

from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class TradeHypothesis:
    """The raw output of a `Strategy` — nothing more.

    Carries zero authority on its own. CLAUDE.md's execution pipeline is
    trade hypothesis -> risk decision -> approved execution intent -> order;
    this is only the first stage. No risk decision or execution intent type
    exists yet (Risk Engine / Paper Trading Execution aren't in the current
    phase), so nothing can legitimately turn this into an order yet.

    `timeframe`/`strategy_key`/`strategy_version`/`parameters` (FX-13) give
    every hypothesis full provenance — which algorithm produced it, which
    revision of that algorithm, with what parameters, on what granularity.
    All four are required: this enrichment only does its job if every
    future concrete `Strategy` is forced to supply full identity, not
    permitted to omit it.

    `strategy_key` identifies the algorithm itself (e.g. `"ema_crossover_v1"`
    — the `_v1` there is part of the algorithm's own identity, changing
    only if the trading logic itself changes). `strategy_version` tracks
    revisions to that same algorithm's implementation/parameterization
    over time without renaming the key — a different axis, not a
    restatement of it.

    `parameters` is a tuple of `(key, value)` string pairs, not a `dict` —
    a `dict` would make this frozen dataclass unhashable, breaking the
    pattern every other domain value object follows. Build it with
    `params_from_dict` rather than hand-writing tuple literals.

    `target_position` (FX-18) is a `TargetPosition` (LONG/SHORT/FLAT), not
    a `TradeSide` (LONG/SHORT only) — a strategy can ask to be flat, which
    no execution-side type can express. See `target_position.py`.
    """

    instrument: Instrument
    target_position: TargetPosition
    generated_at: UtcTimestamp
    timeframe: Granularity
    strategy_key: str
    strategy_version: str
    parameters: tuple[tuple[str, str], ...]
    rationale: str

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError(
                f"instrument must be an Instrument, got {type(self.instrument).__name__}"
            )
        if not isinstance(self.target_position, TargetPosition):
            raise TypeError(
                f"target_position must be a TargetPosition, got "
                f"{type(self.target_position).__name__}"
            )
        if not isinstance(self.generated_at, UtcTimestamp):
            raise TypeError(
                f"generated_at must be a UtcTimestamp, got {type(self.generated_at).__name__}"
            )
        if not isinstance(self.timeframe, Granularity):
            raise TypeError(f"timeframe must be a Granularity, got {type(self.timeframe).__name__}")
        if not isinstance(self.strategy_key, str) or not self.strategy_key.strip():
            raise ValueError("strategy_key must be a non-empty string")
        if not isinstance(self.strategy_version, str) or not self.strategy_version.strip():
            raise ValueError("strategy_version must be a non-empty string")
        self._require_valid_parameters()
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("rationale must be a non-empty string")

    def _require_valid_parameters(self) -> None:
        if not isinstance(self.parameters, tuple):
            raise TypeError(f"parameters must be a tuple, got {type(self.parameters).__name__}")
        seen_keys: set[str] = set()
        for entry in self.parameters:
            if not (isinstance(entry, tuple) and len(entry) == 2):
                raise TypeError("each parameters entry must be a (key, value) tuple of two strings")
            key, value = entry
            if not isinstance(key, str) or not isinstance(value, str):
                raise TypeError("each parameters entry must be a (key, value) tuple of two strings")
            if key in seen_keys:
                raise ValueError(f"duplicate parameter key: {key!r}")
            seen_keys.add(key)


def params_from_dict(params: dict[str, object]) -> tuple[tuple[str, str], ...]:
    """Convert a strategy's own typed parameters (e.g.
    `{"fast_period": 20}`) into `TradeHypothesis.parameters`'s hashable
    `(key, value)` string-pair form, stringifying each value."""
    return tuple((key, str(value)) for key, value in params.items())

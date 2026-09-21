"""In-memory `MacroObservationRepository` test double (FX-41; hardened
FX-41H).

Deliberately re-implements the same point-in-time filtering/ordering/
conflict rules as `SqlAlchemyMacroObservationRepository` (filter
`released_at <= as_of`, then order by revision_sequence-tie-broken
descending; raise `MacroVintageConflictError` on a same-identity,
different-payload `add_vintage`) rather than delegating to it -- this
fake has no database, and its own semantics are exactly what the
`tests/unit` scenario tests in this story exercise.
"""

from forex_agent.application.ports.macro_observation_repository import (
    MacroVintageConflictError,
)
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.timestamps import UtcTimestamp


class FakeMacroObservationRepository:
    """Structurally satisfies `MacroObservationRepository` (a
    `Protocol`) — no inheritance needed; see
    `forex_agent.application.ports.macro_observation_repository`."""

    def __init__(self) -> None:
        self._vintages: dict[tuple[str, object, int], MacroObservationVintage] = {}

    async def add_vintage(self, vintage: MacroObservationVintage) -> None:
        key = (vintage.series_key, vintage.observation_period.value, vintage.revision_sequence)
        existing = self._vintages.get(key)
        if existing is None:
            self._vintages[key] = vintage
            return
        if existing == vintage:
            return  # exact retry -- idempotent, not an error (FX-41H)
        raise MacroVintageConflictError(existing, vintage)

    async def latest_available_as_of(
        self, series_key: str, as_of: UtcTimestamp
    ) -> MacroObservationVintage | None:
        candidates = [
            v
            for v in self._vintages.values()
            if v.series_key == series_key and v.released_at.value <= as_of.value
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda v: (v.observation_period.value, v.released_at.value, v.revision_sequence),
        )

    async def observation_as_known_at(
        self, series_key: str, observation_period: UtcTimestamp, as_of: UtcTimestamp
    ) -> MacroObservationVintage | None:
        candidates = [
            v
            for v in self._vintages.values()
            if v.series_key == series_key
            and v.observation_period.value == observation_period.value
            and v.released_at.value <= as_of.value
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda v: (v.released_at.value, v.revision_sequence))

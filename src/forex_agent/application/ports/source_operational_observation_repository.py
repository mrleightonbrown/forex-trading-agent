"""FX-63: port for storing and point-in-time-querying FTA's own
acquisition-attempt observations -- a genuinely append-only, no-
revision-concept sibling of `application.ports.news_repository.
NewsRepository`. Every stored `SourceOperationalObservation` is a
distinct, independent event; this port has no "latest" or "revision"
concept at all, unlike every FX-56/58/59/62 vintage port -- a retried
attempt is simply another row, never a correction of an earlier one.
"""

from dataclasses import dataclass
from typing import Protocol

from forex_agent.domain.source_operational_observation import SourceOperationalObservation
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class SourceOperationalObservationWriteResult:
    inserted: bool
    """`False` when `(source_key, run_id, attempt_number)` already
    existed -- an idempotent re-delivery of the same logical event,
    never an error (Section 6)."""


class SourceOperationalObservationRepository(Protocol):
    async def add_observation(
        self, observation: SourceOperationalObservation
    ) -> SourceOperationalObservationWriteResult:
        """Idempotent insert keyed on `(source_key, run_id, attempt_
        number)` -- `ON CONFLICT DO NOTHING` semantics. Never raises
        on a genuine duplicate delivery of the SAME observation;
        a caller presenting the SAME natural key with DIFFERENT
        content is a caller bug, not a data condition this port
        itself adjudicates (there is no revision/correction concept
        here to appeal to)."""
        ...

    async def list_observations_for_source_as_of(
        self, source_key: str, window_start: UtcTimestamp, as_of: UtcTimestamp
    ) -> tuple[SourceOperationalObservation, ...]:
        """Every observation for `source_key` with `window_start <=
        availability <= as_of` -- both bounds inclusive. Never returns
        an observation outside this window; never filters by anything
        else (channel, outcome, ...) -- that is the measurement
        layer's own job.

        **FX-63H Section H2**: this is now the ONLY read method this
        port offers, and the ONLY evidence `GetSourceOperationalProfile
        AsOf` uses to judge acquisition coverage for a window --
        whether this window has ANY recorded attempt. An earlier
        version of this port also offered `earliest_observation_
        availability_for_source`, used to infer "coverage starts at
        the earliest-ever-recorded instant" -- retired because an
        observation existing before `window_start` does not prove the
        window itself was continuously instrumented (this codebase has
        no heartbeat/liveness signal, only discrete attempt events);
        see ADR 0011's own FX-63H addendum."""
        ...

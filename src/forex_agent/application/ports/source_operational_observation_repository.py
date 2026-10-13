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
        layer's own job."""
        ...

    async def earliest_observation_availability_for_source(
        self, source_key: str, as_of: UtcTimestamp
    ) -> UtcTimestamp | None:
        """The EARLIEST `availability` recorded for `source_key` with
        `availability <= as_of` -- PIT-filtered, exactly like every
        other `*_as_of` method in this codebase -- or `None` if no
        such observation exists. **Must never consider an observation
        whose own `availability` is after `as_of`**: a future attempt
        that has not yet happened, as of this query's own historical
        instant, must never influence a coverage judgment about an
        earlier instant (historical immutability). Used ONLY to
        determine acquisition-metric COVERAGE (Section 8.4) -- whether
        instrumentation was even running before a requested `window_
        start` -- never to backfill or infer a historical attempt
        that was never actually recorded."""
        ...

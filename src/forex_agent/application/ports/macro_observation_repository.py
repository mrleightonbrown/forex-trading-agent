from typing import Protocol

from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.timestamps import UtcTimestamp


class MacroObservationRepository(Protocol):
    """Port for storing and point-in-time-querying `MacroObservationVintage`
    records (FX-41).

    The defining invariant of both read methods: a query at timestamp T
    must never return a vintage whose `released_at` is after T. Neither
    method takes an `effective_at` cutoff -- `effective_at` describes
    when a value takes legal/economic effect, not when it became
    knowable, so it plays no part in what a point-in-time query is
    allowed to see.

    No HTTP/provider logic belongs behind this port -- see
    `docs/ARCHITECTURE.md`. A concrete implementation only ever receives
    already-constructed `MacroObservationVintage` domain objects;
    translating a specific provider's response into one is an
    infrastructure adapter's job, not this port's.
    """

    async def add_vintage(self, vintage: MacroObservationVintage) -> None:
        """Persist a new vintage. Never mutates or replaces an existing
        one -- a revision is a new vintage with a later `released_at`
        and higher `revision_sequence` for the same
        (series_key, observation_period)."""
        ...

    async def latest_available_as_of(
        self, series_key: str, as_of: UtcTimestamp
    ) -> MacroObservationVintage | None:
        """The most recent observation period for `series_key` that had
        ANY vintage released at or before `as_of`, in that vintage's
        most up-to-date form as of `as_of`.

        Answers: "what is the newest data point the market could have
        known about at all, by this instant, and what did it look like
        by then?" Orders by observation_period first (newest period
        that was knowable at all), then by released_at within that
        period (most recent revision of it that was knowable by
        `as_of`).

        Returns `None` if no vintage of `series_key` has `released_at
        <= as_of`.
        """
        ...

    async def observation_as_known_at(
        self, series_key: str, observation_period: UtcTimestamp, as_of: UtcTimestamp
    ) -> MacroObservationVintage | None:
        """The value known for one specific `observation_period`, as of
        `as_of`.

        Answers: "for THIS period specifically, what was the most
        recently-revised value the market knew, by this instant?"
        Orders by released_at among vintages of that exact
        observation_period.

        Returns `None` if no vintage of that `(series_key,
        observation_period)` pair has `released_at <= as_of` -- this is
        the case exercised by the release-timing test: a period whose
        first vintage has not yet been released as of the query time.
        """
        ...

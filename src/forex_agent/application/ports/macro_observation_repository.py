from enum import Enum
from typing import Protocol

from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.release_timing_rule import ReleaseTimingConfidence
from forex_agent.domain.timestamps import UtcTimestamp


class MacroVintageConflictError(Exception):
    """Raised by `add_vintage` (FX-41H) when a vintage with the same
    natural identity -- `(series_key, observation_period,
    revision_sequence)` -- already exists in storage but its immutable
    payload (`value`, `released_at`, `effective_at`, or `source`)
    differs from the incoming one.

    This is a data-integrity failure, not something to retry or
    silently drop: the natural identity is supposed to uniquely name
    one immutable fact, so two different payloads claiming the same
    identity mean either a caller bug (e.g. a revision reused an
    already-taken `revision_sequence`) or a source that is not
    actually giving out stable, immutable vintages. An exact duplicate
    of an already-stored vintage is NOT an error -- see `add_vintage`'s
    idempotency requirement -- only a genuine content mismatch is.
    """

    def __init__(
        self, existing: MacroObservationVintage, incoming: MacroObservationVintage
    ) -> None:
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            "vintage identity "
            f"(series_key={incoming.series_key!r}, "
            f"observation_period={incoming.observation_period.value.isoformat()!r}, "
            f"revision_sequence={incoming.revision_sequence}) already exists with a "
            f"different payload: existing={existing!r}, incoming={incoming!r}"
        )


class VintageWriteOutcome(Enum):
    """What `add_vintage` actually did (FX-43H).

    Both outcomes are SUCCESSFUL, non-error results -- `add_vintage`
    remains idempotent for an exact retry either way. The distinction
    exists so a caller doing bulk/repeated writes (e.g. a backfill
    that may be re-run) can report an accurate `vintages_inserted` vs
    `vintages_already_present` split instead of only knowing "the call
    didn't raise." `MacroVintageConflictError` remains the separate,
    genuinely-exceptional outcome for a same-identity/different-payload
    write -- this enum only distinguishes between the two NON-error
    cases.
    """

    INSERTED = "INSERTED"
    """A new row was written -- this identity did not exist before."""

    ALREADY_PRESENT = "ALREADY_PRESENT"
    """This exact vintage (identity AND payload) already existed;
    nothing was written."""


class MacroObservationRepository(Protocol):
    """Port for storing and point-in-time-querying `MacroObservationVintage`
    records (FX-41; hardened FX-41H, FX-43H).

    The defining invariant of both read methods: a query at timestamp T
    must never return a vintage whose `released_at` is after T. Neither
    method takes an `effective_at` cutoff -- `effective_at` describes
    when a value takes legal/economic effect, not when it became
    knowable, so it plays no part in what a point-in-time query is
    allowed to see. Ties within a query (same `released_at`, or -- for
    `latest_available_as_of` -- same `observation_period` and
    `released_at`) are broken deterministically by `revision_sequence`
    descending, so which vintage is returned never depends on storage
    or scan order.

    No HTTP/provider logic belongs behind this port -- see
    `docs/ARCHITECTURE.md`. A concrete implementation only ever receives
    already-constructed `MacroObservationVintage` domain objects;
    translating a specific provider's response into one is an
    infrastructure adapter's job, not this port's. Whether a given
    provider/source can be trusted to produce point-in-time-safe
    vintages at all is a `PointInTimeSafety` classification concern
    (`domain.macro_series_definition`), not this port's -- and mapping a
    specific provider's own revision/vintage semantics onto this port's
    natural identity belongs to the provider mapping introduced by the
    future policy-rate registry/ingestion stories, not here.
    """

    async def add_vintage(self, vintage: MacroObservationVintage) -> VintageWriteOutcome:
        """Persist a new vintage. Never mutates or replaces an existing
        one's ECONOMIC VALUE -- a revision is a new vintage with a later
        `released_at` and higher `revision_sequence` for the same
        (series_key, observation_period). See
        `replace_provisional_release_timing` for the one, narrowly
        scoped exception that DOES mutate an existing row -- release-
        timing metadata only, never `value`.

        Idempotent for an exact retry: calling this again with a
        vintage identical in every field to one already stored is a
        no-op, returning `VintageWriteOutcome.ALREADY_PRESENT` rather
        than raising. Returns `VintageWriteOutcome.INSERTED` when a new
        row was actually written. Raises `MacroVintageConflictError`
        (FX-41H) if a vintage with the same `(series_key,
        observation_period, revision_sequence)` identity already exists
        with a *different* `value`, `released_at`, `effective_at`,
        `source`, or `released_at_is_verified` -- the already-stored
        vintage is left completely unchanged in every case.
        """
        ...

    async def replace_provisional_release_timing(
        self,
        series_key: str,
        observation_period: UtcTimestamp,
        revision_sequence: int,
        released_at: UtcTimestamp,
        effective_at: UtcTimestamp | None,
        confidence: ReleaseTimingConfidence,
    ) -> None:
        """Corrects an existing PROVISIONAL vintage's `released_at`/
        `effective_at` in place -- WITHOUT touching its `value` or
        `revision_sequence` (FX-43H).

        `confidence` (FX-44) determines which of the two mutually-
        exclusive-in-practice outcome flags gets set:
          - `ReleaseTimingConfidence.EXACT` sets `released_at_is_
            verified=True`;
          - `ReleaseTimingConfidence.CONSERVATIVE_SAFE_BOUND` sets
            `released_at_is_conservative_bound=True` instead --
            `released_at_is_verified` is NEVER set True for this case.
            FX-44 section 3 is explicit: "do not overload released_at_
            is_verified=True to mean we guessed a safely late time."

        Atomic (FX-43H.1, extended FX-44): an implementation must
        perform this as a single atomic conditional write whose
        predicate includes BOTH `released_at_is_verified = false` AND
        `released_at_is_conservative_bound = false` -- the
        still-fully-provisional check and the write are one operation,
        not a separate read followed by an unconditional write. Two
        concurrent callers racing this method against the same
        identity must never both succeed: at most one write applies,
        and every other caller observes the already-classified failure
        below. `SqlAlchemyMacroObservationRepository` implements this
        via `UPDATE ... WHERE released_at_is_verified = false AND
        released_at_is_conservative_bound = false ... RETURNING id`,
        relying on the database to serialize concurrent attempts
        against the same row.

        This is the explicit, safe replacement path FX-43's effective-
        date-proxy rows (`released_at_is_verified=False`,
        `released_at_is_conservative_bound=False`) are meant to go
        through once genuine release-timing evidence -- exact or
        conservative -- has been established for them (FX-44). It
        exists specifically so that correction does NOT require either
        of two wrong alternatives: (a) representing the correction as a
        new revision -- `revision_sequence` is reserved for genuine
        ECONOMIC VALUE changes, and a timestamp-precision correction is
        not one; or (b) inserting a second vintage at the same
        identity, which the unique constraint already forbids and which
        would in any case leave the old provisional `released_at`
        sitting in storage where a historical as-of query could still
        return it before the correction takes effect.

        Fails closed:
          - raises `ValueError` if no vintage exists at this identity;
          - raises `ValueError` if the existing vintage already has
            EITHER outcome flag set -- only a still-fully-provisional
            row may be replaced this way, precisely so a caller cannot
            use this method to silently rewrite an already-classified
            timestamp (exact OR conservative);
          - callers must not pass a different `value` here -- this
            method has no `value` parameter at all, structurally
            preventing that. A genuine value correction must go through
            `add_vintage` as a new revision instead.

        `VerifyPolicyRateReleaseTiming` (FX-44) is this method's first
        real caller -- see `docs/DECISIONS.md`'s FX-44 entry.
        """
        ...

    async def list_all_for_series(self, series_key: str) -> tuple[MacroObservationVintage, ...]:
        """Every stored vintage for `series_key`, in no particular
        guaranteed order (FX-44).

        Deliberately NOT point-in-time filtered -- unlike `latest_
        available_as_of`/`observation_as_known_at`, this is an
        administrative/batch read for a verification or reporting
        process that needs to examine every vintage's OWN `released_at_
        is_verified`/`released_at_is_conservative_bound` state, not a
        query answering "what did the market know as of instant X."
        `VerifyPolicyRateReleaseTiming` uses this to enumerate the
        change points FX-43 backfilled so it can attempt to resolve
        each one's timing.
        """
        ...

    async def latest_available_as_of(
        self, series_key: str, as_of: UtcTimestamp
    ) -> MacroObservationVintage | None:
        """The most recent observation period for `series_key` that had
        ANY vintage released at or before `as_of`, in that vintage's
        most up-to-date form as of `as_of`.

        Answers: "what is the newest data point the market could have
        known about at all, by this instant, and what did it look like
        by then?" Orders by observation_period descending (newest period
        that was knowable at all), then released_at descending within
        that period (most recent revision of it that was knowable by
        `as_of`), then revision_sequence descending as a deterministic
        tie-breaker (FX-41H) when two vintages of the same period share
        the same released_at.

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
        Orders by released_at descending among vintages of that exact
        observation_period, then revision_sequence descending as a
        deterministic tie-breaker (FX-41H) when two vintages share the
        same released_at.

        Returns `None` if no vintage of that `(series_key,
        observation_period)` pair has `released_at <= as_of` -- this is
        the case exercised by the release-timing test: a period whose
        first vintage has not yet been released as of the query time.
        """
        ...

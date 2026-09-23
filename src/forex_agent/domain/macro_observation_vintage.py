from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain._guards import require_decimal
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class MacroObservationVintage:
    """One point-in-time-safe fact: "series X, for reference period Y,
    was known to have value V, from timestamp T onward" (FX-41).

    This is the single unit both a first release and every later
    revision are represented as -- there is deliberately no separate
    "MacroObservation" wrapper type. The story's own "MacroObservation /
    MacroObservationVintage" naming suggested near-synonymy, and a
    first release is not conceptually different from a revision: it is
    simply the vintage with `revision_sequence == 0`. Modelling them as
    two classes would invent a distinction with no distinct behaviour,
    which is exactly the "giant generic economic-data warehouse" shape
    this story is told not to build. See `docs/DECISIONS.md`.

    Three timestamps, kept explicitly distinct (never collapsed into
    one), because they answer three different questions:

        observation_period: WHICH period this value describes (e.g.
            "February 2024"). This is a calendar fact, not a knowledge
            fact -- it says nothing about when anyone could see it.
        released_at: the FIRST instant this exact vintage became
            publicly knowable (a publication/release timestamp). This
            is what point-in-time queries filter against -- see
            `docs/ARCHITECTURE.md`.
        effective_at: optional. Set only when a value is publicly
            knowable at `released_at` but does not take legal/economic
            effect until materially later (e.g. a central bank
            announces a rate change effective at a future date). Most
            series never need this and leave it `None`.

    A revision to the same `observation_period` is a NEW
    `MacroObservationVintage` with a later `released_at` and a higher
    `revision_sequence` -- never a mutation of the earlier one. Nothing
    in this domain type supports overwriting a previously-constructed
    vintage; immutability is enforced by `frozen=True` here, and by the
    repository/persistence layer never issuing an UPDATE against a
    historical vintage row FOR THE ECONOMIC VALUE -- `released_at_is_
    verified` (FX-43H) is a narrow, deliberate exception to that, and
    only to that: see its own field doc below and `MacroObservation
    Repository.replace_provisional_release_timing`.

    Fields:
        series_key: the `MacroSeriesDefinition.key` this vintage belongs
            to. Kept as a bare string (not the full definition object)
            so a vintage can be constructed/persisted without pulling
            in series metadata that doesn't change per-observation.
        observation_period: which reference period this value describes.
        value: the observed value, Decimal-only per CLAUDE.md.
        released_at: when this exact vintage became publicly knowable.
        revision_sequence: 0 for the first published vintage of this
            observation_period, incrementing for each subsequent
            revision. Not required to be contiguous or provider-
            comparable -- only used to order vintages of the same
            period relative to each other. Reserved EXCLUSIVELY for
            genuine changes to the ECONOMIC VALUE -- a later
            correction to `released_at`'s own precision (see
            `released_at_is_verified`) is a different kind of fact and
            must never be represented as a revision (FX-43H).
        source: free-form provenance label (e.g. "FRED", "ECB_SDW",
            "manual_backfill"). No provider-specific object -- a plain
            string, kept for audit/debugging, never branched on by
            domain logic.
        effective_at: optional; see above. `None` for the (large)
            majority of series where release and effect coincide.
        released_at_is_verified: whether `released_at` (and
            `effective_at`, where set) is a confirmed announcement/
            effective timestamp, as opposed to a same-day proxy
            derived from something else (e.g. FX-43's policy-rate
            backfill, which sets `released_at` to the date a
            provider's raw series shows a value CHANGE -- an
            effective-date proxy, not a verified announcement
            timestamp). Defaults to `False` (FX-43H.1: fail closed --
            a caller that has not actually confirmed its release
            timing must not have that go unnoticed by defaulting to
            "verified"). A caller that genuinely possesses a confirmed
            announcement/effective timestamp must pass
            `released_at_is_verified=True` explicitly; nothing about
            constructing a vintage may silently claim verification it
            was never given. This field exists so a future correction
            to release timing can be represented and applied safely
            (FX-43H) without conflating "we learned the economic value
            was different" (a `revision_sequence` bump) with "we
            learned exactly when this became knowable" (a
            `released_at_is_verified` correction) -- see
            `MacroObservationRepository.
            replace_provisional_release_timing`.
        released_at_is_conservative_bound: whether `released_at` is a
            DELIBERATELY conservative bound -- not the exact confirmed
            announcement moment, but a timestamp researched and chosen
            to be guaranteed no earlier than the true (unknown-exact)
            release (FX-44 section 3). Defaults to `False`. STRUCTURALLY
            mutually exclusive with `released_at_is_verified` (FX-44H):
            `__post_init__` rejects both `True` at once, a timestamp is
            either exactly confirmed or a safe stand-in for an
            unconfirmed one, never claimed as both -- mirrored by a
            Postgres CHECK constraint at the persistence layer, and by
            the fail-closed atomic-UPDATE predicate in `replace_
            provisional_release_timing`/`correct_verified_release_
            timing`, which never write both flags `True` either.
            Exists specifically so a genuinely conservative,
            research-safe timestamp is never confused with an exact
            one: `released_at_is_verified=True` must never be used to
            mean "we guessed a safely late time" -- see `domain.
            research_readiness.is_research_safe`, which treats EITHER
            flag as sufficient for point-in-time research use, while
            keeping the two provenance claims distinct in storage and
            in every report.
    """

    series_key: str
    observation_period: UtcTimestamp
    value: Decimal
    released_at: UtcTimestamp
    revision_sequence: int
    source: str
    effective_at: UtcTimestamp | None = None
    released_at_is_verified: bool = False
    released_at_is_conservative_bound: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.series_key, str) or not self.series_key.strip():
            raise ValueError(f"series_key must be a non-empty string, got {self.series_key!r}")
        if not isinstance(self.observation_period, UtcTimestamp):
            raise TypeError(
                "observation_period must be a UtcTimestamp, "
                f"got {type(self.observation_period).__name__}"
            )
        if not isinstance(self.released_at, UtcTimestamp):
            raise TypeError(
                f"released_at must be a UtcTimestamp, got {type(self.released_at).__name__}"
            )
        if self.effective_at is not None and not isinstance(self.effective_at, UtcTimestamp):
            raise TypeError(
                "effective_at must be a UtcTimestamp or None, "
                f"got {type(self.effective_at).__name__}"
            )
        require_decimal("value", self.value)
        if not isinstance(self.revision_sequence, int) or isinstance(self.revision_sequence, bool):
            raise TypeError(
                f"revision_sequence must be an int, got {type(self.revision_sequence).__name__}"
            )
        if self.revision_sequence < 0:
            raise ValueError(
                f"revision_sequence must not be negative, got {self.revision_sequence}"
            )
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError(f"source must be a non-empty string, got {self.source!r}")
        if not isinstance(self.released_at_is_verified, bool):
            raise TypeError(
                "released_at_is_verified must be a bool, "
                f"got {type(self.released_at_is_verified).__name__}"
            )
        if not isinstance(self.released_at_is_conservative_bound, bool):
            raise TypeError(
                "released_at_is_conservative_bound must be a bool, "
                f"got {type(self.released_at_is_conservative_bound).__name__}"
            )
        if self.released_at_is_verified and self.released_at_is_conservative_bound:
            # FX-44H: structurally impossible to construct a vintage claiming
            # BOTH an exact confirmed timestamp AND a deliberately inexact
            # conservative bound at once -- these are mutually exclusive
            # provenance claims about the SAME released_at value. Mirrored by
            # a Postgres CHECK constraint (infrastructure.db.models.
            # macro_observation_vintage) so this holds in storage too, not
            # just at construction time.
            raise ValueError(
                "released_at_is_verified and released_at_is_conservative_bound must "
                "not both be True -- a timestamp cannot be simultaneously exactly "
                "confirmed and a deliberately inexact conservative bound"
            )

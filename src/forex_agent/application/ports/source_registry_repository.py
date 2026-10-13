"""FX-62: port for FTA's own durable source identity and attribution
registry -- ONE combined port covering both concerns (identity,
Section 4.1/4.2, and attribution, Section 4.3/4.4), mirroring FX-58's
own `NewsCanonicalizationRepository` precedent of one port spanning
multiple closely-related concerns over the same evidence family,
rather than FX-59's own fully-separate-port precedent (justified
there only because semantic annotation is a genuinely independent
evidence family; identity and attribution are not -- attribution
resolution directly depends on identity resolution).

Every `*_as_of` method shares the SAME defining invariant every other
PIT-safe port in this codebase already establishes: a query must
never return/consider a vintage whose `availability` is after the
requested instant (FX-62 Section 8)."""

from dataclasses import dataclass
from typing import Protocol

from forex_agent.domain.intelligence_source import IntelligenceSource
from forex_agent.domain.source_attribution_role import SourceAttributionRole
from forex_agent.domain.source_attribution_vintage import SourceAttributionVintage
from forex_agent.domain.source_identity_vintage import SourceIdentityVintage
from forex_agent.domain.timestamps import UtcTimestamp


class IntelligenceSourceConflictError(Exception):
    """Raised when registering a durable `IntelligenceSource` whose
    `source_key` already exists with a DIFFERENT `source_kind` --
    Section 4.1's own "a durable source key must not be reassigned to
    a different actor" invariant, enforced here rather than merely by
    convention. An exact duplicate registration (same `source_key`,
    same `source_kind`) is NOT an error -- idempotent."""

    def __init__(self, existing: IntelligenceSource, incoming: IntelligenceSource) -> None:
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            f"source_key={incoming.source_key!r} already exists with source_kind="
            f"{existing.source_kind.value!r}, cannot re-register as "
            f"{incoming.source_kind.value!r} -- a durable source key must never be "
            "reassigned to a different actor"
        )


class SourceIdentityVintageConflictError(Exception):
    """Raised by `add_identity_vintage` when a vintage with the same
    natural identity -- `(source_key, revision_sequence)` -- already
    exists in storage but its payload differs from the incoming one
    (mirrors `NewsSemanticAnnotationConflictError`). An exact duplicate
    is NOT an error (idempotent); only a genuine content mismatch is."""

    def __init__(self, existing: SourceIdentityVintage, incoming: SourceIdentityVintage) -> None:
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            "source identity vintage identity "
            f"(source_key={incoming.source_key!r}, revision_sequence="
            f"{incoming.revision_sequence}) already exists with a different payload: "
            f"existing={existing!r}, incoming={incoming!r}"
        )


class SourceAttributionVintageConflictError(Exception):
    """Raised by `add_attribution_vintage` when a vintage with the same
    natural identity -- `(news_item_key, role, revision_sequence)` --
    already exists in storage but its payload differs from the
    incoming one. An exact duplicate is NOT an error (idempotent);
    only a genuine content mismatch is."""

    def __init__(
        self, existing: SourceAttributionVintage, incoming: SourceAttributionVintage
    ) -> None:
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            "source attribution vintage identity "
            f"(news_item_key={incoming.news_item_key!r}, role={incoming.role.value!r}, "
            f"revision_sequence={incoming.revision_sequence}) already exists with a different "
            f"payload: existing={existing!r}, incoming={incoming!r}"
        )


@dataclass(frozen=True, slots=True)
class SourceRegistrationResult:
    """`register_source_with_first_identity_vintage`'s own result --
    `created=True` for a genuinely new durable identity, `False` for
    an idempotent retry of an exact duplicate registration."""

    created: bool


@dataclass(frozen=True, slots=True)
class IdentityVintageWriteResult:
    """`add_identity_vintage`'s own result -- `inserted=True` for a
    genuinely new row, `False` for an idempotent retry of an exact
    duplicate (mirrors `SemanticAnnotationWriteResult`)."""

    inserted: bool


@dataclass(frozen=True, slots=True)
class AttributionVintageWriteResult:
    """`add_attribution_vintage`'s own result -- see `IdentityVintage
    WriteResult`."""

    inserted: bool


class SourceRegistryRepository(Protocol):
    """Port for FX-62's own durable source identity and attribution
    registry -- see the module docstring."""

    # --- Identity -------------------------------------------------------

    async def get_source(self, source_key: str) -> IntelligenceSource | None:
        """The durable `IntelligenceSource` at `source_key`, regardless
        of any `as_of` bound (the identity record itself is immutable
        once registered -- Section 4.1) -- `None` if never registered."""
        ...

    async def list_sources(self) -> tuple[IntelligenceSource, ...]:
        """Every durable `IntelligenceSource` ever registered, in no
        particular guaranteed order -- an administrative/audit/
        bootstrap-idempotency read."""
        ...

    async def register_source_with_first_identity_vintage(
        self, source: IntelligenceSource, first_identity_vintage: SourceIdentityVintage
    ) -> SourceRegistrationResult:
        """Atomically registers a NEW durable identity together with
        its own FIRST identity vintage, in ONE transaction -- mirrors
        `NewsRepository.register_source_item_with_first_vintage`'s own
        FX-56H-established pattern exactly, avoiding the same orphan-
        row race that pattern was introduced to close. `source.source_
        key` must not already exist with a DIFFERENT `source_kind`
        (raises `IntelligenceSourceConflictError`); an exact duplicate
        registration (same `source`, same `first_identity_vintage`) is
        idempotent (`created=False`)."""
        ...

    async def latest_identity_vintage_for_source(
        self, source_key: str
    ) -> SourceIdentityVintage | None:
        """The single latest-availability (tie-broken by highest
        `revision_sequence`) identity vintage ever recorded for this
        source, regardless of any `as_of` bound -- `None` if the
        source has no identity vintage at all. Used by `RecordSource
        IdentityVintage` to enforce PIT ordering and determinism."""
        ...

    async def latest_identity_vintage_as_of(
        self, source_key: str, as_of: UtcTimestamp
    ) -> SourceIdentityVintage | None:
        """The latest identity vintage for this source with
        `availability <= as_of` -- `None` if none qualifies, even if
        `latest_identity_vintage_for_source` would return something
        newer. Used by `ResolveSourceIdentityAsOf`."""
        ...

    async def list_identity_vintages_for_source(
        self, source_key: str
    ) -> tuple[SourceIdentityVintage, ...]:
        """Every stored identity vintage for this source, in no
        particular guaranteed order -- an administrative/audit read,
        and the full-history basis for `RecordSourceIdentityVintage`'s
        own determinism check."""
        ...

    async def add_identity_vintage(
        self, vintage: SourceIdentityVintage
    ) -> IdentityVintageWriteResult:
        """Persist a new identity vintage for an ALREADY-registered
        source. Never mutates or replaces an existing one -- idempotent
        for an exact retry (`inserted=False`); raises `SourceIdentity
        VintageConflictError` for a same-identity, different-payload
        write. `vintage.source_key` must already exist as an
        `IntelligenceSource` -- enforced by a real foreign key in the
        SQL implementation."""
        ...

    # --- Attribution ------------------------------------------------------

    async def latest_attribution_for_role(
        self, news_item_key: str, role: SourceAttributionRole
    ) -> SourceAttributionVintage | None:
        """The single latest-availability (tie-broken by highest
        `revision_sequence`) attribution vintage ever recorded for this
        `(news_item_key, role)` pair, regardless of any `as_of` bound
        -- `None` if none has ever been recorded. Used by `RecordSource
        Attribution` to enforce PIT ordering and determinism."""
        ...

    async def latest_attribution_as_of(
        self, news_item_key: str, role: SourceAttributionRole, as_of: UtcTimestamp
    ) -> SourceAttributionVintage | None:
        """The latest attribution vintage for this `(news_item_key,
        role)` pair with `availability <= as_of` -- `None` if none
        qualifies."""
        ...

    async def list_attribution_vintages(
        self, news_item_key: str, role: SourceAttributionRole
    ) -> tuple[SourceAttributionVintage, ...]:
        """Every stored attribution vintage for this `(news_item_key,
        role)` pair, in no particular guaranteed order -- an
        administrative/audit read, and the full-history basis for
        `RecordSourceAttribution`'s own determinism check."""
        ...

    async def list_latest_attributions_for_item_as_of(
        self, news_item_key: str, as_of: UtcTimestamp
    ) -> tuple[SourceAttributionVintage, ...]:
        """For EVERY `SourceAttributionRole` that has at least one
        attribution vintage with `availability <= as_of` for this
        item, its own latest-as-of vintage -- at most one entry per
        role, deterministically ordered by `role.value` (Section 7's
        own "deterministically ordered applicable attribution
        records"). Used by `ResolveSourceAttributionsAsOf`."""
        ...

    async def add_attribution_vintage(
        self, vintage: SourceAttributionVintage
    ) -> AttributionVintageWriteResult:
        """Persist a new attribution vintage. Never mutates or
        replaces an existing one -- idempotent for an exact retry
        (`inserted=False`); raises `SourceAttributionVintageConflict
        Error` for a same-identity, different-payload write. `vintage.
        news_item_key` must already exist as a `NewsItem`, and
        `(vintage.news_item_key, vintage.evidence_basis_revision_
        sequence)` must already exist as a `NewsItemVintage`; if
        `vintage.attributed_source_key` is not `None`, it must already
        exist as an `IntelligenceSource` -- all enforced by real
        foreign keys in the SQL implementation."""
        ...

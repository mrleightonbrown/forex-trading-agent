"""FX-62: an in-memory fake implementing `SourceRegistryRepository`,
mirroring the real `SqlAlchemySourceRegistryRepository`'s own exact
selection/idempotency semantics (latest-by-(availability, revision_
sequence), `ON CONFLICT DO NOTHING`-style idempotent writes, conflict
detection on a genuine payload mismatch) -- so application-layer tests
exercise the SAME decision rules the real repository enforces, never a
second, independently-maintained approximation."""

from forex_agent.application.ports.source_registry_repository import (
    AttributionVintageWriteResult,
    IdentityVintageWriteResult,
    IntelligenceSourceConflictError,
    SourceAttributionVintageConflictError,
    SourceIdentityVintageConflictError,
    SourceRegistrationResult,
)
from forex_agent.domain.intelligence_source import IntelligenceSource
from forex_agent.domain.source_attribution_role import SourceAttributionRole
from forex_agent.domain.source_attribution_vintage import SourceAttributionVintage
from forex_agent.domain.source_identity_vintage import SourceIdentityVintage
from forex_agent.domain.timestamps import UtcTimestamp


class FakeSourceRegistryRepository:
    def __init__(self) -> None:
        self.sources: dict[str, IntelligenceSource] = {}
        self.identity_vintages: dict[str, list[SourceIdentityVintage]] = {}
        self.attribution_vintages: dict[
            tuple[str, SourceAttributionRole], list[SourceAttributionVintage]
        ] = {}

    # --- Identity -------------------------------------------------------

    async def get_source(self, source_key: str) -> IntelligenceSource | None:
        return self.sources.get(source_key)

    async def list_sources(self) -> tuple[IntelligenceSource, ...]:
        return tuple(self.sources.values())

    async def register_source_with_first_identity_vintage(
        self, source: IntelligenceSource, first_identity_vintage: SourceIdentityVintage
    ) -> SourceRegistrationResult:
        existing_source = self.sources.get(source.source_key)
        if existing_source is None:
            self.sources[source.source_key] = source
            self.identity_vintages[source.source_key] = [first_identity_vintage]
            return SourceRegistrationResult(created=True)

        if existing_source.source_kind != source.source_kind:
            raise IntelligenceSourceConflictError(existing_source, source)

        existing_vintages = self.identity_vintages.get(source.source_key, [])
        existing_vintage = next(
            (
                v
                for v in existing_vintages
                if v.revision_sequence == first_identity_vintage.revision_sequence
            ),
            None,
        )
        if existing_vintage is None:
            raise RuntimeError(
                f"source_key={source.source_key!r} already registered but has no "
                f"revision_sequence={first_identity_vintage.revision_sequence} vintage"
            )
        if existing_vintage == first_identity_vintage:
            return SourceRegistrationResult(created=False)
        raise SourceIdentityVintageConflictError(existing_vintage, first_identity_vintage)

    async def latest_identity_vintage_for_source(
        self, source_key: str
    ) -> SourceIdentityVintage | None:
        candidates = self.identity_vintages.get(source_key, [])
        if not candidates:
            return None
        return max(candidates, key=lambda v: (v.availability.value, v.revision_sequence))

    async def latest_identity_vintage_as_of(
        self, source_key: str, as_of: UtcTimestamp
    ) -> SourceIdentityVintage | None:
        candidates = [
            v
            for v in self.identity_vintages.get(source_key, [])
            if v.availability.value <= as_of.value
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda v: (v.availability.value, v.revision_sequence))

    async def list_identity_vintages_for_source(
        self, source_key: str
    ) -> tuple[SourceIdentityVintage, ...]:
        return tuple(self.identity_vintages.get(source_key, []))

    async def add_identity_vintage(
        self, vintage: SourceIdentityVintage
    ) -> IdentityVintageWriteResult:
        existing_vintages = self.identity_vintages.setdefault(vintage.source_key, [])
        existing = next(
            (v for v in existing_vintages if v.revision_sequence == vintage.revision_sequence),
            None,
        )
        if existing is None:
            existing_vintages.append(vintage)
            return IdentityVintageWriteResult(inserted=True)
        if existing == vintage:
            return IdentityVintageWriteResult(inserted=False)
        raise SourceIdentityVintageConflictError(existing, vintage)

    # --- Attribution ------------------------------------------------------

    async def latest_attribution_for_role(
        self, news_item_key: str, role: SourceAttributionRole
    ) -> SourceAttributionVintage | None:
        candidates = self.attribution_vintages.get((news_item_key, role), [])
        if not candidates:
            return None
        return max(candidates, key=lambda v: (v.availability.value, v.revision_sequence))

    async def latest_attribution_as_of(
        self, news_item_key: str, role: SourceAttributionRole, as_of: UtcTimestamp
    ) -> SourceAttributionVintage | None:
        candidates = [
            v
            for v in self.attribution_vintages.get((news_item_key, role), [])
            if v.availability.value <= as_of.value
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda v: (v.availability.value, v.revision_sequence))

    async def list_attribution_vintages(
        self, news_item_key: str, role: SourceAttributionRole
    ) -> tuple[SourceAttributionVintage, ...]:
        return tuple(self.attribution_vintages.get((news_item_key, role), []))

    async def list_latest_attributions_for_item_as_of(
        self, news_item_key: str, as_of: UtcTimestamp
    ) -> tuple[SourceAttributionVintage, ...]:
        latest_by_role: dict[SourceAttributionRole, SourceAttributionVintage] = {}
        for (item_key, role), vintages in self.attribution_vintages.items():
            if item_key != news_item_key:
                continue
            candidates = [v for v in vintages if v.availability.value <= as_of.value]
            if not candidates:
                continue
            latest_by_role[role] = max(
                candidates, key=lambda v: (v.availability.value, v.revision_sequence)
            )
        return tuple(latest_by_role.values())

    async def add_attribution_vintage(
        self, vintage: SourceAttributionVintage
    ) -> AttributionVintageWriteResult:
        key = (vintage.news_item_key, vintage.role)
        existing_vintages = self.attribution_vintages.setdefault(key, [])
        existing = next(
            (v for v in existing_vintages if v.revision_sequence == vintage.revision_sequence),
            None,
        )
        if existing is None:
            existing_vintages.append(vintage)
            return AttributionVintageWriteResult(inserted=True)
        if existing == vintage:
            return AttributionVintageWriteResult(inserted=False)
        raise SourceAttributionVintageConflictError(existing, vintage)

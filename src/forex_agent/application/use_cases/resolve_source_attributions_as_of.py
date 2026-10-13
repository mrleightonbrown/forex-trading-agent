"""FX-62 Section 7: `ResolveSourceAttributionsAsOf` -- a thin, PIT-safe
read use case returning every role's own latest-as-of attribution for
one NewsItem, deterministically ordered by `role.value` (never row
insertion order). Confirmed and unresolved roles are both returned
-- never silently dropping an unresolved role, mirroring FX-60's own
"a semantic gap is surfaced, never hidden" discipline."""

from dataclasses import dataclass

from forex_agent.application.ports.source_registry_repository import SourceRegistryRepository
from forex_agent.domain.source_attribution_status import SourceAttributionStatus
from forex_agent.domain.source_attribution_vintage import SourceAttributionVintage
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class SourceAttributionsResolutionResult:
    news_item_key: str
    as_of: UtcTimestamp
    attributions: tuple[SourceAttributionVintage, ...]
    """Every role's own latest-as-of attribution vintage, sorted by
    `role.value` -- at most one entry per `SourceAttributionRole`. A
    role with NO attribution vintage at all as of `as_of` is simply
    absent from this tuple (distinct from an explicit `UNRESOLVED`
    vintage, which IS present)."""

    @property
    def confirmed(self) -> tuple[SourceAttributionVintage, ...]:
        return tuple(a for a in self.attributions if a.status is SourceAttributionStatus.CONFIRMED)

    @property
    def unresolved(self) -> tuple[SourceAttributionVintage, ...]:
        return tuple(a for a in self.attributions if a.status is SourceAttributionStatus.UNRESOLVED)


class ResolveSourceAttributionsAsOf:
    """FX-62's own PIT-safe source-attribution resolver -- see the
    module docstring."""

    def __init__(self, repository: SourceRegistryRepository) -> None:
        self._repository = repository

    async def __call__(
        self, news_item_key: str, as_of: UtcTimestamp
    ) -> SourceAttributionsResolutionResult:
        attributions = await self._repository.list_latest_attributions_for_item_as_of(
            news_item_key, as_of
        )
        ordered = tuple(sorted(attributions, key=lambda a: a.role.value))
        return SourceAttributionsResolutionResult(news_item_key, as_of, ordered)

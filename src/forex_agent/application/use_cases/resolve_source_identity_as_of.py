"""FX-62 Section 7: `ResolveSourceIdentityAsOf` -- a thin, PIT-safe
read use case over `SourceRegistryRepository`, exactly as FX-59's own
`GetNewsSemanticStateAsOf` is a thin read over `NewsSemanticRepository`.
Never calls `UtcTimestamp.now()`; the caller's own explicit `as_of`
is the sole knowledge cut."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.source_registry_repository import SourceRegistryRepository
from forex_agent.domain.source_identity_vintage import SourceIdentityVintage
from forex_agent.domain.timestamps import UtcTimestamp


class SourceIdentityResolution(Enum):
    """Whether an identity vintage was knowable as of the requested
    instant -- Section 6's own "an identity discovered today must not
    automatically appear in historical snapshots from last month"
    requirement, made explicit as a result type rather than merely
    relying on a caller to check for `None`."""

    KNOWN = "KNOWN"
    NOT_KNOWN = "NOT_KNOWN"


@dataclass(frozen=True, slots=True)
class SourceIdentityResolutionResult:
    source_key: str
    as_of: UtcTimestamp
    resolution: SourceIdentityResolution
    identity_vintage: SourceIdentityVintage | None
    """`None` iff `resolution is NOT_KNOWN`; otherwise the latest
    identity vintage with `availability <= as_of`."""


class ResolveSourceIdentityAsOf:
    """FX-62's own PIT-safe source-identity resolver -- see the module
    docstring."""

    def __init__(self, repository: SourceRegistryRepository) -> None:
        self._repository = repository

    async def __call__(
        self, source_key: str, as_of: UtcTimestamp
    ) -> SourceIdentityResolutionResult:
        vintage = await self._repository.latest_identity_vintage_as_of(source_key, as_of)
        if vintage is None:
            return SourceIdentityResolutionResult(
                source_key, as_of, SourceIdentityResolution.NOT_KNOWN, None
            )
        return SourceIdentityResolutionResult(
            source_key, as_of, SourceIdentityResolution.KNOWN, vintage
        )

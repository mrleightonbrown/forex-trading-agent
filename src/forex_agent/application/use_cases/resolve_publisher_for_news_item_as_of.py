"""FX-62 Section 7: `ResolvePublisherForNewsItemAsOf` -- a focused
PUBLISHER-role resolver. **This resolver must NEVER silently
substitute the technical ingestion feed for an unknown publishing
actor (Section 7's own explicit prohibition)** -- `UNRESOLVED`/`NOT_
RECORDED` always return `publisher=None`, never a fallback identity."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.source_registry_repository import SourceRegistryRepository
from forex_agent.domain.intelligence_source import IntelligenceSource
from forex_agent.domain.source_attribution_role import SourceAttributionRole
from forex_agent.domain.source_attribution_status import SourceAttributionStatus
from forex_agent.domain.source_attribution_vintage import SourceAttributionVintage
from forex_agent.domain.source_identity_vintage import SourceIdentityVintage
from forex_agent.domain.timestamps import UtcTimestamp


class PublisherResolutionStatus(Enum):
    """FX-62 Section 7's own three-way result: a confirmed publisher,
    an ambiguous/unresolved status, or a not-known result --
    distinguished here as four explicit states so a caller never has
    to re-derive "not-known" from an absent attribution versus an
    explicit `UNRESOLVED` one."""

    #: A single CONFIRMED `PUBLISHER` attribution exists as of `as_of`.
    CONFIRMED = "CONFIRMED"

    #: An explicit `UNRESOLVED` `PUBLISHER` attribution vintage exists
    #: as of `as_of` -- FTA has looked and could not establish one.
    UNRESOLVED = "UNRESOLVED"

    #: No `PUBLISHER` attribution vintage of ANY kind has been
    #: recorded for this item as of `as_of` -- distinct from an
    #: explicit `UNRESOLVED` record (FTA has not yet evaluated this
    #: item's own publisher at all).
    NOT_RECORDED = "NOT_RECORDED"

    #: Defense-in-depth only (Section 9's own explicit requirement):
    #: structurally unreachable under this registry's own `(news_
    #: item_key, role, revision_sequence)` uniqueness constraint,
    #: which guarantees exactly one well-defined latest-as-of row per
    #: `(news_item_key, role)` pair -- retained as an explicit,
    #: never-silently-resolved-by-row-order state rather than assumed
    #: impossible.
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class PublisherResolutionResult:
    news_item_key: str
    as_of: UtcTimestamp
    status: PublisherResolutionStatus
    publisher: IntelligenceSource | None
    """The resolved publisher's own durable identity -- non-`None`
    iff `status is CONFIRMED`. NEVER the technical ingestion feed
    substituted as a fallback."""

    publisher_identity_vintage: SourceIdentityVintage | None
    """The resolved publisher's own latest-as-of identity vintage
    (display name, aliases, ...) -- non-`None` iff `status is
    CONFIRMED` and the publisher itself has a known identity vintage
    as of `as_of`."""

    attribution_vintage: SourceAttributionVintage | None
    """The supporting `SourceAttributionVintage` itself -- non-`None`
    iff `status in (CONFIRMED, UNRESOLVED)`; `None` iff `status is
    NOT_RECORDED`."""


class ResolvePublisherForNewsItemAsOf:
    """FX-62's own focused PUBLISHER-role resolver -- see the module
    docstring."""

    def __init__(self, repository: SourceRegistryRepository) -> None:
        self._repository = repository

    async def __call__(self, news_item_key: str, as_of: UtcTimestamp) -> PublisherResolutionResult:
        attribution = await self._repository.latest_attribution_as_of(
            news_item_key, SourceAttributionRole.PUBLISHER, as_of
        )
        if attribution is None:
            return PublisherResolutionResult(
                news_item_key, as_of, PublisherResolutionStatus.NOT_RECORDED, None, None, None
            )

        if attribution.status is SourceAttributionStatus.UNRESOLVED:
            return PublisherResolutionResult(
                news_item_key,
                as_of,
                PublisherResolutionStatus.UNRESOLVED,
                None,
                None,
                attribution,
            )

        assert attribution.attributed_source_key is not None  # CONFIRMED invariant
        publisher = await self._repository.get_source(attribution.attributed_source_key)
        publisher_identity_vintage = await self._repository.latest_identity_vintage_as_of(
            attribution.attributed_source_key, as_of
        )
        return PublisherResolutionResult(
            news_item_key,
            as_of,
            PublisherResolutionStatus.CONFIRMED,
            publisher,
            publisher_identity_vintage,
            attribution,
        )

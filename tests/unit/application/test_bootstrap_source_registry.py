"""FX-62 Section 12.D: tests for `BootstrapSourceRegistry` -- first
bootstrap produces appropriate identities, second bootstrap is
idempotent, no duplicate identities/attributions, and unsupported
source keys are preserved as unresolved (simply absent) rather than
guessed."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.use_cases.bootstrap_source_registry import BootstrapSourceRegistry
from forex_agent.application.use_cases.record_source_attribution import RecordSourceAttribution
from forex_agent.application.use_cases.record_source_identity_vintage import (
    RecordSourceIdentityVintage,
)
from forex_agent.application.use_cases.resolve_publisher_for_news_item_as_of import (
    PublisherResolutionStatus,
    ResolvePublisherForNewsItemAsOf,
)
from forex_agent.domain.news_semantic_classifying import NewsSemanticClassificationCandidate
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.source_registry_repository import FakeSourceRegistryRepository


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


def _candidate(
    news_item_key: str, source_key: str, revision: int = 0
) -> NewsSemanticClassificationCandidate:
    return NewsSemanticClassificationCandidate(
        news_item_key=news_item_key,
        source_key=source_key,
        basis_news_item_revision_sequence=revision,
        basis_availability=_ts(8),
        headline="Headline",
        summary=None,
        body_text=None,
        source_content_type=None,
        source_channel="test_channel",
    )


class FakeCandidateLookup:
    def __init__(self, candidates: tuple[NewsSemanticClassificationCandidate, ...]) -> None:
        self._candidates = candidates

    async def list_candidates_as_of(
        self, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> tuple[NewsSemanticClassificationCandidate, ...]:
        return self._candidates


def _make_bootstrap(
    repo: FakeSourceRegistryRepository, candidates: tuple[NewsSemanticClassificationCandidate, ...]
) -> BootstrapSourceRegistry:
    return BootstrapSourceRegistry(
        RecordSourceIdentityVintage(repo),
        RecordSourceAttribution(repo),
        FakeCandidateLookup(candidates),
    )


@pytest.mark.asyncio
async def test_first_bootstrap_creates_six_feeds_six_organizations() -> None:
    repo = FakeSourceRegistryRepository()
    bootstrap = _make_bootstrap(repo, ())

    result = await bootstrap(_ts(9))

    assert result.feed_identities_created == 6
    assert result.organization_identities_created == 6
    assert len(await repo.list_sources()) == 12


@pytest.mark.asyncio
async def test_second_bootstrap_is_fully_idempotent() -> None:
    repo = FakeSourceRegistryRepository()
    candidates = (_candidate("ITEM-FED-1", "FED"), _candidate("ITEM-BOE-1", "BOE"))
    bootstrap = _make_bootstrap(repo, candidates)
    first = await bootstrap(_ts(9))

    second = await bootstrap(_ts(9))

    assert first.feed_identities_created == 6
    assert second.feed_identities_created == 0
    assert first.total_attributions_created == 2
    assert second.total_attributions_created == 0
    assert second.total_attributions_unchanged == 2
    assert len(await repo.list_sources()) == 12  # no duplicates
    assert len(repo.attribution_vintages) == 2  # one (item, role) pair per item, no duplicates


@pytest.mark.asyncio
async def test_no_duplicate_identities_or_attributions_after_repeated_runs() -> None:
    repo = FakeSourceRegistryRepository()
    candidates = (_candidate("ITEM-FED-1", "FED"),)
    bootstrap = _make_bootstrap(repo, candidates)

    for _ in range(3):
        await bootstrap(_ts(9))

    assert len(await repo.list_sources()) == 12
    fed_vintages = await repo.list_identity_vintages_for_source("FED")
    assert len(fed_vintages) == 1
    item_attributions = repo.attribution_vintages
    assert sum(len(v) for v in item_attributions.values()) == 1


@pytest.mark.asyncio
async def test_unmapped_source_key_is_preserved_as_unresolved_never_guessed() -> None:
    """FX-62 Section 6's own explicit requirement: preserve unsupported
    mappings as unresolved rather than guessing -- an item from an
    UNMAPPED source_key is simply never attributed by bootstrap."""
    repo = FakeSourceRegistryRepository()
    candidates = (_candidate("ITEM-UNKNOWN-1", "SOME_UNMAPPED_SOURCE"),)
    bootstrap = _make_bootstrap(repo, candidates)

    result = await bootstrap(_ts(9))

    assert result.total_attributions_created == 0
    assert result.total_items_considered == 0  # not counted under any known mapping
    resolve_publisher = ResolvePublisherForNewsItemAsOf(repo)
    resolution = await resolve_publisher("ITEM-UNKNOWN-1", _ts(10))
    assert resolution.status is PublisherResolutionStatus.NOT_RECORDED


@pytest.mark.asyncio
async def test_bootstrapped_publisher_resolves_correctly_through_the_full_chain() -> None:
    repo = FakeSourceRegistryRepository()
    candidates = (_candidate("ITEM-FED-1", "FED"),)
    bootstrap = _make_bootstrap(repo, candidates)
    await bootstrap(_ts(9))

    resolve_publisher = ResolvePublisherForNewsItemAsOf(repo)
    resolution = await resolve_publisher("ITEM-FED-1", _ts(10))

    assert resolution.status is PublisherResolutionStatus.CONFIRMED
    assert resolution.publisher is not None
    assert resolution.publisher.source_key == "FEDERAL_RESERVE"


@pytest.mark.asyncio
async def test_dry_run_writes_nothing() -> None:
    repo = FakeSourceRegistryRepository()
    candidates = (_candidate("ITEM-FED-1", "FED"),)
    bootstrap = _make_bootstrap(repo, candidates)

    result = await bootstrap(_ts(9), dry_run=True)

    assert result.feed_identities_created == 6
    assert result.total_attributions_created == 1
    assert await repo.list_sources() == ()
    assert repo.attribution_vintages == {}


@pytest.mark.asyncio
async def test_does_not_backdate_registered_at_to_item_first_seen() -> None:
    """Section 6: do not backdate identity knowledge to the original
    article publication/ingestion date -- `registered_at` must be the
    bootstrap's own explicit `bootstrap_at`, never a candidate's own
    `basis_availability`."""
    repo = FakeSourceRegistryRepository()
    candidates = (_candidate("ITEM-FED-1", "FED"),)  # candidate's own basis_availability is _ts(8)
    bootstrap = _make_bootstrap(repo, candidates)

    bootstrap_at = _ts(20)
    await bootstrap(bootstrap_at)

    source = await repo.get_source("FED")
    assert source is not None
    assert source.registered_at == bootstrap_at
    assert source.registered_at != _ts(8)

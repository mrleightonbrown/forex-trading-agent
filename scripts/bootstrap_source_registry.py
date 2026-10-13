"""FX-62: runs one idempotent bootstrap pass of the source-identity
and publisher-attribution registry against a live Postgres, for the
six existing, already-admitted news feeds (`domain.intelligence_
source_bootstrap_registry.INTELLIGENCE_SOURCE_BOOTSTRAP_MAPPINGS`).

Wires up already-tested machinery (`BootstrapSourceRegistry`,
`RecordSourceIdentityVintage`, `RecordSourceAttribution`,
`SqlAlchemySourceRegistryRepository`, `SqlAlchemyNewsSemanticRepository`)
rather than adding new behaviour -- same precedent as `scripts/ingest_
*_news.py`. No scheduler or daemon: a single, explicit, one-shot pass;
run it again whenever new items have been ingested through an admitted
feed.

Idempotent: a repeated run with unchanged source data writes nothing
new (`RecordSourceIdentityVintage`/`RecordSourceAttribution` both
return `UNCHANGED`, mirroring FX-56/FX-59's own idempotency).

Performs NO network I/O of any kind -- reads only already-persisted
`NewsItem`/`NewsItemVintage` evidence via `NewsSemanticRepository.
list_candidates_as_of`, and writes only FX-62's own new tables; never
touches `news_items`/`news_item_vintages`/`news_semantic_annotation_
vintages` (Section 11's own read/write boundary).

Run:
    uv run python scripts/bootstrap_source_registry.py
    uv run python scripts/bootstrap_source_registry.py --dry-run
    uv run python scripts/bootstrap_source_registry.py --as-of 2026-01-01T00:00:00Z

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
"""

import argparse
import asyncio
from datetime import datetime

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.use_cases.bootstrap_source_registry import (
    BootstrapSourceRegistry,
    BootstrapSourceRegistryResult,
)
from forex_agent.application.use_cases.record_source_attribution import RecordSourceAttribution
from forex_agent.application.use_cases.record_source_identity_vintage import (
    RecordSourceIdentityVintage,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.news_semantic_repository import SqlAlchemyNewsSemanticRepository
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.db.source_registry_repository import (
    SqlAlchemySourceRegistryRepository,
)


async def main(*, bootstrap_at: UtcTimestamp, dry_run: bool) -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as session:
        registry_repository = SqlAlchemySourceRegistryRepository(session)
        news_repository = SqlAlchemyNewsRepository(session)
        semantic_repository = SqlAlchemyNewsSemanticRepository(session, news_repository)

        record_identity = RecordSourceIdentityVintage(registry_repository)
        record_attribution = RecordSourceAttribution(registry_repository)
        bootstrap = BootstrapSourceRegistry(
            record_identity, record_attribution, semantic_repository
        )

        result = await bootstrap(bootstrap_at, dry_run=dry_run)

    _print_result(result, dry_run=dry_run)


def _print_result(result: BootstrapSourceRegistryResult, *, dry_run: bool) -> None:
    print(f"dry_run: {dry_run}")
    print(f"bootstrap_at: {result.bootstrap_at.value.isoformat()}")
    print(f"feed_identities_created: {result.feed_identities_created}")
    print(f"organization_identities_created: {result.organization_identities_created}")
    print(f"total_items_considered: {result.total_items_considered}")
    print(f"total_attributions_created: {result.total_attributions_created}")
    print(f"total_attributions_unchanged: {result.total_attributions_unchanged}")
    print()
    for mapping_result in result.mapping_results:
        mapping = mapping_result.mapping
        print(
            f"  {mapping.feed_source_key} ({mapping.feed_display_name}) -> "
            f"{mapping.organization_source_key} ({mapping.organization_display_name})"
        )
        print(
            f"    feed_identity={mapping_result.feed_identity_outcome.value} "
            f"organization_identity={mapping_result.organization_identity_outcome.value} "
            f"items_considered={mapping_result.items_considered} "
            f"attributions_created={mapping_result.attributions_created} "
            f"attributions_unchanged={mapping_result.attributions_unchanged}"
        )


def _parse_timestamp(raw: str) -> UtcTimestamp:
    return UtcTimestamp(datetime.fromisoformat(raw.replace("Z", "+00:00")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of", help="ISO-8601 instant to use as bootstrap_at; defaults to now, captured once."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print the outcome without writing anything.",
    )
    args = parser.parse_args()

    resolved_bootstrap_at = _parse_timestamp(args.as_of) if args.as_of else UtcTimestamp.now()

    asyncio.run(main(bootstrap_at=resolved_bootstrap_at, dry_run=args.dry_run))

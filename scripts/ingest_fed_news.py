"""FX-57A: runs one ingestion pass of all three configured Federal
Reserve RSS feeds (monetary-policy press releases, speeches,
testimony) against a live Postgres.

Wires up already-tested machinery (`FedRssSource`, `IngestNewsSourceOnce`,
`RecordNewsObservation`, `SqlAlchemyNewsRepository`) rather than adding
new behaviour, so it has no dedicated test suite of its own -- same
precedent as `scripts/backfill_policy_rate_history.py`. No scheduler or
daemon: this is a single, explicit, one-shot pass; run it again
whenever a new poll is wanted.

Idempotent: a repeated run over unchanged feed content writes nothing
new (`RecordNewsObservation` returns `UNCHANGED`, see FX-56/FX-56H.1).

Run:
    uv run python scripts/ingest_fed_news.py

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
    - Network access to www.federalreserve.gov
"""

import asyncio
import functools

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.ports.news_source import NewsSourceChannelFetcher
from forex_agent.application.use_cases.ingest_news_source_once import (
    IngestNewsSourceOnce,
    NewsIngestionResult,
)
from forex_agent.application.use_cases.record_news_observation import RecordNewsObservation
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.news_sources.fed_rss_source import (
    FED_FEEDS,
    SOURCE_KEY,
    FedRssSource,
)


async def main() -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    source = FedRssSource()
    try:
        async with session_factory() as session:
            repository = SqlAlchemyNewsRepository(session)
            record_observation = RecordNewsObservation(repository)
            ingest_once = IngestNewsSourceOnce(SOURCE_KEY, record_observation)

            fetchers: tuple[NewsSourceChannelFetcher, ...] = tuple(
                functools.partial(source.fetch_feed, feed) for feed in FED_FEEDS
            )
            result = await ingest_once(fetchers)
            await session.commit()
    finally:
        await source.aclose()

    _print_result(result)


def _print_result(result: NewsIngestionResult) -> None:
    print(f"source_key: {result.source_key}")
    print(f"source_channels: {result.source_channels}")
    print(f"retrieved_at: {[t.value.isoformat() for t in result.retrieved_at]}")
    print(f"items_seen: {result.items_seen}")
    print(f"items_invalid: {result.items_invalid}")
    print(f"created: {result.created}")
    print(f"revisions_added: {result.revisions_added}")
    print(f"unchanged: {result.unchanged}")
    print(f"quarantined: {result.quarantined}")
    print(f"errors: {result.errors}")


if __name__ == "__main__":
    asyncio.run(main())

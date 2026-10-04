"""FX-57C: runs one ingestion pass of the three configured Bank of
England RSS feeds (news, speeches, publications) against a live
Postgres.

Wires up already-tested machinery (`BoeRssSource`, `IngestNewsSourceOnce`,
`RecordNewsObservation`, `SqlAlchemyNewsRepository`) rather than adding
new behaviour, so it has no dedicated test suite of its own -- same
precedent as `scripts/ingest_fed_news.py`/`scripts/ingest_ecb_news.py`.
No scheduler or daemon: this is a single, explicit, one-shot pass; run
it again whenever a new poll is wanted.

Each feed holds 50 items (live-reconfirmed) -- a future operational
poller must run frequently enough that a burst of more items than a
feed retains between polls cannot create a silent evidence gap; this
script performs no scheduling of any kind itself.

Idempotent: a repeated run over unchanged feed content writes nothing
new (`RecordNewsObservation` returns `UNCHANGED`, see FX-56/FX-56H.1).

Run:
    uv run python scripts/ingest_boe_news.py

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
    - Network access to www.bankofengland.co.uk
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
from forex_agent.infrastructure.news_sources.boe_rss_source import (
    BOE_FEEDS,
    SOURCE_KEY,
    BoeRssSource,
)


async def main() -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    source = BoeRssSource()
    try:
        async with session_factory() as session:
            repository = SqlAlchemyNewsRepository(session)
            record_observation = RecordNewsObservation(repository)
            ingest_once = IngestNewsSourceOnce(SOURCE_KEY, record_observation)

            fetchers: tuple[NewsSourceChannelFetcher, ...] = tuple(
                functools.partial(source.fetch_feed, feed) for feed in BOE_FEEDS
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
    print(f"items_fetched: {result.items_fetched}")
    print(f"items_normalized: {result.items_normalized}")
    print(f"items_processed: {result.items_processed}")
    print(f"items_invalid: {result.items_invalid}")
    print(f"created: {result.created}")
    print(f"revisions_added: {result.revisions_added}")
    print(f"unchanged: {result.unchanged}")
    print(f"quarantined: {result.quarantined}")
    print(f"errors: {result.errors}")


if __name__ == "__main__":
    asyncio.run(main())

"""FX-57E: runs one ingestion pass of the four adopted Statistics
Canada "The Daily" subject feeds (prices, labour, economic accounts,
international trade) against a live Postgres.

Wires up already-tested machinery (`StatCanSource`, `IngestNewsSourceOnce`,
`RecordNewsObservation`, `SqlAlchemyNewsRepository`) rather than adding
new behaviour, so it has no dedicated test suite of its own -- same
precedent as `scripts/ingest_fed_news.py`/`scripts/ingest_ecb_news.py`/
`scripts/ingest_boe_news.py`/`scripts/ingest_govuk_hmt_news.py`. No
scheduler or daemon: this is a single, explicit, one-shot pass; run it
again whenever a new poll is wanted.

Feeds are fetched SEQUENTIALLY, never concurrently (Section 24), and
every request `StatCanSource` makes -- including internal retry
attempts -- is paced to respect `robots.txt`'s own `Crawl-delay: 2`
(live-reconfirmed) via that class's own injectable pacing.

**FX-57E0/ADR 0006**: unlike every prior FX-57 adapter, the SAME Daily
release can legitimately appear under more than one of these four
feeds within one run. `IngestNewsSourceOnce` now merges such a
benign, content-agreeing overlap into one item's own cumulative
`observed_source_channels` rather than failing the run closed; it
still fails the WHOLE run closed if any such overlap's own content
genuinely disagrees (printed in `errors` would instead be an
uncaught exception in that case, matching every other FX-57 adapter's
own "unexpected conflict propagates, never silently swallowed"
discipline).

Idempotent: a repeated run over unchanged feed content writes nothing
new (`RecordNewsObservation` returns `UNCHANGED`, see FX-56/FX-56H.1).

Run:
    uv run python scripts/ingest_statcan_news.py

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
    - Network access to www150.statcan.gc.ca
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
from forex_agent.infrastructure.news_sources.statcan_source import (
    SOURCE_KEY,
    STATCAN_FEEDS,
    StatCanSource,
)


async def main() -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    source = StatCanSource()
    try:
        async with session_factory() as session:
            repository = SqlAlchemyNewsRepository(session)
            record_observation = RecordNewsObservation(repository)
            ingest_once = IngestNewsSourceOnce(SOURCE_KEY, record_observation)

            fetchers: tuple[NewsSourceChannelFetcher, ...] = tuple(
                functools.partial(source.fetch_feed, feed) for feed in STATCAN_FEEDS
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
    print(f"channel_memberships_added: {result.channel_memberships_added}")
    print(f"errors: {result.errors}")


if __name__ == "__main__":
    asyncio.run(main())

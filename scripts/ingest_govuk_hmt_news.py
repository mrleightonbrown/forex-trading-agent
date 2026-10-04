"""FX-57D: runs one ingestion pass of the GOV.UK HM Treasury "News and
communications" discovery surface against a live Postgres.

Two-stage, as this story's own design requires: (1) DISCOVER current
content paths via the official HM Treasury Atom feed; (2) HYDRATE
each discovered path through the Content API, one fetcher per path,
all sharing the single `hmt_news_and_communications` channel, passed
into `IngestNewsSourceOnce` together. The Atom feed is NEVER itself a
source of stored evidence -- only of which paths to hydrate.

Wires up already-tested machinery (`GovUkHmtSource`, `IngestNewsSourceOnce`,
`RecordNewsObservation`, `SqlAlchemyNewsRepository`) rather than adding
new behaviour, so it has no dedicated test suite of its own -- same
precedent as `scripts/ingest_fed_news.py`/`scripts/ingest_ecb_news.py`/
`scripts/ingest_boe_news.py`. No scheduler or daemon: this is a single,
explicit, one-shot pass; run it again whenever a new poll is wanted.

Every Content API request (discovery included) is paced by
`GovUkHmtSource` itself to stay well under the documented 10 requests/
second/client limit -- this script issues no concurrent requests and
runs no retry loop of its own.

Idempotent: a repeated run over unchanged content writes nothing new
(`RecordNewsObservation` returns `UNCHANGED`, see FX-56/FX-56H.1).

Run:
    uv run python scripts/ingest_govuk_hmt_news.py

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
    - Network access to www.gov.uk
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
from forex_agent.infrastructure.news_sources.govuk_content_api import SOURCE_KEY, GovUkHmtSource


async def main() -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    source = GovUkHmtSource()
    try:
        paths = await source.discover_current_paths()
        print(f"discovered_paths: {len(paths)}")

        async with session_factory() as session:
            repository = SqlAlchemyNewsRepository(session)
            record_observation = RecordNewsObservation(repository)
            ingest_once = IngestNewsSourceOnce(SOURCE_KEY, record_observation)

            fetchers: tuple[NewsSourceChannelFetcher, ...] = tuple(
                functools.partial(source.fetch_content_item, path) for path in paths
            )
            result = await ingest_once(fetchers)
            await session.commit()
    finally:
        await source.aclose()

    _print_result(result)


def _print_result(result: NewsIngestionResult) -> None:
    print(f"source_key: {result.source_key}")
    print(f"source_channels: {set(result.source_channels)}")
    print(f"responses_fetched: {len(result.source_channels)}")
    print(f"retrieved_at_count: {len(result.retrieved_at)}")
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

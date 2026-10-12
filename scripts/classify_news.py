"""FX-59: runs one semantic-classification pass against the already-
ingested, already-canonicalized news evidence in a live Postgres --
zero network I/O (Section 86), no scheduler/daemon (Section 78).

Run (write mode -- persists any newly-discovered/changed semantic
annotations under the `fx59_v1` policy):

    uv run python scripts/classify_news.py

Run (dry-run -- previews real decisions, persists nothing; uses the
EXACT SAME classifier/decision logic as write mode, Section 64):

    uv run python scripts/classify_news.py --dry-run

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
"""

import argparse
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.use_cases.classify_news_once import (
    ClassifyNewsOnce,
    ClassifyNewsRunResult,
)
from forex_agent.application.use_cases.record_news_semantic_annotation import (
    RecordNewsSemanticAnnotation,
)
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.news_semantic_repository import SqlAlchemyNewsSemanticRepository
from forex_agent.infrastructure.db.session import get_engine


async def main(*, dry_run: bool) -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as session:
        news_repository = SqlAlchemyNewsRepository(session)
        semantic_repository = SqlAlchemyNewsSemanticRepository(session, news_repository)
        record = RecordNewsSemanticAnnotation(semantic_repository)
        classify_once = ClassifyNewsOnce(semantic_repository, record)

        result = await classify_once(dry_run=dry_run)
        await session.commit()

    _print_result(result, dry_run=dry_run)


def _print_result(result: ClassifyNewsRunResult, *, dry_run: bool) -> None:
    print(f"dry_run: {dry_run}")
    print(f"run_at: {result.run_at.value.isoformat()}")
    print(f"items_considered: {result.items_considered}")
    print(f"annotations_created: {result.annotations_created}")
    print(f"revisions_added: {result.revisions_added}")
    print(f"unchanged: {result.unchanged}")
    print(f"topics_none: {result.topics_none}")
    print(f"multi_topic_items: {result.multi_topic_items}")
    print(f"multi_currency_items: {result.multi_currency_items}")

    print()
    print("=== classifications_by_topic ===")
    for topic, count in result.classifications_by_topic:
        print(f"  {topic.value}: {count}")

    print()
    print("=== relevance_by_currency ===")
    for currency_code, count in result.relevance_by_currency:
        print(f"  {currency_code}: {count}")

    print()
    print(f"=== MULTI-CURRENCY CLASSIFICATIONS -- {len(result.multi_currency_classifications)} ===")
    for diagnostic in result.multi_currency_classifications:
        currencies = ", ".join(r.currency_code for r in diagnostic.currency_relevance)
        print(
            f"  {diagnostic.news_item_key} [{diagnostic.source_key}] {diagnostic.headline!r} "
            f"-> {currencies}"
        )

    print()
    print(
        "=== EXPLICIT FOREIGN-INSTITUTION CLASSIFICATIONS -- "
        f"{len(result.foreign_institution_classifications)} ==="
    )
    for diagnostic in result.foreign_institution_classifications:
        foreign = ", ".join(e.entity_key for e in diagnostic.non_source_entities)
        print(
            f"  {diagnostic.news_item_key} [{diagnostic.source_key}] {diagnostic.headline!r} "
            f"-> {foreign}"
        )

    print()
    print("=== SAMPLE (up to 5) PER TOPIC ===")
    by_news_item_key = sorted(result.diagnostics, key=lambda d: d.news_item_key)
    for topic, _count in result.classifications_by_topic:
        matching = [d for d in by_news_item_key if topic in d.topics][:5]
        print(f"  {topic.value}:")
        for diagnostic in matching:
            print(
                f"    {diagnostic.news_item_key} [{diagnostic.source_key}] {diagnostic.headline!r}"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview real decisions using the exact same classifier; persist nothing.",
    )
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))

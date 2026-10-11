"""FX-58: runs one canonicalization pass against the already-ingested
news evidence in a live Postgres -- zero network I/O (FX-58 Section
64), no scheduler/daemon (Section 65).

Run (write mode -- persists any newly-discovered SAME_STORY relations):

    uv run python scripts/canonicalize_news.py

Run (dry-run -- previews real decisions, persists nothing; uses the
EXACT SAME matcher/decision logic as write mode, Section 65):

    uv run python scripts/canonicalize_news.py --dry-run

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
"""

import argparse
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.use_cases.canonicalize_news_once import (
    CanonicalizeNewsOnce,
    NewsCanonicalizationRunResult,
)
from forex_agent.application.use_cases.record_news_canonical_relation import (
    RecordNewsCanonicalRelation,
)
from forex_agent.infrastructure.db.news_canonicalization_repository import (
    SqlAlchemyNewsCanonicalizationRepository,
)
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine


async def main(*, dry_run: bool) -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as session:
        news_repository = SqlAlchemyNewsRepository(session)
        canonicalization_repository = SqlAlchemyNewsCanonicalizationRepository(
            session, news_repository
        )
        record = RecordNewsCanonicalRelation(canonicalization_repository)
        canonicalize_once = CanonicalizeNewsOnce(canonicalization_repository, record)

        result = await canonicalize_once(dry_run=dry_run)
        await session.commit()

    _print_result(result, dry_run=dry_run)


def _print_result(result: NewsCanonicalizationRunResult, *, dry_run: bool) -> None:
    print(f"dry_run: {dry_run}")
    print(f"run_at: {result.run_at.value.isoformat()}")
    print(f"items_considered: {result.items_considered}")
    print(f"candidate_pairs: {result.candidate_pairs}")
    print(f"relations_created: {result.relations_created}")
    print(f"relations_unchanged: {result.relations_unchanged}")
    print(f"blocked_by_review_override: {result.blocked_by_review_override}")
    print(f"exact_url_matches: {result.exact_url_matches}")
    print(f"exact_body_matches: {result.exact_body_matches}")
    print(f"exact_headline_summary_matches: {result.exact_headline_summary_matches}")
    if result.blocked_pairs:
        print(f"blocked_pairs: {result.blocked_pairs}")
    for relation in result.created_relations:
        print(
            f"  [{relation.method.value}] "
            f"{relation.left_news_item_key} ({relation.left_headline!r}, "
            f"{relation.left_canonical_url!r}) <-> "
            f"{relation.right_news_item_key} ({relation.right_headline!r}, "
            f"{relation.right_canonical_url!r})"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview proposed relations using the exact same matcher; persist nothing.",
    )
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))

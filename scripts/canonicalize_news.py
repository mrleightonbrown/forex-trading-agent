"""FX-58/FX-58H: runs one canonicalization pass against the already-
ingested news evidence in a live Postgres -- zero network I/O (FX-58
Section 64), no scheduler/daemon (Section 65).

Run (write mode -- persists any newly-discovered automatic SAME_STORY
relations under the `fx58_v2` policy):

    uv run python scripts/canonicalize_news.py

Run (dry-run -- previews real decisions, persists nothing; uses the
EXACT SAME matcher/decision logic as write mode, Section 65):

    uv run python scripts/canonicalize_news.py --dry-run

**FX-58H Section 14: output clearly separates two genuinely different
things.** "AUTOMATIC RELATIONS" are safe-to-write candidates under
`fx58_v2` (`EXACT_CANONICAL_URL`/`EXACT_BODY_TEXT`) -- these are what
write mode actually persists. "REVIEW-ONLY CANDIDATES" are the
demoted exact-headline+summary signal -- weak evidence that will
NEVER be persisted by this script, printed purely for a human
reviewer's own inspection. Never described as "proposed relations."

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
    print(f"headline_summary_review_candidates: {result.headline_summary_review_candidates}")
    if result.blocked_pairs:
        print(f"blocked_pairs: {result.blocked_pairs}")

    print()
    print(
        "=== AUTOMATIC RELATIONS (safe-to-write under fx58_v2) -- "
        f"{len(result.created_relations)} ==="
    )
    for relation in result.created_relations:
        print(
            f"  [{relation.method.value}] "
            f"{relation.left_news_item_key} ({relation.left_headline!r}, "
            f"{relation.left_canonical_url!r}) <-> "
            f"{relation.right_news_item_key} ({relation.right_headline!r}, "
            f"{relation.right_canonical_url!r})"
        )

    print()
    print(
        "=== REVIEW-ONLY CANDIDATES (weak signal -- will NEVER be persisted by this "
        f"script) -- {len(result.review_candidates)} ==="
    )
    for candidate in result.review_candidates:
        print(
            f"  [{candidate.reason.value}] "
            f"{candidate.left_news_item_key} ({candidate.left_headline!r}) <-> "
            f"{candidate.right_news_item_key} ({candidate.right_headline!r})"
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

"""FX-60: a READ-ONLY manual inspection script for `GetPairNews
EvidenceSnapshot` -- no write, no network I/O, no scheduler. Captures
`now()` exactly once (if `--as-of` is omitted) and derives every
other timing value from that single instant; the CORE use case itself
still takes explicit `window_start`/`as_of` (this script never hides
that contract).

Examples:

    uv run python scripts/show_pair_news_snapshot.py --pair EUR/USD --lookback-hours 168
    uv run python scripts/show_pair_news_snapshot.py --pair USD/CAD \\
        --window-start 2026-01-01T00:00:00Z --as-of 2026-01-02T00:00:00Z

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
"""

import argparse
import asyncio
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.use_cases.get_pair_news_evidence_snapshot import (
    GetPairNewsEvidenceSnapshot,
    NewsPairEvidenceGroup,
    NewsPairEvidenceSnapshot,
)
from forex_agent.domain.instrument import parse_instrument
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.news_canonicalization_repository import (
    SqlAlchemyNewsCanonicalizationRepository,
)
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.news_semantic_repository import SqlAlchemyNewsSemanticRepository
from forex_agent.infrastructure.db.session import get_engine


async def main(*, pair_code: str, window_start: UtcTimestamp, as_of: UtcTimestamp) -> None:
    pair = parse_instrument(pair_code)
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as session:
        news_repository = SqlAlchemyNewsRepository(session)
        canonicalization_repository = SqlAlchemyNewsCanonicalizationRepository(
            session, news_repository
        )
        semantic_repository = SqlAlchemyNewsSemanticRepository(session, news_repository)
        get_snapshot = GetPairNewsEvidenceSnapshot(
            news_repository, canonicalization_repository, semantic_repository
        )
        snapshot = await get_snapshot(pair, window_start, as_of)
        # Read-only: nothing is committed, but roll back explicitly so
        # no accidental session-level state lingers.
        await session.rollback()

    _print_snapshot(snapshot)


def _print_snapshot(snapshot: NewsPairEvidenceSnapshot) -> None:
    print(f"policy_version: {snapshot.policy_version}")
    print(f"pair: {snapshot.base_currency}/{snapshot.quote_currency}")
    print(f"window_start: {snapshot.window_start.value.isoformat()}")
    print(f"as_of: {snapshot.as_of.value.isoformat()}")
    print(f"coverage: {snapshot.coverage.value}")
    print()
    print(f"active story count: {len(snapshot.active_entries)}")
    print(f"withdrawn-only count: {len(snapshot.withdrawn_only_entries)}")
    print(f"semantic-gap count: {len(snapshot.semantic_gaps)}")
    print(f"groups_considered: {snapshot.groups_considered}")
    print(f"groups_outside_window: {snapshot.groups_outside_window}")
    print(f"groups_without_eligible_evidence: {snapshot.groups_without_eligible_evidence}")
    print(f"groups_pair_irrelevant: {snapshot.groups_pair_irrelevant}")

    print()
    print(f"=== ACTIVE ENTRIES -- {len(snapshot.active_entries)} ===")
    for entry in snapshot.active_entries:
        _print_entry(entry)

    print()
    print(f"=== WITHDRAWN-ONLY ENTRIES -- {len(snapshot.withdrawn_only_entries)} ===")
    for entry in snapshot.withdrawn_only_entries:
        _print_entry(entry)

    print()
    print(f"=== SEMANTIC GAPS -- {len(snapshot.semantic_gaps)} ===")
    for gap in snapshot.semantic_gaps:
        print(
            f"  group={gap.canonical_group_key} item={gap.news_item_key} "
            f"state={gap.semantic_state.value} current_rev={gap.current_news_revision_sequence} "
            f"basis_rev={gap.annotation_basis_revision_sequence}"
        )


def _print_entry(entry: NewsPairEvidenceGroup) -> None:
    display = next(
        m for m in entry.members if m.news_item_key == entry.display_member_news_item_key
    )
    topics = ", ".join(t.value for t in entry.topics) or "(none)"
    base_reasons = ", ".join(r.value for r in entry.base_relevance_reasons) or "(none)"
    quote_reasons = ", ".join(r.value for r in entry.quote_relevance_reasons) or "(none)"
    print(f"  story_first_seen_at: {entry.story_first_seen_at.value.isoformat()}")
    print(f"  relevance_side: {entry.pair_relevance_side.value}")
    print(f"  headline: {display.headline!r}")
    print(f"  publisher_institution: {display.publisher_institution_entity_key}")
    print(f"  topics: {topics}")
    print(f"  base_reasons: {base_reasons}")
    print(f"  quote_reasons: {quote_reasons}")
    print(f"  canonical_group_key: {entry.canonical_group_key}")
    print(f"  member_count: {len(entry.member_news_item_keys)}")
    print()


def _parse_timestamp(raw: str) -> UtcTimestamp:
    return UtcTimestamp(datetime.fromisoformat(raw.replace("Z", "+00:00")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", required=True, help='e.g. "EUR/USD"')
    parser.add_argument("--window-start", help="ISO-8601 instant, e.g. 2026-01-01T00:00:00Z")
    parser.add_argument(
        "--lookback-hours",
        type=float,
        help="Alternative to --window-start: window_start = as_of - this many hours.",
    )
    parser.add_argument("--as-of", help="ISO-8601 instant; defaults to now, captured once.")
    args = parser.parse_args()

    resolved_as_of = _parse_timestamp(args.as_of) if args.as_of else UtcTimestamp.now()

    if args.window_start:
        resolved_window_start = _parse_timestamp(args.window_start)
    elif args.lookback_hours is not None:
        resolved_window_start = UtcTimestamp(
            resolved_as_of.value - timedelta(hours=args.lookback_hours)
        )
    else:
        parser.error("one of --window-start or --lookback-hours is required")
        raise SystemExit(2)

    asyncio.run(main(pair_code=args.pair, window_start=resolved_window_start, as_of=resolved_as_of))

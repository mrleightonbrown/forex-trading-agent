"""FX-56: `RecordNewsObservation` against the real
`SqlAlchemyNewsRepository`/live Postgres. First-observation atomicity
and PIT ordering hardened by FX-56H.

Mirrors `tests/integration/test_ingest_official_calendar.py`'s own
precedent of testing an ingestion-shaped application use case against
a real repository rather than an in-memory fake -- `Ingest
OfficialCalendarSchedule` has no fake-repository unit test either.

Requires a live Postgres with the FX-56/FX-56H migrations applied --
run `docker compose up -d db && alembic upgrade head` first.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.ports.news_source import NormalizedNewsObservation
from forex_agent.application.use_cases.record_news_observation import (
    NewsObservationOutOfOrderError,
    RecordNewsObservation,
    RecordNewsObservationOutcome,
)
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine

TEST_SOURCE_KEY = "__test_record_source__"
TEST_ITEM_PREFIX = "__test_record_source__"


def _ts(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, minute, second, tzinfo=UTC))


def _observation(
    external_item_id: str,
    observed_at: UtcTimestamp,
    headline: str,
    **overrides: object,
) -> NormalizedNewsObservation:
    defaults: dict[str, object] = {
        "source_key": TEST_SOURCE_KEY,
        "external_item_id": external_item_id,
        "observed_at": observed_at,
        "observation_mode": NewsObservationMode.PROSPECTIVE,
        "headline": headline,
        "source_status": NewsSourceStatus.ACTIVE,
        "evidence_disposition": NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    }
    defaults.update(overrides)
    return NormalizedNewsObservation(**defaults)  # type: ignore[arg-type]


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        await cleanup_session.execute(
            delete(NewsItemVintageRow).where(
                NewsItemVintageRow.news_item_key.startswith(TEST_ITEM_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(NewsSourceMappingRow).where(
                NewsSourceMappingRow.source_key.startswith(TEST_SOURCE_KEY)
            )
        )
        await cleanup_session.execute(
            delete(NewsItemRow).where(NewsItemRow.news_item_key.startswith(TEST_ITEM_PREFIX))
        )
        await cleanup_session.commit()


@pytest.fixture
def use_case(session: AsyncSession) -> RecordNewsObservation:
    return RecordNewsObservation(SqlAlchemyNewsRepository(session))


async def _counts_for_identity(source_key: str, external_item_id: str) -> tuple[int, int, int]:
    """(item_count, mapping_count, vintage_count) for one external
    identity, via a FRESH session/connection -- used to prove that a
    failed first observation leaves truly zero durable rows (FX-56H
    Section 3/11), not merely zero rows visible through the same
    session that attempted the write."""
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as check_session:
        item_count: int = (
            await check_session.execute(
                text(
                    "SELECT COUNT(*) FROM news_items ni "
                    "JOIN news_source_mappings m ON m.news_item_key = ni.news_item_key "
                    "WHERE m.source_key = :source_key AND m.external_item_id = :external_item_id"
                ),
                {"source_key": source_key, "external_item_id": external_item_id},
            )
        ).scalar_one()
        mapping_count: int = (
            await check_session.execute(
                text(
                    "SELECT COUNT(*) FROM news_source_mappings "
                    "WHERE source_key = :source_key AND external_item_id = :external_item_id"
                ),
                {"source_key": source_key, "external_item_id": external_item_id},
            )
        ).scalar_one()
        vintage_count: int = (
            await check_session.execute(
                text(
                    "SELECT COUNT(*) FROM news_item_vintages v "
                    "JOIN news_source_mappings m ON m.news_item_key = v.news_item_key "
                    "WHERE m.source_key = :source_key AND m.external_item_id = :external_item_id"
                ),
                {"source_key": source_key, "external_item_id": external_item_id},
            )
        ).scalar_one()
        return item_count, mapping_count, vintage_count


async def _raw_item_count_by_prefix(source_key: str) -> int:
    """Every `news_items` row whose `news_item_key` starts with
    `{source_key}:` -- i.e. every key `mint_news_item_key` could ever
    have produced for this `source_key`, regardless of whether a
    mapping row exists for it (FX-56H.1 Section 4). `_counts_for_
    identity`'s own `item_count` starts its query FROM `news_source_
    mappings` (a JOIN), which by construction can only ever find an
    item that already HAS a mapping -- it cannot detect a hypothetical
    orphan `NewsItem` with no mapping at all. This can."""
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as check_session:
        count: int = (
            await check_session.execute(
                text("SELECT COUNT(*) FROM news_items WHERE news_item_key LIKE :pattern"),
                {"pattern": f"{source_key}:%"},
            )
        ).scalar_one()
        return count


async def test_first_observation_creates_item_and_revision_zero(
    use_case: RecordNewsObservation,
) -> None:
    observed_at = _ts(2026, 9, 29, 9, 2)
    result = await use_case(_observation("item-1", observed_at, "Headline A"))
    assert result.outcome is RecordNewsObservationOutcome.CREATED
    assert result.revision_sequence == 0


async def test_repeated_identical_observation_is_unchanged(
    use_case: RecordNewsObservation,
) -> None:
    observed_at_1 = _ts(2026, 9, 29, 9, 2)
    observed_at_2 = _ts(2026, 9, 29, 9, 5)
    first = await use_case(_observation("item-2", observed_at_1, "Same headline"))
    second = await use_case(_observation("item-2", observed_at_2, "Same headline"))

    assert second.outcome is RecordNewsObservationOutcome.UNCHANGED
    assert second.news_item_key == first.news_item_key
    assert second.revision_sequence == first.revision_sequence == 0


async def test_changed_headline_adds_a_revision(use_case: RecordNewsObservation) -> None:
    await use_case(_observation("item-3", _ts(2026, 9, 29, 10, 0), "Headline A"))
    second = await use_case(_observation("item-3", _ts(2026, 9, 29, 10, 10), "Headline B"))

    assert second.outcome is RecordNewsObservationOutcome.REVISION_ADDED
    assert second.revision_sequence == 1


async def test_different_external_id_same_headline_creates_different_items(
    use_case: RecordNewsObservation,
) -> None:
    # FX-56 Section 36: no fuzzy/content deduplication at this layer.
    first = await use_case(
        _observation("item-4a", _ts(2026, 9, 29, 10, 0), "Central bank statement")
    )
    second = await use_case(
        _observation("item-4b", _ts(2026, 9, 29, 10, 0), "Central bank statement")
    )
    assert first.news_item_key != second.news_item_key


async def test_source_updated_at_before_fta_observation_does_not_backdate_revision(
    use_case: RecordNewsObservation,
) -> None:
    # FX-56 Section 18/48: a source-claimed update time earlier than
    # FTA's own observation must never move the new revision's own
    # availability backward.
    await use_case(_observation("item-5", _ts(2026, 9, 29, 9, 0), "Original"))
    result = await use_case(
        _observation(
            "item-5",
            _ts(2026, 9, 29, 9, 14),
            "Corrected",
            source_updated_at=_ts(2026, 9, 29, 9, 10),
        )
    )
    assert result.outcome is RecordNewsObservationOutcome.REVISION_ADDED
    assert result.revision_sequence == 1


# --- FX-56H: first-observation atomicity -----------------------------------


async def test_invalid_first_observation_leaves_zero_durable_rows() -> None:
    # FX-56H Section 3/11.1: `NormalizedNewsObservation` itself rejects
    # a blank headline before `RecordNewsObservation` is ever called --
    # confirm that no row of any kind was persisted for this identity.
    with pytest.raises(ValueError, match="headline"):
        _observation("item-invalid-1", _ts(2026, 9, 29, 9, 2), "")

    assert await _counts_for_identity(TEST_SOURCE_KEY, "item-invalid-1") == (0, 0, 0)


async def test_invalid_quarantine_state_leaves_zero_durable_rows() -> None:
    # FX-56H Section 3/11.1, second malformed-input case.
    with pytest.raises(ValueError, match="quarantine_reason"):
        _observation(
            "item-invalid-2",
            _ts(2026, 9, 29, 9, 2),
            "A headline",
            evidence_disposition=NewsEvidenceDisposition.QUARANTINED,
        )

    assert await _counts_for_identity(TEST_SOURCE_KEY, "item-invalid-2") == (0, 0, 0)


async def test_injected_first_vintage_persistence_failure_leaves_zero_durable_rows(
    use_case: RecordNewsObservation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # FX-56H Section 2/11.2, strengthened by FX-56H.1 Section 4:
    # simulate an unexpected infrastructure failure happening AFTER
    # the item/mapping insert succeeded within the same uncommitted
    # transaction, but BEFORE the whole attempt commits -- the entire
    # attempt must roll back, not just the part that failed. Uses a
    # DEDICATED source_key (not the file's shared `TEST_SOURCE_KEY`,
    # whose rows the `session` fixture cleans up automatically) so the
    # raw `news_items` count below is taken independently of
    # `_counts_for_identity`'s own JOIN through `news_source_
    # mappings` -- that JOIN starts FROM the mapping table, so it
    # structurally cannot detect a hypothetical orphan `NewsItem` that
    # has no mapping at all; the raw count can, which is why this test
    # cleans up its own dedicated prefix explicitly.
    dedicated_source_key = f"{TEST_SOURCE_KEY}_injected_failure"
    external_item_id = "item-injected-failure"

    async def _raise(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated first-vintage persistence failure")

    monkeypatch.setattr(SqlAlchemyNewsRepository, "_insert_vintage_row", _raise)

    try:
        with pytest.raises(RuntimeError, match="simulated first-vintage persistence failure"):
            await use_case(
                _observation(
                    external_item_id,
                    _ts(2026, 9, 29, 9, 2),
                    "Headline",
                    source_key=dedicated_source_key,
                )
            )

        assert await _counts_for_identity(dedicated_source_key, external_item_id) == (0, 0, 0)
        # Direct, mapping-independent proof: no orphan `NewsItem` under
        # ANY candidate key survived either.
        assert await _raw_item_count_by_prefix(dedicated_source_key) == 0
    finally:
        await _cleanup_identity(dedicated_source_key, external_item_id)


async def test_successful_first_observation_creates_item_mapping_and_revision0_atomically(
    use_case: RecordNewsObservation,
) -> None:
    # FX-56H Section 2/11.3.
    observed_at = _ts(2026, 9, 29, 9, 2)
    result = await use_case(_observation("item-atomic", observed_at, "Headline"))
    assert result.outcome is RecordNewsObservationOutcome.CREATED

    item_count, mapping_count, vintage_count = await _counts_for_identity(
        TEST_SOURCE_KEY, "item-atomic"
    )
    assert (item_count, mapping_count, vintage_count) == (1, 1, 1)


async def test_revision0_availability_equals_item_first_seen_at(
    use_case: RecordNewsObservation, session: AsyncSession
) -> None:
    # FX-56H Section 4/11.4 -- pinned by an integration test, not only
    # a docstring claim.
    observed_at = _ts(2026, 9, 29, 9, 2)
    result = await use_case(_observation("item-invariant-1", observed_at, "Headline"))

    repo = SqlAlchemyNewsRepository(session)
    item = await repo.get_item(result.news_item_key)
    vintages = await repo.list_vintages(result.news_item_key)
    assert item is not None
    assert len(vintages) == 1
    revision_0 = vintages[0]
    assert revision_0.revision_sequence == 0
    assert revision_0.availability == item.first_seen_at == observed_at


async def test_revision0_observation_mode_equals_item_first_observation_mode(
    use_case: RecordNewsObservation, session: AsyncSession
) -> None:
    # FX-56H Section 4/11.5.
    observed_at = _ts(2026, 9, 29, 9, 2)
    result = await use_case(
        _observation(
            "item-invariant-2",
            observed_at,
            "Headline",
            observation_mode=NewsObservationMode.PROSPECTIVE,
        )
    )

    repo = SqlAlchemyNewsRepository(session)
    item = await repo.get_item(result.news_item_key)
    vintages = await repo.list_vintages(result.news_item_key)
    assert item is not None
    revision_0 = vintages[0]
    assert revision_0.observation_mode == NewsObservationMode.PROSPECTIVE
    assert item.first_observation_mode == NewsObservationMode.PROSPECTIVE


async def _cleanup_identity(source_key: str, external_item_id: str) -> None:
    """Explicit cleanup for a test that deliberately does NOT use the
    `session`/`use_case` fixtures (both run two independent, real
    sessions of their own, so a single shared fixture session would
    not represent the scenario under test) -- without this, a test's
    own rows would survive past it, silently corrupting every later
    run of the SAME test (caught directly: a second run started
    raising `NewsObservationOutOfOrderError` because the first run's
    own un-cleaned-up revision history was still present). Plain raw
    SQL, in FK-dependency order -- `news_item_vintages` AND `news_
    source_mappings` both reference `news_items`, so BOTH must be
    deleted before `news_items` itself, never after (an earlier
    version of this helper deleted `news_items` before `news_source_
    mappings` and failed every run with a foreign-key `IntegrityError`,
    caught immediately by running this test repeatedly as FX-56H's own
    "run concurrency tests repeatedly" verification step requires).
    Deliberately avoids an ORM subquery for clarity."""
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as cleanup_session:
        await cleanup_session.execute(
            text(
                "DELETE FROM news_item_vintages WHERE news_item_key IN ("
                "SELECT news_item_key FROM news_source_mappings "
                "WHERE source_key = :source_key AND external_item_id = :external_item_id)"
            ),
            {"source_key": source_key, "external_item_id": external_item_id},
        )
        news_item_key: str | None = (
            await cleanup_session.execute(
                text(
                    "SELECT news_item_key FROM news_source_mappings "
                    "WHERE source_key = :source_key AND external_item_id = :external_item_id"
                ),
                {"source_key": source_key, "external_item_id": external_item_id},
            )
        ).scalar_one_or_none()
        await cleanup_session.execute(
            text(
                "DELETE FROM news_source_mappings "
                "WHERE source_key = :source_key AND external_item_id = :external_item_id"
            ),
            {"source_key": source_key, "external_item_id": external_item_id},
        )
        if news_item_key is not None:
            await cleanup_session.execute(
                text("DELETE FROM news_items WHERE news_item_key = :key"),
                {"key": news_item_key},
            )
        await cleanup_session.commit()


async def test_concurrent_complete_first_observations_leave_exactly_one_of_each() -> None:
    # FX-56H Section 5/11.6: exercise the FULL first-observation path
    # (`RecordNewsObservation`, not merely `register_source_item`) with
    # two genuinely concurrent sessions submitting the IDENTICAL
    # observation for a never-before-seen identity. Deliberately does
    # NOT use the `session`/`use_case` fixtures -- it needs two REAL,
    # independent sessions/connections, not one shared fixture session
    # -- so it cleans up its own rows explicitly in a `finally` block.
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    external_item_id = "item-concurrent-first"
    observed_at = _ts(2026, 9, 29, 9, 2)

    async def _record() -> RecordNewsObservationOutcome:
        async with session_factory() as own_session:
            own_use_case = RecordNewsObservation(SqlAlchemyNewsRepository(own_session))
            result = await own_use_case(
                _observation(external_item_id, observed_at, "Identical headline")
            )
            return result.outcome

    try:
        outcome_a, outcome_b = await asyncio.gather(_record(), _record())
        outcomes = {outcome_a, outcome_b}
        assert outcomes == {
            RecordNewsObservationOutcome.CREATED,
            RecordNewsObservationOutcome.UNCHANGED,
        }

        item_count, mapping_count, vintage_count = await _counts_for_identity(
            TEST_SOURCE_KEY, external_item_id
        )
        assert (item_count, mapping_count, vintage_count) == (1, 1, 1)
    finally:
        await _cleanup_identity(TEST_SOURCE_KEY, external_item_id)


async def test_concurrent_identical_changed_revision_does_not_falsely_report_revision_added() -> (
    None
):
    # FX-56H Section 6/11.8: once an item already exists, two
    # concurrent writers submitting the SAME changed observation must
    # never BOTH report REVISION_ADDED -- exactly one revision-1 row
    # may exist, and the loser must truthfully report UNCHANGED. Same
    # "no shared fixture session" reasoning as the test above, and the
    # same explicit cleanup requirement.
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    external_item_id = "item-concurrent-changed"
    first_observed = _ts(2026, 9, 29, 9, 0)

    try:
        async with session_factory() as setup_session:
            setup_use_case = RecordNewsObservation(SqlAlchemyNewsRepository(setup_session))
            await setup_use_case(_observation(external_item_id, first_observed, "Original"))

        changed_observed = _ts(2026, 9, 29, 9, 30)

        async def _record_change() -> tuple[RecordNewsObservationOutcome, int]:
            async with session_factory() as own_session:
                own_use_case = RecordNewsObservation(SqlAlchemyNewsRepository(own_session))
                result = await own_use_case(
                    _observation(external_item_id, changed_observed, "Corrected")
                )
                return result.outcome, result.revision_sequence

        outcome_a, outcome_b = await asyncio.gather(_record_change(), _record_change())
        outcomes = {outcome_a[0], outcome_b[0]}
        assert outcomes == {
            RecordNewsObservationOutcome.REVISION_ADDED,
            RecordNewsObservationOutcome.UNCHANGED,
        }
        assert outcome_a[1] == outcome_b[1] == 1

        _, _, vintage_count = await _counts_for_identity(TEST_SOURCE_KEY, external_item_id)
        assert vintage_count == 2  # revision 0 (original) + exactly one revision 1 (corrected)
    finally:
        await _cleanup_identity(TEST_SOURCE_KEY, external_item_id)


async def test_changed_out_of_order_observation_fails_closed(
    use_case: RecordNewsObservation,
) -> None:
    # FX-56H Section 7/11.9.
    later = _ts(2026, 9, 29, 10, 0)
    earlier = _ts(2026, 9, 29, 9, 0)
    await use_case(_observation("item-out-of-order", later, "Current headline"))

    with pytest.raises(NewsObservationOutOfOrderError):
        await use_case(_observation("item-out-of-order", earlier, "Backdated change"))

    _, _, vintage_count = await _counts_for_identity(TEST_SOURCE_KEY, "item-out-of-order")
    assert vintage_count == 1  # the rejected attempt added nothing


async def test_identical_but_earlier_observation_fails_closed(
    use_case: RecordNewsObservation,
) -> None:
    # FX-56H.1 Section 1: the central correction. An earlier observed_
    # at asserts FTA possessed these exact facts earlier than the
    # stored history says, and that assertion must be rejected EVEN
    # WHEN the facts themselves are identical to the latest vintage --
    # silently returning UNCHANGED would knowingly preserve an
    # availability history already known to be wrong.
    later = _ts(2026, 9, 29, 10, 0)
    earlier = _ts(2026, 9, 29, 9, 0)
    await use_case(_observation("item-identical-earlier", later, "Same headline"))

    with pytest.raises(NewsObservationOutOfOrderError):
        await use_case(_observation("item-identical-earlier", earlier, "Same headline"))

    _, _, vintage_count = await _counts_for_identity(TEST_SOURCE_KEY, "item-identical-earlier")
    assert vintage_count == 1  # the rejected attempt added nothing; no retroactive correction


async def test_identical_equal_timestamp_observation_is_unchanged(
    use_case: RecordNewsObservation,
) -> None:
    # FX-56H.1 Section 1: equal timestamps remain explicitly
    # permitted -- the ordering check is strictly "<", never "<=".
    same_instant = _ts(2026, 9, 29, 9, 0)
    first = await use_case(_observation("item-identical-equal", same_instant, "Same headline"))
    second = await use_case(_observation("item-identical-equal", same_instant, "Same headline"))

    assert second.outcome is RecordNewsObservationOutcome.UNCHANGED
    assert second.revision_sequence == first.revision_sequence == 0


async def test_earlier_observation_fails_closed_after_later_observation_wins_first_registration(
    use_case: RecordNewsObservation, session: AsyncSession
) -> None:
    # FX-56H.1 Section 2: pins the outcome of a genuine identity race
    # in which the LATER-timestamped worker happens to win. True
    # concurrency cannot force a specific winner deterministically
    # (see `test_concurrent_complete_first_observations_leave_exactly_
    # one_of_each` for the genuinely concurrent proof, where either
    # side may win); this test instead reproduces the EXACT state a
    # "T2 wins" race leaves behind -- by registering T2 first -- and
    # proves what must happen to the LOSING (T1) observation when it
    # subsequently resolves against the already-created item: it must
    # NOT silently return UNCHANGED, even though T1 < T2. The stored
    # first_seen_at/revision-0 availability must remain untouched; no
    # retroactive correction is attempted.
    t1 = _ts(2026, 9, 29, 9, 0)
    t2 = _ts(2026, 9, 29, 10, 0)
    external_item_id = "item-race-later-wins"

    winner = await use_case(_observation(external_item_id, t2, "Winning headline"))
    assert winner.outcome is RecordNewsObservationOutcome.CREATED

    with pytest.raises(NewsObservationOutOfOrderError):
        await use_case(_observation(external_item_id, t1, "Losing headline"))

    repo = SqlAlchemyNewsRepository(session)
    item = await repo.get_item(winner.news_item_key)
    vintages = await repo.list_vintages(winner.news_item_key)
    assert item is not None
    assert item.first_seen_at == t2  # immutable -- no retroactive correction
    assert len(vintages) == 1
    assert vintages[0].availability == t2
    assert vintages[0].headline == "Winning headline"


async def test_equal_availability_timestamps_remain_deterministic(
    use_case: RecordNewsObservation, session: AsyncSession
) -> None:
    # FX-56H Section 7/11.10: an EQUAL (not earlier) observed_at is
    # permitted; `revision_sequence` provides the deterministic
    # tie-break for PIT ordering.
    same_instant = _ts(2026, 9, 29, 9, 0)
    first = await use_case(_observation("item-equal-ts", same_instant, "Original"))
    second = await use_case(_observation("item-equal-ts", same_instant, "Corrected"))

    assert first.outcome is RecordNewsObservationOutcome.CREATED
    assert second.outcome is RecordNewsObservationOutcome.REVISION_ADDED
    assert second.revision_sequence == 1

    repo = SqlAlchemyNewsRepository(session)
    latest = await repo.latest_vintage_as_of(second.news_item_key, same_instant)
    assert latest is not None
    assert latest.revision_sequence == 1
    assert latest.headline == "Corrected"
    assert latest.availability == same_instant

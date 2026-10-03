"""SQLAlchemy implementation of `NewsRepository` (FX-56; first-
observation atomicity hardened by FX-56H).

`register_source_item`/`register_source_item_with_first_vintage` are
this module's own most important methods -- see `application.ports.
news_repository`'s module docstring for why each must be, and is,
atomic. Both share `_insert_item_and_mapping`: the candidate
`NewsItemRow` and its `NewsSourceMappingRow` are inserted (flushed, not
committed) in ONE transaction; the caller commits them TOGETHER only
if the mapping insert's own `ON CONFLICT DO NOTHING` actually wins. A
losing attempt rolls the WHOLE transaction back -- discarding its own
candidate item insert along with it -- before resolving to the
winner's already-registered identity. This is safe under Postgres's
own `READ COMMITTED` isolation without any extra synchronization: a
second session's conflicting mapping insert blocks on the first
session's row lock until that first transaction commits or rolls
back, then resolves correctly either way once unblocked.

`register_source_item_with_first_vintage` (FX-56H) extends this same
discipline one step further: for a genuinely NEW item, its revision-0
`NewsItemVintageRow` insert joins the SAME uncommitted transaction as
the item/mapping inserts, so all three commit together or none do --
closing a gap the original FX-56 design left open, where a first
observation's identity registration and its first vintage write were
two separate, separately-committed operations, and a failure between
them could leave a durably-committed item with no revision 0 at all.

Every OTHER write in this module keeps the same idempotent `INSERT
... ON CONFLICT DO NOTHING ... RETURNING id` discipline already
established by `SqlAlchemyEconomicEventRepository` -- no method here
ever issues an `UPDATE` against a vintage, item, or mapping row.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.application.ports.news_repository import (
    FirstObservationResult,
    NewsItemRegistrationOutcome,
    NewsItemRegistrationResult,
    NewsVintageConflictError,
    NewsVintageWriteOutcome,
)
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item import NewsItem
from forex_agent.domain.news_item_identity import mint_news_item_key
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.news_source_revision_fact import (
    NewsSourceRevisionFact,
    NewsSourceRevisionKind,
)
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.news_source_timestamp_provenance import NewsSourceTimestampProvenance
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow

_VINTAGE_KEY = ("news_item_key", "revision_sequence")


class MalformedNewsVintageRowError(Exception):
    """Raised when a persisted `NewsItemVintageRow`'s JSONB columns do
    not match the shape `domain.news_item_vintage` expects -- a
    malformed stored structure fails loudly here (FX-56 Section 42),
    never silently."""


class SqlAlchemyNewsRepository:
    """Implements `NewsRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Item identity / registration --------------------------------------

    async def register_source_item(
        self,
        identity: NewsSourceIdentity,
        observed_at: UtcTimestamp,
        observation_mode: NewsObservationMode,
    ) -> NewsItemRegistrationResult:
        existing_key = await self._mapping_news_item_key(identity)
        await self._session.commit()  # release the read-only transaction before mutating
        if existing_key is not None:
            return await self._already_exists_result(existing_key)

        candidate_key = mint_news_item_key(identity.source_key)
        won = await self._insert_item_and_mapping(
            identity, candidate_key, observed_at, observation_mode
        )
        if won:
            await self._session.commit()
            return NewsItemRegistrationResult(
                news_item_key=candidate_key,
                outcome=NewsItemRegistrationOutcome.CREATED,
                first_seen_at=observed_at,
                first_observation_mode=observation_mode,
            )

        # Lost the race: another session already registered this exact
        # external identity. Roll back EVERYTHING from this attempt --
        # including our own uncommitted candidate NewsItemRow insert --
        # so no orphan item can ever be observed or persist.
        await self._session.rollback()
        return await self._already_exists_result(
            await self._require_mapping_news_item_key(identity)
        )

    async def register_source_item_with_first_vintage(
        self,
        identity: NewsSourceIdentity,
        observed_at: UtcTimestamp,
        observation_mode: NewsObservationMode,
        build_vintage: Callable[[str], NewsItemVintage],
    ) -> FirstObservationResult:
        existing_key = await self._mapping_news_item_key(identity)
        await self._session.commit()  # release the read-only transaction before mutating
        if existing_key is not None:
            return FirstObservationResult(existing_key, NewsItemRegistrationOutcome.ALREADY_EXISTS)

        candidate_key = mint_news_item_key(identity.source_key)
        # Construct (and therefore fully domain-validate, e.g. a
        # non-empty headline and quarantine-reason consistency) the
        # first vintage BEFORE any database write is attempted (FX-56H
        # Section 3) -- a raising `build_vintage` leaves zero rows.
        vintage = build_vintage(candidate_key)
        _require_first_vintage_shape(vintage, observed_at, observation_mode)

        try:
            won = await self._insert_item_and_mapping(
                identity, candidate_key, observed_at, observation_mode
            )
            if not won:
                # Lost the identity race -- roll back our own candidate
                # item/vintage attempt entirely and resolve to the
                # winner, exactly like plain `register_source_item`.
                await self._session.rollback()
                existing = await self._require_mapping_news_item_key(identity)
                await self._session.commit()
                return FirstObservationResult(existing, NewsItemRegistrationOutcome.ALREADY_EXISTS)

            await self._insert_vintage_row(_vintage_row_values(vintage))
            await self._session.commit()
            return FirstObservationResult(candidate_key, NewsItemRegistrationOutcome.CREATED)
        except Exception:
            # Any failure past this point -- the vintage insert itself,
            # or anything else -- must discard the WHOLE attempt,
            # including the item/mapping that already succeeded in this
            # same uncommitted transaction (FX-56H Section 2).
            await self._session.rollback()
            raise

    async def _insert_item_and_mapping(
        self,
        identity: NewsSourceIdentity,
        candidate_key: str,
        observed_at: UtcTimestamp,
        observation_mode: NewsObservationMode,
    ) -> bool:
        """Inserts the candidate `NewsItemRow` and attempts its mapping
        insert in the CURRENT (uncommitted) transaction. Returns `True`
        if the mapping insert won the race -- the caller may now commit
        (optionally after further writes in the SAME transaction, e.g.
        a first vintage) -- or `False` if it lost, in which case the
        caller must roll back before resolving to the existing winner.
        Shared by `register_source_item` and `register_source_item_
        with_first_vintage` (FX-56H) so the identity-race handling
        cannot drift between the two."""
        await self._session.execute(
            pg_insert(NewsItemRow).values(
                news_item_key=candidate_key,
                first_seen_at=observed_at.value,
                first_observation_mode=observation_mode.value,
            )
        )
        mapping_stmt = (
            pg_insert(NewsSourceMappingRow)
            .values(
                source_key=identity.source_key,
                external_item_id=identity.external_item_id,
                news_item_key=candidate_key,
            )
            .on_conflict_do_nothing(index_elements=["source_key", "external_item_id"])
            .returning(NewsSourceMappingRow.id)
        )
        inserted_id = (await self._session.execute(mapping_stmt)).scalar_one_or_none()
        return inserted_id is not None

    async def _insert_vintage_row(self, values: dict[str, Any]) -> None:
        """A thin, separately-named wrapper around the revision-0
        insert statement -- exists so a test can monkeypatch exactly
        this one step to simulate an unexpected persistence failure
        (FX-56H's own "injected first-vintage persistence failure"
        test) without needing to fake a lower-level database error."""
        await self._session.execute(pg_insert(NewsItemVintageRow).values(values))

    async def _already_exists_result(self, news_item_key: str) -> NewsItemRegistrationResult:
        item = await self.get_item(news_item_key)
        await self._session.commit()
        assert item is not None  # a mapping must always reference a durably-committed item
        return NewsItemRegistrationResult(
            news_item_key=news_item_key,
            outcome=NewsItemRegistrationOutcome.ALREADY_EXISTS,
            first_seen_at=item.first_seen_at,
            first_observation_mode=item.first_observation_mode,
        )

    async def _mapping_news_item_key(self, identity: NewsSourceIdentity) -> str | None:
        stmt = select(NewsSourceMappingRow.news_item_key).where(
            NewsSourceMappingRow.source_key == identity.source_key,
            NewsSourceMappingRow.external_item_id == identity.external_item_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _require_mapping_news_item_key(self, identity: NewsSourceIdentity) -> str:
        key = await self._mapping_news_item_key(identity)
        assert key is not None  # the failed insert proves the mapping already exists
        return key

    async def get_item(self, news_item_key: str) -> NewsItem | None:
        stmt = select(NewsItemRow).where(NewsItemRow.news_item_key == news_item_key)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _item_to_domain(row)

    async def get_item_by_source_identity(self, identity: NewsSourceIdentity) -> NewsItem | None:
        news_item_key = await self._mapping_news_item_key(identity)
        await self._session.commit()
        if news_item_key is None:
            return None
        return await self.get_item(news_item_key)

    # --- Vintages -----------------------------------------------------------

    async def add_vintage(self, vintage: NewsItemVintage) -> NewsVintageWriteOutcome:
        stmt = (
            pg_insert(NewsItemVintageRow)
            .values(_vintage_row_values(vintage))
            .on_conflict_do_nothing(index_elements=_VINTAGE_KEY)
            .returning(NewsItemVintageRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted_id is not None:
            await self._session.commit()
            return NewsVintageWriteOutcome.INSERTED

        existing_row = await self._select_one_vintage(
            vintage.news_item_key, vintage.revision_sequence
        )
        await self._session.commit()
        assert existing_row is not None  # the failed insert proves the identity already exists
        existing = _vintage_to_domain(existing_row)
        if existing == vintage:
            return NewsVintageWriteOutcome.ALREADY_PRESENT
        raise NewsVintageConflictError(existing, vintage)

    async def _select_one_vintage(
        self, news_item_key: str, revision_sequence: int
    ) -> NewsItemVintageRow | None:
        stmt = select(NewsItemVintageRow).where(
            NewsItemVintageRow.news_item_key == news_item_key,
            NewsItemVintageRow.revision_sequence == revision_sequence,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_vintages(self, news_item_key: str) -> tuple[NewsItemVintage, ...]:
        stmt = select(NewsItemVintageRow).where(NewsItemVintageRow.news_item_key == news_item_key)
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_vintage_to_domain(row) for row in rows)

    async def latest_vintage_as_of(
        self, news_item_key: str, as_of: UtcTimestamp
    ) -> NewsItemVintage | None:
        stmt = (
            select(NewsItemVintageRow)
            .where(
                NewsItemVintageRow.news_item_key == news_item_key,
                NewsItemVintageRow.availability <= as_of.value,
            )
            .order_by(
                NewsItemVintageRow.availability.desc(),
                NewsItemVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else _vintage_to_domain(row)

    async def latest_evidence_eligible_vintage_as_of(
        self,
        news_item_key: str,
        as_of: UtcTimestamp,
        *,
        include_backfill: bool = False,
    ) -> NewsItemVintage | None:
        conditions = [
            NewsItemVintageRow.news_item_key == news_item_key,
            NewsItemVintageRow.availability <= as_of.value,
            NewsItemVintageRow.evidence_disposition
            == NewsEvidenceDisposition.EVIDENCE_ELIGIBLE.value,
        ]
        if not include_backfill:
            conditions.append(
                NewsItemVintageRow.observation_mode != NewsObservationMode.BACKFILL.value
            )
        stmt = (
            select(NewsItemVintageRow)
            .where(*conditions)
            .order_by(
                NewsItemVintageRow.availability.desc(),
                NewsItemVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else _vintage_to_domain(row)


# --- First-vintage shape guard (FX-56H) -----------------------------------


def _require_first_vintage_shape(
    vintage: NewsItemVintage,
    observed_at: UtcTimestamp,
    observation_mode: NewsObservationMode,
) -> None:
    """Defensive check that a `build_vintage` callback passed to
    `register_source_item_with_first_vintage` actually produced a
    genuine first vintage consistent with the item it will belong to
    (FX-56H Section 4) -- a caller-construction bug, not a data
    condition, so this raises `ValueError` rather than anything
    data-shaped."""
    if vintage.revision_sequence != 0:
        raise ValueError(
            f"first vintage must have revision_sequence == 0, got {vintage.revision_sequence}"
        )
    if vintage.availability != observed_at:
        raise ValueError(
            "first vintage availability must equal the item's own observed_at -- "
            f"got availability={vintage.availability!r}, observed_at={observed_at!r}"
        )
    if vintage.observation_mode != observation_mode:
        raise ValueError(
            "first vintage observation_mode must equal the item's own first_observation_mode "
            f"-- got {vintage.observation_mode!r}, expected {observation_mode!r}"
        )


# --- Domain <-> row mapping -----------------------------------------------


def _item_to_domain(row: NewsItemRow) -> NewsItem:
    return NewsItem(
        news_item_key=row.news_item_key,
        first_seen_at=UtcTimestamp(row.first_seen_at),
        first_observation_mode=NewsObservationMode(row.first_observation_mode),
    )


def _vintage_row_values(vintage: NewsItemVintage) -> dict[str, Any]:
    return {
        "news_item_key": vintage.news_item_key,
        "revision_sequence": vintage.revision_sequence,
        "availability": vintage.availability.value,
        "observation_mode": vintage.observation_mode.value,
        "headline": vintage.headline,
        "summary": vintage.summary,
        "body_text": vintage.body_text,
        "canonical_url": vintage.canonical_url,
        "authors": list(vintage.authors),
        "language": vintage.language,
        "source_content_type": vintage.source_content_type,
        "source_published_at": (
            None if vintage.source_published_at is None else vintage.source_published_at.value
        ),
        "source_updated_at": (
            None if vintage.source_updated_at is None else vintage.source_updated_at.value
        ),
        "source_timestamp_provenance": _provenance_to_json(vintage.source_timestamp_provenance),
        "source_revision_metadata": _revision_metadata_to_json(vintage.source_revision_metadata),
        "source_status": vintage.source_status.value,
        "evidence_disposition": vintage.evidence_disposition.value,
        "quarantine_reason": vintage.quarantine_reason,
    }


def _vintage_to_domain(row: NewsItemVintageRow) -> NewsItemVintage:
    return NewsItemVintage(
        news_item_key=row.news_item_key,
        revision_sequence=row.revision_sequence,
        availability=UtcTimestamp(row.availability),
        observation_mode=NewsObservationMode(row.observation_mode),
        headline=row.headline,
        source_status=NewsSourceStatus(row.source_status),
        evidence_disposition=NewsEvidenceDisposition(row.evidence_disposition),
        summary=row.summary,
        body_text=row.body_text,
        canonical_url=row.canonical_url,
        authors=_authors_from_json(row.authors),
        language=row.language,
        source_content_type=row.source_content_type,
        source_published_at=(
            None if row.source_published_at is None else UtcTimestamp(row.source_published_at)
        ),
        source_updated_at=(
            None if row.source_updated_at is None else UtcTimestamp(row.source_updated_at)
        ),
        source_timestamp_provenance=_provenance_from_json(row.source_timestamp_provenance),
        source_revision_metadata=_revision_metadata_from_json(row.source_revision_metadata),
        quarantine_reason=row.quarantine_reason,
    )


def _authors_from_json(data: object) -> tuple[str, ...]:
    if not isinstance(data, list) or not all(isinstance(entry, str) for entry in data):
        raise MalformedNewsVintageRowError(f"authors must be a list of strings, got {data!r}")
    return tuple(data)


def _provenance_to_json(
    items: tuple[NewsSourceTimestampProvenance, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "field_name": provenance.field_name,
            "raw_value": provenance.raw_value,
            "normalized_at": (
                None
                if provenance.normalized_at is None
                else provenance.normalized_at.value.isoformat()
            ),
            "normalization_note": provenance.normalization_note,
        }
        for provenance in items
    ]


def _provenance_from_json(data: object) -> tuple[NewsSourceTimestampProvenance, ...]:
    if not isinstance(data, list):
        raise MalformedNewsVintageRowError(
            f"source_timestamp_provenance must be a list, got {type(data).__name__}"
        )
    result: list[NewsSourceTimestampProvenance] = []
    for entry in data:
        if not isinstance(entry, dict):
            raise MalformedNewsVintageRowError(
                f"each source_timestamp_provenance entry must be an object, got {entry!r}"
            )
        try:
            normalized_raw = entry.get("normalized_at")
            normalized_at = (
                None if normalized_raw is None else UtcTimestamp(_parse_isoformat(normalized_raw))
            )
            result.append(
                NewsSourceTimestampProvenance(
                    field_name=entry["field_name"],
                    raw_value=entry["raw_value"],
                    normalized_at=normalized_at,
                    normalization_note=entry.get("normalization_note"),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise MalformedNewsVintageRowError(
                f"malformed source_timestamp_provenance entry: {entry!r}"
            ) from exc
    return tuple(result)


def _revision_metadata_to_json(
    items: tuple[NewsSourceRevisionFact, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "kind": fact.kind.value,
            "source_timestamp": (
                None if fact.source_timestamp is None else fact.source_timestamp.value.isoformat()
            ),
            "raw_timestamp": fact.raw_timestamp,
            "note": fact.note,
        }
        for fact in items
    ]


def _revision_metadata_from_json(data: object) -> tuple[NewsSourceRevisionFact, ...]:
    if not isinstance(data, list):
        raise MalformedNewsVintageRowError(
            f"source_revision_metadata must be a list, got {type(data).__name__}"
        )
    result: list[NewsSourceRevisionFact] = []
    for entry in data:
        if not isinstance(entry, dict):
            raise MalformedNewsVintageRowError(
                f"each source_revision_metadata entry must be an object, got {entry!r}"
            )
        try:
            source_timestamp_raw = entry.get("source_timestamp")
            source_timestamp = (
                None
                if source_timestamp_raw is None
                else UtcTimestamp(_parse_isoformat(source_timestamp_raw))
            )
            result.append(
                NewsSourceRevisionFact(
                    kind=NewsSourceRevisionKind(entry["kind"]),
                    source_timestamp=source_timestamp,
                    raw_timestamp=entry.get("raw_timestamp"),
                    note=entry.get("note"),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise MalformedNewsVintageRowError(
                f"malformed source_revision_metadata entry: {entry!r}"
            ) from exc
    return tuple(result)


def _parse_isoformat(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"expected an ISO-8601 string, got {type(value).__name__}")
    return datetime.fromisoformat(value)

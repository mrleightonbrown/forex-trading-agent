"""SQLAlchemy implementation of `SourceRegistryRepository` (FX-62).

`register_source_with_first_identity_vintage` is this module's own
atomic creating operation -- simpler than `SqlAlchemyNewsRepository.
register_source_item_with_first_vintage`'s own race handling, since a
`source_key` here is ALWAYS caller-supplied (never minted by this
repository), so there is no "lose the identity-minting race, discard
our own candidate" step: a genuinely new `source_key`'s `INSERT ...
ON CONFLICT DO NOTHING` either wins outright (in which case the FIRST
identity vintage is inserted in the SAME uncommitted transaction,
then both committed together) or loses (in which case nothing of ours
was ever written, and we simply read back the winner's already-
committed state) -- safe under Postgres's own `READ COMMITTED`
isolation for the exact same reason `SqlAlchemyNewsRepository`'s own
docstring already explains: a second session's conflicting insert
blocks on the first session's row lock until that transaction commits
or rolls back.

Every OTHER write in this module keeps the SAME idempotent `INSERT
... ON CONFLICT DO NOTHING ... RETURNING id` discipline already
established throughout this codebase -- no method here ever issues an
`UPDATE` against a source, identity-vintage, or attribution-vintage
row."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.application.ports.source_registry_repository import (
    AttributionVintageWriteResult,
    IdentityVintageWriteResult,
    IntelligenceSourceConflictError,
    SourceAttributionVintageConflictError,
    SourceIdentityVintageConflictError,
    SourceRegistrationResult,
)
from forex_agent.domain.intelligence_source import IntelligenceSource
from forex_agent.domain.intelligence_source_kind import IntelligenceSourceKind
from forex_agent.domain.source_attribution_role import SourceAttributionRole
from forex_agent.domain.source_attribution_status import SourceAttributionStatus
from forex_agent.domain.source_attribution_vintage import SourceAttributionVintage
from forex_agent.domain.source_evidence_kind import SourceEvidenceKind
from forex_agent.domain.source_identity_vintage import SourceIdentityVintage
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.intelligence_source import IntelligenceSourceRow
from forex_agent.infrastructure.db.models.source_attribution_vintage import (
    SourceAttributionVintageRow,
)
from forex_agent.infrastructure.db.models.source_identity_vintage import SourceIdentityVintageRow

_IDENTITY_VINTAGE_KEY = ("source_key", "revision_sequence")
_ATTRIBUTION_VINTAGE_KEY = ("news_item_key", "role", "revision_sequence")


class MalformedSourceRegistryRowError(Exception):
    """Raised when a persisted FX-62 row's own stored shape does not
    match what the domain layer expects -- a malformed stored
    structure fails loudly here, never silently (mirrors
    `MalformedNewsSemanticAnnotationRowError`)."""


class SqlAlchemySourceRegistryRepository:
    """Implements `SourceRegistryRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Identity -------------------------------------------------------

    async def get_source(self, source_key: str) -> IntelligenceSource | None:
        row = await self._select_one_source(source_key)
        await self._session.commit()
        return None if row is None else _source_row_to_domain(row)

    async def list_sources(self) -> tuple[IntelligenceSource, ...]:
        rows = (await self._session.execute(select(IntelligenceSourceRow))).scalars().all()
        await self._session.commit()
        return tuple(_source_row_to_domain(row) for row in rows)

    async def register_source_with_first_identity_vintage(
        self, source: IntelligenceSource, first_identity_vintage: SourceIdentityVintage
    ) -> SourceRegistrationResult:
        insert_source_stmt = (
            pg_insert(IntelligenceSourceRow)
            .values(_source_row_values(source))
            .on_conflict_do_nothing(index_elements=["source_key"])
            .returning(IntelligenceSourceRow.id)
        )
        inserted_source_id = (await self._session.execute(insert_source_stmt)).scalar_one_or_none()

        if inserted_source_id is not None:
            insert_vintage_stmt = (
                pg_insert(SourceIdentityVintageRow)
                .values(_identity_vintage_row_values(first_identity_vintage))
                .on_conflict_do_nothing(index_elements=list(_IDENTITY_VINTAGE_KEY))
                .returning(SourceIdentityVintageRow.id)
            )
            inserted_vintage_id = (
                await self._session.execute(insert_vintage_stmt)
            ).scalar_one_or_none()
            # A brand-new source_key can never already have a revision-0
            # identity vintage -- only this same winning call path could
            # ever have inserted one.
            assert inserted_vintage_id is not None
            await self._session.commit()
            return SourceRegistrationResult(created=True)

        # Lost the race (or this is a genuine idempotent retry) -- the
        # source_key already exists. Nothing of ours was ever written.
        existing_source_row = await self._select_one_source(source.source_key)
        assert existing_source_row is not None
        existing_source = _source_row_to_domain(existing_source_row)
        if existing_source.source_kind != source.source_kind:
            await self._session.commit()
            raise IntelligenceSourceConflictError(existing_source, source)

        existing_vintage_row = await self._select_one_identity_vintage(
            source.source_key, first_identity_vintage.revision_sequence
        )
        await self._session.commit()
        if existing_vintage_row is None:
            # Structurally unreachable under normal operation: every
            # committed IntelligenceSourceRow was itself inserted by
            # THIS SAME method, which always inserts its own revision-0
            # vintage in the same transaction before committing -- so a
            # source that exists without this exact vintage means a
            # caller bypassed this method entirely (e.g. inserted a
            # source row through some other path). Fails loudly rather
            # than silently fabricating a vintage that was never
            # actually written.
            raise RuntimeError(
                f"source_key={source.source_key!r} is already registered but has no "
                f"revision_sequence={first_identity_vintage.revision_sequence} identity vintage "
                "-- this registry's own invariant (every registered source always has its own "
                "first identity vintage) has been violated outside this method"
            )
        existing_vintage = _identity_vintage_row_to_domain(existing_vintage_row)
        if existing_vintage == first_identity_vintage:
            return SourceRegistrationResult(created=False)
        raise SourceIdentityVintageConflictError(existing_vintage, first_identity_vintage)

    async def latest_identity_vintage_for_source(
        self, source_key: str
    ) -> SourceIdentityVintage | None:
        stmt = (
            select(SourceIdentityVintageRow)
            .where(SourceIdentityVintageRow.source_key == source_key)
            .order_by(
                SourceIdentityVintageRow.availability.desc(),
                SourceIdentityVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else _identity_vintage_row_to_domain(row)

    async def latest_identity_vintage_as_of(
        self, source_key: str, as_of: UtcTimestamp
    ) -> SourceIdentityVintage | None:
        stmt = (
            select(SourceIdentityVintageRow)
            .where(
                SourceIdentityVintageRow.source_key == source_key,
                SourceIdentityVintageRow.availability <= as_of.value,
            )
            .order_by(
                SourceIdentityVintageRow.availability.desc(),
                SourceIdentityVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else _identity_vintage_row_to_domain(row)

    async def list_identity_vintages_for_source(
        self, source_key: str
    ) -> tuple[SourceIdentityVintage, ...]:
        stmt = select(SourceIdentityVintageRow).where(
            SourceIdentityVintageRow.source_key == source_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_identity_vintage_row_to_domain(row) for row in rows)

    async def add_identity_vintage(
        self, vintage: SourceIdentityVintage
    ) -> IdentityVintageWriteResult:
        stmt = (
            pg_insert(SourceIdentityVintageRow)
            .values(_identity_vintage_row_values(vintage))
            .on_conflict_do_nothing(index_elements=list(_IDENTITY_VINTAGE_KEY))
            .returning(SourceIdentityVintageRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted_id is not None:
            await self._session.commit()
            return IdentityVintageWriteResult(inserted=True)

        existing_row = await self._select_one_identity_vintage(
            vintage.source_key, vintage.revision_sequence
        )
        await self._session.commit()
        assert existing_row is not None
        existing = _identity_vintage_row_to_domain(existing_row)
        if existing == vintage:
            return IdentityVintageWriteResult(inserted=False)
        raise SourceIdentityVintageConflictError(existing, vintage)

    async def _select_one_source(self, source_key: str) -> IntelligenceSourceRow | None:
        stmt = select(IntelligenceSourceRow).where(IntelligenceSourceRow.source_key == source_key)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _select_one_identity_vintage(
        self, source_key: str, revision_sequence: int
    ) -> SourceIdentityVintageRow | None:
        stmt = select(SourceIdentityVintageRow).where(
            SourceIdentityVintageRow.source_key == source_key,
            SourceIdentityVintageRow.revision_sequence == revision_sequence,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    # --- Attribution ------------------------------------------------------

    async def latest_attribution_for_role(
        self, news_item_key: str, role: SourceAttributionRole
    ) -> SourceAttributionVintage | None:
        stmt = (
            select(SourceAttributionVintageRow)
            .where(
                SourceAttributionVintageRow.news_item_key == news_item_key,
                SourceAttributionVintageRow.role == role.value,
            )
            .order_by(
                SourceAttributionVintageRow.availability.desc(),
                SourceAttributionVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else _attribution_vintage_row_to_domain(row)

    async def latest_attribution_as_of(
        self, news_item_key: str, role: SourceAttributionRole, as_of: UtcTimestamp
    ) -> SourceAttributionVintage | None:
        stmt = (
            select(SourceAttributionVintageRow)
            .where(
                SourceAttributionVintageRow.news_item_key == news_item_key,
                SourceAttributionVintageRow.role == role.value,
                SourceAttributionVintageRow.availability <= as_of.value,
            )
            .order_by(
                SourceAttributionVintageRow.availability.desc(),
                SourceAttributionVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else _attribution_vintage_row_to_domain(row)

    async def list_attribution_vintages(
        self, news_item_key: str, role: SourceAttributionRole
    ) -> tuple[SourceAttributionVintage, ...]:
        stmt = select(SourceAttributionVintageRow).where(
            SourceAttributionVintageRow.news_item_key == news_item_key,
            SourceAttributionVintageRow.role == role.value,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_attribution_vintage_row_to_domain(row) for row in rows)

    async def list_latest_attributions_for_item_as_of(
        self, news_item_key: str, as_of: UtcTimestamp
    ) -> tuple[SourceAttributionVintage, ...]:
        stmt = select(SourceAttributionVintageRow).where(
            SourceAttributionVintageRow.news_item_key == news_item_key,
            SourceAttributionVintageRow.availability <= as_of.value,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()

        latest_by_role: dict[str, SourceAttributionVintageRow] = {}
        for row in rows:
            current = latest_by_role.get(row.role)
            candidate_sort_key = (row.availability, row.revision_sequence)
            if current is None or candidate_sort_key > (
                current.availability,
                current.revision_sequence,
            ):
                latest_by_role[row.role] = row
        return tuple(_attribution_vintage_row_to_domain(row) for row in latest_by_role.values())

    async def add_attribution_vintage(
        self, vintage: SourceAttributionVintage
    ) -> AttributionVintageWriteResult:
        stmt = (
            pg_insert(SourceAttributionVintageRow)
            .values(_attribution_vintage_row_values(vintage))
            .on_conflict_do_nothing(index_elements=list(_ATTRIBUTION_VINTAGE_KEY))
            .returning(SourceAttributionVintageRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted_id is not None:
            await self._session.commit()
            return AttributionVintageWriteResult(inserted=True)

        existing_row = await self._select_one_attribution_vintage(
            vintage.news_item_key, vintage.role, vintage.revision_sequence
        )
        await self._session.commit()
        assert existing_row is not None
        existing = _attribution_vintage_row_to_domain(existing_row)
        if existing == vintage:
            return AttributionVintageWriteResult(inserted=False)
        raise SourceAttributionVintageConflictError(existing, vintage)

    async def _select_one_attribution_vintage(
        self, news_item_key: str, role: SourceAttributionRole, revision_sequence: int
    ) -> SourceAttributionVintageRow | None:
        stmt = select(SourceAttributionVintageRow).where(
            SourceAttributionVintageRow.news_item_key == news_item_key,
            SourceAttributionVintageRow.role == role.value,
            SourceAttributionVintageRow.revision_sequence == revision_sequence,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()


# --- Domain <-> row mapping -----------------------------------------------


def _source_row_values(source: IntelligenceSource) -> dict[str, Any]:
    return {
        "source_key": source.source_key,
        "source_kind": source.source_kind.value,
        "registered_at": source.registered_at.value,
    }


def _source_row_to_domain(row: IntelligenceSourceRow) -> IntelligenceSource:
    try:
        kind = IntelligenceSourceKind(row.source_kind)
    except ValueError as exc:
        raise MalformedSourceRegistryRowError(
            f"malformed source_kind stored for source_key={row.source_key!r}: {row.source_kind!r}"
        ) from exc
    return IntelligenceSource(
        source_key=row.source_key,
        source_kind=kind,
        registered_at=UtcTimestamp(row.registered_at),
    )


def _identity_vintage_row_values(vintage: SourceIdentityVintage) -> dict[str, Any]:
    return {
        "source_key": vintage.source_key,
        "revision_sequence": vintage.revision_sequence,
        "availability": vintage.availability.value,
        "algorithm_version": vintage.algorithm_version,
        "display_name": vintage.display_name,
        "aliases": list(vintage.aliases),
        "authoritative_identifier": vintage.authoritative_identifier,
        "canonical_website": vintage.canonical_website,
        "evidence_kind": vintage.evidence.evidence_kind.value,
        "evidence_description": vintage.evidence.description,
        "correction_reason": vintage.correction_reason,
    }


def _identity_vintage_row_to_domain(row: SourceIdentityVintageRow) -> SourceIdentityVintage:
    aliases = row.aliases
    if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
        raise MalformedSourceRegistryRowError(f"aliases must be a list of strings, got {aliases!r}")
    try:
        evidence_kind = SourceEvidenceKind(row.evidence_kind)
    except ValueError as exc:
        raise MalformedSourceRegistryRowError(
            f"malformed evidence_kind stored for source_key={row.source_key!r}: "
            f"{row.evidence_kind!r}"
        ) from exc
    return SourceIdentityVintage(
        source_key=row.source_key,
        revision_sequence=row.revision_sequence,
        availability=UtcTimestamp(row.availability),
        algorithm_version=row.algorithm_version,
        display_name=row.display_name,
        aliases=tuple(aliases),
        authoritative_identifier=row.authoritative_identifier,
        canonical_website=row.canonical_website,
        evidence=SourceProvenanceEvidence(
            evidence_kind=evidence_kind, description=row.evidence_description
        ),
        correction_reason=row.correction_reason,
    )


def _attribution_vintage_row_values(vintage: SourceAttributionVintage) -> dict[str, Any]:
    return {
        "news_item_key": vintage.news_item_key,
        "role": vintage.role.value,
        "revision_sequence": vintage.revision_sequence,
        "availability": vintage.availability.value,
        "algorithm_version": vintage.algorithm_version,
        "status": vintage.status.value,
        "attributed_source_key": vintage.attributed_source_key,
        "evidence_basis_revision_sequence": vintage.evidence_basis_revision_sequence,
        "evidence_kind": vintage.evidence.evidence_kind.value,
        "evidence_description": vintage.evidence.description,
        "corrects_revision_sequence": vintage.corrects_revision_sequence,
    }


def _attribution_vintage_row_to_domain(
    row: SourceAttributionVintageRow,
) -> SourceAttributionVintage:
    try:
        role = SourceAttributionRole(row.role)
    except ValueError as exc:
        raise MalformedSourceRegistryRowError(
            f"malformed role stored for news_item_key={row.news_item_key!r}: {row.role!r}"
        ) from exc
    try:
        status = SourceAttributionStatus(row.status)
    except ValueError as exc:
        raise MalformedSourceRegistryRowError(
            f"malformed status stored for news_item_key={row.news_item_key!r}: {row.status!r}"
        ) from exc
    try:
        evidence_kind = SourceEvidenceKind(row.evidence_kind)
    except ValueError as exc:
        raise MalformedSourceRegistryRowError(
            f"malformed evidence_kind stored for news_item_key={row.news_item_key!r}: "
            f"{row.evidence_kind!r}"
        ) from exc
    return SourceAttributionVintage(
        news_item_key=row.news_item_key,
        role=role,
        revision_sequence=row.revision_sequence,
        availability=UtcTimestamp(row.availability),
        algorithm_version=row.algorithm_version,
        status=status,
        attributed_source_key=row.attributed_source_key,
        evidence_basis_revision_sequence=row.evidence_basis_revision_sequence,
        evidence=SourceProvenanceEvidence(
            evidence_kind=evidence_kind, description=row.evidence_description
        ),
        corrects_revision_sequence=row.corrects_revision_sequence,
    )

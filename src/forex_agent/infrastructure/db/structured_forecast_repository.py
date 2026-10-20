"""SQLAlchemy implementation of `StructuredForecastRepository` (FX-64).

`register_claim_with_first_vintage` mirrors `SqlAlchemySourceRegistry
Repository.register_source_with_first_identity_vintage`'s own atomic
pattern exactly -- `claim_key` is always caller-supplied (never minted
by this repository), so there is no identity-minting race: a genuinely
new claim's `INSERT ... ON CONFLICT DO NOTHING` either wins outright
(in which case the FIRST vintage is inserted in the SAME uncommitted
transaction, then both committed together) or loses (in which case we
simply read back the winner's already-committed state).

Every value object (`ForecastTargetPeriod`/`ForecastAttribution`/
`ForecastEvidenceReference`) is flattened onto/reassembled from the
ONE `StructuredForecastVintageRow`, mirroring FX-62's own flattening
convention."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.application.ports.structured_forecast_repository import (
    ForecastClaimRegistrationResult,
    ForecastVintageWriteResult,
)
from forex_agent.domain.forecast_attribution import ForecastAttribution
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_claim import ForecastClaim
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.forecast_claim import ForecastClaimRow
from forex_agent.infrastructure.db.models.structured_forecast_vintage import (
    StructuredForecastVintageRow,
)

_VINTAGE_KEY = ("claim_key", "revision_sequence")


class MalformedStructuredForecastRowError(Exception):
    """Raised if a stored row's own enum-shaped string does not match
    any known domain enum member -- a data-integrity defect, never
    silently coerced to a default."""

    def __init__(self, field: str, value: str) -> None:
        self.field = field
        self.value = value
        super().__init__(f"stored structured_forecast_vintages.{field}={value!r} is unknown")


class SqlAlchemyStructuredForecastRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_claim(self, claim_key: str) -> ForecastClaim | None:
        # FX-67: read-only -- no commit (Section 16's own "read-only
        # repository methods must not commit unrelated pending work"
        # rule; this pre-existing FX-64 method is now also called
        # mid-call by FX-67's own inspection use cases' peers).
        stmt = select(ForecastClaimRow).where(ForecastClaimRow.claim_key == claim_key)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return (
            None if row is None else ForecastClaim(row.claim_key, UtcTimestamp(row.registered_at))
        )

    async def register_claim_with_first_vintage(
        self, claim: ForecastClaim, first_vintage: StructuredForecastVintage
    ) -> ForecastClaimRegistrationResult:
        insert_claim_stmt = (
            pg_insert(ForecastClaimRow)
            .values(claim_key=claim.claim_key, registered_at=claim.registered_at.value)
            .on_conflict_do_nothing(index_elements=["claim_key"])
            .returning(ForecastClaimRow.id)
        )
        inserted_id = (await self._session.execute(insert_claim_stmt)).scalar_one_or_none()
        if inserted_id is None:
            await self._session.rollback()
            return ForecastClaimRegistrationResult(created=False)

        await self._session.execute(
            pg_insert(StructuredForecastVintageRow).values(_vintage_row_values(first_vintage))
        )
        await self._session.commit()
        return ForecastClaimRegistrationResult(created=True)

    async def add_vintage(self, vintage: StructuredForecastVintage) -> ForecastVintageWriteResult:
        stmt = (
            pg_insert(StructuredForecastVintageRow)
            .values(_vintage_row_values(vintage))
            .on_conflict_do_nothing(index_elements=list(_VINTAGE_KEY))
            .returning(StructuredForecastVintageRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return ForecastVintageWriteResult(inserted=inserted_id is not None)

    async def list_vintages_for_claim(
        self, claim_key: str
    ) -> tuple[StructuredForecastVintage, ...]:
        # FX-67: read-only -- see `get_claim`'s own note.
        stmt = select(StructuredForecastVintageRow).where(
            StructuredForecastVintageRow.claim_key == claim_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_row_to_domain(row) for row in rows)

    async def latest_vintage_for_claim(self, claim_key: str) -> StructuredForecastVintage | None:
        return await self._select_latest([StructuredForecastVintageRow.claim_key == claim_key])

    async def latest_production_observed_vintage_as_of(
        self, claim_key: str, as_of: UtcTimestamp
    ) -> StructuredForecastVintage | None:
        return await self._select_latest(
            [
                StructuredForecastVintageRow.claim_key == claim_key,
                StructuredForecastVintageRow.provenance_mode
                == ForecastProvenanceMode.PRODUCTION_OBSERVED.value,
                StructuredForecastVintageRow.availability <= as_of.value,
            ]
        )

    async def latest_vintage_as_of_for_research(
        self, claim_key: str, research_as_of: UtcTimestamp
    ) -> StructuredForecastVintage | None:
        return await self._select_latest(
            [
                StructuredForecastVintageRow.claim_key == claim_key,
                StructuredForecastVintageRow.availability <= research_as_of.value,
            ]
        )

    async def list_production_observed_claims_as_of(
        self,
        as_of: UtcTimestamp,
        *,
        target_key: str | None = None,
        window_start: UtcTimestamp | None = None,
        window_end: UtcTimestamp | None = None,
    ) -> tuple[StructuredForecastVintage, ...]:
        conditions = [
            StructuredForecastVintageRow.provenance_mode
            == ForecastProvenanceMode.PRODUCTION_OBSERVED.value,
            StructuredForecastVintageRow.availability <= as_of.value,
        ]
        if target_key is not None:
            conditions.append(StructuredForecastVintageRow.target_key == target_key)
        if window_start is not None:
            conditions.append(StructuredForecastVintageRow.availability >= window_start.value)
        if window_end is not None:
            conditions.append(StructuredForecastVintageRow.availability <= window_end.value)

        # FX-67: read-only -- see `get_claim`'s own note.
        stmt = select(StructuredForecastVintageRow).where(*conditions)
        rows = (await self._session.execute(stmt)).scalars().all()

        latest_by_claim: dict[str, StructuredForecastVintageRow] = {}
        for row in rows:
            current = latest_by_claim.get(row.claim_key)
            candidate_sort_key = (row.availability, row.revision_sequence)
            if current is None or candidate_sort_key > (
                current.availability,
                current.revision_sequence,
            ):
                latest_by_claim[row.claim_key] = row
        return tuple(_row_to_domain(row) for row in latest_by_claim.values())

    async def _select_latest(
        self, conditions: list[ColumnElement[bool]]
    ) -> StructuredForecastVintage | None:
        stmt = (
            select(StructuredForecastVintageRow)
            .where(*conditions)
            .order_by(
                StructuredForecastVintageRow.availability.desc(),
                StructuredForecastVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        # FX-67: read-only -- see `get_claim`'s own note.
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_domain(row)


def _vintage_row_values(vintage: StructuredForecastVintage) -> dict[str, object]:
    attribution = vintage.attribution
    evidence = vintage.evidence
    period = vintage.target_period
    return {
        "claim_key": vintage.claim_key,
        "revision_sequence": vintage.revision_sequence,
        "availability": vintage.availability.value,
        "algorithm_version": vintage.algorithm_version,
        "forecast_type": vintage.forecast_type.value,
        "target_key": vintage.target_key,
        "target_period_kind": period.period_kind.value,
        "calendar_year": period.calendar_year,
        "calendar_quarter": period.calendar_quarter,
        "calendar_month": period.calendar_month,
        "specific_date": period.specific_date.value if period.specific_date else None,
        "policy_meeting_identifier": period.policy_meeting_identifier,
        "numeric_value": vintage.numeric_value,
        "unit": vintage.unit,
        "categorical_outcome": vintage.categorical_outcome,
        "attribution_kind": attribution.kind.value,
        "publisher_source_key": attribution.publisher_source_key,
        "forecaster_source_key": attribution.forecaster_source_key,
        "anonymous_respondent_id": attribution.anonymous_respondent_id,
        "provenance_mode": vintage.provenance_mode.value,
        "evidence_kind": evidence.evidence_kind.value,
        "evidence_description": evidence.description,
        "news_item_key": evidence.news_item_key,
        "basis_revision_sequence": evidence.basis_revision_sequence,
        "document_identifier": evidence.document_identifier,
        "document_locator": evidence.document_locator,
        "official_reference_url": evidence.official_reference_url,
        "content_fingerprint": evidence.content_fingerprint,
        "publisher_declared_publication_at": (
            evidence.publisher_declared_publication_at.value
            if evidence.publisher_declared_publication_at
            else None
        ),
        "original_publication_at": (
            vintage.original_publication_at.value if vintage.original_publication_at else None
        ),
        "correction_reason": vintage.correction_reason,
    }


def _row_to_domain(row: StructuredForecastVintageRow) -> StructuredForecastVintage:
    try:
        forecast_type = ForecastType(row.forecast_type)
    except ValueError as exc:
        raise MalformedStructuredForecastRowError("forecast_type", row.forecast_type) from exc
    try:
        period_kind = ForecastTargetPeriodKind(row.target_period_kind)
    except ValueError as exc:
        raise MalformedStructuredForecastRowError(
            "target_period_kind", row.target_period_kind
        ) from exc
    try:
        attribution_kind = ForecastAttributionKind(row.attribution_kind)
    except ValueError as exc:
        raise MalformedStructuredForecastRowError("attribution_kind", row.attribution_kind) from exc
    try:
        provenance_mode = ForecastProvenanceMode(row.provenance_mode)
    except ValueError as exc:
        raise MalformedStructuredForecastRowError("provenance_mode", row.provenance_mode) from exc
    try:
        evidence_kind = ForecastEvidenceKind(row.evidence_kind)
    except ValueError as exc:
        raise MalformedStructuredForecastRowError("evidence_kind", row.evidence_kind) from exc

    def _dt(value: datetime | None) -> UtcTimestamp | None:
        return None if value is None else UtcTimestamp(value)

    period = ForecastTargetPeriod(
        period_kind=period_kind,
        calendar_year=row.calendar_year,
        calendar_quarter=row.calendar_quarter,
        calendar_month=row.calendar_month,
        specific_date=_dt(row.specific_date),
        policy_meeting_identifier=row.policy_meeting_identifier,
    )
    attribution = ForecastAttribution(
        kind=attribution_kind,
        publisher_source_key=row.publisher_source_key,
        forecaster_source_key=row.forecaster_source_key,
        anonymous_respondent_id=row.anonymous_respondent_id,
    )
    evidence = ForecastEvidenceReference(
        evidence_kind=evidence_kind,
        description=row.evidence_description,
        news_item_key=row.news_item_key,
        basis_revision_sequence=row.basis_revision_sequence,
        document_identifier=row.document_identifier,
        document_locator=row.document_locator,
        official_reference_url=row.official_reference_url,
        content_fingerprint=row.content_fingerprint,
        publisher_declared_publication_at=_dt(row.publisher_declared_publication_at),
    )
    return StructuredForecastVintage(
        claim_key=row.claim_key,
        revision_sequence=row.revision_sequence,
        availability=UtcTimestamp(row.availability),
        algorithm_version=row.algorithm_version,
        forecast_type=forecast_type,
        target_key=row.target_key,
        target_period=period,
        attribution=attribution,
        provenance_mode=provenance_mode,
        evidence=evidence,
        numeric_value=Decimal(row.numeric_value) if row.numeric_value is not None else None,
        unit=row.unit,
        categorical_outcome=row.categorical_outcome,
        original_publication_at=_dt(row.original_publication_at),
        correction_reason=row.correction_reason,
    )

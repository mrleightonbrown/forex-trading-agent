"""SQLAlchemy implementation of `ForecastOutcomeRepository` (FX-65).
Mirrors `SqlAlchemyStructuredForecastRepository`'s own flattening and
idempotent-insert conventions exactly."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.application.ports.forecast_outcome_repository import (
    ForecastOutcomeDefinitionWriteResult,
    ForecastOutcomeVintageWriteResult,
)
from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_outcome_definition import ForecastOutcomeDefinition
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.outcome_vintage_selection_policy import OutcomeVintageSelectionPolicy
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.forecast_outcome_definition import (
    ForecastOutcomeDefinitionRow,
)
from forex_agent.infrastructure.db.models.forecast_outcome_vintage import ForecastOutcomeVintageRow

_DEFINITION_KEY = ("definition_key", "version_sequence")
_VINTAGE_KEY = ("outcome_key", "revision_sequence")


class MalformedForecastOutcomeRowError(Exception):
    def __init__(self, field: str, value: str) -> None:
        self.field = field
        self.value = value
        super().__init__(f"stored forecast_outcome row {field}={value!r} is unknown")


def _dt(value: datetime | None) -> UtcTimestamp | None:
    return None if value is None else UtcTimestamp(value)


class SqlAlchemyForecastOutcomeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_outcome_definition(
        self, definition_key: str
    ) -> ForecastOutcomeDefinition | None:
        stmt = (
            select(ForecastOutcomeDefinitionRow)
            .where(ForecastOutcomeDefinitionRow.definition_key == definition_key)
            .order_by(ForecastOutcomeDefinitionRow.version_sequence.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else _definition_row_to_domain(row)

    async def list_outcome_definition_versions(
        self, definition_key: str
    ) -> tuple[ForecastOutcomeDefinition, ...]:
        stmt = select(ForecastOutcomeDefinitionRow).where(
            ForecastOutcomeDefinitionRow.definition_key == definition_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_definition_row_to_domain(row) for row in rows)

    async def add_outcome_definition_version(
        self, definition: ForecastOutcomeDefinition
    ) -> ForecastOutcomeDefinitionWriteResult:
        stmt = (
            pg_insert(ForecastOutcomeDefinitionRow)
            .values(_definition_row_values(definition))
            .on_conflict_do_nothing(index_elements=list(_DEFINITION_KEY))
            .returning(ForecastOutcomeDefinitionRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return ForecastOutcomeDefinitionWriteResult(inserted=inserted_id is not None)

    async def latest_outcome_vintage(self, outcome_key: str) -> ForecastOutcomeVintage | None:
        stmt = (
            select(ForecastOutcomeVintageRow)
            .where(ForecastOutcomeVintageRow.outcome_key == outcome_key)
            .order_by(
                ForecastOutcomeVintageRow.availability.desc(),
                ForecastOutcomeVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else _vintage_row_to_domain(row)

    async def list_vintages_for_outcome(
        self, outcome_key: str
    ) -> tuple[ForecastOutcomeVintage, ...]:
        stmt = select(ForecastOutcomeVintageRow).where(
            ForecastOutcomeVintageRow.outcome_key == outcome_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_vintage_row_to_domain(row) for row in rows)

    async def add_outcome_vintage(
        self, vintage: ForecastOutcomeVintage
    ) -> ForecastOutcomeVintageWriteResult:
        stmt = (
            pg_insert(ForecastOutcomeVintageRow)
            .values(_vintage_row_values(vintage))
            .on_conflict_do_nothing(index_elements=list(_VINTAGE_KEY))
            .returning(ForecastOutcomeVintageRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return ForecastOutcomeVintageWriteResult(inserted=inserted_id is not None)


def _definition_row_values(definition: ForecastOutcomeDefinition) -> dict[str, object]:
    return {
        "definition_key": definition.definition_key,
        "version_sequence": definition.version_sequence,
        "target_key": definition.target_key,
        "outcome_type": definition.outcome_type.value,
        "provider_source_key": definition.provider_source_key,
        "required_source_series_identifier": definition.required_source_series_identifier,
        "outcome_vintage_selection_policy": definition.outcome_vintage_selection_policy.value,
        "availability": definition.availability.value,
        "supporting_definition_reference": definition.supporting_definition_reference,
        "correction_reason": definition.correction_reason,
    }


def _definition_row_to_domain(row: ForecastOutcomeDefinitionRow) -> ForecastOutcomeDefinition:
    try:
        outcome_type = ForecastType(row.outcome_type)
    except ValueError as exc:
        raise MalformedForecastOutcomeRowError("outcome_type", row.outcome_type) from exc
    try:
        policy = OutcomeVintageSelectionPolicy(row.outcome_vintage_selection_policy)
    except ValueError as exc:
        raise MalformedForecastOutcomeRowError(
            "outcome_vintage_selection_policy", row.outcome_vintage_selection_policy
        ) from exc
    return ForecastOutcomeDefinition(
        definition_key=row.definition_key,
        version_sequence=row.version_sequence,
        target_key=row.target_key,
        outcome_type=outcome_type,
        provider_source_key=row.provider_source_key,
        required_source_series_identifier=row.required_source_series_identifier,
        outcome_vintage_selection_policy=policy,
        availability=UtcTimestamp(row.availability),
        supporting_definition_reference=row.supporting_definition_reference,
        correction_reason=row.correction_reason,
    )


def _vintage_row_values(vintage: ForecastOutcomeVintage) -> dict[str, object]:
    evidence = vintage.evidence
    period = vintage.target_period
    review = vintage.authentication_review
    return {
        "outcome_key": vintage.outcome_key,
        "revision_sequence": vintage.revision_sequence,
        "definition_key": vintage.definition_key,
        "definition_version_sequence": vintage.definition_version_sequence,
        "availability": vintage.availability.value,
        "target_period_kind": period.period_kind.value,
        "calendar_year": period.calendar_year,
        "calendar_quarter": period.calendar_quarter,
        "calendar_month": period.calendar_month,
        "specific_date": period.specific_date.value if period.specific_date else None,
        "policy_meeting_identifier": period.policy_meeting_identifier,
        "outcome_type": vintage.outcome_type.value,
        "numeric_value": vintage.numeric_value,
        "unit": vintage.unit,
        "categorical_outcome": vintage.categorical_outcome,
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
        "reviewed_by": review.reviewed_by,
        "review_method": review.review_method,
        "reviewed_at": review.reviewed_at.value,
        "corroboration_reference": review.corroboration_reference,
        "provenance_mode": vintage.provenance_mode.value,
        "provider_release_identifier": vintage.provider_release_identifier,
        "provider_published_at": (
            vintage.provider_published_at.value if vintage.provider_published_at else None
        ),
        "content_integrity_reference": vintage.content_integrity_reference,
        "correction_reason": vintage.correction_reason,
    }


def _vintage_row_to_domain(row: ForecastOutcomeVintageRow) -> ForecastOutcomeVintage:
    try:
        outcome_type = ForecastType(row.outcome_type)
    except ValueError as exc:
        raise MalformedForecastOutcomeRowError("outcome_type", row.outcome_type) from exc
    try:
        period_kind = ForecastTargetPeriodKind(row.target_period_kind)
    except ValueError as exc:
        raise MalformedForecastOutcomeRowError(
            "target_period_kind", row.target_period_kind
        ) from exc
    try:
        evidence_kind = ForecastEvidenceKind(row.evidence_kind)
    except ValueError as exc:
        raise MalformedForecastOutcomeRowError("evidence_kind", row.evidence_kind) from exc
    try:
        provenance_mode = ForecastProvenanceMode(row.provenance_mode)
    except ValueError as exc:
        raise MalformedForecastOutcomeRowError("provenance_mode", row.provenance_mode) from exc

    period = ForecastTargetPeriod(
        period_kind=period_kind,
        calendar_year=row.calendar_year,
        calendar_quarter=row.calendar_quarter,
        calendar_month=row.calendar_month,
        specific_date=_dt(row.specific_date),
        policy_meeting_identifier=row.policy_meeting_identifier,
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
    review = EvidenceAuthenticationReview(
        reviewed_by=row.reviewed_by,
        review_method=row.review_method,
        reviewed_at=UtcTimestamp(row.reviewed_at),
        corroboration_reference=row.corroboration_reference,
    )
    return ForecastOutcomeVintage(
        outcome_key=row.outcome_key,
        revision_sequence=row.revision_sequence,
        definition_key=row.definition_key,
        definition_version_sequence=row.definition_version_sequence,
        availability=UtcTimestamp(row.availability),
        target_period=period,
        outcome_type=outcome_type,
        evidence=evidence,
        authentication_review=review,
        provenance_mode=provenance_mode,
        numeric_value=Decimal(row.numeric_value) if row.numeric_value is not None else None,
        unit=row.unit,
        categorical_outcome=row.categorical_outcome,
        provider_release_identifier=row.provider_release_identifier,
        provider_published_at=_dt(row.provider_published_at),
        content_integrity_reference=row.content_integrity_reference,
        correction_reason=row.correction_reason,
    )

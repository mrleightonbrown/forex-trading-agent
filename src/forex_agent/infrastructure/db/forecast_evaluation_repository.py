"""SQLAlchemy implementation of `ForecastEvaluationRepository` (FX-65).
Mirrors `SqlAlchemyStructuredForecastRepository`'s own `_select_latest`
and production-vs-research filtering conventions exactly."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.application.ports.forecast_evaluation_repository import (
    ForecastEvaluationProtocolWriteResult,
    StructuredForecastEvaluationWriteResult,
)
from forex_agent.domain.categorical_evaluation_result import CategoricalEvaluationResult
from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol
from forex_agent.domain.forecast_evaluation_result import ForecastEvaluationResult
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.outcome_vintage_selection_policy import OutcomeVintageSelectionPolicy
from forex_agent.domain.structured_forecast_evaluation_vintage import (
    StructuredForecastEvaluationVintage,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.forecast_evaluation_protocol import (
    ForecastEvaluationProtocolRow,
)
from forex_agent.infrastructure.db.models.structured_forecast_evaluation_vintage import (
    StructuredForecastEvaluationVintageRow,
)

_PROTOCOL_KEY = ("protocol_key", "version_sequence")
_EVALUATION_KEY = ("evaluation_key", "revision_sequence")


class MalformedForecastEvaluationRowError(Exception):
    def __init__(self, field: str, value: str) -> None:
        self.field = field
        self.value = value
        super().__init__(f"stored forecast_evaluation row {field}={value!r} is unknown")


def _dt(value: datetime | None) -> UtcTimestamp | None:
    return None if value is None else UtcTimestamp(value)


def _latest_per_key(
    rows: Sequence[StructuredForecastEvaluationVintageRow],
) -> list[StructuredForecastEvaluationVintageRow]:
    """Reduces `rows` (already filtered by the caller to whichever
    `availability` bound applies) to one row per `evaluation_key` --
    the latest by `(availability, revision_sequence)` among the rows
    actually passed in. Shared by `list_latest_evaluations_for_
    protocol` (unbounded) and `list_latest_evaluations_for_protocol_
    as_of` (FX-66H H1's own PIT-bounded selection) so the two can
    never silently diverge in HOW "latest" is computed, only in WHICH
    rows are eligible to compete for it."""
    latest_by_key: dict[str, StructuredForecastEvaluationVintageRow] = {}
    for row in rows:
        current = latest_by_key.get(row.evaluation_key)
        candidate_sort_key = (row.availability, row.revision_sequence)
        if current is None or candidate_sort_key > (
            current.availability,
            current.revision_sequence,
        ):
            latest_by_key[row.evaluation_key] = row
    return list(latest_by_key.values())


class SqlAlchemyForecastEvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_protocol_version(self, protocol_key: str) -> ForecastEvaluationProtocol | None:
        # FX-67: read-only -- no commit (Section 16's own "read-only
        # repository methods must not commit unrelated pending work"
        # rule; this pre-existing FX-65 method is now also called
        # mid-call by `GetForecastPerformanceInspection`).
        stmt = (
            select(ForecastEvaluationProtocolRow)
            .where(ForecastEvaluationProtocolRow.protocol_key == protocol_key)
            .order_by(ForecastEvaluationProtocolRow.version_sequence.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _protocol_row_to_domain(row)

    async def list_protocol_versions(
        self, protocol_key: str
    ) -> tuple[ForecastEvaluationProtocol, ...]:
        # FX-67: read-only -- see sibling method above.
        stmt = select(ForecastEvaluationProtocolRow).where(
            ForecastEvaluationProtocolRow.protocol_key == protocol_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_protocol_row_to_domain(row) for row in rows)

    async def add_protocol_version(
        self, protocol: ForecastEvaluationProtocol
    ) -> ForecastEvaluationProtocolWriteResult:
        stmt = (
            pg_insert(ForecastEvaluationProtocolRow)
            .values(_protocol_row_values(protocol))
            .on_conflict_do_nothing(index_elements=list(_PROTOCOL_KEY))
            .returning(ForecastEvaluationProtocolRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return ForecastEvaluationProtocolWriteResult(inserted=inserted_id is not None)

    async def latest_evaluation_vintage(
        self, evaluation_key: str
    ) -> StructuredForecastEvaluationVintage | None:
        return await self._select_latest(
            [StructuredForecastEvaluationVintageRow.evaluation_key == evaluation_key]
        )

    async def list_vintages_for_evaluation(
        self, evaluation_key: str
    ) -> tuple[StructuredForecastEvaluationVintage, ...]:
        # FX-67: read-only -- see `latest_protocol_version`'s own note.
        stmt = select(StructuredForecastEvaluationVintageRow).where(
            StructuredForecastEvaluationVintageRow.evaluation_key == evaluation_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_evaluation_row_to_domain(row) for row in rows)

    async def add_evaluation_vintage(
        self, vintage: StructuredForecastEvaluationVintage
    ) -> StructuredForecastEvaluationWriteResult:
        stmt = (
            pg_insert(StructuredForecastEvaluationVintageRow)
            .values(_evaluation_row_values(vintage))
            .on_conflict_do_nothing(index_elements=list(_EVALUATION_KEY))
            .returning(StructuredForecastEvaluationVintageRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return StructuredForecastEvaluationWriteResult(inserted=inserted_id is not None)

    async def latest_production_observed_evaluation_as_of(
        self, evaluation_key: str, as_of: UtcTimestamp
    ) -> StructuredForecastEvaluationVintage | None:
        return await self._select_latest(
            [
                StructuredForecastEvaluationVintageRow.evaluation_key == evaluation_key,
                StructuredForecastEvaluationVintageRow.evaluation_mode
                == ForecastProvenanceMode.PRODUCTION_OBSERVED.value,
                StructuredForecastEvaluationVintageRow.availability <= as_of.value,
            ]
        )

    async def latest_evaluation_as_of_for_research(
        self, evaluation_key: str, research_as_of: UtcTimestamp
    ) -> StructuredForecastEvaluationVintage | None:
        return await self._select_latest(
            [
                StructuredForecastEvaluationVintageRow.evaluation_key == evaluation_key,
                StructuredForecastEvaluationVintageRow.availability <= research_as_of.value,
            ]
        )

    async def list_latest_evaluations_for_protocol(
        self, protocol_key: str, evaluation_mode: ForecastProvenanceMode
    ) -> tuple[StructuredForecastEvaluationVintage, ...]:
        # FX-66H.1 (H3/F66-06): genuinely READ-ONLY -- no commit. A
        # commit here would prematurely flush any UNRELATED pending
        # write the caller's own shared session is still holding
        # (e.g. mid-`BuildForecastPerformancePopulationAsOf`/`Record
        # ForecastPerformanceSnapshot`), exactly the FX-65H.3 (H2)
        # lesson: "a read-only repository lookup must not commit
        # unrelated pending writes in the caller's session."
        stmt = select(StructuredForecastEvaluationVintageRow).where(
            StructuredForecastEvaluationVintageRow.protocol_key == protocol_key,
            StructuredForecastEvaluationVintageRow.evaluation_mode == evaluation_mode.value,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_evaluation_row_to_domain(row) for row in _latest_per_key(rows))

    async def list_latest_evaluations_for_protocol_as_of(
        self, protocol_key: str, evaluation_mode: ForecastProvenanceMode, as_of: UtcTimestamp
    ) -> tuple[StructuredForecastEvaluationVintage, ...]:
        # FX-66H.1 (H3/F66-06): read-only -- see sibling method above.
        stmt = select(StructuredForecastEvaluationVintageRow).where(
            StructuredForecastEvaluationVintageRow.protocol_key == protocol_key,
            StructuredForecastEvaluationVintageRow.evaluation_mode == evaluation_mode.value,
            StructuredForecastEvaluationVintageRow.availability <= as_of.value,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_evaluation_row_to_domain(row) for row in _latest_per_key(rows))

    async def _select_latest(
        self, conditions: list[ColumnElement[bool]]
    ) -> StructuredForecastEvaluationVintage | None:
        stmt = (
            select(StructuredForecastEvaluationVintageRow)
            .where(*conditions)
            .order_by(
                StructuredForecastEvaluationVintageRow.availability.desc(),
                StructuredForecastEvaluationVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        # FX-67: read-only -- see `latest_protocol_version`'s own note.
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _evaluation_row_to_domain(row)


def _protocol_row_values(protocol: ForecastEvaluationProtocol) -> dict[str, object]:
    return {
        "protocol_key": protocol.protocol_key,
        "version_sequence": protocol.version_sequence,
        "supported_forecast_type": protocol.supported_forecast_type.value,
        "target_key": protocol.target_key,
        "outcome_definition_key": protocol.outcome_definition_key,
        "outcome_definition_version_sequence": protocol.outcome_definition_version_sequence,
        "outcome_vintage_selection_policy": protocol.outcome_vintage_selection_policy.value,
        "fixed_outcome_revision_sequence": protocol.fixed_outcome_revision_sequence,
        "metric": protocol.metric.value,
        "availability": protocol.availability.value,
        "rationale": protocol.rationale,
        "correction_reason": protocol.correction_reason,
    }


def _protocol_row_to_domain(row: ForecastEvaluationProtocolRow) -> ForecastEvaluationProtocol:
    try:
        forecast_type = ForecastType(row.supported_forecast_type)
    except ValueError as exc:
        raise MalformedForecastEvaluationRowError(
            "supported_forecast_type", row.supported_forecast_type
        ) from exc
    try:
        policy = OutcomeVintageSelectionPolicy(row.outcome_vintage_selection_policy)
    except ValueError as exc:
        raise MalformedForecastEvaluationRowError(
            "outcome_vintage_selection_policy", row.outcome_vintage_selection_policy
        ) from exc
    try:
        metric = ForecastEvaluationMetric(row.metric)
    except ValueError as exc:
        raise MalformedForecastEvaluationRowError("metric", row.metric) from exc
    return ForecastEvaluationProtocol(
        protocol_key=row.protocol_key,
        version_sequence=row.version_sequence,
        supported_forecast_type=forecast_type,
        target_key=row.target_key,
        outcome_definition_key=row.outcome_definition_key,
        outcome_definition_version_sequence=row.outcome_definition_version_sequence,
        outcome_vintage_selection_policy=policy,
        metric=metric,
        availability=UtcTimestamp(row.availability),
        rationale=row.rationale,
        fixed_outcome_revision_sequence=row.fixed_outcome_revision_sequence,
        correction_reason=row.correction_reason,
    )


def _evaluation_row_values(vintage: StructuredForecastEvaluationVintage) -> dict[str, object]:
    result = vintage.result
    review = vintage.forecast_authentication_review
    return {
        "evaluation_key": vintage.evaluation_key,
        "revision_sequence": vintage.revision_sequence,
        "forecast_claim_key": vintage.forecast_claim_key,
        "forecast_revision_sequence": vintage.forecast_revision_sequence,
        "protocol_key": vintage.protocol_key,
        "protocol_version_sequence": vintage.protocol_version_sequence,
        "outcome_definition_key": vintage.outcome_definition_key,
        "outcome_definition_version_sequence": vintage.outcome_definition_version_sequence,
        "outcome_key": vintage.outcome_key,
        "outcome_revision_sequence": vintage.outcome_revision_sequence,
        "evaluation_mode": vintage.evaluation_mode.value,
        "algorithm_version": vintage.algorithm_version,
        "availability": vintage.availability.value,
        "metric": result.metric.value,
        "signed_error": result.signed_error,
        "absolute_error": result.absolute_error,
        "result_unit": result.unit,
        "categorical_result": result.categorical_result.value
        if result.categorical_result
        else None,
        "forecast_reviewed_by": review.reviewed_by,
        "forecast_review_method": review.review_method,
        "forecast_reviewed_at": review.reviewed_at.value,
        "forecast_corroboration_reference": review.corroboration_reference,
        "correction_reason": vintage.correction_reason,
    }


def _evaluation_row_to_domain(
    row: StructuredForecastEvaluationVintageRow,
) -> StructuredForecastEvaluationVintage:
    try:
        evaluation_mode = ForecastProvenanceMode(row.evaluation_mode)
    except ValueError as exc:
        raise MalformedForecastEvaluationRowError("evaluation_mode", row.evaluation_mode) from exc
    try:
        metric = ForecastEvaluationMetric(row.metric)
    except ValueError as exc:
        raise MalformedForecastEvaluationRowError("metric", row.metric) from exc

    categorical_result = (
        CategoricalEvaluationResult(row.categorical_result) if row.categorical_result else None
    )
    result = ForecastEvaluationResult(
        metric=metric,
        signed_error=Decimal(row.signed_error) if row.signed_error is not None else None,
        absolute_error=Decimal(row.absolute_error) if row.absolute_error is not None else None,
        unit=row.result_unit,
        categorical_result=categorical_result,
    )
    review = EvidenceAuthenticationReview(
        reviewed_by=row.forecast_reviewed_by,
        review_method=row.forecast_review_method,
        reviewed_at=UtcTimestamp(row.forecast_reviewed_at),
        corroboration_reference=row.forecast_corroboration_reference,
    )
    return StructuredForecastEvaluationVintage(
        evaluation_key=row.evaluation_key,
        revision_sequence=row.revision_sequence,
        forecast_claim_key=row.forecast_claim_key,
        forecast_revision_sequence=row.forecast_revision_sequence,
        protocol_key=row.protocol_key,
        protocol_version_sequence=row.protocol_version_sequence,
        outcome_definition_key=row.outcome_definition_key,
        outcome_definition_version_sequence=row.outcome_definition_version_sequence,
        outcome_key=row.outcome_key,
        outcome_revision_sequence=row.outcome_revision_sequence,
        evaluation_mode=evaluation_mode,
        algorithm_version=row.algorithm_version,
        availability=UtcTimestamp(row.availability),
        result=result,
        forecast_authentication_review=review,
        correction_reason=row.correction_reason,
    )

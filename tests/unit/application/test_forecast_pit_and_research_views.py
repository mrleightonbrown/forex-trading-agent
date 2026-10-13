"""FX-64 Section 7/17.C: tests for `GetForecastClaimAsOf`, `ListForecast
ClaimsAsOf`, and `GetRetrospectiveForecastResearchView` -- the single
most important architectural feature of this story: production PIT
and retrospective research are separate dimensions, with NO implicit
fallback from one to the other."""

from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.application.use_cases.get_forecast_claim_as_of import (
    ForecastClaimResolution,
    GetForecastClaimAsOf,
)
from forex_agent.application.use_cases.get_retrospective_forecast_research_view import (
    GetRetrospectiveForecastResearchView,
)
from forex_agent.application.use_cases.list_forecast_claims_as_of import ListForecastClaimsAsOf
from forex_agent.application.use_cases.record_structured_forecast import RecordStructuredForecast
from forex_agent.application.use_cases.validate_structured_forecast_candidate import (
    StructuredForecastCandidate,
)
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.structured_forecast_repository import FakeStructuredForecastRepository


def _ts(year: int, month: int = 1, day: int = 1) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, tzinfo=UTC))


def _candidate(**overrides: object) -> StructuredForecastCandidate:
    defaults: dict[str, object] = {
        "claim_key": "CLAIM-1",
        "availability": _ts(2026),
        "algorithm_version": "fx64_v1",
        "forecast_type": ForecastType.NUMERIC_POINT,
        "target_key": "EA_HICP_YOY_ANNUAL_AVERAGE",
        "target_period_kind": ForecastTargetPeriodKind.CALENDAR_YEAR,
        "calendar_year": 2025,
        "attribution_kind": ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        "publisher_source_key": "ECB",
        "evidence_kind": ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        "evidence_description": "test evidence",
        "document_identifier": "DOC-1",
        "provenance_mode": ForecastProvenanceMode.PRODUCTION_OBSERVED,
        "numeric_value": Decimal("1.9"),
        "unit": "PERCENT_YOY",
    }
    defaults.update(overrides)
    return StructuredForecastCandidate(**defaults)  # type: ignore[arg-type]


async def test_production_forecast_invisible_before_fta_acquisition() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)
    await record(_candidate(availability=_ts(2026, 6)), registered_at=_ts(2026, 6))

    get_claim = GetForecastClaimAsOf(repo)
    before = await get_claim("CLAIM-1", _ts(2026, 3))
    after = await get_claim("CLAIM-1", _ts(2026, 9))

    assert before.resolution is ForecastClaimResolution.NOT_KNOWN
    assert after.resolution is ForecastClaimResolution.KNOWN


async def test_retrospective_forecast_invisible_in_production_replay() -> None:
    """FX-64 Section 7's own required invariant: a forecast originally
    published in 2023 but first acquired by FTA (as research) in 2026
    must NEVER appear in an ordinary production query, regardless of
    `as_of`."""
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)
    await record(
        _candidate(
            provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
            availability=_ts(2026, 1),  # FTA's own actual discovery instant
            original_publication_at=_ts(2023, 1, 20),  # the TRUE original publication
        ),
        registered_at=_ts(2026, 1),
    )

    get_claim = GetForecastClaimAsOf(repo)
    production_2024 = await get_claim("CLAIM-1", _ts(2024))
    production_after_discovery = await get_claim("CLAIM-1", _ts(2027))

    assert production_2024.resolution is ForecastClaimResolution.NOT_KNOWN
    # Even AFTER the real discovery instant, an ordinary PRODUCTION
    # query must still never surface a RETROSPECTIVE_RESEARCH vintage.
    assert production_after_discovery.resolution is ForecastClaimResolution.NOT_KNOWN


async def test_explicit_retrospective_research_retrieval() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)
    await record(
        _candidate(
            provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
            availability=_ts(2026, 1),
            original_publication_at=_ts(2023, 1, 20),
        ),
        registered_at=_ts(2026, 1),
    )

    research_view = GetRetrospectiveForecastResearchView(repo)
    result = await research_view("CLAIM-1", _ts(2027))

    assert result.vintage is not None
    assert result.is_retrospective is True
    # FTA's own actual discovery instant is preserved, never backdated.
    assert result.vintage.availability == _ts(2026, 1)
    assert result.vintage.original_publication_at == _ts(2023, 1, 20)


async def test_retrospective_research_view_before_discovery_is_empty() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)
    await record(
        _candidate(
            provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
            availability=_ts(2026, 1),
            original_publication_at=_ts(2023, 1, 20),
        ),
        registered_at=_ts(2026, 1),
    )

    research_view = GetRetrospectiveForecastResearchView(repo)
    result = await research_view("CLAIM-1", _ts(2025))

    assert result.vintage is None


async def test_future_forecast_revision_excluded_from_earlier_snapshot() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)
    await record(_candidate(availability=_ts(2026, 1)), registered_at=_ts(2026, 1))

    get_claim = GetForecastClaimAsOf(repo)
    before = await get_claim("CLAIM-1", _ts(2026, 2))

    await record(
        _candidate(
            availability=_ts(2026, 6), numeric_value=Decimal("2.5"), document_identifier="DOC-2"
        ),
        registered_at=_ts(2026, 1),
    )
    after_future_recorded = await get_claim("CLAIM-1", _ts(2026, 2))

    assert before.vintage is not None
    assert before.vintage.numeric_value == Decimal("1.9")
    assert after_future_recorded.vintage is not None
    assert after_future_recorded.vintage.numeric_value == Decimal("1.9")
    assert before == after_future_recorded


async def test_list_forecast_claims_as_of_excludes_retrospective() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)
    await record(
        _candidate(claim_key="PROD-CLAIM", availability=_ts(2026, 1)), registered_at=_ts(2026, 1)
    )
    await record(
        _candidate(
            claim_key="RETRO-CLAIM",
            provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
            availability=_ts(2026, 1),
            original_publication_at=_ts(2023, 1, 20),
        ),
        registered_at=_ts(2026, 1),
    )

    list_claims = ListForecastClaimsAsOf(repo)
    result = await list_claims(_ts(2027))

    claim_keys = {v.claim_key for v in result.vintages}
    assert claim_keys == {"PROD-CLAIM"}


async def test_list_forecast_claims_as_of_bounded_by_target_key() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)
    await record(_candidate(claim_key="CLAIM-A"), registered_at=_ts(2026))
    await record(
        _candidate(
            claim_key="CLAIM-B",
            target_key="CA_UNEMPLOYMENT_RATE_QUARTERLY_AVERAGE",
            target_period_kind=ForecastTargetPeriodKind.CALENDAR_QUARTER,
            calendar_year=2025,
            calendar_quarter=1,
            unit="PERCENT",
        ),
        registered_at=_ts(2026),
    )

    list_claims = ListForecastClaimsAsOf(repo)
    result = await list_claims(_ts(2027), target_key="EA_HICP_YOY_ANNUAL_AVERAGE")

    assert {v.claim_key for v in result.vintages} == {"CLAIM-A"}

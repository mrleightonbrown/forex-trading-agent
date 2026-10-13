"""FX-64 Section 13/17.D: tests for `RecordStructuredForecast` --
eligibility short-circuit, CREATED/REVISION_ADDED/UNCHANGED/REJECTED
outcomes, PIT ordering, and the full-payload determinism invariant
(mirrors FX-62H's own corrected lesson: the determinism key includes
the full evidence object, and the comparison covers every derived
forecast-defining property, not merely the value)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.use_cases.record_structured_forecast import (
    OutOfOrderStructuredForecastError,
    RecordStructuredForecast,
    StructuredForecastDeterminismError,
    StructuredForecastOutcome,
)
from forex_agent.application.use_cases.validate_structured_forecast_candidate import (
    StructuredForecastCandidate,
)
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_capture_eligibility import ForecastCaptureEligibility
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.structured_forecast_repository import FakeStructuredForecastRepository


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


def _candidate(**overrides: object) -> StructuredForecastCandidate:
    defaults: dict[str, object] = {
        "claim_key": "ECB-SPF-2025Q1:EA_HICP_YOY_ANNUAL_AVERAGE:AGGREGATE",
        "availability": _ts(9),
        "algorithm_version": "fx64_v1",
        "forecast_type": ForecastType.NUMERIC_POINT,
        "target_key": "EA_HICP_YOY_ANNUAL_AVERAGE",
        "target_period_kind": ForecastTargetPeriodKind.CALENDAR_YEAR,
        "calendar_year": 2025,
        "attribution_kind": ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        "publisher_source_key": "ECB",
        "evidence_kind": ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        "evidence_description": "Read from published survey results table.",
        "document_identifier": "ECB-SPF-2025Q1",
        "provenance_mode": ForecastProvenanceMode.PRODUCTION_OBSERVED,
        "numeric_value": Decimal("1.9"),
        "unit": "PERCENT_YOY",
    }
    defaults.update(overrides)
    return StructuredForecastCandidate(**defaults)  # type: ignore[arg-type]


# --- Eligibility short-circuit -----------------------------------------------


async def test_rejected_candidate_is_never_persisted() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)

    result = await record(_candidate(target_key="NOT_A_REAL_TARGET"), registered_at=_ts(9))

    assert result.outcome is StructuredForecastOutcome.REJECTED
    assert result.eligibility is ForecastCaptureEligibility.INSUFFICIENT_SPECIFICATION
    assert result.vintage is None
    assert len(repo.claims) == 0


# --- Basic CREATED / UNCHANGED / REVISION_ADDED -----------------------------


async def test_first_registration_is_created() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)

    result = await record(_candidate(), registered_at=_ts(9))

    assert result.outcome is StructuredForecastOutcome.CREATED
    assert result.vintage is not None
    assert result.vintage.revision_sequence == 0
    assert len(repo.claims) == 1


async def test_exact_repeat_is_unchanged_idempotent() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)
    await record(_candidate(), registered_at=_ts(9))

    result = await record(_candidate(availability=_ts(10)), registered_at=_ts(9))

    assert result.outcome is StructuredForecastOutcome.UNCHANGED
    assert len(await repo.list_vintages_for_claim(_candidate().claim_key)) == 1


async def test_genuinely_different_evidence_mints_revision() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)
    await record(_candidate(), registered_at=_ts(9))

    result = await record(
        _candidate(
            availability=_ts(10),
            numeric_value=Decimal("2.0"),
            document_identifier="ECB-SPF-2025Q1-REVISED",
        ),
        registered_at=_ts(9),
    )

    assert result.outcome is StructuredForecastOutcome.REVISION_ADDED
    assert result.vintage is not None
    assert result.vintage.revision_sequence == 1
    assert result.vintage.numeric_value == Decimal("2.0")


async def test_dry_run_writes_nothing() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)

    result = await record(_candidate(), registered_at=_ts(9), dry_run=True)

    assert result.outcome is StructuredForecastOutcome.CREATED
    assert len(repo.claims) == 0


async def test_registered_at_only_used_on_first_registration() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)
    await record(_candidate(), registered_at=_ts(9))

    await record(
        _candidate(
            availability=_ts(10),
            numeric_value=Decimal("2.0"),
            document_identifier="ECB-SPF-2025Q1-REVISED",
        ),
        registered_at=_ts(23),  # should be ignored -- claim already registered
    )

    claim = await repo.get_claim(_candidate().claim_key)
    assert claim is not None
    assert claim.registered_at == _ts(9)


# --- PIT ordering -------------------------------------------------------------


async def test_out_of_order_availability_is_rejected() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)
    await record(_candidate(availability=_ts(10)), registered_at=_ts(9))

    with pytest.raises(OutOfOrderStructuredForecastError):
        await record(
            _candidate(
                availability=_ts(9),
                numeric_value=Decimal("2.0"),
                document_identifier="DOC-2",
            ),
            registered_at=_ts(9),
        )


async def test_equal_availability_is_permitted() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)
    await record(_candidate(availability=_ts(9)), registered_at=_ts(9))

    result = await record(
        _candidate(availability=_ts(9), numeric_value=Decimal("2.0"), document_identifier="DOC-2"),
        registered_at=_ts(9),
    )

    assert result.outcome is StructuredForecastOutcome.REVISION_ADDED


# --- Full-history determinism: each dimension individually ------------------


async def _seed_and_move_latest(repo: FakeStructuredForecastRepository) -> None:
    record = RecordStructuredForecast(repo)
    shared_evidence_doc = "ECB-SPF-2025Q1"
    await record(
        _candidate(availability=_ts(9), document_identifier=shared_evidence_doc),
        registered_at=_ts(9),
    )
    await record(
        _candidate(
            availability=_ts(10),
            numeric_value=Decimal("2.5"),
            document_identifier="ECB-SPF-2025Q1-OTHER",
        ),
        registered_at=_ts(9),
    )


async def test_value_only_conflict_detected() -> None:
    repo = FakeStructuredForecastRepository()
    await _seed_and_move_latest(repo)
    record = RecordStructuredForecast(repo)

    with pytest.raises(StructuredForecastDeterminismError):
        await record(
            _candidate(
                availability=_ts(11),
                numeric_value=Decimal("9.9"),  # differs from the original 1.9 under SAME evidence
                document_identifier="ECB-SPF-2025Q1",
            ),
            registered_at=_ts(9),
        )


async def test_unit_only_conflict_detected() -> None:
    repo = FakeStructuredForecastRepository()
    await _seed_and_move_latest(repo)
    record = RecordStructuredForecast(repo)

    with pytest.raises(StructuredForecastDeterminismError):
        await record(
            _candidate(
                availability=_ts(11),
                unit="PERCENT",  # differs from the original PERCENT_YOY
                document_identifier="ECB-SPF-2025Q1",
            ),
            registered_at=_ts(9),
        )


async def test_target_period_conflict_detected() -> None:
    repo = FakeStructuredForecastRepository()
    await _seed_and_move_latest(repo)
    record = RecordStructuredForecast(repo)

    with pytest.raises(StructuredForecastDeterminismError):
        await record(
            _candidate(
                availability=_ts(11),
                calendar_year=2026,  # differs from the original 2025
                document_identifier="ECB-SPF-2025Q1",
            ),
            registered_at=_ts(9),
        )


async def test_target_definition_conflict_detected() -> None:
    repo = FakeStructuredForecastRepository()
    await _seed_and_move_latest(repo)
    record = RecordStructuredForecast(repo)

    with pytest.raises(StructuredForecastDeterminismError):
        await record(
            _candidate(
                availability=_ts(11),
                target_key="CA_UNEMPLOYMENT_RATE_QUARTERLY_AVERAGE",
                target_period_kind=ForecastTargetPeriodKind.CALENDAR_QUARTER,
                calendar_year=2025,
                calendar_quarter=1,
                unit="PERCENT",
                document_identifier="ECB-SPF-2025Q1",
            ),
            registered_at=_ts(9),
        )


async def test_attribution_only_conflict_detected() -> None:
    repo = FakeStructuredForecastRepository()
    await _seed_and_move_latest(repo)
    record = RecordStructuredForecast(repo)

    with pytest.raises(StructuredForecastDeterminismError):
        await record(
            _candidate(
                availability=_ts(11),
                attribution_kind=ForecastAttributionKind.NAMED_INSTITUTION,
                forecaster_source_key="ECB",
                document_identifier="ECB-SPF-2025Q1",
            ),
            registered_at=_ts(9),
        )


# --- Full-history version reversion / new-evidence correction --------------


async def test_full_history_v1_a_v2_b_v1_a_succeeds() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)
    await record(
        _candidate(availability=_ts(9), numeric_value=Decimal("1.9"), document_identifier="V1"),
        registered_at=_ts(9),
    )
    await record(
        _candidate(availability=_ts(10), numeric_value=Decimal("2.5"), document_identifier="V2"),
        registered_at=_ts(9),
    )

    result = await record(
        _candidate(availability=_ts(11), numeric_value=Decimal("1.9"), document_identifier="V1"),
        registered_at=_ts(9),
    )

    assert result.outcome is StructuredForecastOutcome.REVISION_ADDED
    assert result.vintage is not None
    assert result.vintage.numeric_value == Decimal("1.9")


async def test_full_history_v1_a_v2_b_v1_c_is_determinism_error() -> None:
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)
    await record(
        _candidate(availability=_ts(9), numeric_value=Decimal("1.9"), document_identifier="V1"),
        registered_at=_ts(9),
    )
    await record(
        _candidate(availability=_ts(10), numeric_value=Decimal("2.5"), document_identifier="V2"),
        registered_at=_ts(9),
    )

    with pytest.raises(StructuredForecastDeterminismError):
        await record(
            _candidate(
                availability=_ts(11), numeric_value=Decimal("3.3"), document_identifier="V1"
            ),
            registered_at=_ts(9),
        )


async def test_new_evidence_correction_is_not_a_violation() -> None:
    """A genuinely different evidence object under the same algorithm
    version is a different basis -- never compared, regardless of how
    many fields differ (mirrors Section 13's own "legitimate source
    correction supported by a different evidence object")."""
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)
    await record(
        _candidate(
            availability=_ts(9),
            numeric_value=Decimal("1.9"),
            document_identifier="ORIGINAL-DOC",
        ),
        registered_at=_ts(9),
    )

    result = await record(
        _candidate(
            availability=_ts(10),
            numeric_value=Decimal("2.1"),
            document_identifier="CORRECTED-DOC",
            evidence_description="Source issued a correction to the originally published figure.",
        ),
        registered_at=_ts(9),
        correction_reason="source-issued correction",
    )

    assert result.outcome is StructuredForecastOutcome.REVISION_ADDED


async def test_concurrent_duplicate_submission_at_the_use_case_level() -> None:
    """Both submissions present the IDENTICAL candidate -- the second
    must be UNCHANGED, never a determinism error against itself."""
    repo = FakeStructuredForecastRepository()
    record = RecordStructuredForecast(repo)

    first = await record(_candidate(), registered_at=_ts(9))
    second = await record(_candidate(), registered_at=_ts(9))

    assert first.outcome is StructuredForecastOutcome.CREATED
    assert second.outcome is StructuredForecastOutcome.UNCHANGED
    assert len(await repo.list_vintages_for_claim(_candidate().claim_key)) == 1

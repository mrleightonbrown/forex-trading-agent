"""FX-65: tests for `RecordForecastOutcome` -- mirrors FX-64/64H's own
coverage (CREATED/REVISION_ADDED/UNCHANGED/REJECTED, PIT ordering,
content determinism, and the FX-64H-style provenance-consistency
invariant applied here from the start)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.ports.forecast_outcome_repository import OutcomeIdentityClaimResult
from forex_agent.application.use_cases.record_forecast_outcome import (
    ForecastOutcomeDeterminismError,
    ForecastOutcomeIdentityConflictError,
    ForecastOutcomeIdentityImmutabilityError,
    ForecastOutcomeOutcome,
    ForecastOutcomeProvenanceConsistencyError,
    OutOfOrderForecastOutcomeError,
    RecordForecastOutcome,
)
from forex_agent.application.use_cases.validate_forecast_outcome_candidate import (
    ForecastOutcomeCandidate,
)
from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_outcome_capture_eligibility import (
    ForecastOutcomeCaptureEligibility,
)
from forex_agent.domain.forecast_outcome_identity import (
    ForecastOutcomeIdentityBinding,
    canonical_target_period_key,
)
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.forecast_outcome_repository import FakeForecastOutcomeRepository


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


def _candidate(**overrides: object) -> ForecastOutcomeCandidate:
    defaults: dict[str, object] = {
        "outcome_key": "BOC-RATE-DECISION-2024-12-11",
        "availability": _ts(9),
        "definition_key": "BOC-RATE-OUTCOME",
        "definition_version_sequence": 0,
        "target_period_kind": ForecastTargetPeriodKind.POLICY_MEETING,
        "policy_meeting_identifier": "BOC-2024-12-11",
        "outcome_type": ForecastType.NUMERIC_POINT,
        "evidence_kind": ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        "evidence_description": "Official press release",
        "document_identifier": "BOC-PR-2024-12-11",
        "provenance_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "reviewed_by": "FTA research operator",
        "review_method": "Direct review of official press release",
        "reviewed_at": _ts(9),
        "numeric_value": Decimal("3.25"),
        "unit": "PERCENT",
    }
    defaults.update(overrides)
    return ForecastOutcomeCandidate(**defaults)  # type: ignore[arg-type]


async def test_rejected_candidate_is_never_persisted() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)

    result = await record(_candidate(unit=None))

    assert result.outcome is ForecastOutcomeOutcome.REJECTED
    assert result.eligibility is ForecastOutcomeCaptureEligibility.INSUFFICIENT_SPECIFICATION
    assert len(repo.vintages) == 0


async def test_first_registration_is_created() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)

    result = await record(_candidate())

    assert result.outcome is ForecastOutcomeOutcome.CREATED
    assert result.vintage is not None
    assert result.vintage.revision_sequence == 0


async def test_exact_repeat_is_unchanged() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate())

    result = await record(_candidate(availability=_ts(10)))

    assert result.outcome is ForecastOutcomeOutcome.UNCHANGED
    assert len(await repo.list_vintages_for_outcome(_candidate().outcome_key)) == 1


async def test_out_of_order_availability_is_rejected() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate(availability=_ts(10)))

    with pytest.raises(OutOfOrderForecastOutcomeError):
        await record(
            _candidate(
                availability=_ts(9), numeric_value=Decimal("3.00"), document_identifier="DOC-2"
            )
        )


async def test_value_conflict_under_same_evidence_is_determinism_error() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate())

    with pytest.raises(ForecastOutcomeDeterminismError):
        await record(_candidate(availability=_ts(10), numeric_value=Decimal("9.99")))


async def test_new_evidence_correction_mints_revision() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate())

    result = await record(
        _candidate(
            availability=_ts(10),
            numeric_value=Decimal("3.00"),
            document_identifier="BOC-PR-2024-12-11-CORRECTED",
        ),
        correction_reason="source-issued correction",
    )

    assert result.outcome is ForecastOutcomeOutcome.REVISION_ADDED
    assert result.vintage is not None
    assert result.vintage.numeric_value == Decimal("3.00")


async def test_provenance_change_under_same_basis_is_rejected() -> None:
    """Mirrors FX-64H's own H1 lesson, applied to outcomes from day
    one: resubmitting the IDENTICAL evidence/payload under a DIFFERENT
    `provenance_mode` is refused, never silently absorbed."""
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate(provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH))

    with pytest.raises(ForecastOutcomeProvenanceConsistencyError):
        await record(
            _candidate(
                availability=_ts(10), provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED
            )
        )

    assert len(await repo.list_vintages_for_outcome(_candidate().outcome_key)) == 1


# --- FX-65H.1: outcome-identity binding -------------------------------------


async def test_second_outcome_key_for_the_same_identity_is_rejected() -> None:
    """Two outcomes with identical definition, target period, and unit
    -- differing only in `outcome_key` and value -- cannot both be
    registered: the SECOND one is refused, closing the substitution
    risk at its source."""
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate(outcome_key="BOC-RATE-DECISION-2024-12-11-A"))

    with pytest.raises(ForecastOutcomeIdentityConflictError):
        await record(
            _candidate(
                outcome_key="BOC-RATE-DECISION-2024-12-11-B",
                numeric_value=Decimal("3.10"),
                document_identifier="DOC-OTHER",
            )
        )


async def test_rejected_identity_conflict_writes_nothing() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate(outcome_key="BOC-RATE-DECISION-2024-12-11-A"))

    with pytest.raises(ForecastOutcomeIdentityConflictError):
        await record(
            _candidate(
                outcome_key="BOC-RATE-DECISION-2024-12-11-B",
                numeric_value=Decimal("3.10"),
                document_identifier="DOC-OTHER",
            )
        )

    assert await repo.list_vintages_for_outcome("BOC-RATE-DECISION-2024-12-11-B") == ()


async def test_correctly_bound_outcome_identity_is_accepted() -> None:
    """The SAME outcome_key registering further revisions of its own
    established identity is never flagged as a conflict against
    itself."""
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate())

    result = await record(
        _candidate(
            availability=_ts(10),
            numeric_value=Decimal("3.00"),
            document_identifier="BOC-PR-2024-12-11-CORRECTED",
        ),
        correction_reason="source-issued correction",
    )

    assert result.outcome is ForecastOutcomeOutcome.REVISION_ADDED


async def test_different_target_period_is_not_a_conflict() -> None:
    """A different real-world outcome (a different meeting) under the
    SAME definition is a legitimately separate identity, never
    flagged."""
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate(outcome_key="BOC-RATE-DECISION-2024-12-11"))

    result = await record(
        _candidate(
            outcome_key="BOC-RATE-DECISION-2025-01-29",
            policy_meeting_identifier="BOC-2025-01-29",
            document_identifier="DOC-OTHER-MEETING",
        )
    )

    assert result.outcome is ForecastOutcomeOutcome.CREATED


# --- FX-65H.2: immutable measurement identity (H2) --------------------------


async def test_same_key_with_changed_target_period_is_rejected() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate())

    with pytest.raises(ForecastOutcomeIdentityImmutabilityError):
        await record(
            _candidate(
                availability=_ts(10),
                policy_meeting_identifier="BOC-2025-01-29",
                document_identifier="DOC-OTHER-MEETING",
            )
        )


async def test_same_key_with_changed_definition_is_rejected() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate())

    with pytest.raises(ForecastOutcomeIdentityImmutabilityError):
        await record(
            _candidate(
                availability=_ts(10),
                definition_key="SOME-OTHER-DEFINITION",
                document_identifier="DOC-OTHER-DEFINITION",
            )
        )


async def test_same_key_with_changed_outcome_type_is_rejected() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate())

    with pytest.raises(ForecastOutcomeIdentityImmutabilityError):
        await record(
            _candidate(
                availability=_ts(10),
                outcome_type=ForecastType.CATEGORICAL_EVENT,
                numeric_value=None,
                unit=None,
                categorical_outcome="CUT",
                document_identifier="DOC-OTHER-TYPE",
            )
        )


async def test_same_key_with_changed_unit_is_rejected() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate())

    with pytest.raises(ForecastOutcomeIdentityImmutabilityError):
        await record(
            _candidate(
                availability=_ts(10), unit="BASIS_POINTS", document_identifier="DOC-OTHER-UNIT"
            )
        )


async def test_rejected_immutability_conflict_writes_nothing() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate())

    with pytest.raises(ForecastOutcomeIdentityImmutabilityError):
        await record(
            _candidate(
                availability=_ts(10),
                unit="BASIS_POINTS",
                document_identifier="DOC-OTHER-UNIT",
            )
        )

    history = await repo.list_vintages_for_outcome(_candidate().outcome_key)
    assert len(history) == 1


async def test_same_key_with_revised_value_and_unchanged_identity_is_accepted() -> None:
    """A legitimate revision of the SAME observed variable/event --
    same identity, new value -- is never flagged by H2."""
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate())

    result = await record(
        _candidate(
            availability=_ts(10),
            numeric_value=Decimal("3.00"),
            document_identifier="DOC-REVISED-VALUE",
        )
    )

    assert result.outcome is ForecastOutcomeOutcome.REVISION_ADDED


async def test_dry_run_identity_conflict_check_is_read_only() -> None:
    """A dry-run that WOULD conflict raises the same exception, but
    never mutates (H4: no `claim_outcome_identity_binding` call, since
    `dry_run=True` skips the atomic claim entirely)."""
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate(outcome_key="BOC-RATE-DECISION-2024-12-11-A"))

    with pytest.raises(ForecastOutcomeIdentityConflictError):
        await record(
            _candidate(
                outcome_key="BOC-RATE-DECISION-2024-12-11-B",
                numeric_value=Decimal("3.10"),
                document_identifier="DOC-OTHER",
            ),
            dry_run=True,
        )

    assert "BOC-RATE-DECISION-2024-12-11-B" not in repo.identity_bindings
    assert await repo.list_vintages_for_outcome("BOC-RATE-DECISION-2024-12-11-B") == ()


async def test_dry_run_legitimate_new_identity_is_not_flagged() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)

    result = await record(_candidate(), dry_run=True)

    assert result.outcome is ForecastOutcomeOutcome.CREATED
    assert repo.identity_bindings == {}


# --- FX-65H.3 (H1): same-key concurrent first-registration races -----------


def _winner_binding(**overrides: object) -> ForecastOutcomeIdentityBinding:
    defaults: dict[str, object] = {
        "definition_key": "BOC-RATE-OUTCOME",
        "target_period_key": canonical_target_period_key(
            ForecastTargetPeriod(
                period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
                policy_meeting_identifier="BOC-2024-12-11",
            )
        ),
        "outcome_type": ForecastType.NUMERIC_POINT,
        "unit": "PERCENT",
        "outcome_key": "BOC-RATE-DECISION-2024-12-11",
    }
    defaults.update(overrides)
    return ForecastOutcomeIdentityBinding(**defaults)  # type: ignore[arg-type]


def _winner_vintage(**overrides: object) -> ForecastOutcomeVintage:
    defaults: dict[str, object] = {
        "outcome_key": "BOC-RATE-DECISION-2024-12-11",
        "revision_sequence": 0,
        "definition_key": "BOC-RATE-OUTCOME",
        "definition_version_sequence": 0,
        "availability": _ts(9),
        "target_period": ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
            policy_meeting_identifier="BOC-2024-12-11",
        ),
        "outcome_type": ForecastType.NUMERIC_POINT,
        "evidence": ForecastEvidenceReference(
            evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
            description="Official press release",
            document_identifier="BOC-PR-2024-12-11",
        ),
        "authentication_review": EvidenceAuthenticationReview(
            reviewed_by="FTA research operator",
            review_method="Direct review of official press release",
            reviewed_at=_ts(9),
        ),
        "provenance_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "numeric_value": Decimal("3.25"),
        "unit": "PERCENT",
    }
    defaults.update(overrides)
    return ForecastOutcomeVintage(**defaults)  # type: ignore[arg-type]


class _RacingFakeRepository(FakeForecastOutcomeRepository):
    """Simulates a concurrent writer that commits its OWN first
    registration for the SAME `outcome_key` in the window between our
    own `latest_outcome_vintage` read and our own atomic claim attempt
    -- exercises FX-65H.3 (H1)'s own loop-based re-classification,
    which a single-process fake repository cannot otherwise race."""

    def __init__(
        self, winner_binding: ForecastOutcomeIdentityBinding, winner_vintage: ForecastOutcomeVintage
    ) -> None:
        super().__init__()
        self._pending_winner: (
            tuple[ForecastOutcomeIdentityBinding, ForecastOutcomeVintage] | None
        ) = (
            winner_binding,
            winner_vintage,
        )

    async def claim_outcome_identity_and_add_first_vintage(
        self, binding: ForecastOutcomeIdentityBinding, first_vintage: ForecastOutcomeVintage
    ) -> OutcomeIdentityClaimResult:
        if self._pending_winner is not None:
            winner_binding, winner_vintage = self._pending_winner
            self._pending_winner = None
            self.identity_bindings[winner_binding.outcome_key] = winner_binding
            self.vintages.setdefault(winner_vintage.outcome_key, []).append(winner_vintage)
            return OutcomeIdentityClaimResult(claimed=False)
        return await super().claim_outcome_identity_and_add_first_vintage(binding, first_vintage)


async def test_same_key_identical_concurrent_submission_is_unchanged_against_persisted_winner() -> (
    None
):
    """A genuinely identical concurrent submission must be reported
    UNCHANGED against what the WINNER actually persisted, never
    against the loser's own un-persisted attempt."""
    winner_vintage = _winner_vintage(correction_reason="winner's own marker")
    repo = _RacingFakeRepository(_winner_binding(), winner_vintage)
    record = RecordForecastOutcome(repo)

    result = await record(_candidate())

    assert result.outcome is ForecastOutcomeOutcome.UNCHANGED
    assert result.vintage is winner_vintage
    history = await repo.list_vintages_for_outcome("BOC-RATE-DECISION-2024-12-11")
    assert len(history) == 1


async def test_same_key_concurrent_different_value_same_evidence_is_not_silently_unchanged() -> (
    None
):
    """A concurrent submission under the SAME evidentiary basis but a
    DIFFERENT value must never be reported UNCHANGED -- this is
    exactly the FX-65H.2-era bug: losing the atomic claim used to be
    treated as an automatic, content-blind duplicate."""
    winner_vintage = _winner_vintage()
    repo = _RacingFakeRepository(_winner_binding(), winner_vintage)
    record = RecordForecastOutcome(repo)

    with pytest.raises(ForecastOutcomeDeterminismError):
        await record(_candidate(numeric_value=Decimal("3.10")))

    history = await repo.list_vintages_for_outcome("BOC-RATE-DECISION-2024-12-11")
    assert len(history) == 1
    assert history[0] is winner_vintage


async def test_same_key_concurrent_different_evidence_mints_new_revision() -> None:
    """A concurrent submission under genuinely NEW evidence is
    appended as the next revision, never discarded as if it had lost
    an identical first-registration race."""
    winner_vintage = _winner_vintage()
    repo = _RacingFakeRepository(_winner_binding(), winner_vintage)
    record = RecordForecastOutcome(repo)

    result = await record(
        _candidate(numeric_value=Decimal("3.10"), document_identifier="BOC-PR-2024-12-11-CORR")
    )

    assert result.outcome is ForecastOutcomeOutcome.REVISION_ADDED
    assert result.vintage is not None
    assert result.vintage.revision_sequence == 1
    history = await repo.list_vintages_for_outcome("BOC-RATE-DECISION-2024-12-11")
    assert len(history) == 2

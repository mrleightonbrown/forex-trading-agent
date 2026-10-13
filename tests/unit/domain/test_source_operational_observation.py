"""FX-63 Section 13.A: domain tests for `SourceOperationalObservation`
-- valid construction, invalid identity/attempt rejection, UTC-aware
timestamp enforcement, and immutability."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from forex_agent.domain.source_acquisition_outcome import SourceAcquisitionOutcome
from forex_agent.domain.source_operational_observation import SourceOperationalObservation
from forex_agent.domain.source_operational_observation_kind import SourceOperationalObservationKind
from forex_agent.domain.timestamps import UtcTimestamp


def _ts() -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, 9, tzinfo=UTC))


def _observation(**overrides: object) -> SourceOperationalObservation:
    defaults: dict[str, object] = {
        "source_key": "FED",
        "source_channel": "press_monetary",
        "run_id": "run-1",
        "attempt_number": 1,
        "kind": SourceOperationalObservationKind.ACQUISITION_ATTEMPT,
        "outcome": SourceAcquisitionOutcome.SUCCESS,
        "availability": _ts(),
        "http_status": 200,
        "policy_version": "fx63_v1",
    }
    defaults.update(overrides)
    return SourceOperationalObservation(**defaults)  # type: ignore[arg-type]


def test_constructs_with_valid_fields() -> None:
    observation = _observation()
    assert observation.source_key == "FED"
    assert observation.attempt_number == 1


def test_http_status_may_be_none() -> None:
    observation = _observation(outcome=SourceAcquisitionOutcome.NETWORK_FAILURE, http_status=None)
    assert observation.http_status is None


def test_empty_source_key_rejected() -> None:
    with pytest.raises(ValueError, match="source_key"):
        _observation(source_key="")


def test_empty_source_channel_rejected() -> None:
    with pytest.raises(ValueError, match="source_channel"):
        _observation(source_channel="  ")


def test_empty_run_id_rejected() -> None:
    with pytest.raises(ValueError, match="run_id"):
        _observation(run_id="")


def test_attempt_number_below_one_rejected() -> None:
    with pytest.raises(ValueError, match="attempt_number"):
        _observation(attempt_number=0)


def test_attempt_number_must_be_int() -> None:
    with pytest.raises(TypeError, match="attempt_number"):
        _observation(attempt_number=1.5)


def test_wrong_kind_type_rejected() -> None:
    with pytest.raises(TypeError, match="kind"):
        _observation(kind="ACQUISITION_ATTEMPT")


def test_wrong_outcome_type_rejected() -> None:
    with pytest.raises(TypeError, match="outcome"):
        _observation(outcome="SUCCESS")


def test_naive_availability_rejected() -> None:
    # UtcTimestamp itself rejects a naive datetime at construction --
    # this type can never even be handed one.
    with pytest.raises(ValueError, match="naive"):
        UtcTimestamp(datetime(2026, 1, 1, 9))  # noqa: DTZ001


def test_availability_must_be_utc_timestamp() -> None:
    with pytest.raises(TypeError, match="availability"):
        _observation(availability=datetime(2026, 1, 1, 9, tzinfo=UTC))


def test_http_status_out_of_range_rejected() -> None:
    with pytest.raises(ValueError, match="http_status"):
        _observation(http_status=99)


def test_empty_policy_version_rejected() -> None:
    with pytest.raises(ValueError, match="policy_version"):
        _observation(policy_version="")


def test_observation_is_immutable() -> None:
    observation = _observation()
    with pytest.raises(FrozenInstanceError):
        observation.source_key = "ECB"  # type: ignore[misc]


def test_distinct_retry_attempts_are_distinct_values() -> None:
    first = _observation(attempt_number=1, outcome=SourceAcquisitionOutcome.HTTP_FAILURE)
    second = _observation(attempt_number=2, outcome=SourceAcquisitionOutcome.SUCCESS)
    assert first != second
    assert first.attempt_number != second.attempt_number


def test_outcome_never_implies_publisher_failure() -> None:
    """Section 5: the observation itself carries no publisher
    identity or judgment at all -- this is a structural property of
    the type (no such field exists), proven here by checking its own
    field set contains no publisher-shaped attribute."""
    observation = _observation(outcome=SourceAcquisitionOutcome.HTTP_FAILURE)
    field_names = set(observation.__dataclass_fields__)
    assert not any("publisher" in name for name in field_names)
    assert not any("trust" in name or "reputation" in name for name in field_names)

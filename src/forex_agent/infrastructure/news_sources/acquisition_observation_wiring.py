"""FX-63: a small, shared wiring helper every `scripts/ingest_*.py`
entrypoint uses to turn an adapter's own `http_fetch.FetchAttemptOutcome`
into a durable `SourceOperationalObservation`, recorded via `Record
SourceOperationalObservation`. Lives in `infrastructure.news_sources`
(not `scripts/`, which has no `__init__.py` and is never imported
from -- every script there runs standalone) so six scripts can share
the IDENTICAL `FetchAttemptOutcomeKind` -> `SourceAcquisitionOutcome`
mapping without risking the two enums silently drifting out of sync
across six independently-maintained copies."""

from forex_agent.application.use_cases.record_source_operational_observation import (
    RecordSourceOperationalObservation,
)
from forex_agent.domain.source_acquisition_outcome import SourceAcquisitionOutcome
from forex_agent.infrastructure.news_sources.http_fetch import (
    AcquisitionAttemptRecorder,
    FetchAttemptOutcome,
    FetchAttemptOutcomeKind,
)

_OUTCOME_MAP: dict[FetchAttemptOutcomeKind, SourceAcquisitionOutcome] = {
    FetchAttemptOutcomeKind.SUCCESS: SourceAcquisitionOutcome.SUCCESS,
    FetchAttemptOutcomeKind.HTTP_FAILURE: SourceAcquisitionOutcome.HTTP_FAILURE,
    FetchAttemptOutcomeKind.TIMEOUT: SourceAcquisitionOutcome.TIMEOUT,
    FetchAttemptOutcomeKind.NETWORK_FAILURE: SourceAcquisitionOutcome.NETWORK_FAILURE,
}


def make_acquisition_recorder(
    record_observation: RecordSourceOperationalObservation,
) -> AcquisitionAttemptRecorder:
    """Returns an `AcquisitionAttemptRecorder` closure suitable for any
    adapter's own `on_acquisition_attempt` constructor parameter."""

    async def _on_acquisition_attempt(
        source_key: str, source_channel: str, run_id: str, outcome: FetchAttemptOutcome
    ) -> None:
        await record_observation(
            source_key=source_key,
            source_channel=source_channel,
            run_id=run_id,
            attempt_number=outcome.attempt_number,
            outcome=_OUTCOME_MAP[outcome.outcome_kind],
            availability=outcome.observed_at,
            http_status=outcome.http_status,
        )

    return _on_acquisition_attempt

"""FX-63: a small, shared wiring helper every `scripts/ingest_*.py`
entrypoint uses to turn an adapter's own `http_fetch.FetchAttemptOutcome`
into a durable `SourceOperationalObservation`, recorded via `Record
SourceOperationalObservation`. Lives in `infrastructure.news_sources`
(not `scripts/`, which has no `__init__.py` and is never imported
from -- every script there runs standalone) so six scripts can share
the IDENTICAL `FetchAttemptOutcomeKind` -> `SourceAcquisitionOutcome`
mapping without risking the two enums silently drifting out of sync
across six independently-maintained copies.

**FX-63H Section H1 (points 3/4)**: `make_acquisition_recorder` takes
a `session_factory`, NOT an already-bound `RecordSourceOperational
Observation` -- EVERY recorded attempt opens, uses, and closes its
OWN independent session/transaction, committing or rolling back
completely independently of whatever session the caller's own
NewsItem-persistence flow is using. This is deliberate: observation
persistence must never be able to commit or roll back unrelated
pending work in a shared session. Combined with `http_fetch.fetch_
text`'s own `on_attempt`/`on_attempt_error` isolation (which catches
and reports whatever THIS function raises), a failure opening or
writing through this independent session can never affect the
underlying fetch's own outcome."""

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.record_source_operational_observation import (
    RecordSourceOperationalObservation,
)
from forex_agent.domain.source_acquisition_outcome import SourceAcquisitionOutcome
from forex_agent.infrastructure.db.source_operational_observation_repository import (
    SqlAlchemySourceOperationalObservationRepository,
)
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

SessionFactory = Callable[[], AsyncSession]


def make_acquisition_recorder(
    session_factory: async_sessionmaker[AsyncSession],
) -> AcquisitionAttemptRecorder:
    """Returns an `AcquisitionAttemptRecorder` closure suitable for any
    adapter's own `on_acquisition_attempt` constructor parameter.
    `session_factory` is typically the SAME `async_sessionmaker` the
    calling script already built for its own `NewsRepository` session
    -- a new, independent session is opened from it for EVERY single
    recorded attempt, never the script's own already-open session."""

    async def _on_acquisition_attempt(
        source_key: str, source_channel: str, run_id: str, outcome: FetchAttemptOutcome
    ) -> None:
        async with session_factory() as session:
            repository = SqlAlchemySourceOperationalObservationRepository(session)
            record_observation = RecordSourceOperationalObservation(repository)
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

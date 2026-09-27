"""FX-54: unit tests for `GetEventRiskEvidenceSnapshot`'s own input
validation and no-network-I/O structural guarantee. Full PIT/pair-
relevance/grouping behaviour against a real repository is covered by
`tests/integration/test_get_event_risk_evidence_snapshot.py` -- these
tests deliberately never reach the repository at all (a stub that
raises on every method proves validation happens BEFORE any repository
call)."""

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from forex_agent.application.use_cases.get_event_risk_evidence_snapshot import (
    GetEventRiskEvidenceSnapshot,
)
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp

_AS_OF = UtcTimestamp(datetime(2026, 9, 1, tzinfo=UTC))
_INSTRUMENT = Instrument(base_currency="GBP", quote_currency="USD")


class _UnreachableRepository:
    """Every method raises -- proves the use case never calls the
    repository when its own input validation already fails."""

    def __getattr__(self, name: str) -> object:
        def _unreachable(*args: object, **kwargs: object) -> object:
            raise AssertionError(f"repository.{name} must not be called")

        return _unreachable


def test_constructor_takes_no_http_client_or_provider_dependency() -> None:
    # FX-54 Section 24: this use case must perform no network I/O of
    # its own -- structurally guaranteed by its own constructor never
    # accepting anything but the repository port.
    signature = inspect.signature(GetEventRiskEvidenceSnapshot.__init__)
    assert list(signature.parameters) == ["self", "repository"]


@pytest.mark.asyncio
async def test_negative_lookahead_rejected_before_any_repository_call() -> None:
    use_case = GetEventRiskEvidenceSnapshot(_UnreachableRepository())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="lookahead"):
        await use_case(_INSTRUMENT, _AS_OF, timedelta(hours=-1), timedelta(0))


@pytest.mark.asyncio
async def test_negative_lookback_rejected_before_any_repository_call() -> None:
    use_case = GetEventRiskEvidenceSnapshot(_UnreachableRepository())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="lookback"):
        await use_case(_INSTRUMENT, _AS_OF, timedelta(0), timedelta(hours=-1))


@pytest.mark.asyncio
async def test_zero_horizons_are_accepted() -> None:
    # Zero-length horizons are not negative -- must not raise, even
    # though the repository stub would fail if actually called (it
    # will be called here, since validation passes; use a repository
    # that returns empty results instead).
    class _EmptyRepository:
        async def known_events_in_window(
            self, start: object, end: object, as_of: object
        ) -> tuple[object, ...]:
            return ()

        async def known_releases_in_window(
            self, start: object, end: object, as_of: object
        ) -> tuple[object, ...]:
            return ()

    use_case = GetEventRiskEvidenceSnapshot(_EmptyRepository())  # type: ignore[arg-type]
    snapshot = await use_case(_INSTRUMENT, _AS_OF, timedelta(0), timedelta(0))
    assert snapshot.upcoming_schedule_groups == ()
    assert snapshot.recent_release_groups == ()

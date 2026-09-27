"""FX-54V: unit tests for `GetPolicyRateHistory` against
`FakeMacroObservationRepository` -- no database, no research-readiness
gate."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.use_cases.get_policy_rate_history import GetPolicyRateHistory
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.policy_rate_differential import RateSemantics
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.macro_observation_repository import FakeMacroObservationRepository

_INSTRUMENT = Instrument(base_currency="GBP", quote_currency="USD")


def _ts(year: int, month: int, day: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, tzinfo=UTC))


def _vintage(series_key: str, period: tuple[int, int, int], value: str) -> MacroObservationVintage:
    return MacroObservationVintage(
        series_key=series_key,
        observation_period=_ts(*period),
        value=Decimal(value),
        released_at=_ts(*period),
        revision_sequence=0,
        source="test",
        released_at_is_verified=True,
    )


@pytest.mark.asyncio
async def test_returns_chronological_history_for_both_legs() -> None:
    repo = FakeMacroObservationRepository()
    await repo.add_vintage(_vintage("GBP_POLICY_RATE", (2026, 1, 1), "4.75"))
    await repo.add_vintage(_vintage("GBP_POLICY_RATE", (2026, 6, 1), "4.25"))
    await repo.add_vintage(_vintage("USD_POLICY_RATE", (2026, 3, 1), "4.00"))
    use_case = GetPolicyRateHistory(repository=repo)

    history = await use_case(_INSTRUMENT, _ts(2026, 9, 20), RateSemantics.ANNOUNCED)

    assert [v.value for v in history.base_history] == [Decimal("4.75"), Decimal("4.25")]
    assert [v.value for v in history.quote_history] == [Decimal("4.00")]
    assert history.base_currency == "GBP"
    assert history.quote_currency == "USD"


@pytest.mark.asyncio
async def test_excludes_decisions_not_yet_knowable_at_as_of() -> None:
    repo = FakeMacroObservationRepository()
    await repo.add_vintage(_vintage("GBP_POLICY_RATE", (2026, 1, 1), "4.75"))
    await repo.add_vintage(_vintage("GBP_POLICY_RATE", (2026, 12, 1), "4.25"))  # future
    use_case = GetPolicyRateHistory(repository=repo)

    history = await use_case(_INSTRUMENT, _ts(2026, 9, 20), RateSemantics.ANNOUNCED)

    assert [v.value for v in history.base_history] == [Decimal("4.75")]


@pytest.mark.asyncio
async def test_currency_with_no_canonical_series_returns_empty_history() -> None:
    repo = FakeMacroObservationRepository()
    use_case = GetPolicyRateHistory(repository=repo)
    unregistered_pair = Instrument(base_currency="AUD", quote_currency="USD")

    history = await use_case(unregistered_pair, _ts(2026, 9, 20), RateSemantics.ANNOUNCED)

    assert history.base_history == ()


@pytest.mark.asyncio
async def test_effective_semantics_empty_when_no_effective_at_populated() -> None:
    # GBP's own real-world gap (FX-46) -- must be an honest empty
    # tuple, never an error and never a fabricated point.
    repo = FakeMacroObservationRepository()
    await repo.add_vintage(_vintage("GBP_POLICY_RATE", (2026, 1, 1), "4.75"))
    use_case = GetPolicyRateHistory(repository=repo)

    history = await use_case(_INSTRUMENT, _ts(2026, 9, 20), RateSemantics.EFFECTIVE)

    assert history.base_history == ()

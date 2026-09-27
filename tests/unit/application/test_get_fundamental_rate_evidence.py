"""FX-54V: unit tests for `GetFundamentalRateEvidence` against
`FakeMacroObservationRepository` -- no database, no research-readiness
gate (see the use case's own module docstring for why FX-45's
`ComputePolicyRateDifferential` is deliberately NOT reused here)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.use_cases.get_fundamental_rate_evidence import (
    GetFundamentalRateEvidence,
)
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.policy_rate_differential import RateSemantics
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.macro_observation_repository import FakeMacroObservationRepository

_INSTRUMENT = Instrument(base_currency="GBP", quote_currency="USD")


def _ts(year: int, month: int, day: int, hour: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, tzinfo=UTC))


@pytest.mark.asyncio
async def test_both_sides_available_computes_raw_differential() -> None:
    repo = FakeMacroObservationRepository()
    await repo.add_vintage(
        MacroObservationVintage(
            series_key="GBP_POLICY_RATE",
            observation_period=_ts(2026, 9, 1),
            value=Decimal("3.75"),
            released_at=_ts(2026, 9, 1),
            revision_sequence=0,
            source="BOE_DATABASE",
            released_at_is_verified=True,
        )
    )
    await repo.add_vintage(
        MacroObservationVintage(
            series_key="USD_POLICY_RATE",
            observation_period=_ts(2026, 9, 1),
            value=Decimal("3.875"),
            released_at=_ts(2026, 9, 1),
            revision_sequence=0,
            source="FRED",
            released_at_is_verified=True,
        )
    )
    use_case = GetFundamentalRateEvidence(repository=repo)

    evidence = await use_case(_INSTRUMENT, _ts(2026, 9, 20), RateSemantics.ANNOUNCED)

    assert evidence.base is not None and evidence.base.rate == Decimal("3.75")
    assert evidence.quote is not None
    assert evidence.differential == Decimal("-0.125")
    assert evidence.pair == "GBP/USD"


@pytest.mark.asyncio
async def test_missing_side_is_reported_with_explicit_reason_never_hidden() -> None:
    # GBP has zero EFFECTIVE-dated history (FX-46's own documented gap).
    repo = FakeMacroObservationRepository()
    await repo.add_vintage(
        MacroObservationVintage(
            series_key="GBP_POLICY_RATE",
            observation_period=_ts(2026, 9, 1),
            value=Decimal("3.75"),
            released_at=_ts(2026, 9, 1),
            revision_sequence=0,
            source="BOE_DATABASE",
            released_at_is_verified=True,
            # effective_at deliberately omitted
        )
    )
    await repo.add_vintage(
        MacroObservationVintage(
            series_key="USD_POLICY_RATE",
            observation_period=_ts(2026, 9, 1),
            value=Decimal("3.875"),
            released_at=_ts(2026, 9, 1),
            effective_at=_ts(2026, 9, 2),
            revision_sequence=0,
            source="FRED",
            released_at_is_verified=True,
        )
    )
    use_case = GetFundamentalRateEvidence(repository=repo)

    evidence = await use_case(_INSTRUMENT, _ts(2026, 9, 20), RateSemantics.EFFECTIVE)

    assert evidence.base is None
    assert evidence.base_unavailable_reason is not None
    assert "GBP" in evidence.base_unavailable_reason
    assert evidence.quote is not None  # USD's own real evidence still reported
    assert evidence.differential is None  # never a fabricated/partial value


@pytest.mark.asyncio
async def test_currency_with_no_canonical_series_is_unavailable() -> None:
    repo = FakeMacroObservationRepository()
    use_case = GetFundamentalRateEvidence(repository=repo)
    unregistered_pair = Instrument(base_currency="AUD", quote_currency="USD")

    evidence = await use_case(unregistered_pair, _ts(2026, 9, 20), RateSemantics.ANNOUNCED)

    assert evidence.base is None
    assert "AUD" in (evidence.base_unavailable_reason or "")
    assert evidence.differential is None

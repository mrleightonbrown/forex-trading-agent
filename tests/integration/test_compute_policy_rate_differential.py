"""FX-45: `ComputePolicyRateDifferential` against live Postgres, using
the REAL policy-rate history FX-43/FX-43H/FX-44/FX-44H/FX-44H.1
ingested and hardened. See tests/unit/application/
test_compute_policy_rate_differential.py for the fast, DB-free
equivalents of the core scenarios exercised here.

Requires a live Postgres with migrations applied AND the real
policy-rate backfill/verification/remediation already run --
`docker compose up -d db && uv run alembic upgrade head`, then
`scripts/backfill_policy_rate_history.py`,
`scripts/verify_policy_rate_release_timing.py`, and
`scripts/remediate_usd_release_timing.py`, in that order, first (all
idempotent -- safe to re-run).
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.compute_policy_rate_differential import (
    ComputePolicyRateDifferential,
)
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.policy_rate_differential import (
    DifferentialUnavailable,
    PolicyRateDifferentialFeature,
    RateSemantics,
)
from forex_agent.domain.research_readiness import ResearchIntervalNotReadyError
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.macro_observation_repository import (
    SqlAlchemyMacroObservationRepository,
)
from forex_agent.infrastructure.db.session import get_engine


def _ts(*args: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(*args, tzinfo=UTC))


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session


def _feature(result: object) -> PolicyRateDifferentialFeature:
    assert isinstance(result, PolicyRateDifferentialFeature)
    return result


def _unavailable(result: object) -> DifferentialUnavailable:
    assert isinstance(result, DifferentialUnavailable)
    return result


@pytest.mark.asyncio
async def test_eur_usd_real_orientation(session: AsyncSession) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    use_case = ComputePolicyRateDifferential(repository=repo)
    as_of = _ts(2023, 6, 1)

    eur_usd = _feature(await use_case(Instrument("EUR", "USD"), as_of, RateSemantics.ANNOUNCED))
    usd_eur = _feature(await use_case(Instrument("USD", "EUR"), as_of, RateSemantics.ANNOUNCED))

    # Real, verified data as of this story: EUR 3.75% (effective 2023-05-10),
    # USD 5.125% (effective 2023-05-04, target-range midpoint).
    assert eur_usd.current.base.rate == Decimal("3.75")
    assert eur_usd.current.quote.rate == Decimal("5.125")
    assert eur_usd.current.differential == Decimal("3.75") - Decimal("5.125")
    assert eur_usd.current.differential == -usd_eur.current.differential


@pytest.mark.asyncio
async def test_usd_cad_real_orientation(session: AsyncSession) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    use_case = ComputePolicyRateDifferential(repository=repo)
    as_of = _ts(2023, 8, 1)

    usd_cad = _feature(await use_case(Instrument("USD", "CAD"), as_of, RateSemantics.ANNOUNCED))
    cad_usd = _feature(await use_case(Instrument("CAD", "USD"), as_of, RateSemantics.ANNOUNCED))

    assert usd_cad.current.differential == -cad_usd.current.differential


@pytest.mark.asyncio
async def test_gbp_usd_effective_semantics_unavailable(session: AsyncSession) -> None:
    # FX-45 section 6, this story's own real finding: GBP's registry has
    # never had a verified effective_at populated for any change point
    # (FX-44's own resolver -- see docs/DECISIONS.md's FX-45 entry) --
    # EFFECTIVE semantics is therefore genuinely unavailable for GBP,
    # not a bug to work around.
    repo = SqlAlchemyMacroObservationRepository(session)
    use_case = ComputePolicyRateDifferential(repository=repo)

    result = _unavailable(
        await use_case(Instrument("GBP", "USD"), _ts(2023, 6, 1), RateSemantics.EFFECTIVE)
    )

    assert "GBP" in result.reason
    assert "effective_at" in result.reason


@pytest.mark.asyncio
async def test_usd_cad_effective_semantics_unavailable(session: AsyncSession) -> None:
    # Same real finding as GBP, for CAD (100% conservative-tier -- no
    # exact-tier, no effective_at, anywhere in this registry today).
    repo = SqlAlchemyMacroObservationRepository(session)
    use_case = ComputePolicyRateDifferential(repository=repo)

    result = _unavailable(
        await use_case(Instrument("USD", "CAD"), _ts(2023, 6, 1), RateSemantics.EFFECTIVE)
    )

    assert "CAD" in result.reason
    assert "effective_at" in result.reason


@pytest.mark.asyncio
async def test_usd_jpy_unavailable_real(session: AsyncSession) -> None:
    # JPY provider ingestion remains unresolved (FX-43/FX-43H) -- zero
    # real rows exist for it, so this fails closed via the readiness
    # gate's own no_baseline path, not a special case.
    repo = SqlAlchemyMacroObservationRepository(session)
    use_case = ComputePolicyRateDifferential(repository=repo)

    with pytest.raises(ResearchIntervalNotReadyError) as exc_info:
        await use_case(Instrument("USD", "JPY"), _ts(2023, 6, 1), RateSemantics.ANNOUNCED)

    assert exc_info.value.no_baseline


@pytest.mark.asyncio
async def test_interval_crossing_a_real_unresolved_crisis_observation_is_rejected(
    session: AsyncSession,
) -> None:
    # FX-45 section 11's own required test: a real, known-irregular USD
    # date (2008-01-22, the inter-meeting 75bp emergency cut -- still
    # unresolved, deliberately not researched in this story) falls
    # inside the ~6-month(+margin) lookback window for this as_of, and
    # must block the WHOLE calculation rather than being silently
    # skipped.
    repo = SqlAlchemyMacroObservationRepository(session)
    use_case = ComputePolicyRateDifferential(repository=repo)

    with pytest.raises(ResearchIntervalNotReadyError) as exc_info:
        await use_case(Instrument("EUR", "USD"), _ts(2008, 2, 1), RateSemantics.ANNOUNCED)

    assert not exc_info.value.no_baseline
    offending_dates = {
        v.observation_period.value.date() for v in exc_info.value.provisional_vintages
    }
    assert date(2008, 1, 22) in offending_dates


@pytest.mark.asyncio
async def test_three_state_regression_real_2026_09_17_observation(session: AsyncSession) -> None:
    # FX-45 section 10's mandatory regression, against the REAL,
    # FX-44H.1-remediated USD row: decision 2026-09-16 14:00 ET (18:00
    # UTC), effective 2026-09-17. EUR is stable across this entire
    # window (its own last change was effective 2026-09-16, released
    # 2026-09-10 -- well before the USD transition this test isolates),
    # so USD/EUR's differential movement here is driven by USD alone.
    repo = SqlAlchemyMacroObservationRepository(session)
    use_case = ComputePolicyRateDifferential(repository=repo)
    instrument = Instrument("USD", "EUR")

    just_before_release = UtcTimestamp(datetime(2026, 9, 16, 17, 59, 59, tzinfo=UTC))
    just_after_release = UtcTimestamp(datetime(2026, 9, 16, 18, 1, 0, tzinfo=UTC))
    once_effective = UtcTimestamp(datetime(2026, 9, 17, 0, 0, 0, tzinfo=UTC))

    before_announced = _feature(
        await use_case(instrument, just_before_release, RateSemantics.ANNOUNCED)
    )
    before_effective = _feature(
        await use_case(instrument, just_before_release, RateSemantics.EFFECTIVE)
    )
    assert before_announced.current.base.rate == Decimal("3.625")
    assert before_effective.current.base.rate == Decimal("3.625")

    after_announced = _feature(
        await use_case(instrument, just_after_release, RateSemantics.ANNOUNCED)
    )
    after_effective = _feature(
        await use_case(instrument, just_after_release, RateSemantics.EFFECTIVE)
    )
    assert after_announced.current.base.rate == Decimal("3.875")  # NEW, already announced
    assert after_effective.current.base.rate == Decimal("3.625")  # still OLD, not yet effective

    effective_announced = _feature(
        await use_case(instrument, once_effective, RateSemantics.ANNOUNCED)
    )
    effective_effective = _feature(
        await use_case(instrument, once_effective, RateSemantics.EFFECTIVE)
    )
    assert effective_announced.current.base.rate == Decimal("3.875")
    assert effective_effective.current.base.rate == Decimal("3.875")


@pytest.mark.asyncio
async def test_future_unreleased_provisional_observation_does_not_block_real(
    session: AsyncSession,
) -> None:
    # FX-45H section 3's own real, committed finding: USD's 1998-10-15
    # row (an inter-meeting emergency cut) is genuinely provisional --
    # released_at_is_verified AND released_at_is_conservative_bound are
    # both False, and released_at == observation_period == 1998-10-15,
    # i.e. not yet released as of 1998-10-08. Before this story, the
    # readiness window padded 14 days forward from as_of unconditionally
    # and let this not-yet-released row block the query anyway. GBP has
    # a real, verified decision ON 1998-10-08 itself (11:00 UTC),
    # giving a clean two-leg regression at a real historical instant.
    repo = SqlAlchemyMacroObservationRepository(session)
    use_case = ComputePolicyRateDifferential(repository=repo)
    as_of = UtcTimestamp(datetime(1998, 10, 8, 18, 0, 0, tzinfo=UTC))

    result = _feature(await use_case(Instrument("GBP", "USD"), as_of, RateSemantics.ANNOUNCED))

    # USD's own current state as of this instant is still the real
    # 1998-09-29 conservative-bound row (5.25%) -- the not-yet-released
    # 1998-10-15 row must be neither visible nor able to block.
    assert result.current.base.rate == Decimal("7.25")  # GBP, 1998-10-08
    assert result.current.quote.rate == Decimal("5.25")  # USD, still 1998-09-29
    assert result.current.quote.observation_period.value.date() == date(1998, 9, 29)


@pytest.mark.asyncio
async def test_deterministic_output_for_identical_inputs_real(session: AsyncSession) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    use_case = ComputePolicyRateDifferential(repository=repo)
    instrument = Instrument("EUR", "USD")
    as_of = _ts(2023, 6, 1)

    first = _feature(await use_case(instrument, as_of, RateSemantics.ANNOUNCED))
    second = _feature(await use_case(instrument, as_of, RateSemantics.ANNOUNCED))

    assert first == second

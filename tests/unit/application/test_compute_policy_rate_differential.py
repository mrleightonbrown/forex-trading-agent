"""FX-45: fast, DB-free tests for `ComputePolicyRateDifferential`
against `FakeMacroObservationRepository`. See tests/integration/
test_compute_policy_rate_differential.py for the live-Postgres
equivalents of the core scenarios exercised here."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.use_cases.compute_policy_rate_differential import (
    ComputePolicyRateDifferential,
)
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.policy_rate_differential import (
    DifferentialDirection,
    DifferentialUnavailable,
    PolicyRateDifferentialFeature,
    RateSemantics,
)
from forex_agent.domain.research_readiness import ResearchIntervalNotReadyError
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.macro_observation_repository import FakeMacroObservationRepository


def _ts(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    microsecond: int = 0,
) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, minute, second, microsecond, tzinfo=UTC))


async def _seed_exact(
    fake: FakeMacroObservationRepository,
    series_key: str,
    observation_period: tuple[int, ...],
    released_at: tuple[int, ...],
    value: str,
    effective_at: tuple[int, ...] | None = None,
) -> None:
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=series_key,
            observation_period=_ts(*observation_period),
            value=Decimal(value),
            released_at=_ts(*released_at),
            effective_at=None if effective_at is None else _ts(*effective_at),
            revision_sequence=0,
            source="TEST",
            released_at_is_verified=True,
        )
    )


async def _seed_provisional(
    fake: FakeMacroObservationRepository,
    series_key: str,
    observation_period: tuple[int, ...],
    released_at: tuple[int, ...],
    value: str,
) -> None:
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=series_key,
            observation_period=_ts(*observation_period),
            value=Decimal(value),
            released_at=_ts(*released_at),
            revision_sequence=0,
            source="TEST",
        )
    )


def _feature(result: object) -> PolicyRateDifferentialFeature:
    assert isinstance(result, PolicyRateDifferentialFeature)
    return result


# ---------------------------------------------------------------------------
# Orientation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eur_usd_orientation() -> None:
    fake = FakeMacroObservationRepository()
    await _seed_exact(fake, "EUR_POLICY_RATE", (2023, 5, 10), (2023, 5, 4, 11, 45, 0), "3.75")
    await _seed_exact(fake, "USD_POLICY_RATE", (2023, 5, 4), (2023, 5, 3, 18, 0, 0), "5.125")
    use_case = ComputePolicyRateDifferential(repository=fake)
    as_of = _ts(2023, 6, 1)

    eur_usd = _feature(await use_case(Instrument("EUR", "USD"), as_of, RateSemantics.ANNOUNCED))
    usd_eur = _feature(await use_case(Instrument("USD", "EUR"), as_of, RateSemantics.ANNOUNCED))

    assert eur_usd.current.differential == Decimal("3.75") - Decimal("5.125")
    assert eur_usd.current.differential == -usd_eur.current.differential


@pytest.mark.asyncio
async def test_usd_cad_orientation() -> None:
    fake = FakeMacroObservationRepository()
    await _seed_exact(fake, "USD_POLICY_RATE", (2023, 5, 4), (2023, 5, 3, 18, 0, 0), "5.125")
    await _seed_exact(fake, "CAD_POLICY_RATE", (2023, 6, 8), (2023, 6, 7, 14, 0, 0), "4.75")
    use_case = ComputePolicyRateDifferential(repository=fake)
    as_of = _ts(2023, 7, 1)

    usd_cad = _feature(await use_case(Instrument("USD", "CAD"), as_of, RateSemantics.ANNOUNCED))
    cad_usd = _feature(await use_case(Instrument("CAD", "USD"), as_of, RateSemantics.ANNOUNCED))

    assert usd_cad.current.differential == Decimal("5.125") - Decimal("4.75")
    assert usd_cad.current.differential == -cad_usd.current.differential


@pytest.mark.asyncio
async def test_reversed_pair_reverses_sign_property() -> None:
    # FX-45 section 9's own required property test, at the full use-case
    # level (not just the pure rate_differential function).
    fake = FakeMacroObservationRepository()
    await _seed_exact(fake, "EUR_POLICY_RATE", (2023, 5, 10), (2023, 5, 4, 11, 45, 0), "3.75")
    await _seed_exact(fake, "USD_POLICY_RATE", (2023, 5, 4), (2023, 5, 3, 18, 0, 0), "5.125")
    use_case = ComputePolicyRateDifferential(repository=fake)
    as_of = _ts(2023, 6, 1)

    forward = _feature(await use_case(Instrument("EUR", "USD"), as_of, RateSemantics.ANNOUNCED))
    backward = _feature(await use_case(Instrument("USD", "EUR"), as_of, RateSemantics.ANNOUNCED))

    assert forward.current.differential == -backward.current.differential


# ---------------------------------------------------------------------------
# Announced vs effective divergence, at the full feature level
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_announced_and_effective_differentials_diverge() -> None:
    fake = FakeMacroObservationRepository()
    # USD: decision 2026-09-16 14:00 ET (18:00 UTC), effective 2026-09-17.
    await _seed_exact(
        fake,
        "USD_POLICY_RATE",
        (2025, 12, 11),
        (2025, 12, 10, 19, 0, 0),
        "3.625",
        effective_at=(2025, 12, 11),
    )
    await _seed_exact(
        fake,
        "USD_POLICY_RATE",
        (2026, 9, 17),
        (2026, 9, 16, 18, 0, 0),
        "3.875",
        effective_at=(2026, 9, 17),
    )
    # EUR: stable throughout -- isolates the differential's movement to USD alone.
    await _seed_exact(
        fake,
        "EUR_POLICY_RATE",
        (2025, 6, 11),
        (2025, 6, 5, 11, 45, 0),
        "2.15",
        effective_at=(2025, 6, 11),
    )
    use_case = ComputePolicyRateDifferential(repository=fake)
    just_after_release = UtcTimestamp(datetime(2026, 9, 16, 18, 1, 0, tzinfo=UTC))

    announced = _feature(
        await use_case(Instrument("USD", "EUR"), just_after_release, RateSemantics.ANNOUNCED)
    )
    effective = _feature(
        await use_case(Instrument("USD", "EUR"), just_after_release, RateSemantics.EFFECTIVE)
    )

    assert announced.current.differential != effective.current.differential
    assert announced.current.base.rate == Decimal("3.875")  # NEW
    assert effective.current.base.rate == Decimal("3.625")  # still OLD


@pytest.mark.asyncio
async def test_future_announcement_invisible_before_released_at() -> None:
    fake = FakeMacroObservationRepository()
    await _seed_exact(
        fake,
        "USD_POLICY_RATE",
        (2025, 12, 11),
        (2025, 12, 10, 19, 0, 0),
        "3.625",
        effective_at=(2025, 12, 11),
    )
    await _seed_exact(
        fake,
        "USD_POLICY_RATE",
        (2026, 9, 17),
        (2026, 9, 16, 18, 0, 0),
        "3.875",
        effective_at=(2026, 9, 17),
    )
    await _seed_exact(fake, "EUR_POLICY_RATE", (2025, 6, 11), (2025, 6, 5, 11, 45, 0), "2.15")
    use_case = ComputePolicyRateDifferential(repository=fake)
    just_before_release = UtcTimestamp(datetime(2026, 9, 16, 17, 59, 59, tzinfo=UTC))

    result = _feature(
        await use_case(Instrument("USD", "EUR"), just_before_release, RateSemantics.ANNOUNCED)
    )

    assert result.current.base.rate == Decimal("3.625")  # still OLD, one second before release


@pytest.mark.asyncio
async def test_effective_rate_does_not_change_early() -> None:
    fake = FakeMacroObservationRepository()
    await _seed_exact(
        fake,
        "USD_POLICY_RATE",
        (2025, 12, 11),
        (2025, 12, 10, 19, 0, 0),
        "3.625",
        effective_at=(2025, 12, 11),
    )
    await _seed_exact(
        fake,
        "USD_POLICY_RATE",
        (2026, 9, 17),
        (2026, 9, 16, 18, 0, 0),
        "3.875",
        effective_at=(2026, 9, 17),
    )
    await _seed_exact(
        fake,
        "EUR_POLICY_RATE",
        (2025, 6, 11),
        (2025, 6, 5, 11, 45, 0),
        "2.15",
        effective_at=(2025, 6, 11),
    )
    use_case = ComputePolicyRateDifferential(repository=fake)
    # Well after release, but before the effective date.
    after_release_before_effective = UtcTimestamp(datetime(2026, 9, 16, 23, 59, 59, tzinfo=UTC))

    result = _feature(
        await use_case(
            Instrument("USD", "EUR"), after_release_before_effective, RateSemantics.EFFECTIVE
        )
    )

    assert result.current.base.rate == Decimal("3.625")  # still OLD


# ---------------------------------------------------------------------------
# FX-45 section 10's mandatory three-state regression, at the full
# feature level (announced vs effective differential, not just one leg).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_three_state_regression_around_the_real_2026_09_17_observation() -> None:
    fake = FakeMacroObservationRepository()
    await _seed_exact(
        fake,
        "USD_POLICY_RATE",
        (2025, 12, 11),
        (2025, 12, 10, 19, 0, 0),
        "3.625",
        effective_at=(2025, 12, 11),
    )
    await _seed_exact(
        fake,
        "USD_POLICY_RATE",
        (2026, 9, 17),
        (2026, 9, 16, 18, 0, 0),
        "3.875",
        effective_at=(2026, 9, 17),
    )
    await _seed_exact(
        fake,
        "EUR_POLICY_RATE",
        (2025, 6, 11),
        (2025, 6, 5, 11, 45, 0),
        "2.15",
        effective_at=(2025, 6, 11),
    )
    use_case = ComputePolicyRateDifferential(repository=fake)
    instrument = Instrument("USD", "EUR")
    old_differential = Decimal("3.625") - Decimal("2.15")
    new_differential = Decimal("3.875") - Decimal("2.15")

    just_before_release = UtcTimestamp(datetime(2026, 9, 16, 17, 59, 59, tzinfo=UTC))
    just_after_release = UtcTimestamp(datetime(2026, 9, 16, 18, 1, 0, tzinfo=UTC))
    once_effective = UtcTimestamp(datetime(2026, 9, 17, 0, 0, 0, tzinfo=UTC))

    # Immediately before release: both states = OLD.
    announced = _feature(await use_case(instrument, just_before_release, RateSemantics.ANNOUNCED))
    effective = _feature(await use_case(instrument, just_before_release, RateSemantics.EFFECTIVE))
    assert announced.current.differential == old_differential
    assert effective.current.differential == old_differential

    # Immediately after release, before effective: announced = NEW, effective = OLD.
    announced = _feature(await use_case(instrument, just_after_release, RateSemantics.ANNOUNCED))
    effective = _feature(await use_case(instrument, just_after_release, RateSemantics.EFFECTIVE))
    assert announced.current.differential == new_differential
    assert effective.current.differential == old_differential

    # Once effective: both = NEW.
    announced = _feature(await use_case(instrument, once_effective, RateSemantics.ANNOUNCED))
    effective = _feature(await use_case(instrument, once_effective, RateSemantics.EFFECTIVE))
    assert announced.current.differential == new_differential
    assert effective.current.differential == new_differential


# ---------------------------------------------------------------------------
# FX-45H section 3 -- a future, not-yet-released observation must not
# block a query evaluated before it existed; a released-but-future-
# effective observation must still remain visible under ANNOUNCED.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_future_unreleased_provisional_observation_does_not_block() -> None:
    # Mirrors the real 1998-10-08/1998-10-15 USD finding: a provisional
    # observation whose own observation_period/released_at lies a few
    # days in the FUTURE relative to as_of -- well inside the 14-day
    # axis-safety margin -- must not block a query evaluated before it
    # was ever released.
    fake = FakeMacroObservationRepository()
    await _seed_exact(fake, "USD_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 18, 0, 0), "5.375")
    # Not yet released as of as_of below.
    await _seed_provisional(fake, "USD_POLICY_RATE", (2024, 6, 8), (2024, 6, 8), "5.625")
    await _seed_exact(fake, "EUR_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 11, 45, 0), "4.00")
    use_case = ComputePolicyRateDifferential(repository=fake)

    result = _feature(
        await use_case(Instrument("USD", "EUR"), _ts(2024, 6, 1), RateSemantics.ANNOUNCED)
    )

    assert result.current.base.rate == Decimal("5.375")  # the not-yet-released row is invisible


@pytest.mark.asyncio
async def test_already_announced_future_effective_observation_remains_visible() -> None:
    # The other side of the same preservation: a decision that IS
    # already released must remain fully visible under ANNOUNCED even
    # though its own observation_period/effective_at falls a few days
    # in the future relative to as_of -- only a genuinely unreleased
    # event must be excluded.
    fake = FakeMacroObservationRepository()
    await _seed_exact(fake, "USD_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 18, 0, 0), "5.375")
    await _seed_exact(
        fake,
        "USD_POLICY_RATE",
        (2024, 6, 5),
        (2024, 5, 29, 18, 0, 0),
        "5.625",
        effective_at=(2024, 6, 5),
    )
    await _seed_exact(fake, "EUR_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 11, 45, 0), "4.00")
    use_case = ComputePolicyRateDifferential(repository=fake)

    result = _feature(
        await use_case(Instrument("USD", "EUR"), _ts(2024, 6, 1), RateSemantics.ANNOUNCED)
    )

    assert result.current.base.rate == Decimal("5.625")  # already announced, must be visible


# ---------------------------------------------------------------------------
# FX-45H section 2 -- fail closed on an intervening decision whose
# effective timing is unknown, at the full use-case level.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_effective_unavailable_when_newer_decision_has_no_effective_at() -> None:
    fake = FakeMacroObservationRepository()
    await _seed_exact(
        fake,
        "USD_POLICY_RATE",
        (2024, 1, 1),
        (2023, 12, 31, 18, 0, 0),
        "5.375",
        effective_at=(2024, 1, 1),
    )
    # A newer decision, already released, but its own effective date is
    # not yet established.
    await _seed_exact(fake, "USD_POLICY_RATE", (2024, 5, 1), (2024, 4, 30, 18, 0, 0), "5.625")
    await _seed_exact(
        fake,
        "EUR_POLICY_RATE",
        (2024, 1, 1),
        (2023, 12, 31, 11, 45, 0),
        "4.00",
        effective_at=(2024, 1, 1),
    )
    use_case = ComputePolicyRateDifferential(repository=fake)

    result = await use_case(Instrument("USD", "EUR"), _ts(2024, 6, 1), RateSemantics.EFFECTIVE)

    assert isinstance(result, DifferentialUnavailable)
    assert "USD" in result.reason
    assert "effective_at" in result.reason


# ---------------------------------------------------------------------------
# Research readiness -- carry-in, in-interval, no-baseline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_carry_in_state_is_included_when_safe() -> None:
    fake = FakeMacroObservationRepository()
    # Only a carry-in far before as_of -- no in-interval changes at all.
    await _seed_exact(fake, "USD_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 18, 0, 0), "5.375")
    await _seed_exact(fake, "EUR_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 11, 45, 0), "4.00")
    use_case = ComputePolicyRateDifferential(repository=fake)

    result = _feature(
        await use_case(Instrument("USD", "EUR"), _ts(2024, 6, 1), RateSemantics.ANNOUNCED)
    )

    assert result.current.base.rate == Decimal("5.375")


@pytest.mark.asyncio
async def test_provisional_carry_in_blocks_calculation() -> None:
    fake = FakeMacroObservationRepository()
    await _seed_provisional(fake, "USD_POLICY_RATE", (2024, 1, 1), (2024, 1, 1), "5.375")
    await _seed_exact(fake, "EUR_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 11, 45, 0), "4.00")
    use_case = ComputePolicyRateDifferential(repository=fake)

    with pytest.raises(ResearchIntervalNotReadyError):
        await use_case(Instrument("USD", "EUR"), _ts(2024, 6, 1), RateSemantics.ANNOUNCED)


@pytest.mark.asyncio
async def test_provisional_in_interval_observation_blocks_calculation() -> None:
    fake = FakeMacroObservationRepository()
    await _seed_exact(fake, "USD_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 18, 0, 0), "5.375")
    # A provisional change INSIDE the ~6-month lookback window, before as_of.
    await _seed_provisional(fake, "USD_POLICY_RATE", (2024, 3, 1), (2024, 3, 1), "5.125")
    await _seed_exact(fake, "EUR_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 11, 45, 0), "4.00")
    use_case = ComputePolicyRateDifferential(repository=fake)

    with pytest.raises(ResearchIntervalNotReadyError) as exc_info:
        await use_case(Instrument("USD", "EUR"), _ts(2024, 6, 1), RateSemantics.ANNOUNCED)

    assert not exc_info.value.no_baseline
    assert any(v.observation_period == _ts(2024, 3, 1) for v in exc_info.value.provisional_vintages)


@pytest.mark.asyncio
async def test_no_baseline_blocks_calculation() -> None:
    fake = FakeMacroObservationRepository()
    await _seed_exact(fake, "EUR_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 11, 45, 0), "4.00")
    # USD has NO history at all.
    use_case = ComputePolicyRateDifferential(repository=fake)

    with pytest.raises(ResearchIntervalNotReadyError) as exc_info:
        await use_case(Instrument("USD", "EUR"), _ts(2024, 6, 1), RateSemantics.ANNOUNCED)

    assert exc_info.value.no_baseline


# ---------------------------------------------------------------------------
# Unsupported currencies -- fail closed, never synthesize a zero rate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usd_jpy_unavailable() -> None:
    # JPY is a registered canonical currency (FX-42H/FX-42H.1) with ZERO
    # ingested history (FX-43/FX-43H) -- this manifests as a raised
    # ResearchIntervalNotReadyError(no_baseline=True), the same fail-closed
    # mechanism used throughout this story, not a special case.
    fake = FakeMacroObservationRepository()
    await _seed_exact(fake, "USD_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 18, 0, 0), "5.375")
    use_case = ComputePolicyRateDifferential(repository=fake)

    with pytest.raises(ResearchIntervalNotReadyError) as exc_info:
        await use_case(Instrument("USD", "JPY"), _ts(2024, 6, 1), RateSemantics.ANNOUNCED)

    assert exc_info.value.no_baseline


@pytest.mark.asyncio
async def test_xau_usd_unavailable() -> None:
    # XAU is not a currency with a canonical policy rate at all -- returned,
    # not raised, and never touches the repository.
    fake = FakeMacroObservationRepository()
    use_case = ComputePolicyRateDifferential(repository=fake)

    result = await use_case(Instrument("XAU", "USD"), _ts(2024, 6, 1), RateSemantics.ANNOUNCED)

    assert isinstance(result, DifferentialUnavailable)
    assert "XAU" in result.reason


@pytest.mark.asyncio
async def test_effective_semantics_unavailable_when_effective_at_never_populated() -> None:
    # FX-45 section 6: a currency whose EXACT-tier vintages never had a
    # verified effective_at (this story's real GBP/CAD situation) must
    # report EFFECTIVE as unavailable, not silently fall back to
    # released_at or observation_period.
    fake = FakeMacroObservationRepository()
    await _seed_exact(
        fake, "GBP_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 12, 0, 0), "5.25"
    )  # no effective_at
    await _seed_exact(
        fake,
        "USD_POLICY_RATE",
        (2024, 1, 1),
        (2023, 12, 31, 18, 0, 0),
        "5.375",
        effective_at=(2024, 1, 1),
    )
    use_case = ComputePolicyRateDifferential(repository=fake)

    result = await use_case(Instrument("GBP", "USD"), _ts(2024, 6, 1), RateSemantics.EFFECTIVE)

    assert isinstance(result, DifferentialUnavailable)
    assert "GBP" in result.reason
    assert "effective_at" in result.reason


# ---------------------------------------------------------------------------
# 3m/6m change unavailable when history is insufficient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_3m_and_6m_unavailable_with_insufficient_history() -> None:
    fake = FakeMacroObservationRepository()
    # Only ONE change point, one month before as_of -- nothing 3 or 6
    # months back.
    await _seed_exact(fake, "USD_POLICY_RATE", (2024, 5, 1), (2024, 4, 30, 18, 0, 0), "5.375")
    await _seed_exact(fake, "EUR_POLICY_RATE", (2024, 5, 1), (2024, 4, 30, 11, 45, 0), "4.00")
    use_case = ComputePolicyRateDifferential(repository=fake)

    result = _feature(
        await use_case(Instrument("USD", "EUR"), _ts(2024, 6, 1), RateSemantics.ANNOUNCED)
    )

    assert result.change_3m is None
    assert result.direction_3m is None
    assert result.change_6m is None
    assert result.direction_6m is None
    assert result.change_since_previous is None  # no previous observation either
    assert result.current.differential == Decimal("5.375") - Decimal("4.00")  # current still works


# ---------------------------------------------------------------------------
# Direction classification, end to end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_widening_narrowing_unchanged_end_to_end() -> None:
    fake = FakeMacroObservationRepository()
    # USD steps: 4.875 (Jan) -> 5.375 (May, +0.5) -- differential widens.
    await _seed_exact(fake, "USD_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 18, 0, 0), "4.875")
    await _seed_exact(fake, "USD_POLICY_RATE", (2024, 5, 1), (2024, 4, 30, 18, 0, 0), "5.375")
    await _seed_exact(fake, "EUR_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 11, 45, 0), "4.00")
    use_case = ComputePolicyRateDifferential(repository=fake)

    result = _feature(
        await use_case(Instrument("USD", "EUR"), _ts(2024, 6, 1), RateSemantics.ANNOUNCED)
    )

    assert result.change_since_previous == Decimal("0.5")
    assert result.direction_since_previous is DifferentialDirection.WIDENING


@pytest.mark.asyncio
async def test_unchanged_when_the_mover_reverts_to_the_same_differential() -> None:
    fake = FakeMacroObservationRepository()
    await _seed_exact(fake, "USD_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 18, 0, 0), "5.00")
    await _seed_exact(fake, "USD_POLICY_RATE", (2024, 5, 1), (2024, 4, 30, 18, 0, 0), "5.00")
    await _seed_exact(fake, "EUR_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 11, 45, 0), "4.00")
    use_case = ComputePolicyRateDifferential(repository=fake)

    result = _feature(
        await use_case(Instrument("USD", "EUR"), _ts(2024, 6, 1), RateSemantics.ANNOUNCED)
    )

    assert result.change_since_previous == Decimal("0")
    assert result.direction_since_previous is DifferentialDirection.UNCHANGED


# ---------------------------------------------------------------------------
# Determinism / no float
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deterministic_output_for_identical_inputs() -> None:
    fake = FakeMacroObservationRepository()
    await _seed_exact(fake, "USD_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 18, 0, 0), "5.375")
    await _seed_exact(fake, "EUR_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 11, 45, 0), "4.00")
    use_case = ComputePolicyRateDifferential(repository=fake)
    instrument = Instrument("USD", "EUR")
    as_of = _ts(2024, 6, 1)

    first = _feature(await use_case(instrument, as_of, RateSemantics.ANNOUNCED))
    second = _feature(await use_case(instrument, as_of, RateSemantics.ANNOUNCED))

    assert first == second


@pytest.mark.asyncio
async def test_no_float_anywhere_in_the_result() -> None:
    fake = FakeMacroObservationRepository()
    await _seed_exact(fake, "USD_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 18, 0, 0), "5.375")
    await _seed_exact(fake, "EUR_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 11, 45, 0), "4.00")
    use_case = ComputePolicyRateDifferential(repository=fake)

    result = _feature(
        await use_case(Instrument("USD", "EUR"), _ts(2024, 6, 1), RateSemantics.ANNOUNCED)
    )

    assert isinstance(result.current.differential, Decimal)
    assert isinstance(result.current.base.rate, Decimal)
    assert isinstance(result.current.quote.rate, Decimal)
    assert not isinstance(result.current.differential, float)

"""FX-44H: fast, DB-free tests for `RemediateReleaseTiming` against
`FakeMacroObservationRepository`. See tests/integration/
test_remediate_release_timing.py for the live-Postgres equivalents of
the core scenarios exercised here."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.use_cases.remediate_release_timing import (
    RemediateReleaseTiming,
    RemediationOutcome,
)
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.macro_observation_repository import FakeMacroObservationRepository

SERIES_KEY = "USD_POLICY_RATE"


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


def _exact_vintage(
    period_args: tuple[int, ...], released_at_args: tuple[int, ...]
) -> MacroObservationVintage:
    return MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(*period_args),
        value=Decimal("1.875"),
        released_at=_ts(*released_at_args),
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=True,
    )


@pytest.mark.asyncio
async def test_stale_exact_row_is_corrected() -> None:
    # FX-44H's own concrete case: FX-44 stored released_at equal to the
    # stored (effective) date itself, with no effective_at -- the
    # registry now resolves a genuinely different released_at plus a
    # populated effective_at.
    fake = FakeMacroObservationRepository()
    await fake.add_vintage(_exact_vintage((2018, 6, 14), (2018, 6, 14)))
    remediate = RemediateReleaseTiming(repository=fake)

    records = await remediate("USD", SERIES_KEY)

    corrected_released_at = UtcTimestamp(datetime(2018, 6, 13, 18, 0, 0, tzinfo=UTC))  # 2pm EDT

    [record] = records
    assert record.outcome is RemediationOutcome.CORRECTED
    assert record.previous_released_at == _ts(2018, 6, 14)
    assert record.corrected_released_at == corrected_released_at
    assert record.corrected_effective_at == _ts(2018, 6, 14)

    stored = await fake.observation_as_known_at(SERIES_KEY, _ts(2018, 6, 14), _ts(2099, 1, 1))
    assert stored is not None
    assert stored.released_at == corrected_released_at
    assert stored.effective_at == _ts(2018, 6, 14)
    assert stored.released_at_is_verified is True  # tier unchanged


@pytest.mark.asyncio
async def test_rerun_is_idempotent() -> None:
    # FX-44H test requirement: corrected classified rows can be
    # remediated once and are idempotent.
    fake = FakeMacroObservationRepository()
    await fake.add_vintage(_exact_vintage((2018, 6, 14), (2018, 6, 14)))
    remediate = RemediateReleaseTiming(repository=fake)

    first = await remediate("USD", SERIES_KEY)
    [first_record] = first
    assert first_record.outcome is RemediationOutcome.CORRECTED

    second = await remediate("USD", SERIES_KEY)
    [second_record] = second
    assert second_record.outcome is RemediationOutcome.ALREADY_CORRECT

    stored = await fake.observation_as_known_at(SERIES_KEY, _ts(2018, 6, 14), _ts(2099, 1, 1))
    assert stored is not None
    # unchanged by the second run
    assert stored.released_at == UtcTimestamp(datetime(2018, 6, 13, 18, 0, 0, tzinfo=UTC))


@pytest.mark.asyncio
async def test_already_correct_row_is_reported_without_writing() -> None:
    # A row whose stored timing ALREADY matches what the registry
    # resolves (e.g. hand-constructed to already be right) must be
    # reported ALREADY_CORRECT on the very first run too, not CORRECTED.
    fake = FakeMacroObservationRepository()
    already_right = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(2018, 6, 14),
        value=Decimal("1.875"),
        released_at=_ts(2018, 6, 13, 18, 0, 0),
        effective_at=_ts(2018, 6, 14),
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=True,
    )
    await fake.add_vintage(already_right)
    remediate = RemediateReleaseTiming(repository=fake)

    [record] = await remediate("USD", SERIES_KEY)

    assert record.outcome is RemediationOutcome.ALREADY_CORRECT


@pytest.mark.asyncio
async def test_provisional_row_is_not_remediated() -> None:
    # Remediation only ever touches the EXACT tier -- a plain
    # provisional row is VerifyPolicyRateReleaseTiming's concern, not
    # this mechanism's.
    fake = FakeMacroObservationRepository()
    provisional = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(2018, 6, 14),
        value=Decimal("1.875"),
        released_at=_ts(2018, 6, 14),
        revision_sequence=0,
        source="FRED",
    )
    await fake.add_vintage(provisional)
    remediate = RemediateReleaseTiming(repository=fake)

    records = await remediate("USD", SERIES_KEY)

    assert records == ()  # not even reported -- entirely out of scope


@pytest.mark.asyncio
async def test_conservative_bound_row_is_not_remediated() -> None:
    fake = FakeMacroObservationRepository()
    conservative = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(1994, 2, 4),
        value=Decimal("3.25"),
        released_at=_ts(1994, 2, 4, 23, 59, 59),
        revision_sequence=0,
        source="FRED",
        released_at_is_conservative_bound=True,
    )
    await fake.add_vintage(conservative)
    remediate = RemediateReleaseTiming(repository=fake)

    records = await remediate("USD", SERIES_KEY)

    assert records == ()


@pytest.mark.asyncio
async def test_unresolved_exact_row_is_reported_not_applicable() -> None:
    # A row that WAS exact-classified, but for a date the registry no
    # longer covers at all (e.g. a known-irregular date someone
    # incorrectly marked exact by hand) -- reported, not silently
    # dropped, but not corrected either (nothing to correct TO).
    fake = FakeMacroObservationRepository()
    irregular_but_marked_exact = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(2008, 1, 22),  # known irregular -- registry has no rule
        value=Decimal("3.5"),
        released_at=_ts(2008, 1, 22, 8, 0, 0),
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=True,
    )
    await fake.add_vintage(irregular_but_marked_exact)
    remediate = RemediateReleaseTiming(repository=fake)

    [record] = await remediate("USD", SERIES_KEY)

    assert record.outcome is RemediationOutcome.NOT_APPLICABLE
    # Untouched.
    stored = await fake.observation_as_known_at(SERIES_KEY, _ts(2008, 1, 22), _ts(2099, 1, 1))
    assert stored is not None
    assert stored.released_at == _ts(2008, 1, 22, 8, 0, 0)


@pytest.mark.asyncio
async def test_2015_12_16_and_2016_12_14_corrected_with_preserved_identity() -> None:
    # FX-44H.1: reproduces FX-44H's own historical bug -- released_at
    # already correct, effective_at wrongly equal to the stored date.
    # Proves both corrections AND that value/revision_sequence/
    # series_key/observation identity are all preserved.
    fake = FakeMacroObservationRepository()
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=_ts(2015, 12, 16),
            value=Decimal("0.375"),
            released_at=UtcTimestamp(datetime(2015, 12, 16, 19, 0, 0, tzinfo=UTC)),
            effective_at=_ts(2015, 12, 16),  # FX-44H's own bug
            revision_sequence=0,
            source="FRED",
            released_at_is_verified=True,
        )
    )
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=_ts(2016, 12, 14),
            value=Decimal("0.625"),
            released_at=UtcTimestamp(datetime(2016, 12, 14, 19, 0, 0, tzinfo=UTC)),
            effective_at=_ts(2016, 12, 14),  # FX-44H's own bug
            revision_sequence=0,
            source="FRED",
            released_at_is_verified=True,
        )
    )
    remediate = RemediateReleaseTiming(repository=fake)

    records = await remediate("USD", SERIES_KEY)
    by_period = {r.observation_period: r for r in records}
    assert by_period[_ts(2015, 12, 16)].outcome is RemediationOutcome.CORRECTED
    assert by_period[_ts(2016, 12, 14)].outcome is RemediationOutcome.CORRECTED

    result_2015 = await fake.observation_as_known_at(SERIES_KEY, _ts(2015, 12, 16), _ts(2099, 1, 1))
    assert result_2015 is not None
    assert result_2015.effective_at is not None
    assert result_2015.effective_at.value == datetime(2015, 12, 17, 0, 0, 0, tzinfo=UTC)
    assert result_2015.value == Decimal("0.375")
    assert result_2015.revision_sequence == 0
    assert result_2015.series_key == SERIES_KEY
    assert result_2015.observation_period == _ts(2015, 12, 16)

    result_2016 = await fake.observation_as_known_at(SERIES_KEY, _ts(2016, 12, 14), _ts(2099, 1, 1))
    assert result_2016 is not None
    assert result_2016.effective_at is not None
    assert result_2016.effective_at.value == datetime(2016, 12, 15, 0, 0, 0, tzinfo=UTC)
    assert result_2016.value == Decimal("0.625")
    assert result_2016.revision_sequence == 0
    assert result_2016.series_key == SERIES_KEY
    assert result_2016.observation_period == _ts(2016, 12, 14)

    # Idempotent rerun.
    second = await remediate("USD", SERIES_KEY)
    second_by_period = {r.observation_period: r for r in second}
    assert second_by_period[_ts(2015, 12, 16)].outcome is RemediationOutcome.ALREADY_CORRECT
    assert second_by_period[_ts(2016, 12, 14)].outcome is RemediationOutcome.ALREADY_CORRECT

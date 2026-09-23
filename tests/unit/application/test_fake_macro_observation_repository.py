"""FX-41: point-in-time query semantics, exercised against the fake
repository. FX-41H: conflict/idempotency hardening and deterministic
tie-breaking. `FakeMacroObservationRepository` re-implements the same
filter/order/conflict rules as `SqlAlchemyMacroObservationRepository`
-- see tests/integration/test_macro_observation_repository.py for the
live-Postgres equivalents of the scenarios below.

Core invariant under test throughout: a query at timestamp T must never
return a vintage whose released_at is after T.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.ports.macro_observation_repository import (
    MacroObservationRepository,
    MacroVintageConflictError,
    VintageWriteOutcome,
)
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.release_timing_rule import ReleaseTimingConfidence
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.macro_observation_repository import FakeMacroObservationRepository

SERIES_KEY = "US_CPI_YOY"


def _ts(*args: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(*args, tzinfo=UTC))


def test_fake_satisfies_macro_observation_repository_protocol() -> None:
    # Assignment alone is the check: mypy verifies
    # FakeMacroObservationRepository matches the MacroObservationRepository
    # Protocol shape structurally.
    fake: MacroObservationRepository = FakeMacroObservationRepository()
    assert fake is not None


@pytest.mark.asyncio
async def test_release_timing_february_observation_released_march_12() -> None:
    # FX-41 worked example: a February observation released March 12
    # 13:30 UTC must not be visible in a query the day before, and must
    # become visible from the exact release instant onward.
    fake = FakeMacroObservationRepository()
    february = _ts(2024, 2, 1)
    released_at = _ts(2024, 3, 12, 13, 30)
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=february,
            value=Decimal("3.2"),
            released_at=released_at,
            revision_sequence=0,
            source="FRED",
        )
    )

    before_release = await fake.observation_as_known_at(SERIES_KEY, february, _ts(2024, 3, 11))
    assert before_release is None

    at_release = await fake.observation_as_known_at(SERIES_KEY, february, released_at)
    assert at_release is not None
    assert at_release.value == Decimal("3.2")

    after_release = await fake.observation_as_known_at(
        SERIES_KEY, february, _ts(2024, 3, 12, 13, 31)
    )
    assert after_release is not None
    assert after_release.value == Decimal("3.2")


@pytest.mark.asyncio
async def test_revision_initial_value_then_later_revision() -> None:
    # FX-41 worked example: initial value 2.1 available July 1; revision
    # 2.4 available August 1. A query at July 15 returns 2.1; a query at
    # August 15 returns 2.4 -- the earlier vintage is never overwritten,
    # it simply stops being the most recent one as of a later as-of time.
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=period,
            value=Decimal("2.1"),
            released_at=_ts(2024, 7, 1),
            revision_sequence=0,
            source="FRED",
        )
    )
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=period,
            value=Decimal("2.4"),
            released_at=_ts(2024, 8, 1),
            revision_sequence=1,
            source="FRED",
        )
    )

    as_of_july_15 = await fake.observation_as_known_at(SERIES_KEY, period, _ts(2024, 7, 15))
    assert as_of_july_15 is not None
    assert as_of_july_15.value == Decimal("2.1")

    as_of_august_15 = await fake.observation_as_known_at(SERIES_KEY, period, _ts(2024, 8, 15))
    assert as_of_august_15 is not None
    assert as_of_august_15.value == Decimal("2.4")


@pytest.mark.asyncio
async def test_no_future_leakage_earlier_query_cannot_see_later_vintage() -> None:
    # Explicit no-future-leakage test: a vintage released in the future
    # relative to the as-of time must never be returned, by either query
    # method.
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    future_vintage = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=Decimal("99.9"),
        released_at=_ts(2099, 1, 1),
        revision_sequence=0,
        source="FRED",
    )
    await fake.add_vintage(future_vintage)

    assert await fake.observation_as_known_at(SERIES_KEY, period, _ts(2024, 1, 1)) is None
    assert await fake.latest_available_as_of(SERIES_KEY, _ts(2024, 1, 1)) is None


@pytest.mark.asyncio
async def test_latest_available_as_of_ignores_unreleased_future_period() -> None:
    fake = FakeMacroObservationRepository()
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=_ts(2024, 1, 1),
            value=Decimal("3.0"),
            released_at=_ts(2024, 2, 12),
            revision_sequence=0,
            source="FRED",
        )
    )
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=_ts(2024, 2, 1),
            value=Decimal("3.4"),
            released_at=_ts(2024, 3, 12),
            revision_sequence=0,
            source="FRED",
        )
    )

    # Both periods released by this point -- the February one is newer.
    result = await fake.latest_available_as_of(SERIES_KEY, _ts(2024, 4, 1))
    assert result is not None
    assert result.observation_period == _ts(2024, 2, 1)
    assert result.value == Decimal("3.4")

    # Only January has been released by this point.
    result = await fake.latest_available_as_of(SERIES_KEY, _ts(2024, 2, 20))
    assert result is not None
    assert result.observation_period == _ts(2024, 1, 1)
    assert result.value == Decimal("3.0")


@pytest.mark.asyncio
async def test_latest_available_as_of_reflects_most_recent_known_revision() -> None:
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=period,
            value=Decimal("2.1"),
            released_at=_ts(2024, 7, 1),
            revision_sequence=0,
            source="FRED",
        )
    )
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=period,
            value=Decimal("2.4"),
            released_at=_ts(2024, 8, 1),
            revision_sequence=1,
            source="FRED",
        )
    )

    result = await fake.latest_available_as_of(SERIES_KEY, _ts(2024, 7, 15))
    assert result is not None
    assert result.value == Decimal("2.1")

    result = await fake.latest_available_as_of(SERIES_KEY, _ts(2024, 8, 15))
    assert result is not None
    assert result.value == Decimal("2.4")


@pytest.mark.asyncio
async def test_add_vintage_is_idempotent_for_identical_identity() -> None:
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    vintage = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=Decimal("2.1"),
        released_at=_ts(2024, 7, 1),
        revision_sequence=0,
        source="FRED",
    )
    await fake.add_vintage(vintage)
    await fake.add_vintage(vintage)

    assert len(fake._vintages) == 1  # whitebox check of the fake itself


@pytest.mark.asyncio
async def test_different_series_do_not_leak_into_each_other() -> None:
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    await fake.add_vintage(
        MacroObservationVintage(
            series_key="US_CPI_YOY",
            observation_period=period,
            value=Decimal("2.1"),
            released_at=_ts(2024, 7, 1),
            revision_sequence=0,
            source="FRED",
        )
    )

    result = await fake.observation_as_known_at("EA_CPI_YOY", period, _ts(2024, 8, 1))
    assert result is None


def _base_vintage(period: UtcTimestamp) -> MacroObservationVintage:
    return MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=Decimal("2.1"),
        released_at=_ts(2024, 7, 1),
        revision_sequence=0,
        source="FRED",
    )


@pytest.mark.asyncio
async def test_exact_duplicate_add_vintage_succeeds_without_duplicating() -> None:
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    vintage = _base_vintage(period)

    first = await fake.add_vintage(vintage)
    second = await fake.add_vintage(vintage)  # must not raise

    assert first is VintageWriteOutcome.INSERTED
    assert second is VintageWriteOutcome.ALREADY_PRESENT
    assert len(fake._vintages) == 1


@pytest.mark.asyncio
async def test_same_identity_different_value_is_a_conflict() -> None:
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    original = _base_vintage(period)
    different_value = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=Decimal("9.9"),
        released_at=original.released_at,
        revision_sequence=0,
        source="FRED",
    )
    await fake.add_vintage(original)

    with pytest.raises(MacroVintageConflictError):
        await fake.add_vintage(different_value)

    result = await fake.observation_as_known_at(SERIES_KEY, period, _ts(2024, 7, 15))
    assert result is not None
    assert result.value == Decimal("2.1")


@pytest.mark.asyncio
async def test_same_identity_different_released_at_is_a_conflict() -> None:
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    original = _base_vintage(period)
    different_released_at = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=original.value,
        released_at=_ts(2024, 7, 2),
        revision_sequence=0,
        source="FRED",
    )
    await fake.add_vintage(original)

    with pytest.raises(MacroVintageConflictError):
        await fake.add_vintage(different_released_at)

    result = await fake.observation_as_known_at(SERIES_KEY, period, _ts(2024, 7, 15))
    assert result is not None
    assert result.released_at == original.released_at


@pytest.mark.asyncio
async def test_same_identity_different_source_is_a_conflict() -> None:
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    original = _base_vintage(period)
    different_source = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=original.value,
        released_at=original.released_at,
        revision_sequence=0,
        source="ECB_SDW",
    )
    await fake.add_vintage(original)

    with pytest.raises(MacroVintageConflictError):
        await fake.add_vintage(different_source)

    result = await fake.observation_as_known_at(SERIES_KEY, period, _ts(2024, 7, 15))
    assert result is not None
    assert result.source == "FRED"


@pytest.mark.asyncio
async def test_same_identity_different_effective_at_is_a_conflict() -> None:
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    original = _base_vintage(period)
    different_effective_at = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=original.value,
        released_at=original.released_at,
        revision_sequence=0,
        source="FRED",
        effective_at=_ts(2024, 8, 1),
    )
    await fake.add_vintage(original)

    with pytest.raises(MacroVintageConflictError):
        await fake.add_vintage(different_effective_at)

    result = await fake.observation_as_known_at(SERIES_KEY, period, _ts(2024, 7, 15))
    assert result is not None
    assert result.effective_at is None


@pytest.mark.asyncio
async def test_conflict_error_carries_existing_and_incoming_vintages() -> None:
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    original = _base_vintage(period)
    conflicting = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=Decimal("9.9"),
        released_at=original.released_at,
        revision_sequence=0,
        source="FRED",
    )
    await fake.add_vintage(original)

    with pytest.raises(MacroVintageConflictError) as excinfo:
        await fake.add_vintage(conflicting)

    assert excinfo.value.existing.value == Decimal("2.1")
    assert excinfo.value.incoming.value == Decimal("9.9")


@pytest.mark.asyncio
async def test_tie_break_by_revision_sequence_when_released_at_matches() -> None:
    # FX-41H: two vintages of the same observation_period sharing the same
    # released_at must resolve deterministically to the higher
    # revision_sequence.
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    shared_released_at = _ts(2024, 7, 1)
    lower_revision = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=Decimal("2.1"),
        released_at=shared_released_at,
        revision_sequence=0,
        source="FRED",
    )
    higher_revision = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=Decimal("2.4"),
        released_at=shared_released_at,
        revision_sequence=1,
        source="FRED",
    )
    # Inserted in ascending order so a naive "first match wins" scan would
    # return the wrong (lower-revision) vintage.
    await fake.add_vintage(lower_revision)
    await fake.add_vintage(higher_revision)

    known_at = await fake.observation_as_known_at(SERIES_KEY, period, _ts(2024, 7, 15))
    assert known_at is not None
    assert known_at.value == Decimal("2.4")
    assert known_at.revision_sequence == 1

    latest = await fake.latest_available_as_of(SERIES_KEY, _ts(2024, 7, 15))
    assert latest is not None
    assert latest.value == Decimal("2.4")
    assert latest.revision_sequence == 1


# ---------------------------------------------------------------------------
# FX-43H: replace_provisional_release_timing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replace_provisional_release_timing_corrects_in_place() -> None:
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    proxy_released_at = period  # FX-43's own convention: proxy == observation_period
    provisional = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=Decimal("2.1"),
        released_at=proxy_released_at,
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=False,
    )
    await fake.add_vintage(provisional)

    verified_released_at = _ts(2024, 5, 30)  # the real announcement preceded the proxy date
    verified_effective_at = period
    await fake.replace_provisional_release_timing(
        SERIES_KEY,
        period,
        0,
        verified_released_at,
        verified_effective_at,
        ReleaseTimingConfidence.EXACT,
    )

    corrected = await fake.observation_as_known_at(SERIES_KEY, period, verified_released_at)
    assert corrected is not None
    assert corrected.released_at == verified_released_at
    assert corrected.effective_at == verified_effective_at
    assert corrected.released_at_is_verified is True
    assert corrected.released_at_is_conservative_bound is False
    assert corrected.value == Decimal("2.1")  # the economic value never changed
    assert corrected.revision_sequence == 0  # never treated as a revision


@pytest.mark.asyncio
async def test_replace_provisional_release_timing_leaves_no_second_visible_row() -> None:
    # The story's own critical property: a corrected release timestamp
    # must not coexist with an earlier proxy row a historical as-of query
    # could accidentally see.
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    proxy_released_at = _ts(2024, 7, 1)
    provisional = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=Decimal("2.1"),
        released_at=proxy_released_at,
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=False,
    )
    await fake.add_vintage(provisional)

    verified_released_at = _ts(2024, 6, 15)  # earlier than the proxy
    await fake.replace_provisional_release_timing(
        SERIES_KEY, period, 0, verified_released_at, None, ReleaseTimingConfidence.EXACT
    )

    # A query at the OLD proxy's released_at must now see the CORRECTED
    # timestamp reasoning, not a stale second row -- there is only ever
    # one row for this identity.
    result = await fake.observation_as_known_at(SERIES_KEY, period, proxy_released_at)
    assert result is not None
    assert result.released_at == verified_released_at  # not the old proxy value
    assert len(fake._vintages) == 1


@pytest.mark.asyncio
async def test_replace_provisional_release_timing_rejects_missing_identity() -> None:
    fake = FakeMacroObservationRepository()

    with pytest.raises(ValueError, match="no vintage exists"):
        await fake.replace_provisional_release_timing(
            SERIES_KEY, _ts(2024, 6, 1), 0, _ts(2024, 6, 1), None, ReleaseTimingConfidence.EXACT
        )


@pytest.mark.asyncio
async def test_replace_provisional_release_timing_rejects_already_verified_row() -> None:
    # FX-43H fail-closed guarantee: this method must never silently
    # rewrite an already-verified timestamp.
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    already_verified = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=Decimal("2.1"),
        released_at=_ts(2024, 7, 1),
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=True,
    )
    await fake.add_vintage(already_verified)

    with pytest.raises(ValueError, match="already released_at_is_verified=True"):
        await fake.replace_provisional_release_timing(
            SERIES_KEY, period, 0, _ts(2024, 6, 15), None, ReleaseTimingConfidence.EXACT
        )


@pytest.mark.asyncio
async def test_replace_provisional_release_timing_rejects_already_conservative_row() -> None:
    # FX-44: the symmetric fail-closed guarantee for the OTHER outcome
    # flag -- a conservative-safe-bound row must never be silently
    # rewritten either, not just an exact-verified one.
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    already_conservative = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=Decimal("2.1"),
        released_at=_ts(2024, 7, 1),
        revision_sequence=0,
        source="FRED",
        released_at_is_conservative_bound=True,
    )
    await fake.add_vintage(already_conservative)

    with pytest.raises(ValueError, match="already released_at_is_conservative_bound=True"):
        await fake.replace_provisional_release_timing(
            SERIES_KEY, period, 0, _ts(2024, 6, 15), None, ReleaseTimingConfidence.EXACT
        )

    # Untouched.
    result = await fake.observation_as_known_at(SERIES_KEY, period, _ts(2024, 7, 1))
    assert result is not None
    assert result.released_at == _ts(2024, 7, 1)


# ---------------------------------------------------------------------------
# FX-44H: correct_verified_release_timing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correct_verified_release_timing_corrects_a_stale_exact_row() -> None:
    fake = FakeMacroObservationRepository()
    period = _ts(2018, 6, 14)
    stale = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=Decimal("1.875"),
        released_at=_ts(2018, 6, 14),  # FX-44's original, wrong value
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=True,
    )
    await fake.add_vintage(stale)

    corrected_released_at = _ts(2018, 6, 13)
    corrected_effective_at = _ts(2018, 6, 14)
    await fake.correct_verified_release_timing(
        SERIES_KEY,
        period,
        0,
        expected_current_released_at=_ts(2018, 6, 14),
        expected_current_effective_at=None,
        corrected_released_at=corrected_released_at,
        corrected_effective_at=corrected_effective_at,
    )

    result = await fake.observation_as_known_at(SERIES_KEY, period, _ts(2099, 1, 1))
    assert result is not None
    assert result.released_at == corrected_released_at
    assert result.effective_at == corrected_effective_at
    assert result.released_at_is_verified is True  # tier unchanged
    assert result.value == Decimal("1.875")  # value untouched
    assert result.revision_sequence == 0  # never treated as a revision


@pytest.mark.asyncio
async def test_correct_verified_release_timing_is_idempotent_on_rerun() -> None:
    # FX-44H test requirement: corrected classified rows can be
    # remediated once and are idempotent.
    fake = FakeMacroObservationRepository()
    period = _ts(2018, 6, 14)
    stale = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=Decimal("1.875"),
        released_at=_ts(2018, 6, 14),
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=True,
    )
    await fake.add_vintage(stale)

    await fake.correct_verified_release_timing(
        SERIES_KEY,
        period,
        0,
        expected_current_released_at=_ts(2018, 6, 14),
        expected_current_effective_at=None,
        corrected_released_at=_ts(2018, 6, 13),
        corrected_effective_at=_ts(2018, 6, 14),
    )

    # A second attempt using the SAME (now stale) expected_current_released_at
    # must fail closed, not silently reapply.
    with pytest.raises(ValueError, match="already corrected"):
        await fake.correct_verified_release_timing(
            SERIES_KEY,
            period,
            0,
            expected_current_released_at=_ts(2018, 6, 14),
            expected_current_effective_at=None,
            corrected_released_at=_ts(2018, 6, 13),
            corrected_effective_at=_ts(2018, 6, 14),
        )

    result = await fake.observation_as_known_at(SERIES_KEY, period, _ts(2099, 1, 1))
    assert result is not None
    assert result.released_at == _ts(2018, 6, 13)  # unchanged by the rejected second attempt


@pytest.mark.asyncio
async def test_correct_verified_release_timing_rejects_missing_identity() -> None:
    fake = FakeMacroObservationRepository()

    with pytest.raises(ValueError, match="no vintage exists"):
        await fake.correct_verified_release_timing(
            SERIES_KEY,
            _ts(2018, 6, 14),
            0,
            expected_current_released_at=_ts(2018, 6, 14),
            expected_current_effective_at=None,
            corrected_released_at=_ts(2018, 6, 13),
            corrected_effective_at=_ts(2018, 6, 14),
        )


@pytest.mark.asyncio
async def test_correct_verified_release_timing_rejects_non_verified_row() -> None:
    # A still-provisional (or conservative-bound) row has nothing to
    # "correct" via this method -- it isn't in the EXACT tier at all.
    fake = FakeMacroObservationRepository()
    period = _ts(2018, 6, 14)
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=period,
            value=Decimal("1.875"),
            released_at=period,
            revision_sequence=0,
            source="FRED",
        )
    )

    with pytest.raises(ValueError, match="not released_at_is_verified=True"):
        await fake.correct_verified_release_timing(
            SERIES_KEY,
            period,
            0,
            expected_current_released_at=period,
            expected_current_effective_at=None,
            corrected_released_at=_ts(2018, 6, 13),
            corrected_effective_at=_ts(2018, 6, 14),
        )


@pytest.mark.asyncio
async def test_correct_verified_release_timing_rejects_stale_expected_value() -> None:
    # The optimistic-concurrency guard: an expected_current_released_at
    # that does not match what's ACTUALLY stored must be rejected, not
    # blindly applied -- covers "someone already corrected this
    # differently" as well as "you never knew the real current value".
    fake = FakeMacroObservationRepository()
    period = _ts(2018, 6, 14)
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=period,
            value=Decimal("1.875"),
            released_at=_ts(2018, 6, 14),
            revision_sequence=0,
            source="FRED",
            released_at_is_verified=True,
        )
    )

    with pytest.raises(ValueError, match="does not currently have"):
        await fake.correct_verified_release_timing(
            SERIES_KEY,
            period,
            0,
            expected_current_released_at=_ts(1999, 1, 1),  # wrong -- not what's stored
            expected_current_effective_at=None,
            corrected_released_at=_ts(2018, 6, 13),
            corrected_effective_at=_ts(2018, 6, 14),
        )


@pytest.mark.asyncio
async def test_correct_verified_release_timing_has_no_value_parameter() -> None:
    import inspect

    signature = inspect.signature(FakeMacroObservationRepository.correct_verified_release_timing)
    assert "value" not in signature.parameters


@pytest.mark.asyncio
async def test_replace_provisional_release_timing_has_no_value_parameter() -> None:
    # Structural guarantee, not just a runtime check: the method signature
    # itself has no way to pass a different economic value -- a genuine
    # value correction can only go through add_vintage as a new revision.
    import inspect

    signature = inspect.signature(FakeMacroObservationRepository.replace_provisional_release_timing)
    assert "value" not in signature.parameters

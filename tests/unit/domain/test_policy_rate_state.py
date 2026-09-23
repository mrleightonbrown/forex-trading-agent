from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.policy_rate_state import (
    announced_state_as_of,
    effective_state_as_of,
    previous_announced_state,
    previous_effective_state,
)
from forex_agent.domain.timestamps import UtcTimestamp

SERIES_KEY = "USD_POLICY_RATE"


def _ts(*args: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(*args, tzinfo=UTC))


def _vintage(
    observation_period_args: tuple[int, ...],
    released_at_args: tuple[int, ...],
    value: str,
    effective_at_args: tuple[int, ...] | None = None,
    revision_sequence: int = 0,
) -> MacroObservationVintage:
    return MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(*observation_period_args),
        value=Decimal(value),
        released_at=_ts(*released_at_args),
        effective_at=None if effective_at_args is None else _ts(*effective_at_args),
        revision_sequence=revision_sequence,
        source="FRED",
        released_at_is_verified=True,
    )


# FX-44H.1's own real, verified worked example: 2026-09-16 14:00 EDT
# decision (18:00 UTC), 2026-09-17 effective. Used throughout as the
# canonical "one real change point" fixture.
_SEP_2026 = _vintage(
    (2026, 9, 17), (2026, 9, 16, 18, 0, 0), "3.875", effective_at_args=(2026, 9, 17)
)
_EARLIER = _vintage(
    (2025, 12, 11), (2025, 12, 10, 19, 0, 0), "3.625", effective_at_args=(2025, 12, 11)
)
_STILL_EARLIER = _vintage(
    (2025, 10, 30), (2025, 10, 29, 18, 0, 0), "4.125", effective_at_args=(2025, 10, 30)
)


def test_announced_state_as_of_returns_latest_released_at_before_or_at() -> None:
    vintages = [_EARLIER, _SEP_2026]

    result = announced_state_as_of(vintages, UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC)))

    assert result == _SEP_2026


def test_announced_state_as_of_excludes_future_released_at() -> None:
    # FX-45 section 1/5: a decision released Wed 14:00 ET must not be
    # visible one minute before that.
    vintages = [_EARLIER, _SEP_2026]
    just_before_release = UtcTimestamp(datetime(2026, 9, 16, 17, 59, 59, tzinfo=UTC))

    result = announced_state_as_of(vintages, just_before_release)

    assert result == _EARLIER  # not yet visible -- old state still governs


def test_announced_state_as_of_visible_exactly_at_released_at() -> None:
    vintages = [_EARLIER, _SEP_2026]
    at_release = UtcTimestamp(datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC))

    result = announced_state_as_of(vintages, at_release)

    assert result == _SEP_2026


def test_announced_state_as_of_returns_none_with_no_matching_history() -> None:
    result = announced_state_as_of([_SEP_2026], UtcTimestamp(datetime(2020, 1, 1, tzinfo=UTC)))

    assert result is None


def test_announced_state_as_of_tie_breaks_by_revision_sequence() -> None:
    same_released_at = _ts(2026, 9, 16, 18, 0, 0)
    lower_rev = _vintage((2026, 9, 17), (2026, 9, 16, 18, 0, 0), "3.875", revision_sequence=0)
    higher_rev = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(2026, 9, 17),
        value=Decimal("3.900"),
        released_at=same_released_at,
        revision_sequence=1,
        source="FRED",
        released_at_is_verified=True,
    )

    result = announced_state_as_of(
        [lower_rev, higher_rev], UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC))
    )

    assert result == higher_rev


def test_effective_state_as_of_returns_latest_effective_at_before_or_at() -> None:
    vintages = [_EARLIER, _SEP_2026]

    result = effective_state_as_of(vintages, UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC)))

    assert result == _SEP_2026


def test_effective_state_as_of_does_not_change_before_effective_date() -> None:
    # FX-45 section 1/10: announced but not yet effective.
    vintages = [_EARLIER, _SEP_2026]
    after_release_before_effective = UtcTimestamp(datetime(2026, 9, 16, 20, 0, 0, tzinfo=UTC))

    result = effective_state_as_of(vintages, after_release_before_effective)

    assert result == _EARLIER  # old rate still operationally in force


def test_effective_state_as_of_excludes_vintages_without_effective_at() -> None:
    # FX-45 section 6: never fall back to released_at/observation_period.
    no_effective_at = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(2018, 6, 14),
        value=Decimal("1.875"),
        released_at=_ts(2018, 6, 13, 18, 0, 0),
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=True,
    )

    result = effective_state_as_of(
        [no_effective_at], UtcTimestamp(datetime(2099, 1, 1, tzinfo=UTC))
    )

    assert result is None


def test_effective_state_as_of_returns_none_when_nothing_has_taken_effect_yet() -> None:
    result = effective_state_as_of([_SEP_2026], UtcTimestamp(datetime(2020, 1, 1, tzinfo=UTC)))

    assert result is None


def test_previous_announced_state_finds_the_prior_entry() -> None:
    vintages = [_STILL_EARLIER, _EARLIER, _SEP_2026]

    result = previous_announced_state(vintages, _SEP_2026)

    assert result == _EARLIER


def test_previous_announced_state_returns_none_for_earliest_entry() -> None:
    vintages = [_STILL_EARLIER, _EARLIER, _SEP_2026]

    result = previous_announced_state(vintages, _STILL_EARLIER)

    assert result is None


def test_previous_effective_state_finds_the_prior_entry() -> None:
    vintages = [_STILL_EARLIER, _EARLIER, _SEP_2026]

    result = previous_effective_state(vintages, _SEP_2026)

    assert result == _EARLIER


def test_previous_effective_state_returns_none_when_current_has_no_effective_at() -> None:
    no_effective_at = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(2018, 6, 14),
        value=Decimal("1.875"),
        released_at=_ts(2018, 6, 13, 18, 0, 0),
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=True,
    )

    result = previous_effective_state([_EARLIER, no_effective_at], no_effective_at)

    assert result is None


def test_announced_and_effective_diverge_around_a_real_verified_observation() -> None:
    # FX-45 section 1's own required regression: prove the two notions
    # genuinely diverge, using the real, FX-44H.1-verified USD case
    # (2026-09-16 14:00 ET decision, 2026-09-17 effective).
    vintages = [_EARLIER, _SEP_2026]

    just_after_release = UtcTimestamp(
        datetime(2026, 9, 16, 18, 1, 0, tzinfo=UTC)
    )  # "Wednesday 14:01"

    announced = announced_state_as_of(vintages, just_after_release)
    effective = effective_state_as_of(vintages, just_after_release)

    assert announced is not None and announced.value == Decimal("3.875")  # NEW
    assert effective is not None and effective.value == Decimal("3.625")  # still OLD
    assert announced != effective

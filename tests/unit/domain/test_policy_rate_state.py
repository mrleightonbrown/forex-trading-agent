from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.policy_rate_state import (
    announced_state_as_of,
    effective_state_as_of,
    known_as_of,
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

    result = previous_effective_state(
        vintages, _SEP_2026, UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC))
    )

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

    result = previous_effective_state(
        [_EARLIER, no_effective_at], no_effective_at, UtcTimestamp(datetime(2099, 1, 1, tzinfo=UTC))
    )

    assert result is None


def test_announced_state_as_of_includes_a_released_decision_days_before_its_own_period() -> None:
    # FX-45H section 3's own required preservation: a decision that is
    # ALREADY RELEASED remains visible under ANNOUNCED even though its
    # own observation_period/effective_at lies several days in the
    # future relative to as_of -- only a genuinely NOT-YET-RELEASED
    # vintage must be excluded, never a released-but-future-effective
    # one.
    released_early = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(2026, 9, 24),  # 7 days after released_at
        value=Decimal("4.125"),
        released_at=_ts(2026, 9, 17),
        effective_at=_ts(2026, 9, 24),
        revision_sequence=0,
        source="ECB_SDW",
        released_at_is_verified=True,
    )
    as_of = UtcTimestamp(datetime(2026, 9, 18, tzinfo=UTC))  # after release, before its own period

    result = announced_state_as_of([_EARLIER, released_early], as_of)

    assert result == released_early


# ---------------------------------------------------------------------------
# known_as_of -- FX-45H section 1/3's shared point-in-time filter
# ---------------------------------------------------------------------------


def test_known_as_of_filters_by_released_at() -> None:
    vintages = [_STILL_EARLIER, _EARLIER, _SEP_2026]

    result = known_as_of(vintages, UtcTimestamp(datetime(2025, 12, 15, tzinfo=UTC)))

    assert result == (_STILL_EARLIER, _EARLIER)  # _SEP_2026 not yet released


def test_known_as_of_is_inclusive_at_released_at() -> None:
    result = known_as_of([_SEP_2026], UtcTimestamp(datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)))

    assert result == (_SEP_2026,)


def test_known_as_of_excludes_strictly_future_released_at() -> None:
    result = known_as_of([_SEP_2026], UtcTimestamp(datetime(2026, 9, 16, 17, 59, 59, tzinfo=UTC)))

    assert result == ()


# ---------------------------------------------------------------------------
# FX-45H section 1 -- EFFECTIVE must be point-in-time safe: a revision
# with an OLD effective_at but a released_at still in the future must
# stay invisible before its own released_at.
# ---------------------------------------------------------------------------


def test_effective_state_as_of_excludes_a_revision_not_yet_released() -> None:
    # A retroactively-disclosed/corrected effective_at: the value for
    # the SAME decision (2025-12-11) is corrected, but not published
    # until much later. Before that publication, the ORIGINAL vintage
    # must still govern -- the correction must not leak in early.
    late_revision = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(2025, 12, 11),
        value=Decimal("3.600"),
        released_at=_ts(2026, 9, 20),
        effective_at=_ts(2025, 12, 11),
        revision_sequence=1,
        source="FRED",
        released_at_is_verified=True,
    )
    vintages = [_EARLIER, late_revision]
    before_disclosure = UtcTimestamp(datetime(2026, 9, 19, tzinfo=UTC))

    result = effective_state_as_of(vintages, before_disclosure)

    assert result == _EARLIER
    assert result.value == Decimal("3.625")  # the ORIGINAL value, not the correction


def test_effective_state_as_of_reveals_the_revision_once_released() -> None:
    late_revision = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(2025, 12, 11),
        value=Decimal("3.600"),
        released_at=_ts(2026, 9, 20),
        effective_at=_ts(2025, 12, 11),
        revision_sequence=1,
        source="FRED",
        released_at_is_verified=True,
    )
    vintages = [_EARLIER, late_revision]

    result = effective_state_as_of(vintages, UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC)))

    assert result == late_revision


# ---------------------------------------------------------------------------
# FX-45H section 2 -- fail closed on an intervening decision whose
# effective timing is unknown, for both effective_state_as_of and
# previous_effective_state.
# ---------------------------------------------------------------------------


def test_effective_state_as_of_unavailable_when_newer_decision_has_no_effective_at() -> None:
    # A newer decision has already been released (known) but its own
    # effective date is not yet established -- reporting the OLD
    # decision's rate would silently assume the new one has not yet
    # taken effect, which this code cannot verify either way.
    newer_unknown_effective = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(2026, 9, 17),
        value=Decimal("3.875"),
        released_at=_ts(2026, 9, 16, 18, 0, 0),
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=True,
        # effective_at deliberately omitted -- unknown
    )
    vintages = [_EARLIER, newer_unknown_effective]

    result = effective_state_as_of(vintages, UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC)))

    assert result is None  # NOT _EARLIER


def test_effective_state_as_of_unblocked_once_the_newer_decision_gets_its_own_effective_at() -> (
    None
):
    # Once a later revision of the SAME newer decision establishes its
    # own effective_at, the block lifts and normal EFFECTIVE semantics
    # resumes.
    newer_resolved = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(2026, 9, 17),
        value=Decimal("3.875"),
        released_at=_ts(2026, 9, 16, 18, 0, 0),
        effective_at=_ts(2026, 9, 17),
        revision_sequence=1,
        source="FRED",
        released_at_is_verified=True,
    )
    vintages = [_EARLIER, newer_resolved]

    result = effective_state_as_of(vintages, UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC)))

    assert result == newer_resolved


def test_previous_effective_state_excludes_a_not_yet_released_predecessor() -> None:
    # Symmetric with effective_state_as_of's own PIT test: a vintage
    # whose effective_at would otherwise win the "previous" search must
    # stay invisible before its own released_at.
    not_yet_released = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(2026, 3, 1),
        value=Decimal("3.750"),
        released_at=_ts(2026, 9, 20),
        effective_at=_ts(2026, 3, 1),  # otherwise the latest "previous" candidate
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=True,
    )
    vintages = [_EARLIER, not_yet_released, _SEP_2026]
    as_of = UtcTimestamp(datetime(2026, 9, 19, tzinfo=UTC))  # before not_yet_released's release

    result = previous_effective_state(vintages, _SEP_2026, as_of)

    assert result == _EARLIER  # NOT not_yet_released, despite its later effective_at


def test_previous_effective_state_unavailable_with_unresolved_intervening_decision() -> None:
    # An intervening decision (between the found predecessor and
    # current) has been released but its own effective_at is
    # unestablished -- cannot say whether THAT decision, not the found
    # predecessor, actually governed immediately before current.
    intervening_unknown_effective = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=_ts(2026, 3, 1),  # between _EARLIER and _SEP_2026
        value=Decimal("3.750"),
        released_at=_ts(2026, 2, 28, 18, 0, 0),
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=True,
        # effective_at deliberately omitted -- unknown
    )
    vintages = [_EARLIER, intervening_unknown_effective, _SEP_2026]

    result = previous_effective_state(
        vintages, _SEP_2026, UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC))
    )

    assert result is None  # NOT _EARLIER


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

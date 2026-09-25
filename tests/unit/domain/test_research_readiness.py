from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.research_readiness import (
    ResearchIntervalNotReadyError,
    is_research_safe,
    require_research_ready_interval,
    select_research_candidates,
)
from forex_agent.domain.timestamps import UtcTimestamp


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


def _vintage(period_args: tuple[int, ...], **overrides: object) -> MacroObservationVintage:
    defaults: dict[str, object] = {
        "series_key": "USD_POLICY_RATE",
        "observation_period": _ts(*period_args),
        "value": Decimal("2.0"),
        "released_at": _ts(*period_args),
        "revision_sequence": 0,
        "source": "FRED",
    }
    defaults.update(overrides)
    return MacroObservationVintage(**defaults)  # type: ignore[arg-type]


def test_is_research_safe_true_for_verified() -> None:
    vintage = _vintage((2020, 1, 1), released_at_is_verified=True)
    assert is_research_safe(vintage) is True


def test_is_research_safe_true_for_conservative_bound() -> None:
    vintage = _vintage((2020, 1, 1), released_at_is_conservative_bound=True)
    assert is_research_safe(vintage) is True


def test_is_research_safe_false_for_plain_provisional() -> None:
    vintage = _vintage((2020, 1, 1))
    assert is_research_safe(vintage) is False


def test_all_safe_interval_passes() -> None:
    vintages = [
        _vintage((2020, 1, 1), released_at_is_verified=True),
        _vintage((2020, 6, 1), released_at_is_conservative_bound=True),
    ]

    require_research_ready_interval(vintages, _ts(2020, 1, 1), _ts(2021, 1, 1))  # must not raise


def test_mixed_verified_and_provisional_range_is_rejected() -> None:
    # FX-44 test requirement: mixed verified/provisional range is
    # rejected as research-ready.
    vintages = [
        _vintage((2020, 1, 1), released_at_is_verified=True),
        _vintage((2020, 6, 1)),  # plain provisional -- fails the whole interval
    ]

    with pytest.raises(ResearchIntervalNotReadyError) as exc_info:
        require_research_ready_interval(vintages, _ts(2020, 1, 1), _ts(2021, 1, 1))

    assert len(exc_info.value.provisional_vintages) == 1
    assert exc_info.value.provisional_vintages[0].observation_period == _ts(2020, 6, 1)


def test_single_provisional_observation_fails_closed() -> None:
    # FX-44 section 8's critical invariant, verbatim: "a single
    # provisional observation in the selected research interval must
    # fail closed" -- even with only one candidate vintage.
    vintages = [_vintage((2020, 3, 1))]

    with pytest.raises(ResearchIntervalNotReadyError):
        require_research_ready_interval(vintages, _ts(2020, 1, 1), _ts(2021, 1, 1))


def test_provisional_carry_in_blocks_an_otherwise_empty_interval() -> None:
    # FX-44H's own required regression: an unresolved 2008-01-22-like
    # observation (the real USD registry's own known-irregular
    # inter-meeting date) with a February interval that contains NO
    # change points of its own at all. The rate governing every instant
    # in February 2008 is exactly the one set by the Jan 22 change --
    # if that carry-in state is provisional, the whole interval is
    # unsafe, even though nothing "inside" February looks wrong.
    vintages = [_vintage((2008, 1, 22))]  # provisional -- no rule covers this date

    with pytest.raises(ResearchIntervalNotReadyError) as exc_info:
        require_research_ready_interval(vintages, _ts(2008, 2, 1), _ts(2008, 3, 1))

    assert not exc_info.value.no_baseline
    assert len(exc_info.value.provisional_vintages) == 1
    assert exc_info.value.provisional_vintages[0].observation_period == _ts(2008, 1, 22)


def test_verified_carry_in_permits_an_otherwise_empty_interval() -> None:
    # The safe counterpart to the above: if the SAME carry-in change is
    # verified instead, an interval with no in-interval changes at all
    # passes cleanly -- proves this isn't "no data ever passes", only
    # "unsafe or missing data never passes".
    vintages = [_vintage((2008, 1, 22), released_at_is_verified=True)]

    require_research_ready_interval(vintages, _ts(2008, 2, 1), _ts(2008, 3, 1))  # must not raise


def test_superseded_provisional_vintage_does_not_block() -> None:
    # A provisional vintage that is NOT the carry-in (a later, verified
    # change supersedes it before the interval even starts) must not
    # block -- distinct from the old, incorrect assumption that
    # anything merely "outside the interval" is automatically safe to
    # ignore (see test_provisional_carry_in_blocks_an_otherwise_empty_
    # interval above, where an outside-the-interval vintage DOES block
    # because it IS the carry-in).
    vintages = [
        _vintage((2018, 1, 1)),  # provisional, but superseded before the interval starts
        _vintage((2019, 1, 1), released_at_is_verified=True),  # the TRUE carry-in
        _vintage((2020, 6, 1), released_at_is_verified=True),  # in-interval
    ]

    require_research_ready_interval(vintages, _ts(2020, 1, 1), _ts(2021, 1, 1))  # must not raise


def test_interval_end_is_exclusive() -> None:
    vintages = [
        _vintage((2019, 1, 1), released_at_is_verified=True),  # carry-in, keeps this non-empty
        _vintage((2021, 1, 1)),  # provisional, but exactly AT interval_end -- excluded
    ]

    require_research_ready_interval(vintages, _ts(2020, 1, 1), _ts(2021, 1, 1))  # must not raise


def test_empty_candidate_set_fails_closed() -> None:
    # FX-44H: "an empty/incomplete candidate set must not silently pass
    # as research-ready" -- no history at all for this series is worse
    # than "provisional", not vacuously fine.
    with pytest.raises(ResearchIntervalNotReadyError) as exc_info:
        require_research_ready_interval([], _ts(2020, 1, 1), _ts(2021, 1, 1))

    assert exc_info.value.no_baseline is True
    assert exc_info.value.provisional_vintages == ()


def test_no_baseline_interval_fails_closed_even_with_unrelated_history() -> None:
    # History exists for the series, but none of it is at-or-before
    # interval_start and none of it falls inside the interval either --
    # still an empty candidate set for THIS interval.
    vintages = [_vintage((2030, 1, 1), released_at_is_verified=True)]  # entirely after

    with pytest.raises(ResearchIntervalNotReadyError) as exc_info:
        require_research_ready_interval(vintages, _ts(2020, 1, 1), _ts(2021, 1, 1))

    assert exc_info.value.no_baseline is True


def test_error_message_lists_offending_identities() -> None:
    vintages = [_vintage((2020, 6, 1))]

    with pytest.raises(ResearchIntervalNotReadyError, match="USD_POLICY_RATE"):
        require_research_ready_interval(vintages, _ts(2020, 1, 1), _ts(2021, 1, 1))


class TestSelectResearchCandidates:
    """Direct tests of the derivation helper FX-44H introduced --
    `require_research_ready_interval` is a thin wrapper around this."""

    def test_includes_carry_in_and_in_interval_observations(self) -> None:
        carry_in = _vintage((2019, 1, 1), released_at_is_verified=True)
        in_interval = _vintage((2020, 6, 1), released_at_is_verified=True)
        history = [carry_in, in_interval]

        candidates = select_research_candidates(history, _ts(2020, 1, 1), _ts(2021, 1, 1))

        assert set(candidates) == {carry_in, in_interval}

    def test_carry_in_is_the_latest_observation_period_at_or_before_start(self) -> None:
        older = _vintage((2018, 1, 1), released_at_is_verified=True)
        newer = _vintage((2019, 1, 1), released_at_is_verified=True)  # the true carry-in
        history = [older, newer]

        candidates = select_research_candidates(history, _ts(2020, 1, 1), _ts(2021, 1, 1))

        assert candidates == (newer,)  # older is superseded, not a candidate at all

    def test_no_duplicate_when_carry_in_equals_interval_start(self) -> None:
        at_start = _vintage((2020, 1, 1), released_at_is_verified=True)

        candidates = select_research_candidates([at_start], _ts(2020, 1, 1), _ts(2021, 1, 1))

        assert candidates == (at_start,)  # not doubled up

    def test_empty_history_yields_no_candidates(self) -> None:
        assert select_research_candidates([], _ts(2020, 1, 1), _ts(2021, 1, 1)) == ()

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.research_readiness import (
    ResearchIntervalNotReadyError,
    is_research_safe,
    require_research_ready_interval,
)
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(*args: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(*args, tzinfo=UTC))


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
    # fail closed" -- even with only one candidate vintage, and even
    # though it's a conservative-bound sibling right next to it.
    vintages = [_vintage((2020, 3, 1))]

    with pytest.raises(ResearchIntervalNotReadyError):
        require_research_ready_interval(vintages, _ts(2020, 1, 1), _ts(2021, 1, 1))


def test_provisional_vintage_outside_the_interval_does_not_block() -> None:
    # The gate only judges what falls inside [start, end) -- a
    # provisional vintage for an unrelated period must not block an
    # otherwise fully research-safe interval.
    vintages = [
        _vintage((2020, 6, 1), released_at_is_verified=True),
        _vintage((2019, 1, 1)),  # provisional, but outside the interval below
    ]

    require_research_ready_interval(vintages, _ts(2020, 1, 1), _ts(2021, 1, 1))  # must not raise


def test_interval_end_is_exclusive() -> None:
    vintages = [_vintage((2021, 1, 1))]  # provisional, exactly at interval_end

    require_research_ready_interval(vintages, _ts(2020, 1, 1), _ts(2021, 1, 1))  # must not raise


def test_error_message_lists_offending_identities() -> None:
    vintages = [_vintage((2020, 6, 1))]

    with pytest.raises(ResearchIntervalNotReadyError, match="USD_POLICY_RATE"):
        require_research_ready_interval(vintages, _ts(2020, 1, 1), _ts(2021, 1, 1))

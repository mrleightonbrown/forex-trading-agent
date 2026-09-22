from datetime import UTC, datetime

import pytest

from forex_agent.domain.policy_rate_release_timing_registry import (
    ReleaseTimingResolution,
    UnresolvedTiming,
    resolve_release_timing,
)
from forex_agent.domain.release_timing_rule import ReleaseTimingConfidence
from forex_agent.domain.timestamps import UtcTimestamp


def _period(*args: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(*args, tzinfo=UTC))


def test_usd_regular_post_2013_meeting_is_exact() -> None:
    result = resolve_release_timing("USD", _period(2018, 6, 14))

    assert isinstance(result, ReleaseTimingResolution)
    assert result.confidence is ReleaseTimingConfidence.EXACT
    assert result.released_at.value == datetime(2018, 6, 14, 18, 0, 0, tzinfo=UTC)  # 2pm EDT
    assert result.effective_at is None


def test_usd_regular_pre_2013_meeting_is_conservative_and_later_than_proxy() -> None:
    result = resolve_release_timing("USD", _period(1994, 2, 4))

    assert isinstance(result, ReleaseTimingResolution)
    assert result.confidence is ReleaseTimingConfidence.CONSERVATIVE_SAFE_BOUND
    # Safe direction: strictly later than the old midnight-UTC proxy for
    # the SAME calendar date, never earlier.
    assert result.released_at.value > datetime(1994, 2, 4, 0, 0, 0, tzinfo=UTC)


def test_usd_known_irregular_date_is_unresolved() -> None:
    # 2008-01-22: inter-meeting 75bp emergency cut.
    result = resolve_release_timing("USD", _period(2008, 1, 22))

    assert isinstance(result, UnresolvedTiming)
    assert "inter-meeting" in result.reason.lower() or "emergency" in result.reason.lower()


def test_gbp_regular_thursday_is_exact_noon_london() -> None:
    result = resolve_release_timing("GBP", _period(2007, 7, 5))

    assert isinstance(result, ReleaseTimingResolution)
    assert result.confidence is ReleaseTimingConfidence.EXACT
    assert result.released_at.value == datetime(2007, 7, 5, 11, 0, 0, tzinfo=UTC)  # noon BST


def test_gbp_known_irregular_date_is_unresolved() -> None:
    result = resolve_release_timing("GBP", _period(2020, 3, 11))  # COVID emergency cut

    assert isinstance(result, UnresolvedTiming)


def test_cad_regular_date_is_conservative() -> None:
    result = resolve_release_timing("CAD", _period(2022, 7, 14))

    assert isinstance(result, ReleaseTimingResolution)
    assert result.confidence is ReleaseTimingConfidence.CONSERVATIVE_SAFE_BOUND
    assert result.released_at.value > datetime(2022, 7, 14, 0, 0, 0, tzinfo=UTC)


def test_cad_known_irregular_date_is_unresolved() -> None:
    result = resolve_release_timing("CAD", _period(2020, 3, 16))  # COVID emergency cut

    assert isinstance(result, UnresolvedTiming)


def test_eur_announcement_before_effective_date() -> None:
    # FX-44 test requirement: announcement before effective date. The
    # 2022-06-11 decision publicly moved rates from the 2022-07-21
    # Thursday meeting; the stored proxy (2022-07-27) is the true
    # EFFECTIVE date (first MRO operation following the decision).
    result = resolve_release_timing("EUR", _period(2022, 7, 27))

    assert isinstance(result, ReleaseTimingResolution)
    assert result.effective_at is not None
    assert result.released_at.value < result.effective_at.value
    assert result.released_at.value == datetime(2022, 7, 21, 12, 15, 0, tzinfo=UTC)
    assert result.effective_at.value == datetime(2022, 7, 27, 0, 0, 0, tzinfo=UTC)


def test_eur_pre_2022_rule_uses_1345_cet() -> None:
    result = resolve_release_timing("EUR", _period(2014, 6, 11))  # decision date: 2014-06-05

    assert isinstance(result, ReleaseTimingResolution)
    assert result.confidence is ReleaseTimingConfidence.EXACT
    assert result.released_at.value == datetime(2014, 6, 5, 11, 45, 0, tzinfo=UTC)  # 13:45 CEST


def test_eur_early_era_is_unresolved() -> None:
    # Before the confirmed 2006-03-08 Wednesday-effective-date pattern.
    result = resolve_release_timing("EUR", _period(1999, 4, 9))

    assert isinstance(result, UnresolvedTiming)


def test_eur_launch_date_is_unresolved() -> None:
    result = resolve_release_timing("EUR", _period(1999, 1, 1))

    assert isinstance(result, UnresolvedTiming)


def test_jpy_raises_out_of_scope() -> None:
    # FX-44's own instruction: "JPY remains out of scope."
    with pytest.raises(ValueError, match="JPY"):
        resolve_release_timing("JPY", _period(2020, 1, 1))


def test_unsupported_currency_raises() -> None:
    with pytest.raises(ValueError, match="AUD"):
        resolve_release_timing("AUD", _period(2020, 1, 1))

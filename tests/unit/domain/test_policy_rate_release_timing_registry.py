from datetime import UTC, date, datetime

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
    # FX-44H: the stored date (2018-06-14) is the operational EFFECTIVE
    # date -- the actual FOMC decision was the day before (2018-06-13,
    # the second day of the June 12-13, 2018 meeting), per the Fed's own
    # published meeting calendar. released_at is therefore EARLIER than
    # the stored observation_period/effective_at, not equal to it.
    result = resolve_release_timing("USD", _period(2018, 6, 14))

    assert isinstance(result, ReleaseTimingResolution)
    assert result.confidence is ReleaseTimingConfidence.EXACT
    assert result.released_at.value == datetime(2018, 6, 13, 18, 0, 0, tzinfo=UTC)  # 2pm EDT
    assert result.effective_at is not None
    assert result.effective_at.value == datetime(2018, 6, 14, 0, 0, 0, tzinfo=UTC)
    assert result.released_at.value < result.effective_at.value


def test_usd_2026_09_17_worked_example() -> None:
    # FX-44H's own worked example, verbatim: FRED/effective date
    # 2026-09-17; FOMC statement 2026-09-16 14:00 EDT.
    result = resolve_release_timing("USD", _period(2026, 9, 17))

    assert isinstance(result, ReleaseTimingResolution)
    assert result.confidence is ReleaseTimingConfidence.EXACT
    assert result.released_at.value == datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)  # 2pm EDT
    assert result.effective_at is not None
    assert result.effective_at.value == datetime(2026, 9, 17, 0, 0, 0, tzinfo=UTC)


def test_usd_liftoff_2015_has_same_day_gap_not_minus_one() -> None:
    # FX-44H's own verified exception: the two earliest EXACT-tier
    # meetings (2015-12-16 "liftoff" and 2016-12-14) predate the
    # standard next-day effective-date mechanism -- a blind "-1 day"
    # transformation would get these two wrong. Proves the explicit
    # mapping, not a formula, drives this resolution.
    result = resolve_release_timing("USD", _period(2015, 12, 16))

    assert isinstance(result, ReleaseTimingResolution)
    assert result.released_at.value == datetime(2015, 12, 16, 19, 0, 0, tzinfo=UTC)  # 2pm EST
    assert result.effective_at is not None
    assert result.effective_at.value == datetime(2015, 12, 16, 0, 0, 0, tzinfo=UTC)
    # Same calendar day -- NOT the +1 day gap every later meeting has.
    assert result.released_at.value.date() == result.effective_at.value.date()


def test_usd_exact_date_not_in_explicit_mapping_is_unresolved() -> None:
    # FX-44H: no formulaic fallback for the EXACT tier -- a date that
    # LOOKS like a regular post-2013 meeting but was never individually
    # verified and added to USD_EFFECTIVE_TO_DECISION_DATE must not
    # resolve, even though it falls chronologically inside the "exact
    # era". 2027-01-01 stands in for "a future change point this
    # registry has not yet been taught about".
    result = resolve_release_timing("USD", _period(2027, 1, 1))

    assert isinstance(result, UnresolvedTiming)


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


def test_eur_non_wednesday_effective_date_is_unresolved_unless_explicitly_mapped() -> None:
    # FX-44H fail-closed requirement: a date within the "Wednesday
    # effective-date era" that is NOT actually a Wednesday, and has no
    # explicit override, must never get the generic six-day
    # transformation applied -- including a date this registry has
    # never seen before (simulated here with a synthetic future
    # Thursday, structurally identical to "a later backfill run
    # ingests a new anomalous EUR change point").
    thursday = _period(2026, 9, 17)
    assert thursday.value.weekday() == 3  # sanity: this IS a Thursday, not a Wednesday

    result = resolve_release_timing("EUR", thursday)

    assert isinstance(result, UnresolvedTiming)
    assert "not a Wednesday" in result.reason
    assert "EUR_EXPLICIT_DECISION_DATE_OVERRIDES" in result.reason


def test_eur_non_wednesday_date_resolves_when_explicitly_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The ONLY sanctioned escape hatch: an individually researched,
    # explicit date -> decision_date entry. Proves the override
    # mechanism itself works (distinct from proving it's empty today).
    import forex_agent.domain.policy_rate_release_timing_registry as registry

    thursday = _period(2026, 9, 17)
    monkeypatch.setitem(
        registry.EUR_EXPLICIT_DECISION_DATE_OVERRIDES,
        thursday.value.date(),
        date(2026, 9, 10),
    )

    result = resolve_release_timing("EUR", thursday)

    assert isinstance(result, ReleaseTimingResolution)
    assert result.effective_at == thursday


def test_jpy_raises_out_of_scope() -> None:
    # FX-44's own instruction: "JPY remains out of scope."
    with pytest.raises(ValueError, match="JPY"):
        resolve_release_timing("JPY", _period(2020, 1, 1))


def test_unsupported_currency_raises() -> None:
    with pytest.raises(ValueError, match="AUD"):
        resolve_release_timing("AUD", _period(2020, 1, 1))

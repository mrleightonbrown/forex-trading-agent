"""FX-46: tests for the pure, deterministic research building blocks."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.use_cases.compute_policy_rate_differential import (
    ComputePolicyRateDifferential,
)
from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_source import CandleSource
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.policy_rate_differential import RateSemantics
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.research.policy_rate_differential_research import (
    ChangeGroup,
    Disposition,
    FeatureEvaluation,
    LevelGroup,
    TransitionStatus,
    assign_era,
    build_change_events,
    classify_change,
    classify_level,
    compute_forward_return,
    describe,
    evaluate_feature,
    find_entry_index,
    mid_open,
    select_weekly_bars,
)
from tests.fakes.macro_observation_repository import FakeMacroObservationRepository

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
USD_CAD = Instrument(base_currency="USD", quote_currency="CAD")


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


def _candle(
    instrument: Instrument,
    start: tuple[int, ...],
    bid_open: str,
    ask_open: str,
    granularity: Granularity = Granularity.D,
) -> Candle:
    flat_bid = Ohlc(
        open=Decimal(bid_open),
        high=Decimal(bid_open),
        low=Decimal(bid_open),
        close=Decimal(bid_open),
    )
    flat_ask = Ohlc(
        open=Decimal(ask_open),
        high=Decimal(ask_open),
        low=Decimal(ask_open),
        close=Decimal(ask_open),
    )
    return Candle(
        instrument=instrument,
        granularity=granularity,
        start_time=_ts(*start),
        bid=flat_bid,
        ask=flat_ask,
        volume=1,
        is_finalized=True,
        source=CandleSource.AGGREGATED,
    )


# ---------------------------------------------------------------------------
# select_weekly_bars
# ---------------------------------------------------------------------------


def test_select_weekly_bars_picks_first_bar_of_each_iso_week() -> None:
    # 2026-09-14 is a Monday (start of an ISO week); 09-16 is the same
    # week, 09-21 is the following Monday (a new ISO week).
    mon = _candle(EUR_USD, (2026, 9, 14), "1.10", "1.1002")
    wed = _candle(EUR_USD, (2026, 9, 16), "1.11", "1.1102")
    next_mon = _candle(EUR_USD, (2026, 9, 21), "1.12", "1.1202")

    result = select_weekly_bars([mon, wed, next_mon])

    assert result == [mon, next_mon]  # wed is skipped -- same ISO week as mon


def test_select_weekly_bars_handles_iso_year_boundary_week() -> None:
    # 2018-12-31 is a Monday belonging to ISO week 1 of 2019 (not week
    # 53 of 2018) -- isocalendar() must be used, not plain .year/.
    # isocalendar() week grouping to get this right.
    dec_31 = _candle(EUR_USD, (2018, 12, 31), "1.10", "1.1002")
    jan_2 = _candle(EUR_USD, (2019, 1, 2), "1.11", "1.1102")  # same ISO week as dec_31
    jan_7 = _candle(EUR_USD, (2019, 1, 7), "1.12", "1.1202")  # next ISO week (Monday)

    result = select_weekly_bars([dec_31, jan_2, jan_7])

    assert result == [dec_31, jan_7]


def test_select_weekly_bars_output_stable_under_input_ordering() -> None:
    mon = _candle(EUR_USD, (2026, 9, 14), "1.10", "1.1002")
    wed = _candle(EUR_USD, (2026, 9, 16), "1.11", "1.1102")
    next_mon = _candle(EUR_USD, (2026, 9, 21), "1.12", "1.1202")

    forward = select_weekly_bars([mon, wed, next_mon])
    shuffled = select_weekly_bars([next_mon, mon, wed])

    assert forward == shuffled == [mon, next_mon]


# ---------------------------------------------------------------------------
# classify_level / classify_change
# ---------------------------------------------------------------------------


def test_classify_level_positive_negative_zero() -> None:
    assert classify_level(Decimal("0.5")) is LevelGroup.POSITIVE
    assert classify_level(Decimal("-0.5")) is LevelGroup.NEGATIVE
    assert classify_level(Decimal("0")) is LevelGroup.ZERO


def test_classify_change_increased_decreased_unchanged() -> None:
    assert classify_change(Decimal("0.25")) is ChangeGroup.INCREASED
    assert classify_change(Decimal("-0.25")) is ChangeGroup.DECREASED
    assert classify_change(Decimal("0")) is ChangeGroup.UNCHANGED


# ---------------------------------------------------------------------------
# build_change_events
# ---------------------------------------------------------------------------


def test_build_change_events_admissible_transition() -> None:
    day1 = FeatureEvaluation(_ts(2026, 1, 1), Disposition.USABLE, Decimal("1.0"), None)
    day2 = FeatureEvaluation(_ts(2026, 1, 2), Disposition.USABLE, Decimal("1.5"), None)

    events = build_change_events([day1, day2])

    assert len(events) == 2
    assert events[0].status is TransitionStatus.NO_PRIOR_DAY
    assert events[1].status is TransitionStatus.ADMISSIBLE
    assert events[1].delta == Decimal("0.5")
    assert events[1].group is ChangeGroup.INCREASED


def test_build_change_events_no_event_inferred_across_blocked_gap() -> None:
    day1 = FeatureEvaluation(_ts(2026, 1, 1), Disposition.USABLE, Decimal("1.0"), None)
    day2_blocked = FeatureEvaluation(
        _ts(2026, 1, 2), Disposition.BLOCKED, None, "provisional_timing"
    )
    day3 = FeatureEvaluation(_ts(2026, 1, 3), Disposition.USABLE, Decimal("1.9"), None)

    events = build_change_events([day1, day2_blocked, day3])

    # day2 is BLOCKED -- contributes no event at all.
    assert len(events) == 2
    assert events[0].as_of == _ts(2026, 1, 1)
    assert events[0].status is TransitionStatus.NO_PRIOR_DAY
    assert events[1].as_of == _ts(2026, 1, 3)
    assert events[1].status is TransitionStatus.GAP
    assert events[1].group is None
    assert events[1].delta is None
    assert events[1].differential == Decimal("1.9")  # day's own value IS still recorded


def test_build_change_events_no_event_inferred_across_unavailable_gap() -> None:
    day1 = FeatureEvaluation(_ts(2026, 1, 1), Disposition.USABLE, Decimal("1.0"), None)
    day2_unavailable = FeatureEvaluation(
        _ts(2026, 1, 2), Disposition.UNAVAILABLE, None, "effective_at not populated"
    )
    day3 = FeatureEvaluation(_ts(2026, 1, 3), Disposition.USABLE, Decimal("0.5"), None)

    events = build_change_events([day1, day2_unavailable, day3])

    assert len(events) == 2
    assert events[1].status is TransitionStatus.GAP


def test_build_change_events_simultaneous_base_and_quote_change_is_one_net_event() -> None:
    # Both legs moving on the same evaluation date collapses into a
    # single derived differential value each day (FX-45's own design)
    # -- this test proves the change-event layer inherits that
    # naturally: exactly ONE event, with the correct NET delta, never
    # two.
    before = FeatureEvaluation(_ts(2026, 1, 1), Disposition.USABLE, Decimal("1.000"), None)
    # base +0.75, quote -0.25 => net differential change = +1.00
    after_both_moved = FeatureEvaluation(
        _ts(2026, 1, 2), Disposition.USABLE, Decimal("2.000"), None
    )

    events = build_change_events([before, after_both_moved])

    assert len(events) == 2
    assert events[1].status is TransitionStatus.ADMISSIBLE
    assert events[1].delta == Decimal("1.000")
    assert events[1].group is ChangeGroup.INCREASED


def test_build_change_events_output_stable_under_input_ordering() -> None:
    day1 = FeatureEvaluation(_ts(2026, 1, 1), Disposition.USABLE, Decimal("1.0"), None)
    day2 = FeatureEvaluation(_ts(2026, 1, 2), Disposition.USABLE, Decimal("1.5"), None)
    day3 = FeatureEvaluation(_ts(2026, 1, 3), Disposition.USABLE, Decimal("1.2"), None)

    forward = build_change_events([day1, day2, day3])
    shuffled = build_change_events([day3, day1, day2])

    assert forward == shuffled


# ---------------------------------------------------------------------------
# mid_open
# ---------------------------------------------------------------------------


def test_mid_open_uses_bid_and_ask_average_not_either_alone() -> None:
    candle = _candle(EUR_USD, (2026, 1, 1), bid_open="1.1000", ask_open="1.1010")

    assert mid_open(candle) == Decimal("1.1005")


# ---------------------------------------------------------------------------
# find_entry_index -- strictly-after semantics
# ---------------------------------------------------------------------------


def test_find_entry_index_selects_first_bar_strictly_after_as_of() -> None:
    bars = [
        _candle(EUR_USD, (2026, 1, 1), "1.10", "1.1002"),
        _candle(EUR_USD, (2026, 1, 2), "1.11", "1.1102"),
        _candle(EUR_USD, (2026, 1, 5), "1.12", "1.1202"),
    ]

    # Feature evaluated exactly AT the first bar's own open -- entry
    # must be the SECOND bar, never the first (not "at or after").
    index = find_entry_index(bars, _ts(2026, 1, 1))

    assert index == 1


def test_find_entry_index_none_when_as_of_at_or_after_last_bar() -> None:
    bars = [_candle(EUR_USD, (2026, 1, 1), "1.10", "1.1002")]

    assert find_entry_index(bars, _ts(2026, 1, 1)) is None
    assert find_entry_index(bars, _ts(2026, 1, 2)) is None


# ---------------------------------------------------------------------------
# compute_forward_return -- exact 1d/5d/20d indexing, censoring
# ---------------------------------------------------------------------------


def _bar_series(n: int, instrument: Instrument = EUR_USD) -> list[Candle]:
    """`n` daily bars starting 2026-01-01, each with a DISTINCT mid
    price (open = 1.0000 + 0.0001*i) so indexing errors are directly
    observable in the resulting return value, not masked by identical
    prices."""
    bars = []
    day = 1
    for i in range(n):
        price = f"{Decimal('1.0000') + Decimal('0.0001') * i}"
        bars.append(_candle(instrument, (2026, 1, day), price, price))
        day += 1
    return bars


def test_compute_forward_return_1d_5d_20d_indexing_is_exact() -> None:
    bars = _bar_series(25)  # indices 0..24

    r1 = compute_forward_return(bars, entry_index=0, horizon_days=1)
    r5 = compute_forward_return(bars, entry_index=0, horizon_days=5)
    r20 = compute_forward_return(bars, entry_index=0, horizon_days=20)

    assert r1.future_time == bars[1].start_time
    assert r5.future_time == bars[5].start_time
    assert r20.future_time == bars[20].start_time
    assert not r1.censored and not r5.censored and not r20.censored
    assert r1.entry_mid == mid_open(bars[0])
    assert r1.future_mid == mid_open(bars[1])
    assert r1.return_value == (mid_open(bars[1]) / mid_open(bars[0])) - 1


def test_compute_forward_return_insufficient_future_bars_is_censored() -> None:
    bars = _bar_series(15)  # only 14 bars available after index 0

    r20 = compute_forward_return(bars, entry_index=0, horizon_days=20)

    assert r20.censored is True
    assert r20.future_time is None
    assert r20.future_mid is None
    assert r20.return_value is None
    # entry itself is still recorded even when the horizon is censored.
    assert r20.entry_mid == mid_open(bars[0])


def test_compute_forward_return_exactly_enough_bars_is_not_censored() -> None:
    bars = _bar_series(21)  # entry at 0, future at 20 -- exactly enough

    r20 = compute_forward_return(bars, entry_index=0, horizon_days=20)

    assert r20.censored is False
    assert r20.future_time == bars[20].start_time


# ---------------------------------------------------------------------------
# Return orientation -- positive return = base currency appreciated
# ---------------------------------------------------------------------------


def test_eur_usd_rising_mid_price_is_a_positive_return() -> None:
    entry = _candle(EUR_USD, (2026, 1, 1), "1.1000", "1.1002")
    future = _candle(EUR_USD, (2026, 1, 2), "1.1100", "1.1102")  # EUR appreciated vs USD

    result = compute_forward_return([entry, future], entry_index=0, horizon_days=1)

    assert result.return_value is not None
    assert result.return_value > 0


def test_usd_cad_rising_mid_price_is_a_positive_return() -> None:
    entry = _candle(USD_CAD, (2026, 1, 1), "1.3500", "1.3502")
    future = _candle(USD_CAD, (2026, 1, 2), "1.3600", "1.3602")  # USD appreciated vs CAD

    result = compute_forward_return([entry, future], entry_index=0, horizon_days=1)

    assert result.return_value is not None
    assert result.return_value > 0


def test_falling_mid_price_is_a_negative_return() -> None:
    entry = _candle(EUR_USD, (2026, 1, 1), "1.1000", "1.1002")
    future = _candle(EUR_USD, (2026, 1, 2), "1.0900", "1.0902")

    result = compute_forward_return([entry, future], entry_index=0, horizon_days=1)

    assert result.return_value is not None
    assert result.return_value < 0


# ---------------------------------------------------------------------------
# Lookahead regression -- the story's own explicit required test
# ---------------------------------------------------------------------------


def test_forward_return_never_uses_the_feature_evaluation_bars_own_close() -> None:
    """Explicit lookahead regression (FX-46 section 18): the entry bar's
    own OHLC close is set to a price that would give the OPPOSITE-signed
    return if it were (incorrectly) used as either the entry or exit
    price. If a future edit changes `compute_forward_return`/`find_
    entry_index` to use the feature-evaluation candle's own close (or
    any price at/before `as_of`) instead of the NEXT bar's open, this
    test fails.
    """
    feature_bar = Candle(
        instrument=EUR_USD,
        granularity=Granularity.D,
        start_time=_ts(2026, 1, 1),
        # Open low, but closes MUCH higher -- if the close were wrongly
        # used as the entry price, the subsequent real entry (next
        # bar's open, lower) would make the return NEGATIVE instead of
        # the correct POSITIVE.
        bid=Ohlc(
            open=Decimal("1.1000"),
            high=Decimal("1.2000"),
            low=Decimal("1.0990"),
            close=Decimal("1.1990"),
        ),
        ask=Ohlc(
            open=Decimal("1.1002"),
            high=Decimal("1.2002"),
            low=Decimal("1.0992"),
            close=Decimal("1.1992"),
        ),
        volume=1,
        is_finalized=True,
        source=CandleSource.AGGREGATED,
    )
    next_bar = _candle(
        EUR_USD, (2026, 1, 2), "1.1050", "1.1052"
    )  # real entry: slightly above feature_bar's OWN open
    bars = [feature_bar, next_bar]

    entry_index = find_entry_index(bars, as_of=feature_bar.start_time)
    assert entry_index == 1  # never 0 -- the feature bar itself must never be the entry

    result = compute_forward_return(bars, entry_index=entry_index, horizon_days=1)
    # Only one bar exists after the correct entry (next_bar itself, index 1) --
    # horizon_days=1 needs index 2, which does not exist, so this is
    # correctly censored. The real point of this test is entry_index == 1
    # above and entry_mid below -- confirming the wrong (close-based)
    # price was never used as the entry reference.
    assert result.entry_mid == mid_open(next_bar)
    assert result.entry_mid != mid_open(feature_bar)
    assert result.entry_mid != (feature_bar.bid.close + feature_bar.ask.close) / 2


# ---------------------------------------------------------------------------
# assign_era -- exact boundary dates
# ---------------------------------------------------------------------------


def test_assign_era_exact_boundaries() -> None:
    assert assign_era(_ts(2004, 12, 31)) is None  # before every defined era
    assert assign_era(_ts(2005, 1, 1)) == "2005-2011"
    assert assign_era(_ts(2011, 12, 31)) == "2005-2011"
    assert assign_era(_ts(2012, 1, 1)) == "2012-2018"
    assert assign_era(_ts(2018, 12, 31)) == "2012-2018"
    assert assign_era(_ts(2019, 1, 1)) == "2019-cutoff"
    assert assign_era(_ts(2026, 9, 1)) == "2019-cutoff"


# ---------------------------------------------------------------------------
# describe -- descriptive stats
# ---------------------------------------------------------------------------


def test_describe_empty_is_all_none_except_count() -> None:
    result = describe([])

    assert result.count == 0
    assert result.mean is None
    assert result.stdev is None


def test_describe_single_value_has_no_stdev() -> None:
    result = describe([Decimal("0.01")])

    assert result.count == 1
    assert result.mean == Decimal("0.01")
    assert result.stdev is None  # sample stdev undefined with n=1


def test_describe_basic_stats() -> None:
    values = [Decimal("-1"), Decimal("0"), Decimal("1"), Decimal("2")]

    result = describe(values)

    assert result.count == 4
    assert result.mean == Decimal("0.5")
    assert result.minimum == Decimal("-1")
    assert result.maximum == Decimal("2")
    assert result.positive_fraction == Decimal("2") / Decimal("4")  # 1 and 2 are > 0


# ---------------------------------------------------------------------------
# evaluate_feature -- async, via the real use case + fake repository
# ---------------------------------------------------------------------------


async def _seed(
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


@pytest.mark.asyncio
async def test_evaluate_feature_research_interval_not_ready_becomes_blocked() -> None:
    fake = FakeMacroObservationRepository()
    # EUR has no history at all -- no_baseline.
    await _seed(fake, "USD_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 18, 0, 0), "5.375")
    use_case = ComputePolicyRateDifferential(repository=fake)

    result = await evaluate_feature(
        use_case, Instrument("EUR", "USD"), _ts(2024, 6, 1), RateSemantics.ANNOUNCED
    )

    assert result.disposition is Disposition.BLOCKED
    assert result.differential is None
    assert result.reason == "missing_baseline"


@pytest.mark.asyncio
async def test_evaluate_feature_differential_unavailable_becomes_unavailable() -> None:
    fake = FakeMacroObservationRepository()
    await _seed(
        fake, "GBP_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 12, 0, 0), "5.25"
    )  # no effective_at
    await _seed(
        fake,
        "USD_POLICY_RATE",
        (2024, 1, 1),
        (2023, 12, 31, 18, 0, 0),
        "5.375",
        effective_at=(2024, 1, 1),
    )
    use_case = ComputePolicyRateDifferential(repository=fake)

    result = await evaluate_feature(
        use_case, Instrument("GBP", "USD"), _ts(2024, 6, 1), RateSemantics.EFFECTIVE
    )

    assert result.disposition is Disposition.UNAVAILABLE
    assert result.differential is None
    assert result.reason is not None
    assert "GBP" in result.reason
    assert "effective_at" in result.reason


@pytest.mark.asyncio
async def test_evaluate_feature_usable_records_the_real_differential() -> None:
    fake = FakeMacroObservationRepository()
    await _seed(fake, "EUR_POLICY_RATE", (2023, 5, 10), (2023, 5, 4, 11, 45, 0), "3.75")
    await _seed(fake, "USD_POLICY_RATE", (2023, 5, 4), (2023, 5, 3, 18, 0, 0), "5.125")
    use_case = ComputePolicyRateDifferential(repository=fake)

    result = await evaluate_feature(
        use_case, Instrument("EUR", "USD"), _ts(2023, 6, 1), RateSemantics.ANNOUNCED
    )

    assert result.disposition is Disposition.USABLE
    assert result.differential == Decimal("3.75") - Decimal("5.125")
    assert result.reason is None


@pytest.mark.asyncio
async def test_evaluate_feature_effective_never_falls_back_to_announced() -> None:
    # GBP/CAD-style: EXACT released_at but NO effective_at anywhere --
    # EFFECTIVE must report unavailable, never silently substitute the
    # ANNOUNCED value (which IS usable for this same data).
    fake = FakeMacroObservationRepository()
    await _seed(fake, "GBP_POLICY_RATE", (2024, 1, 1), (2023, 12, 31, 12, 0, 0), "5.25")
    await _seed(
        fake,
        "USD_POLICY_RATE",
        (2024, 1, 1),
        (2023, 12, 31, 18, 0, 0),
        "5.375",
        effective_at=(2024, 1, 1),
    )
    use_case = ComputePolicyRateDifferential(repository=fake)
    instrument = Instrument("GBP", "USD")
    as_of = _ts(2024, 6, 1)

    announced = await evaluate_feature(use_case, instrument, as_of, RateSemantics.ANNOUNCED)
    effective = await evaluate_feature(use_case, instrument, as_of, RateSemantics.EFFECTIVE)

    assert announced.disposition is Disposition.USABLE
    assert effective.disposition is Disposition.UNAVAILABLE
    assert effective.differential is None  # never silently set to announced.differential

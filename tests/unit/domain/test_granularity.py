from forex_agent.domain.granularity import Granularity


def test_granularity_values_match_oanda_naming() -> None:
    # Same reasoning as Instrument.symbol: match OANDA's own naming so no
    # translation table is needed when FX-6 fetches candles from OANDA.
    assert Granularity.M1.value == "M1"
    assert Granularity.M15.value == "M15"
    assert Granularity.H1.value == "H1"
    assert Granularity.H4.value == "H4"
    assert Granularity.D.value == "D"


def test_granularity_members_are_unique() -> None:
    values = [g.value for g in Granularity]
    assert len(values) == len(set(values))

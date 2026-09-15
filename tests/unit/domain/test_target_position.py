from forex_agent.domain.target_position import TargetPosition


def test_target_position_values_are_their_own_names() -> None:
    assert TargetPosition.LONG.value == "LONG"
    assert TargetPosition.SHORT.value == "SHORT"
    assert TargetPosition.FLAT.value == "FLAT"


def test_target_position_members_are_unique() -> None:
    values = [p.value for p in TargetPosition]
    assert len(values) == len(set(values))


def test_target_position_has_no_trade_side_equivalent() -> None:
    # The whole point of a separate enum (FX-18): FLAT is a legitimate
    # target with no corresponding TradeSide, since a trade/open position
    # is always LONG or SHORT and never FLAT.
    assert {p.name for p in TargetPosition} == {"LONG", "SHORT", "FLAT"}

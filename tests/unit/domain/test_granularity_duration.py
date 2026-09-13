from datetime import timedelta

import pytest

from forex_agent.domain.granularity import Granularity
from forex_agent.domain.granularity_duration import fixed_duration


def test_fixed_durations() -> None:
    assert fixed_duration(Granularity.M1) == timedelta(minutes=1)
    assert fixed_duration(Granularity.M5) == timedelta(minutes=5)
    assert fixed_duration(Granularity.H1) == timedelta(hours=1)
    assert fixed_duration(Granularity.D) == timedelta(days=1)


@pytest.mark.parametrize("granularity", [Granularity.W, Granularity.M])
def test_variable_length_granularities_are_rejected(granularity: Granularity) -> None:
    with pytest.raises(ValueError, match="fixed duration"):
        fixed_duration(granularity)

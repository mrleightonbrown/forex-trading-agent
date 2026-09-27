"""FX-52A Section 43: real-source validation for `OnsScheduleSource`
against ONS's own live public RSS feed."""

import pytest

from forex_agent.domain.economic_indicator_registry import indicator_by_key
from forex_agent.infrastructure.economic_calendar_sources.ons_schedule_source import (
    OnsScheduleSource,
)


@pytest.mark.asyncio
async def test_ons_feed_is_reachable() -> None:
    source = OnsScheduleSource()
    try:
        observations = await source.fetch_schedule()
    finally:
        await source.aclose()

    # ONS's own upcoming-release window may or may not currently contain
    # a GDP bulletin -- only assert reachability/shape, never a fixed
    # count, since real calendar contents legitimately vary over time.
    for observation in observations:
        assert observation.source == "ONS_RSS"
        assert observation.schedule_timezone == "Europe/London"
        for indicator_key in observation.indicator_keys:
            assert indicator_by_key(indicator_key) is not None

"""FX-52A Section 43: real-source validation for `BocScheduleSource`
against the Bank of Canada's own live public ICS feed.

FX-52AH: marked `live_source` -- excluded from ordinary `pytest`/CI
runs; run explicitly via `pytest -m live_source`, reported separately.
"""

import pytest

from forex_agent.domain.economic_indicator_registry import indicator_by_key
from forex_agent.infrastructure.economic_calendar_sources.boc_schedule_source import (
    BocScheduleSource,
)


@pytest.mark.live_source
@pytest.mark.asyncio
async def test_boc_schedule_feed_is_reachable_and_yields_mapped_observations() -> None:
    source = BocScheduleSource()
    try:
        result = await source.fetch_schedule()
    finally:
        await source.aclose()

    assert result.mapped_count > 0, (
        "expected at least one mapped rate-announcement observation from "
        "the Bank of Canada's live feed"
    )
    for observation in result.observations:
        assert observation.source == "BOC_ICS"
        assert observation.indicator_keys == ("CAD_POLICY_RATE_DECISION",)
        assert indicator_by_key("CAD_POLICY_RATE_DECISION") is not None

"""FX-52A Section 43: real-source validation for `BocReleaseSource`
against the Bank of Canada's own live public press-release feed."""

import pytest

from forex_agent.infrastructure.economic_calendar_sources.boc_release_source import (
    BocReleaseSource,
)


@pytest.mark.asyncio
async def test_boc_release_feed_is_reachable() -> None:
    source = BocReleaseSource()
    try:
        observations = await source.fetch_releases()
    finally:
        await source.aclose()

    # A rate-announcement press release may or may not be in the current
    # feed window -- only assert reachability/shape when one is present,
    # never a fixed count.
    for observation in observations:
        assert observation.source == "BOC_RSS"
        assert observation.indicator_keys == ("CAD_POLICY_RATE_DECISION",)

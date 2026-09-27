"""FX-52A Section 43: real-source validation for `BlsScheduleSource`
against BLS's own live public ICS feed -- non-destructive (a single
GET), no credentials required. Not part of the deterministic unit
suite (see tests/unit/infrastructure/test_bls_schedule_source.py for
that); this proves today's real feed still parses and maps the way
this story's own research pass found it to.

FX-52AH: marked `live_source` -- excluded from ordinary `pytest`/CI
runs (see `pyproject.toml`'s `addopts`); run explicitly and separately
via `pytest -m live_source` and report that result on its own, never
folded into the deterministic suite's own pass/fail count.

KNOWN, EXPECTED FAILURE (confirmed during this story's own real-source
validation pass, not a regression to chase): a plain server-side
`httpx` request to BLS's feed currently receives a 403 "Access Denied"
response from BLS's own infrastructure, even with realistic browser
headers -- see `bls_schedule_source`'s own module docstring for the
full finding. This test is left failing, visibly and honestly, exactly
like this project's own pre-existing weekend-market-closure OANDA
tests, rather than silently skipped -- do not "fix" it by suppressing
the failure; fix it only once BLS's feed is actually reachable again
from wherever this project runs.
"""

import pytest

from forex_agent.domain.economic_indicator_registry import indicator_by_key
from forex_agent.infrastructure.economic_calendar_sources.bls_schedule_source import (
    BlsScheduleSource,
)


@pytest.mark.live_source
@pytest.mark.asyncio
async def test_bls_feed_is_reachable_and_yields_mapped_observations() -> None:
    source = BlsScheduleSource()
    try:
        result = await source.fetch_schedule()
    finally:
        await source.aclose()

    assert result.mapped_count > 0, "expected at least one mapped observation from BLS's live feed"
    for observation in result.observations:
        assert observation.source == "BLS_ICS"
        assert observation.schedule_timezone == "America/New_York"
        for indicator_key in observation.indicator_keys:
            assert indicator_by_key(indicator_key) is not None

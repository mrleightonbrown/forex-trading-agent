"""FX-57B Section 46/47: real-source validation for `EcbRssSource`
against the ECB's own live public RSS feed -- non-destructive (one
GET), no credentials required. Not part of the deterministic unit
suite (see tests/unit/infrastructure/news_sources/test_ecb_rss_
source.py for that); this proves today's real feed still parses and
maps the way this story's own live-validation pass found it to.

Marked `live_source` -- excluded from ordinary `pytest`/CI runs (see
`pyproject.toml`'s `addopts`); run explicitly and separately via
`pytest -m live_source` and report that result on its own, never
folded into the deterministic suite's own pass/fail count.

Deliberately non-fragile: asserts shape (guid/headline presence,
correct channel, known or newly-reported content classes, no
exception) and reports field-presence facts, never an exact title,
item count, or pubDate value, which can change at any time on the
ECB's own site. Detects -- without failing -- an unrecognized content
class so a genuinely new ECB document class is visible in the test
output rather than silently invalidated with no trace (FX-57B Section
17's own "document it" instruction).
"""

import pytest

from forex_agent.infrastructure.news_sources.ecb_rss_source import ECB_FEEDS, EcbRssSource


@pytest.mark.live_source
@pytest.mark.asyncio
async def test_ecb_press_feed_is_reachable_and_yields_valid_items() -> None:
    source = EcbRssSource()
    try:
        feed = ECB_FEEDS[0]
        outcome = await source.fetch_feed(feed)

        assert outcome.source_channel == feed.channel
        print(
            f"[live] {feed.channel}: items={len(outcome.observations)} "
            f"invalid={outcome.items_invalid} retrieved_at={outcome.retrieved_at.value}"
        )
        if outcome.items_invalid:
            print(f"[live] invalid_reasons={outcome.invalid_reasons!r}")

        assert len(outcome.observations) > 0, "expected at least one live ECB item"

        content_types_seen: set[str] = set()
        for observation in outcome.observations:
            assert observation.source_key == "ECB"
            assert observation.external_item_id
            assert observation.headline.strip()
            assert observation.source_channel == feed.channel
            assert observation.authors == ()
            assert observation.language == "en"
            assert observation.source_updated_at is None
            assert observation.body_text is None
            content_types_seen.add(observation.source_content_type or "")
            if observation.source_published_at is not None:
                assert observation.source_timestamp_provenance

        print(f"[live] content types seen: {sorted(content_types_seen)}")
        assert content_types_seen <= {"press_release", "speech", "interview"}
    finally:
        await source.aclose()

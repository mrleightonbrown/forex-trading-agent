"""FX-57A Section 55: real-source validation for `FedRssSource` against
the Federal Reserve's own live public RSS feeds -- non-destructive (one
GET per configured feed), no credentials required. Not part of the
deterministic unit suite (see tests/unit/infrastructure/news_sources/
test_fed_rss_source.py for that); this proves today's real feeds still
parse and map the way this story's own live-validation pass found them
to.

Marked `live_source` -- excluded from ordinary `pytest`/CI runs (see
`pyproject.toml`'s `addopts`); run explicitly and separately via
`pytest -m live_source` and report that result on its own, never
folded into the deterministic suite's own pass/fail count.

Deliberately non-fragile: asserts shape (guid/headline presence,
correct content type, no exception) and reports field-presence facts,
never an exact title, item count, or pubDate value, which can change
at any time on the Fed's own site.
"""

import pytest

from forex_agent.infrastructure.news_sources.fed_rss_source import FED_FEEDS, FedRssSource


@pytest.mark.live_source
@pytest.mark.asyncio
async def test_all_three_fed_feeds_are_reachable_and_yield_valid_items() -> None:
    source = FedRssSource()
    try:
        for feed in FED_FEEDS:
            outcome = await source.fetch_feed(feed)

            assert outcome.source_channel == feed.channel
            print(
                f"[live] {feed.channel}: items={len(outcome.observations)} "
                f"invalid={outcome.items_invalid} retrieved_at={outcome.retrieved_at.value}"
            )

            for observation in outcome.observations:
                assert observation.source_key == "FED"
                assert observation.external_item_id
                assert observation.headline.strip()
                assert observation.source_content_type == feed.content_type
                assert observation.authors == ()
                assert observation.language == "en"
                assert observation.source_updated_at is None
                if observation.source_published_at is not None:
                    assert observation.source_timestamp_provenance
                if not observation.source_timestamp_provenance:
                    continue
                provenance = observation.source_timestamp_provenance[0]
                print(
                    f"[live] {feed.channel} pubDate example: raw={provenance.raw_value!r} "
                    f"normalized={provenance.normalized_at} note={provenance.normalization_note!r}"
                )
    finally:
        await source.aclose()

"""FX-57E: real-source validation for `StatCanSource` against
Statistics Canada's own live Atom feeds -- non-destructive (one GET
per configured feed, conservatively paced), no credentials required.
Not part of the deterministic unit suite (see tests/unit/
infrastructure/news_sources/test_statcan_atom_parsing.py and
test_statcan_source.py for that); this proves today's real StatCan
feeds still parse and map the way this story's own live-validation
pass found them to.

Marked `live_source` -- excluded from ordinary `pytest`/CI runs (see
`pyproject.toml`'s `addopts`); run explicitly and separately via
`pytest -m live_source` and report that result on its own, never
folded into the deterministic suite's own pass/fail count.

**The cross-subject overlap check is INVERTED from every other FX-57
adapter's own live test (FX-57E0/ADR 0006).** Fed/ECB/BoE/GOV.UK's own
live tests assert their own channels remain fully disjoint, because
their own live research found exactly that. StatCan's own live
research found the OPPOSITE: the SAME Daily release genuinely,
reproducibly, cross-lists under more than one subject feed. This test
therefore does NOT assert empty pairwise id intersections -- it
asserts that ANY overlap found is BENIGN (the overlapping ids carry
IDENTICAL titles), which is exactly the condition under which
`IngestNewsSourceOnce` safely merges both into one item's own
cumulative `observed_source_channels` rather than failing the run
closed. A genuinely CONFLICTING overlap (same id, differing title)
would fail this test loudly -- that is precisely the shape that would
also make a real ingestion run raise `ConflictingDuplicateExternal
IdError`, and is worth a human look immediately, not a silent
production failure.

**Item-level invalids are EXPECTED here, unlike every other FX-57
adapter.** Live research found a recurring StatCan "Product/Study"
catalogue-reference entry type (re-announced with a fresh `updated`
value on almost every poll, structurally distinct from a dated Daily
release) in three of the four adopted feeds. This test does not
assert `items_invalid == 0` (the ECB/BoE/GOV.UK precedent) -- it
asserts every invalid reason matches that SPECIFIC, already-understood
pattern, so a genuinely NEW kind of invalid entry (true source-schema
drift) still fails this test loudly rather than being silently
absorbed alongside the expected catalogue-reference noise.
"""

import re

import pytest

from forex_agent.infrastructure.news_sources.statcan_source import (
    SOURCE_KEY,
    STATCAN_FEEDS,
    StatCanSource,
)

_EXPECTED_INVALID_REASON = re.compile(r"recurring product/catalogue reference")


@pytest.mark.live_source
@pytest.mark.asyncio
async def test_all_four_statcan_feeds_are_reachable_and_yield_valid_items() -> None:
    source = StatCanSource()
    ids_by_channel: dict[str, set[str]] = {}
    titles_by_channel_and_id: dict[tuple[str, str], str] = {}
    try:
        for feed in STATCAN_FEEDS:
            outcome = await source.fetch_feed(feed)

            assert outcome.source_channel == feed.channel
            print(
                f"[live] {feed.channel}: items={len(outcome.observations)} "
                f"invalid={outcome.items_invalid} retrieved_at={outcome.retrieved_at.value}"
            )
            for reason in outcome.invalid_reasons:
                assert _EXPECTED_INVALID_REASON.search(reason), (
                    f"live StatCan {feed.channel!r} feed produced an invalid entry with an "
                    f"UNEXPECTED reason (not the known recurring catalogue-reference pattern) "
                    f"-- this may be genuine source-schema drift needing review: {reason!r}"
                )

            assert len(outcome.observations) > 0, f"expected at least one live {feed.channel} item"
            ids_by_channel[feed.channel] = {o.external_item_id for o in outcome.observations}
            for observation in outcome.observations:
                titles_by_channel_and_id[(feed.channel, observation.external_item_id)] = (
                    observation.headline
                )

            for observation in outcome.observations:
                assert observation.source_key == SOURCE_KEY
                assert observation.source_channel == feed.channel
                assert observation.external_item_id
                assert observation.headline.strip()
                assert observation.authors == ()
                assert observation.language == "en"
                assert observation.source_content_type == "daily_release"
                assert observation.body_text is None
                assert observation.source_updated_at is None
                assert observation.observed_at == outcome.retrieved_at
                assert observation.canonical_url == observation.external_item_id
                assert re.match(
                    r"^https://www\.statcan\.gc\.ca/daily-quotidien/\d{6}/dq\d{6}[a-z]+-eng\.htm$",
                    observation.external_item_id,
                ), (
                    "live StatCan id no longer matches the expected dq-token shape: "
                    f"{observation.external_item_id!r}"
                )

                if observation.source_published_at is not None:
                    assert observation.source_published_at.value <= outcome.retrieved_at.value, (
                        f"future-dated StatCan item found: external_item_id="
                        f"{observation.external_item_id!r} source_published_at="
                        f"{observation.source_published_at.value!r} is AFTER this response's "
                        f"own retrieved_at={outcome.retrieved_at.value!r} -- this contradicts "
                        "this story's own live-validation finding of zero future-dated items"
                    )
                assert len(observation.source_timestamp_provenance) == 1
                assert observation.source_timestamp_provenance[0].field_name == "updated"
    finally:
        await source.aclose()

    # FX-57E0/ADR 0006: cross-subject overlap is EXPECTED -- assert
    # any overlap found is BENIGN (identical titles), not that no
    # overlap exists.
    channels = list(ids_by_channel)
    total_overlap_pairs = 0
    for i, channel_a in enumerate(channels):
        for channel_b in channels[i + 1 :]:
            overlap = ids_by_channel[channel_a] & ids_by_channel[channel_b]
            if overlap:
                total_overlap_pairs += len(overlap)
                print(f"[live] cross-subject overlap {channel_a} & {channel_b}: {sorted(overlap)}")
            for shared_id in overlap:
                title_a = titles_by_channel_and_id[(channel_a, shared_id)]
                title_b = titles_by_channel_and_id[(channel_b, shared_id)]
                assert title_a == title_b, (
                    f"GENUINE cross-subject CONFLICT found: id={shared_id!r} has DIFFERING "
                    f"titles between {channel_a!r} ({title_a!r}) and {channel_b!r} "
                    f"({title_b!r}) -- this is exactly the shape that would make a real "
                    "ingestion run raise ConflictingDuplicateExternalIdError; needs review "
                    "before assuming it is safe to run the manual ingestion script"
                )
    print(f"[live] total cross-subject overlapping ids this run: {total_overlap_pairs}")

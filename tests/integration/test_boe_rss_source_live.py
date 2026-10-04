"""FX-57C Section 44/47: real-source validation for `BoeRssSource`
against the Bank of England's own live public RSS feeds -- non-
destructive (one GET per configured feed), no credentials required.
Not part of the deterministic unit suite (see tests/unit/
infrastructure/news_sources/test_boe_rss_source.py for that); this
proves today's real feeds still parse and map the way this story's
own live-validation pass found them to.

Marked `live_source` -- excluded from ordinary `pytest`/CI runs (see
`pyproject.toml`'s `addopts`); run explicitly and separately via
`pytest -m live_source` and report that result on its own, never
folded into the deterministic suite's own pass/fail count.

Deliberately non-fragile about CONTENT: asserts shape (opaque guid/
headline presence, correct channel, no exception) and reports field-
presence facts, never an exact title, item count, or pubDate value,
which can change at any time on the BoE's own site.

**Strict about `items_invalid`, following ECB's own FX-57BH
precedent (Section 43)**: asserts `items_invalid == 0` per feed,
including the actual invalid reasons in the failure message. A live
BoE item going invalid can mean a source-schema drift, an identity
change, or a missing headline/guid -- any of which needs a human to
look, not a quietly-green live test.

**Also actively re-checks the future-dated-item finding every run
(Section 20)**: compares every observation's own `source_published_
at` against the response's own `retrieved_at` and fails loudly if any
item's source pubDate is in the future relative to FTA's own
retrieval instant -- this story's own live-validation pass found NONE,
but this assertion exists so a genuine change in BoE's own publishing
behaviour (e.g. a scheduled/upcoming item newly appearing in one of
these feeds) is caught immediately rather than silently ingested as
ordinary current evidence.

**FX-57CH Section 7: actively re-checks cross-channel GUID overlap
every run, not just once during research.** After all three feeds
have been fetched, every pairwise intersection of their own GUID sets
is computed and asserted empty, naming any offending GUID and the
channels it was found in. `IngestNewsSourceOnce` itself now fails an
ingestion run closed if this ever happens (`CrossChannelIdentity
CollisionError`) -- this live test exists so a genuine change in
BoE's own feed design (the source shape this story's whole design
rests on) is caught here, visibly, rather than only being discovered
the next time the real manual ingestion run unexpectedly raises.
"""

import pytest

from forex_agent.infrastructure.news_sources.boe_rss_source import BOE_FEEDS, BoeRssSource


@pytest.mark.live_source
@pytest.mark.asyncio
async def test_all_three_boe_feeds_are_reachable_and_yield_valid_items() -> None:
    source = BoeRssSource()
    guids_by_channel: dict[str, set[str]] = {}
    try:
        for feed in BOE_FEEDS:
            outcome = await source.fetch_feed(feed)

            assert outcome.source_channel == feed.channel
            print(
                f"[live] {feed.channel}: items={len(outcome.observations)} "
                f"invalid={outcome.items_invalid} retrieved_at={outcome.retrieved_at.value}"
            )
            if outcome.items_invalid:
                print(f"[live] invalid_reasons={outcome.invalid_reasons!r}")
            assert outcome.items_invalid == 0, (
                f"{outcome.items_invalid} live BoE {feed.channel} item(s) were invalid -- "
                "this may be a source-schema drift, an identity change, or a missing "
                f"headline/guid needing review, not an adapter bug to paper over: "
                f"{outcome.invalid_reasons!r}"
            )

            assert len(outcome.observations) > 0, f"expected at least one live {feed.channel} item"

            guids_by_channel[feed.channel] = {o.external_item_id for o in outcome.observations}

            pub_date_shapes_seen: set[str] = set()
            for observation in outcome.observations:
                assert observation.source_key == "BOE"
                assert observation.external_item_id
                assert observation.headline.strip()
                assert observation.source_channel == feed.channel
                assert observation.source_content_type == feed.content_type
                assert observation.authors == ()
                assert observation.language == "en"
                assert observation.source_updated_at is None
                assert observation.body_text is None

                if observation.source_published_at is not None:
                    assert observation.source_timestamp_provenance
                    provenance = observation.source_timestamp_provenance[0]
                    suffix = provenance.raw_value.strip()[-1]
                    pub_date_shapes_seen.add("Z" if suffix == "Z" else "offset")
                    assert observation.source_published_at.value <= outcome.retrieved_at.value, (
                        f"future-dated BoE item found: external_item_id="
                        f"{observation.external_item_id!r} source_published_at="
                        f"{observation.source_published_at.value!r} is AFTER this response's "
                        f"own retrieved_at={outcome.retrieved_at.value!r} -- this contradicts "
                        "this story's own live-validation finding of zero future-dated items "
                        "and needs review before assuming it is safe to ingest as ordinary "
                        "eligible evidence"
                    )

            print(f"[live] {feed.channel} pubDate shapes seen: {sorted(pub_date_shapes_seen)}")
    finally:
        await source.aclose()

    channels = list(guids_by_channel)
    for i, channel_a in enumerate(channels):
        for channel_b in channels[i + 1 :]:
            overlap = guids_by_channel[channel_a] & guids_by_channel[channel_b]
            assert not overlap, (
                f"cross-channel GUID overlap found between {channel_a!r} and "
                f"{channel_b!r}: {sorted(overlap)!r} -- this contradicts this story's own "
                "live-validation finding of zero cross-channel overlap; IngestNewsSourceOnce "
                "would now fail this ingestion run closed (CrossChannelIdentityCollisionError) "
                "rather than silently forcing it through the single-channel-per-vintage model"
            )

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
asserts that ANY overlap found is BENIGN, using the EXACT SAME
compatibility rule production ingestion uses
(`ingest_news_source_once._same_non_channel_facts` -- imported
directly rather than re-implemented, FX-57EH Section 5), not a
hand-picked subset of fields. A genuinely CONFLICTING overlap (same
id, differing non-channel facts) fails this test loudly -- that is
precisely the shape that would also make a real ingestion run raise
`ConflictingDuplicateExternalIdError`, and is worth a human look
immediately, not a silent production failure.

**Item-level invalids are EXPECTED here, unlike every other FX-57
adapter -- but only the EXACT known shape is tolerated (FX-57EH
Section 2/4).** Live research found a recurring StatCan "Product/
Study" catalogue-reference entry type (re-announced with a fresh
`updated` value on almost every poll, structurally distinct from a
dated Daily release) in three of the four adopted feeds. This test
does not assert `items_invalid == 0` (the ECB/BoE/GOV.UK precedent)
-- but it no longer tolerates an invalid entry merely because its own
diagnostic STRING happens to mention "catalogue" either (the original
FX-57E version of this test did, which could have silently absorbed a
genuinely NEW non-Daily shape alongside the already-understood noise).
It extracts the actual offending id from each invalid reason and
re-checks it against `is_known_catalogue_reference_id` -- the SAME
exact shape predicate the parser itself uses -- so a truly novel
non-Daily shape (real source-schema drift) fails this test loudly.
"""

import ast
import re

import pytest

from forex_agent.application.ports.news_source import NormalizedNewsObservation
from forex_agent.application.use_cases.ingest_news_source_once import _same_non_channel_facts
from forex_agent.infrastructure.news_sources.statcan_atom_parsing import (
    is_known_catalogue_reference_id,
)
from forex_agent.infrastructure.news_sources.statcan_source import (
    SOURCE_KEY,
    STATCAN_FEEDS,
    StatCanSource,
)

_DAILY_RELEASE_ID_RE = re.compile(
    r"^https://www\.statcan\.gc\.ca/daily-quotidien/\d{6}/dq\d{6}[a-z]+-eng\.htm$"
)


def _extract_offending_id(invalid_reason: str) -> str:
    """Pulls the trailing `repr(entry_id)` off one of `statcan_atom_
    parsing.py`'s own invalid-reason strings (both of its own
    diagnostics end with `: {entry_id_raw!r}`) -- using `ast.
    literal_eval` rather than a loose substring/regex match on the
    surrounding prose, so this test re-verifies the ACTUAL id against
    the ACTUAL shape predicate, never the diagnostic's own wording."""
    tail = invalid_reason.rsplit(": ", 1)[-1]
    value = ast.literal_eval(tail)
    assert isinstance(value, str)
    return value


@pytest.mark.live_source
@pytest.mark.asyncio
async def test_all_four_statcan_feeds_are_reachable_and_yield_valid_items() -> None:
    source = StatCanSource()
    ids_by_channel: dict[str, set[str]] = {}
    observations_by_channel_and_id: dict[tuple[str, str], NormalizedNewsObservation] = {}
    try:
        for feed in STATCAN_FEEDS:
            outcome = await source.fetch_feed(feed)

            assert outcome.source_channel == feed.channel
            print(
                f"[live] {feed.channel}: items={len(outcome.observations)} "
                f"invalid={outcome.items_invalid} retrieved_at={outcome.retrieved_at.value}"
            )
            for reason in outcome.invalid_reasons:
                offending_id = _extract_offending_id(reason)
                assert is_known_catalogue_reference_id(offending_id), (
                    f"live StatCan {feed.channel!r} feed produced an invalid entry whose own "
                    f"id does NOT match the known recurring catalogue-reference shape -- this "
                    f"is a genuinely UNEXPECTED non-Daily shape, possibly real source-schema "
                    f"drift needing review: id={offending_id!r} reason={reason!r}"
                )

            assert len(outcome.observations) > 0, f"expected at least one live {feed.channel} item"
            ids_by_channel[feed.channel] = {o.external_item_id for o in outcome.observations}
            for observation in outcome.observations:
                observations_by_channel_and_id[(feed.channel, observation.external_item_id)] = (
                    observation
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
                assert _DAILY_RELEASE_ID_RE.match(observation.external_item_id), (
                    "live StatCan id no longer matches the expected dq-token shape: "
                    f"{observation.external_item_id!r}"
                )

                # FX-57EH Section 7: every accepted Daily-release
                # observation must carry a genuine, normalized
                # source_published_at and exactly one "updated"
                # provenance fact with a non-empty raw value -- live-
                # reconfirmed on every sampled item this story's own
                # research found. This is a live DRIFT assertion only;
                # it does not change the parser's own fail-soft
                # behavior for a malformed OPTIONAL timestamp.
                assert observation.source_published_at is not None, (
                    f"live StatCan item {observation.external_item_id!r} has no normalized "
                    "source_published_at -- this contradicts this story's own live-validation "
                    "finding that every sampled Daily-release entry's <updated> value "
                    "normalizes successfully"
                )
                assert observation.source_published_at.value <= outcome.retrieved_at.value, (
                    f"future-dated StatCan item found: external_item_id="
                    f"{observation.external_item_id!r} source_published_at="
                    f"{observation.source_published_at.value!r} is AFTER this response's "
                    f"own retrieved_at={outcome.retrieved_at.value!r} -- this contradicts "
                    "this story's own live-validation finding of zero future-dated items"
                )
                assert len(observation.source_timestamp_provenance) == 1
                provenance = observation.source_timestamp_provenance[0]
                assert provenance.field_name == "updated"
                assert provenance.raw_value.strip()
                assert provenance.normalized_at is not None, (
                    f"live StatCan item {observation.external_item_id!r} carries an "
                    f"'updated' provenance entry whose raw value ({provenance.raw_value!r}) "
                    "failed to normalize -- this contradicts this story's own live-"
                    "validation finding that every sampled item's own timestamp normalizes"
                )
    finally:
        await source.aclose()

    # FX-57E0/ADR 0006: cross-subject overlap is EXPECTED -- assert
    # any overlap found is BENIGN using the EXACT production
    # compatibility rule (FX-57EH Section 5), not a hand-picked
    # subset of fields (e.g. title alone).
    channels = list(ids_by_channel)
    total_overlap_pairs = 0
    for i, channel_a in enumerate(channels):
        for channel_b in channels[i + 1 :]:
            overlap = ids_by_channel[channel_a] & ids_by_channel[channel_b]
            if overlap:
                total_overlap_pairs += len(overlap)
                print(f"[live] cross-subject overlap {channel_a} & {channel_b}: {sorted(overlap)}")
            for shared_id in overlap:
                observation_a = observations_by_channel_and_id[(channel_a, shared_id)]
                observation_b = observations_by_channel_and_id[(channel_b, shared_id)]
                assert _same_non_channel_facts(observation_a, observation_b), (
                    f"GENUINE cross-subject CONFLICT found: id={shared_id!r} has DIFFERING "
                    f"non-channel facts between {channel_a!r} and {channel_b!r} (headline_a="
                    f"{observation_a.headline!r}, headline_b={observation_b.headline!r}) -- "
                    "this is exactly the shape that would make a real ingestion run raise "
                    "ConflictingDuplicateExternalIdError; needs review before assuming it is "
                    "safe to run the manual ingestion script"
                )
    print(f"[live] total cross-subject overlapping ids this run: {total_overlap_pairs}")

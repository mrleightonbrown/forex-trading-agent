"""FX-57D: real-source validation for `GovUkHmtSource` against the
real GOV.UK Atom discovery feed and Content API -- non-destructive
(one discovery GET, plus one Content API GET per discovered path, all
conservatively paced), no credentials required. Not part of the
deterministic unit suite (see tests/unit/infrastructure/news_sources/
test_govuk_discovery.py and test_govuk_content_api.py for that); this
proves today's real GOV.UK feeds/API still parse and map the way this
story's own live-validation pass found them to -- mirrors FX-57A/B/C's
own `test_fed_rss_source_live.py`/`test_ecb_rss_source_live.py`/
`test_boe_rss_source_live.py`.

Marked `live_source` -- excluded from ordinary `pytest`/CI runs (see
`pyproject.toml`'s `addopts`); run explicitly and separately via
`pytest -m live_source` and report that result on its own, never
folded into the deterministic suite's own pass/fail count.

**Bounded, not exhaustive**: the live HMT discovery feed (at the time
of this story's own research) returns ~20 entries -- small enough to
hydrate EVERY discovered path once, which is also exactly what lets
this test actively re-check the content_id-collision gate (Section
14/55) across the WHOLE discovered set every run, not just a sample.
If the feed's own depth ever grows materially, this test still only
issues one paced request per entry -- never historical enumeration,
never pagination, never the GOV.UK Search API.

**Deliberately non-fragile about CONTENT**: asserts shape (locale,
content_id presence/shape, HMT organisation membership, PIT-safe
timestamp ordering) and reports field-presence facts, never an exact
title, item count, or timestamp value, which can change at any time on
GOV.UK's own site.

**Strict about structural facts this story's own live research
established**: every sampled item must be `locale == "en"` (Section
40 -- a non-English item under the same discovery surface would mean
identity may need to become `content_id` + `locale`, requiring a
design conversation, not a silent adapter patch); every item must
resolve as HM-Treasury-associated (discovery is already scoped to HMT,
so a hydration-time rejection here would itself be a live finding
worth seeing loudly); no two distinct discovered paths may hydrate to
the same `content_id` (the Section 14/55 collision gate) -- this
story's own research found zero live collisions across all 20 sampled
paths, but this assertion exists so a genuine future collision is
caught here, visibly, rather than only being discovered the next time
the real manual ingestion run unexpectedly raises `ConflictingDuplicate
ExternalIdError`. Also re-checks that no item's `source_published_at`
is after this response's own `retrieved_at`, and that a present
`publishing_scheduled_at` is never silently treated as ordinary
evidence if it is still in the future relative to retrieval.
"""

import pytest

from forex_agent.infrastructure.news_sources.govuk_content_api import (
    CHANNEL,
    SOURCE_KEY,
    GovUkHmtSource,
)


@pytest.mark.live_source
@pytest.mark.asyncio
async def test_hmt_discovery_and_content_api_hydration_yield_valid_items() -> None:
    source = GovUkHmtSource()
    try:
        paths = await source.discover_current_paths()
        print(f"[live] discovered {len(paths)} HMT path(s): {paths!r}")
        assert len(paths) > 0, "expected at least one live HMT discovery path"
        assert len(set(paths)) == len(paths), "discovery itself returned duplicate paths"

        content_ids_by_path: dict[str, str] = {}
        locales_seen: set[str] = set()

        for path in paths:
            outcome = await source.fetch_content_item(path)

            assert outcome.source_channel == CHANNEL
            if outcome.items_invalid:
                print(f"[live] {path}: INVALID -- {outcome.invalid_reasons!r}")
            assert outcome.items_invalid == 0, (
                f"live HMT path {path!r} hydrated to an invalid item -- this may be a "
                "source-schema drift, an organisation-membership change, or a missing "
                f"identity field needing review, not an adapter bug to paper over: "
                f"{outcome.invalid_reasons!r}"
            )
            assert len(outcome.observations) == 1, (
                f"expected exactly one observation for path {path!r}, got "
                f"{len(outcome.observations)}"
            )
            observation = outcome.observations[0]

            assert observation.source_key == SOURCE_KEY
            assert observation.source_channel == CHANNEL
            assert observation.external_item_id
            assert observation.headline.strip()
            assert observation.authors == ()
            assert observation.observed_at == outcome.retrieved_at

            assert observation.language == "en", (
                f"live HMT path {path!r} is locale={observation.language!r}, not 'en' -- "
                "this contradicts this story's own live-validation finding of all-English "
                "content; identity may now need to become content_id+locale, which needs a "
                "design conversation, not a silent adapter patch"
            )
            locales_seen.add(observation.language)

            existing_path = content_ids_by_path.get(observation.external_item_id)
            assert existing_path is None, (
                f"content_id={observation.external_item_id!r} was hydrated from TWO "
                f"different discovery paths ({existing_path!r} and {path!r}) in this SAME "
                "live run -- this contradicts this story's own live-validation finding of "
                "zero cross-path content_id collisions; IngestNewsSourceOnce would fail "
                "this ingestion run closed (ConflictingDuplicateExternalIdError) rather "
                "than silently representing these as two separate items"
            )
            content_ids_by_path[observation.external_item_id] = path

            if observation.source_published_at is not None:
                assert observation.source_published_at.value <= outcome.retrieved_at.value, (
                    f"future-dated HMT item found: content_id="
                    f"{observation.external_item_id!r} source_published_at="
                    f"{observation.source_published_at.value!r} is AFTER this response's "
                    f"own retrieved_at={outcome.retrieved_at.value!r} -- this contradicts "
                    "this story's own live-validation finding of zero future-dated items "
                    "and needs review before assuming it is safe to ingest as ordinary "
                    "eligible evidence"
                )

            scheduled_provenance = next(
                (
                    p
                    for p in observation.source_timestamp_provenance
                    if p.field_name == "publishing_scheduled_at"
                ),
                None,
            )
            if scheduled_provenance is not None and scheduled_provenance.normalized_at is not None:
                assert scheduled_provenance.normalized_at.value <= outcome.retrieved_at.value, (
                    f"content_id={observation.external_item_id!r} carries a "
                    f"publishing_scheduled_at={scheduled_provenance.raw_value!r} still in the "
                    "FUTURE relative to this response's own retrieved_at, while the item is "
                    "substantively exposed through the Content API -- this is the exact "
                    "scheduled-but-exposed case this story's own spec says must STOP or be "
                    "quarantined with an explicit GOV.UK-specific reason, never silently "
                    "ingested as ordinary eligible evidence"
                )

        print(f"[live] hydrated {len(content_ids_by_path)} unique content_id(s), 0 invalid")
        print(f"[live] locales seen: {sorted(locales_seen)}")
    finally:
        await source.aclose()

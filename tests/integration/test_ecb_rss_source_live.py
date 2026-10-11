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

Deliberately non-fragile about CONTENT: asserts shape (guid/headline
presence, correct channel, no exception) and reports field-presence
facts, never an exact title, item count, or pubDate value, which can
change at any time on the ECB's own site.

**FX-57BH Section 6**: deliberately FRAGILE about `items_invalid`,
unlike the deterministic unit suite -- this live test now asserts
`items_invalid == 0`, including the actual invalid reasons in the
failure message. A live ECB item going invalid can mean a newly
introduced content class, an identity-schema change, a missing
headline/guid, or some other source-contract drift -- any of which
needs a human to look, not a quietly-green live test. This does NOT
relax the production adapter's own fail-closed behavior in any way
(an unrecognized content class still fails closed as an invalid item,
never silently admitted) -- it only makes THIS live-drift detector
surface that fact loudly instead of swallowing it.

**FX-57BH.1 (2026-10-11)**: this test's own `items_invalid == 0`
assertion is exactly what caught the `mg` ("Monetary policy accounts")
content class this story adopted -- a live
`/press/accounts/.../ecb.mg...` item the adapter correctly, fail-
closed refused as unrecognized. With `mg` now admitted, `content_
types_seen` is extended to include `"monetary_policy_account"`, and a
new conditional structural assertion fires for any observation whose
own URL lives under `/press/accounts/`: it must carry exactly that
content type. This assertion is intentionally conditional, not
required every run -- the feed is shallow and accounts are periodic,
so a run with no current account present must still pass cleanly
(Section 22)."""

import pytest

from forex_agent.infrastructure.news_sources.ecb_rss_source import ECB_FEEDS, EcbRssSource

_ACCOUNTS_PATH_SEGMENT = "/press/accounts/"


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
        assert outcome.items_invalid == 0, (
            f"{outcome.items_invalid} live ECB item(s) were invalid -- this may be a "
            "newly introduced content class, an identity-schema change, a missing "
            f"headline/guid, or another source-contract change needing review, not an "
            f"adapter bug to paper over: {outcome.invalid_reasons!r}"
        )

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

            # FX-57BH.1 Section 22: conditional, not required every
            # run -- fires only for an observation whose own URL is
            # actually under /press/accounts/ (periodic, shallow feed).
            if observation.canonical_url is not None and (
                _ACCOUNTS_PATH_SEGMENT in observation.canonical_url
            ):
                assert observation.source_content_type == "monetary_policy_account", (
                    f"live ECB item under {_ACCOUNTS_PATH_SEGMENT!r} "
                    f"({observation.canonical_url!r}) has source_content_type="
                    f"{observation.source_content_type!r}, not 'monetary_policy_account' -- "
                    "this contradicts this story's own live-validation finding"
                )

        print(f"[live] content types seen: {sorted(content_types_seen)}")
        assert content_types_seen <= {
            "press_release",
            "speech",
            "interview",
            "monetary_policy_account",
        }
    finally:
        await source.aclose()

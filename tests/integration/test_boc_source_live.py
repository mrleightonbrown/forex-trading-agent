"""FX-57F: real-source validation for `BocSource` against the Bank of
Canada's own live press-releases feed -- non-destructive (one GET),
no credentials required. Not part of the deterministic unit suite
(see tests/unit/infrastructure/news_sources/test_boc_rdf_parsing.py,
test_boc_timestamp_remediation.py, and test_boc_source.py for that);
this proves today's real BoC feed still parses and remediates the way
this story's own live-validation pass found it to.

Marked `live_source` -- excluded from ordinary `pytest`/CI runs (see
`pyproject.toml`'s `addopts`); run explicitly and separately via
`pytest -m live_source` and report that result on its own, never
folded into the deterministic suite's own pass/fail count.

**Section 55's own most important assertion: the dc:date defect shape
is STILL exactly the one this story verified and built remediation
for.** Every live item carrying a `dc:date` must show the EXACT known-
malformed shape (a plain local-looking wall-clock suffixed with the
literal, misleading `+00:00`) and must remediate successfully to a
`source_published_at` that is NOT the literal-UTC reading of that same
string. If the Bank of Canada has since fixed its own feed's offset,
this assertion fails LOUDLY rather than silently continuing to apply
an now-unnecessary (or actively wrong) reinterpretation -- exactly the
behavior Section 23 of this story's own spec required before writing
any remediation code at all, now re-checked on every live run.

**FX-57FH Section 2: EVERY accepted live observation, not merely "at
least one," must carry a dc:date and remediate successfully.** FX-57F's
own live research established that every accepted current press-
release item carries `dc:date` in the exact known malformed shape --
the original version of this test only asserted that fact for at
least one sampled item, and silently `continue`d past any observation
with no timestamp provenance at all. That was too weak to catch the
Bank legitimately beginning to omit `dc:date` from some items: this
test now asserts the full dc:date contract (exactly one provenance
fact, non-blank raw value, the known malformed shape, a non-`None`
`normalized_at`, `source_published_at == normalized_at`) for EVERY
observation, with no skip -- if the Bank begins omitting `dc:date`,
this fails loudly for review, rather than passing through unnoticed.
This is a live DRIFT assertion only; `boc_source.py`'s own fail-soft
handling of a genuinely missing `dc:date` in a synthetic/future
fixture is intentionally UNCHANGED (Section 2's own explicit
instruction) -- only this live test's own expectation was tightened.

**FX-57FH Section 9: strengthened PIT/mode assertions**, re-checked on
every live run alongside every assertion already present before this
hardening pass (exact malformed raw shape, successful remediation, the
4/5-hour EDT/EST shift, identity/link equality, `source_content_type`,
one channel)."""

import re
from datetime import UTC, datetime

import pytest

from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.infrastructure.news_sources.boc_source import CHANNEL, SOURCE_KEY, BocSource

_KNOWN_MALFORMED_SHAPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")


@pytest.mark.live_source
@pytest.mark.asyncio
async def test_boc_press_releases_feed_is_reachable_and_yields_valid_items() -> None:
    source = BocSource()
    try:
        outcome = await source.fetch_press_releases()

        assert outcome.source_channel == CHANNEL
        print(
            f"[live] {CHANNEL}: items={len(outcome.observations)} "
            f"invalid={outcome.items_invalid} retrieved_at={outcome.retrieved_at.value}"
        )
        assert outcome.items_invalid == 0, (
            f"live BoC press-releases feed produced {outcome.items_invalid} invalid item(s): "
            f"{outcome.invalid_reasons!r} -- this contradicts this story's own live-validation "
            "finding of zero invalid items on every sampled poll"
        )
        assert len(outcome.observations) > 0, "expected at least one live BoC press release"

        items_with_dc_date = 0
        for observation in outcome.observations:
            assert observation.source_key == SOURCE_KEY
            assert observation.source_channel == CHANNEL
            assert observation.external_item_id
            assert observation.headline.strip()
            assert observation.authors == ()
            assert observation.language == "en"
            assert observation.source_content_type == "press_release"
            assert observation.body_text is None
            assert observation.source_updated_at is None
            assert observation.observed_at == outcome.retrieved_at
            # Live-confirmed identity shape: rdf:about always equals <link>.
            assert observation.canonical_url == observation.external_item_id

            # FX-57FH Section 9: PIT/mode assertions, every item.
            assert observation.observation_mode == NewsObservationMode.PROSPECTIVE
            assert observation.source_status == NewsSourceStatus.ACTIVE
            assert observation.evidence_disposition == NewsEvidenceDisposition.EVIDENCE_ELIGIBLE

            # FX-57FH Section 2: EVERY accepted live observation must
            # carry exactly one dc:date provenance fact that remediates
            # successfully -- no longer merely "at least one sampled
            # item," and no longer skipped via `continue` when absent.
            assert observation.source_timestamp_provenance, (
                f"live BoC item {observation.external_item_id!r} has NO dc:date timestamp "
                "provenance at all -- this contradicts this story's own live-validation "
                "finding that every currently-accepted press-release item carries dc:date; "
                "if the Bank has begun legitimately omitting it, this needs review before "
                "assuming the existing 'every item has dc:date' assumption still holds"
            )
            items_with_dc_date += 1
            assert len(observation.source_timestamp_provenance) == 1
            provenance = observation.source_timestamp_provenance[0]
            assert provenance.field_name == "dc:date"
            raw = provenance.raw_value
            assert raw.strip(), (
                f"live BoC item {observation.external_item_id!r} has a blank dc:date raw value"
            )

            assert _KNOWN_MALFORMED_SHAPE_RE.match(raw), (
                f"live BoC item {observation.external_item_id!r} has a dc:date "
                f"({raw!r}) that no longer matches the known-malformed shape this story "
                "verified and built remediation for -- the Bank may have fixed its own "
                "feed's timestamp semantics; this needs architecture review BEFORE "
                "assuming the existing remediation is still correct, per this story's own "
                "Section 23"
            )
            assert provenance.normalized_at is not None, (
                f"live BoC item {observation.external_item_id!r} carries the known-"
                f"malformed dc:date shape ({raw!r}) but remediation produced no "
                "normalized_at -- unexpected for a shape matching the known pattern "
                "(a DST-ambiguous/nonexistent instant is possible but was not expected "
                "among today's live items)"
            )
            assert observation.source_published_at == provenance.normalized_at

            # FX-57FH Section 3/9: the production fail-closed guard
            # already refuses to return a future-dated observation at
            # all, so this must always hold for anything reaching here
            # -- re-asserted directly as a redundant live PIT check.
            assert observation.source_published_at.value <= outcome.retrieved_at.value, (
                f"live BoC item {observation.external_item_id!r} has source_published_at "
                f"({observation.source_published_at.value!r}) AFTER this response's own "
                f"retrieved_at ({outcome.retrieved_at.value!r}) -- the production fail-"
                "closed guard should have already rejected this response entirely"
            )

            # Re-confirms the defect ACTUALLY matters: the literal-UTC
            # reading of the raw string must differ from the remediated
            # instant by exactly 4 or 5 hours (EDT or EST) -- proving
            # ZoneInfo-driven DST reinterpretation genuinely ran, not a
            # no-op that happened to pass the regex above.
            literal_utc_reading = datetime.fromisoformat(raw.strip().replace("+00:00", "")).replace(
                tzinfo=UTC
            )
            shift_hours = (
                provenance.normalized_at.value - literal_utc_reading
            ).total_seconds() / 3600
            assert shift_hours in (4.0, 5.0), (
                f"live BoC item {observation.external_item_id!r} remediated dc:date "
                f"{raw!r} by {shift_hours} hours, not the expected 4 (EDT) or 5 (EST) -- "
                "this is not the known America/Toronto defect shape this story verified"
            )

        print(f"[live] items with a dc:date provenance entry: {items_with_dc_date}")
        assert items_with_dc_date == len(outcome.observations), (
            "expected EVERY live BoC observation to carry a dc:date provenance fact "
            f"({items_with_dc_date} of {len(outcome.observations)} did)"
        )
    finally:
        await source.aclose()

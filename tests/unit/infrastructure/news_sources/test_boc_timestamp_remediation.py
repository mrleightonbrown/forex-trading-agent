"""FX-57F: deterministic fixture matrix for `remediate_boc_dc_date` --
the dedicated remediation of the Bank of Canada's own known-malformed
`dc:date` defect (America/Toronto local wall-clock mislabelled with a
literal `+00:00`). No network access -- see this module's own
docstring in `boc_timestamp_remediation.py` for the live research that
confirmed the defect, and tests/integration/test_boc_source_live.py
for the live re-confirmation this story's own `live_source` test
performs on every run.

Cases A-J (Section 51):
  A: summer (EDT) wall-clock, a directly live-observed anchor
  B: winter (EST) wall-clock, the officially-scheduled-time anchor
  C: raw value preserved byte-for-byte regardless of outcome
  D: UTC offset is ALWAYS +04:00/+05:00-consistent, never the literal +00:00
  E: unexpected but well-formed non-+00:00 offset is NOT reinterpreted
  F: malformed wall-clock portion -> None, raw preserved
  G: completely unparseable raw string -> None, raw preserved
  H: DST-ambiguous Toronto local time (autumn fall-back) -> no guess
  I: DST-nonexistent Toronto local time (spring-forward gap) -> no guess
  J: fractional-seconds shape (never observed live) is unrecognized
"""

from datetime import UTC, datetime

from forex_agent.infrastructure.news_sources.boc_timestamp_remediation import (
    remediate_boc_dc_date,
)


def test_a_summer_edt_live_anchor_reinterpreted_correctly() -> None:
    # Live-observed 2026-09-02 FAD release, officially scheduled 09:45 (ET).
    result = remediate_boc_dc_date("2026-09-02T09:47:53+00:00")
    assert result.normalized_at is not None
    assert result.normalized_at.value == datetime(2026, 9, 2, 13, 47, 53, tzinfo=UTC)


def test_b_winter_est_schedule_anchor_reinterpreted_correctly() -> None:
    # Officially-scheduled 09:45 (ET) January rate announcement -- EST is UTC-5.
    result = remediate_boc_dc_date("2026-01-28T09:47:00+00:00")
    assert result.normalized_at is not None
    assert result.normalized_at.value == datetime(2026, 1, 28, 14, 47, 0, tzinfo=UTC)


def test_c_raw_value_is_never_part_of_this_function_contract_but_note_mentions_it() -> None:
    # remediate_boc_dc_date itself has no raw-preservation field (the
    # ADAPTER is responsible for keeping the raw string in
    # NewsSourceTimestampProvenance.raw_value) -- this asserts the note
    # explicitly references the original raw string for traceability.
    raw = "2026-09-02T09:47:53+00:00"
    result = remediate_boc_dc_date(raw)
    assert result.normalization_note is not None


def test_d_literal_utc_offset_reading_is_never_used() -> None:
    result = remediate_boc_dc_date("2026-09-02T09:47:53+00:00")
    assert result.normalized_at is not None
    literal_utc_reading = datetime(2026, 9, 2, 9, 47, 53, tzinfo=UTC)
    assert result.normalized_at.value != literal_utc_reading


def test_e_unexpected_correct_looking_offset_is_not_reinterpreted() -> None:
    # A -04:00 offset LOOKS already-correct for EDT, but is not the
    # specific verified malformed shape -- must not be touched.
    result = remediate_boc_dc_date("2026-09-02T09:47:53-04:00")
    assert result.normalized_at is None
    assert "does not match" in result.normalization_note


def test_e_unexpected_est_looking_offset_is_not_reinterpreted() -> None:
    result = remediate_boc_dc_date("2026-01-28T09:47:00-05:00")
    assert result.normalized_at is None
    assert "does not match" in result.normalization_note


def test_f_malformed_wall_clock_portion_yields_none_and_a_note() -> None:
    result = remediate_boc_dc_date("2026-13-99T99:99:99+00:00")
    assert result.normalized_at is None
    assert result.normalization_note is not None


def test_g_unparseable_raw_string_yields_none_and_a_note() -> None:
    result = remediate_boc_dc_date("not-a-timestamp-at-all")
    assert result.normalized_at is None
    assert "does not match" in result.normalization_note


def test_g_empty_string_yields_none_and_a_note() -> None:
    result = remediate_boc_dc_date("")
    assert result.normalized_at is None


def test_h_dst_ambiguous_fall_back_wall_clock_is_never_guessed() -> None:
    # 2026-11-01 02:00->01:00 fall-back: 01:30 Toronto local occurs twice.
    result = remediate_boc_dc_date("2026-11-01T01:30:00+00:00")
    assert result.normalized_at is None
    assert "AMBIGUOUS" in result.normalization_note


def test_i_dst_nonexistent_spring_forward_wall_clock_is_never_guessed() -> None:
    # 2026-03-08 02:00->03:00 spring-forward: 02:30 Toronto local never occurs.
    result = remediate_boc_dc_date("2026-03-08T02:30:00+00:00")
    assert result.normalized_at is None
    assert "NONEXISTENT" in result.normalization_note


def test_j_fractional_seconds_shape_is_unrecognized() -> None:
    # Never observed live -- must not silently fall through to the
    # old reinterpretation just because it "looks close."
    result = remediate_boc_dc_date("2026-09-02T09:47:53.123+00:00")
    assert result.normalized_at is None
    assert "does not match" in result.normalization_note


def test_whitespace_is_stripped_before_matching() -> None:
    result = remediate_boc_dc_date("  2026-09-02T09:47:53+00:00  ")
    assert result.normalized_at is not None
    assert result.normalized_at.value == datetime(2026, 9, 2, 13, 47, 53, tzinfo=UTC)


def test_z_wall_clock_shortly_before_a_dst_boundary_still_resolves() -> None:
    # 2026-11-01 00:59:59 Toronto local is EDT (UTC-4), unambiguous --
    # one second before the fall-back window begins.
    result = remediate_boc_dc_date("2026-11-01T00:59:59+00:00")
    assert result.normalized_at is not None
    assert result.normalized_at.value == datetime(2026, 11, 1, 4, 59, 59, tzinfo=UTC)


def test_z_wall_clock_shortly_after_a_dst_boundary_resolves_to_the_new_offset() -> None:
    # 2026-11-01 02:00:00 Toronto local is unambiguously EST (UTC-5) --
    # one second after the fall-back window ends.
    result = remediate_boc_dc_date("2026-11-01T02:00:00+00:00")
    assert result.normalized_at is not None
    assert result.normalized_at.value == datetime(2026, 11, 1, 7, 0, 0, tzinfo=UTC)

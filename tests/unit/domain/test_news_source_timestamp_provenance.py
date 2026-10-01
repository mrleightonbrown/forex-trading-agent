from datetime import UTC, datetime

import pytest

from forex_agent.domain.news_source_timestamp_provenance import NewsSourceTimestampProvenance
from forex_agent.domain.timestamps import UtcTimestamp

_T = UtcTimestamp(datetime(2026, 9, 2, 13, 45, tzinfo=UTC))


def test_raw_value_preserved_with_no_normalization() -> None:
    # FX-56 Section 51/52: do not fabricate a normalized value.
    provenance = NewsSourceTimestampProvenance(
        field_name="dc:date", raw_value="2026-09-02T09:45:53+00:00"
    )
    assert provenance.raw_value == "2026-09-02T09:45:53+00:00"
    assert provenance.normalized_at is None
    assert provenance.normalization_note is None


def test_normalized_at_can_accompany_the_raw_value_without_overwriting_it() -> None:
    provenance = NewsSourceTimestampProvenance(
        field_name="dc:date",
        raw_value="2026-09-02T09:45:53+00:00",
        normalized_at=_T,
        normalization_note="raw value mislabels America/Toronto local time as +00:00",
    )
    assert provenance.raw_value == "2026-09-02T09:45:53+00:00"
    assert provenance.normalized_at == _T


def test_field_name_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="field_name"):
        NewsSourceTimestampProvenance(field_name="", raw_value="x")


def test_raw_value_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="raw_value"):
        NewsSourceTimestampProvenance(field_name="dc:date", raw_value="")


def test_normalized_at_must_be_a_utc_timestamp_or_none() -> None:
    with pytest.raises(TypeError, match="normalized_at"):
        NewsSourceTimestampProvenance(
            field_name="dc:date",
            raw_value="x",
            normalized_at=datetime(2026, 9, 2, tzinfo=UTC),  # type: ignore[arg-type]
        )


def test_normalization_note_must_be_non_empty_if_present() -> None:
    with pytest.raises(ValueError, match="normalization_note"):
        NewsSourceTimestampProvenance(field_name="dc:date", raw_value="x", normalization_note="")

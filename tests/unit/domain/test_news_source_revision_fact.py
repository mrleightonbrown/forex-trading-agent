from datetime import UTC, datetime

import pytest

from forex_agent.domain.news_source_revision_fact import (
    NewsSourceRevisionFact,
    NewsSourceRevisionKind,
)
from forex_agent.domain.timestamps import UtcTimestamp

_T = UtcTimestamp(datetime(2026, 9, 28, 15, 56, 37, tzinfo=UTC))


def test_minimal_fact_constructs() -> None:
    fact = NewsSourceRevisionFact(kind=NewsSourceRevisionKind.UPDATE)
    assert fact.kind is NewsSourceRevisionKind.UPDATE
    assert fact.source_timestamp is None
    assert fact.raw_timestamp is None
    assert fact.note is None


def test_full_fact_constructs() -> None:
    fact = NewsSourceRevisionFact(
        kind=NewsSourceRevisionKind.CORRECTION,
        source_timestamp=_T,
        raw_timestamp="2026-09-28T15:56:37Z",
        note="First published.",
    )
    assert fact.kind is NewsSourceRevisionKind.CORRECTION
    assert fact.source_timestamp == _T
    assert fact.note == "First published."


def test_kind_must_be_the_enum() -> None:
    with pytest.raises(TypeError, match="kind"):
        NewsSourceRevisionFact(kind="CORRECTION")  # type: ignore[arg-type]


def test_source_timestamp_must_be_a_utc_timestamp_or_none() -> None:
    with pytest.raises(TypeError, match="source_timestamp"):
        NewsSourceRevisionFact(
            kind=NewsSourceRevisionKind.UPDATE,
            source_timestamp=datetime(2026, 9, 28, tzinfo=UTC),  # type: ignore[arg-type]
        )


def test_raw_timestamp_must_be_non_empty_if_present() -> None:
    with pytest.raises(ValueError, match="raw_timestamp"):
        NewsSourceRevisionFact(kind=NewsSourceRevisionKind.UPDATE, raw_timestamp="")


def test_note_must_be_non_empty_if_present() -> None:
    with pytest.raises(ValueError, match="note"):
        NewsSourceRevisionFact(kind=NewsSourceRevisionKind.UPDATE, note="")


def test_withdrawal_kind_is_distinguishable() -> None:
    fact = NewsSourceRevisionFact(kind=NewsSourceRevisionKind.WITHDRAWAL)
    assert fact.kind is NewsSourceRevisionKind.WITHDRAWAL

"""FX-62 Section 12.A: domain tests for `IntelligenceSource` -- durable
identity creation, every actor kind, and immutability (frozen
dataclass, never literally reassignable)."""

from datetime import UTC, datetime

import pytest

from forex_agent.domain.intelligence_source import IntelligenceSource
from forex_agent.domain.intelligence_source_kind import IntelligenceSourceKind
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(hour: int = 9) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


@pytest.mark.parametrize(
    "kind",
    [
        IntelligenceSourceKind.ORGANIZATION,
        IntelligenceSourceKind.PERSON,
        IntelligenceSourceKind.PUBLICATION,
        IntelligenceSourceKind.TECHNICAL_FEED,
    ],
)
def test_every_source_kind_constructs_successfully(kind: IntelligenceSourceKind) -> None:
    source = IntelligenceSource(source_key="X", source_kind=kind, registered_at=_ts())
    assert source.source_kind is kind


def test_source_key_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="source_key"):
        IntelligenceSource(
            source_key="", source_kind=IntelligenceSourceKind.ORGANIZATION, registered_at=_ts()
        )


def test_source_kind_must_be_the_enum_type() -> None:
    with pytest.raises(TypeError, match="source_kind"):
        IntelligenceSource(source_key="X", source_kind="ORGANIZATION", registered_at=_ts())  # type: ignore[arg-type]


def test_registered_at_must_be_a_utc_timestamp() -> None:
    with pytest.raises(TypeError, match="registered_at"):
        IntelligenceSource(
            source_key="X",
            source_kind=IntelligenceSourceKind.ORGANIZATION,
            registered_at=datetime(2026, 1, 1, tzinfo=UTC),  # type: ignore[arg-type]
        )


def test_is_frozen_and_immutable() -> None:
    source = IntelligenceSource(
        source_key="X", source_kind=IntelligenceSourceKind.ORGANIZATION, registered_at=_ts()
    )
    with pytest.raises(Exception):  # noqa: B017 -- FrozenInstanceError, a dataclasses internal
        source.source_key = "Y"  # type: ignore[misc]


def test_feed_and_organization_are_genuinely_different_identities() -> None:
    """FX-62 Section 4.1's own explicit warning: a feed and its
    publisher are NOT automatically the same actor -- confirmed here
    by constructing both kinds with genuinely different source_key
    values and asserting they are unequal."""
    feed = IntelligenceSource(
        source_key="BOE", source_kind=IntelligenceSourceKind.TECHNICAL_FEED, registered_at=_ts()
    )
    organization = IntelligenceSource(
        source_key="BANK_OF_ENGLAND",
        source_kind=IntelligenceSourceKind.ORGANIZATION,
        registered_at=_ts(),
    )
    assert feed != organization
    assert feed.source_key != organization.source_key

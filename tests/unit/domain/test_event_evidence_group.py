"""FX-54: unit tests for `EventEvidenceGroup` -- a plain, generic
container with no aggregate/ranking behaviour of its own."""

import pytest

from forex_agent.domain.event_evidence_group import EventEvidenceGroup


def test_holds_members_verbatim() -> None:
    group = EventEvidenceGroup(group_key="grp1", members=("a", "b", "c"))
    assert group.group_key == "grp1"
    assert group.members == ("a", "b", "c")


def test_rejects_blank_group_key() -> None:
    with pytest.raises(ValueError, match="group_key"):
        EventEvidenceGroup(group_key="", members=("a",))


def test_rejects_empty_members() -> None:
    with pytest.raises(ValueError, match="members"):
        EventEvidenceGroup(group_key="grp1", members=())


def test_is_frozen() -> None:
    group = EventEvidenceGroup(group_key="grp1", members=("a",))
    with pytest.raises(AttributeError):
        group.group_key = "grp2"  # type: ignore[misc]


def test_has_no_ranking_or_aggregate_field() -> None:
    # FX-54 Section 17: this type must structurally have nowhere to
    # invent a "primary member" or a group-level aggregate fact.
    fields = set(EventEvidenceGroup.__dataclass_fields__)
    assert fields == {"group_key", "members"}

"""FX-61: pure builder converting a `NewsPairEvidenceSnapshot` (FX-60,
already fetched) into a JSON-safe dict for the "Market Context"
dashboard's News Evidence section. No I/O, no repository access, no
reinterpretation: every field here is a direct, renamed passthrough of
FX-60's own evidence. Formally, `View(pair, window_start, as_of) =
Present(FX60(pair, window_start, as_of))` -- this builder is
deterministic and side-effect-free; the SAME snapshot object always
produces the SAME view dict.

**Make FX-60's evidence understandable without changing what FX-60
says.** Three things this module deliberately preserves, per the
architect's own review notes on FX-60H.1:

1. **Provenance survives presentation.** A canonical group's FULL
   membership (`canonical_member_news_item_keys`, FX-60H.1) and its
   evidence-ELIGIBLE subset (`member_news_item_keys`) are exposed as
   two SEPARATE fields here, exactly as FX-60 itself distinguishes
   them -- never flattened into one list.
2. **Missing classification stays visible.** `coverage`/`empty_state`/
   per-group `has_semantic_gaps`/per-group `semantic_gaps` are always
   present in the output, never omitted or buried, so a caller cannot
   mistake an INCOMPLETE_SEMANTICS snapshot for a complete one.
3. **No directional interpretation of any kind.** This module emits
   no `direction`/`sentiment`/`stance`/`bullish`/`bearish`/`hawkish`/
   `dovish`/`importance`/`score`/`weight` field anywhere -- confirmed
   by a dedicated contract test scanning both this module's own
   source and its own output for forbidden tokens.
   `pair_relevance_side` (`BASE_ONLY`/`QUOTE_ONLY`/`BOTH`) is purely
   categorical location evidence, exactly as FX-60 itself defines it:
   it never means "buy"/"sell"/"bullish"/"bearish"."""

import re
from typing import Any
from urllib.parse import urlparse

from forex_agent.application.use_cases.get_pair_news_evidence_snapshot import (
    NewsPairEvidenceGroup,
    NewsPairEvidenceMember,
    NewsPairEvidenceSnapshot,
    NewsPairSemanticGap,
    NewsPairSnapshotAccounting,
)
from forex_agent.domain.news_canonical_relation_vintage import NewsCanonicalRelationVintage
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification

#: FX-61 Section 6: this view's own presentation contract version --
#: independent of `snapshot_policy_version` (FX-60's own `fx60_v1`),
#: which is passed through unchanged alongside it.
PRESENTATION_VERSION = "fx61_v1"

#: FX-61 Section 4.2: a persistent, restrained explanation shown
#: alongside every snapshot -- never implies direction or significance.
RELEVANCE_EXPLANATION_NOTE = (
    "News relevance describes which currencies are mentioned or implicated by the "
    "classified evidence. It does not indicate expected currency direction or trading "
    "significance."
)

#: FX-61 Section 8: four distinct, non-collapsed user-visible "no
#: stories" situations -- never a single generic "No news" message.
EMPTY_STATE_NO_PIT_VISIBLE_NEWS = "no_pit_visible_news"
EMPTY_STATE_NO_WINDOW_ELIGIBLE_EVIDENCE = "no_window_eligible_evidence"
EMPTY_STATE_NO_RELEVANT_STORIES = "no_relevant_stories"

EMPTY_STATE_MESSAGES: dict[str, str] = {
    EMPTY_STATE_NO_PIT_VISIBLE_NEWS: "No news was known to FTA as of this instant.",
    EMPTY_STATE_NO_WINDOW_ELIGIBLE_EVIDENCE: (
        "News may exist, but none qualifies under the requested window and eligibility policy."
    ),
    EMPTY_STATE_NO_RELEVANT_STORIES: (
        "Classified evidence exists, but none was confirmed relevant to this pair in this window."
    ),
}

#: FX-61 Section 4.6, hardened FX-61H Section H2: only these schemes
#: may ever reach the presentation layer as a clickable `canonical_
#: url` -- `javascript:`/`data:`/any other scheme is dropped here, at
#: the source, rather than trusted to client-side handling alone.
_SAFE_URL_SCHEMES = {"http", "https"}

#: FX-61H Section H2: every ASCII C0 control character (0x00-0x1F),
#: DEL (0x7F), and the plain space (0x20) -- a legitimate URL never
#: contains any of these literally (a real space must be percent-
#: encoded as `%20`); rejecting the whole 0x00-0x20 range in one
#: sweep catches NUL/newline/tab/CR injection attempts and bare
#: whitespace together, rather than two separate checks.
_CONTROL_OR_SPACE_PATTERN = re.compile(r"[\x00-\x20\x7f]")


def _safe_external_url(url: str | None) -> str | None:
    """FX-61H Section H2: only a well-formed, absolute `http`/`https`
    URL with a non-empty hostname and no control/space characters is
    ever returned -- anything else (missing scheme, missing host,
    `javascript:`/`data:`, malformed authority, embedded control
    characters) is rejected to `None` HERE, at the single source of
    truth, never left for the client to filter."""
    if url is None:
        return None
    if _CONTROL_OR_SPACE_PATTERN.search(url):
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme.lower() not in _SAFE_URL_SCHEMES:
        return None
    try:
        hostname = parsed.hostname
    except ValueError:
        return None
    if not hostname:
        return None
    return url


def _entity_view(entity: NewsEntityAnnotation) -> dict[str, Any]:
    return {
        "entity_type": entity.entity_type.value,
        "entity_key": entity.entity_key,
        "evidence": [kind.value for kind in entity.evidence],
    }


def _classification_view(classification: NewsSemanticClassification) -> dict[str, Any]:
    return {
        "topics": [t.topic.value for t in classification.topics],
        "entities": [_entity_view(e) for e in classification.entities],
        "currency_relevance": [
            {
                "currency_code": relevance.currency_code,
                "reasons": [reason.value for reason in relevance.reasons],
            }
            for relevance in classification.currency_relevance
        ],
    }


def _member_view(member: NewsPairEvidenceMember) -> dict[str, Any]:
    return {
        "news_item_key": member.news_item_key,
        "first_seen_at": member.first_seen_at.value.isoformat(),
        "basis_news_item_revision_sequence": member.basis_news_item_revision_sequence,
        "news_vintage_availability": member.news_vintage_availability.value.isoformat(),
        "semantic_annotation_revision_sequence": member.semantic_annotation_revision_sequence,
        "semantic_annotation_availability": (
            member.semantic_annotation_availability.value.isoformat()
        ),
        "semantic_algorithm_version": member.semantic_algorithm_version,
        "headline": member.headline,
        "summary": member.summary,
        "canonical_url": _safe_external_url(member.canonical_url),
        "source_content_type": member.source_content_type,
        "source_channel": member.source_channel,
        "source_published_at": (
            None
            if member.source_published_at is None
            else member.source_published_at.value.isoformat()
        ),
        "source_status": member.source_status.value,
        "classification": _classification_view(member.classification),
        "publisher_institution_entity_key": member.publisher_institution_entity_key,
        "publisher_jurisdiction_entity_key": member.publisher_jurisdiction_entity_key,
    }


def _relation_view(relation: NewsCanonicalRelationVintage) -> dict[str, Any]:
    """FX-61 Section 4.5: source-backed relationship records, kept
    exactly as FX-58 stored them -- never a synthesized edge, never
    collapsed into a bare pair of keys. An ineligible intermediate
    member may appear here as an endpoint without ever having its own
    member-detail record (FX-60H.1); this builder never fabricates
    one to compensate."""
    return {
        "left_news_item_key": relation.left_news_item_key,
        "right_news_item_key": relation.right_news_item_key,
        "relation_kind": relation.relation_kind.value,
        "method": relation.method.value,
        "algorithm_version": relation.algorithm_version,
        "availability": relation.availability.value.isoformat(),
        "revision_sequence": relation.revision_sequence,
        "left_item_revision_sequence": relation.left_item_revision_sequence,
        "right_item_revision_sequence": relation.right_item_revision_sequence,
    }


def _semantic_gap_view(gap: NewsPairSemanticGap) -> dict[str, Any]:
    return {
        "canonical_group_key": gap.canonical_group_key,
        "news_item_key": gap.news_item_key,
        "semantic_state": gap.semantic_state.value,
        "current_news_revision_sequence": gap.current_news_revision_sequence,
        "annotation_basis_revision_sequence": gap.annotation_basis_revision_sequence,
    }


def _group_view(
    group: NewsPairEvidenceGroup, group_gaps: tuple[NewsPairSemanticGap, ...]
) -> dict[str, Any]:
    source_channels = sorted({member.source_channel for member in group.members})
    return {
        "canonical_group_key": group.canonical_group_key,
        "story_first_seen_at": group.story_first_seen_at.value.isoformat(),
        "display_member_news_item_key": group.display_member_news_item_key,
        # FX-60H.1 Section H2.1: deliberately TWO separate fields --
        # never flattened into one. `member_news_item_keys` is the
        # evidence-ELIGIBLE subset; `canonical_member_news_item_keys`
        # is the FULL FX-58 canonical membership (may include a
        # member with no eligible evidence of its own at all).
        "member_news_item_keys": list(group.member_news_item_keys),
        "canonical_member_news_item_keys": list(group.canonical_member_news_item_keys),
        "pair_relevance_side": group.pair_relevance_side.value,
        "base_relevance_reasons": [r.value for r in group.base_relevance_reasons],
        "quote_relevance_reasons": [r.value for r in group.quote_relevance_reasons],
        "topics": [t.value for t in group.topics],
        "entities": [_entity_view(e) for e in group.entities],
        "active_relevant_member_keys": list(group.active_relevant_member_keys),
        "withdrawn_relevant_member_keys": list(group.withdrawn_relevant_member_keys),
        "semantic_gap_member_keys": list(group.semantic_gap_member_keys),
        "has_semantic_gaps": len(group.semantic_gap_member_keys) > 0,
        "semantic_gaps": [_semantic_gap_view(g) for g in group_gaps],
        "members": [_member_view(m) for m in group.members],
        "relation_provenance": [_relation_view(r) for r in group.relation_provenance],
        "source_channels": source_channels,
    }


def _accounting_view(accounting: NewsPairSnapshotAccounting) -> dict[str, Any]:
    """A direct, complete passthrough of every `NewsPairSnapshotAccounting`
    field -- FX-61 Section 4.3 explicitly forbids computing any
    base-vs-quote score/balance/net-lean from these counts; this
    builder exposes exactly the counts FX-60H's own accounting already
    produced, nothing derived or aggregated beyond that."""
    return {
        "items_pit_visible": accounting.items_pit_visible,
        "items_snapshot_eligible": accounting.items_snapshot_eligible,
        "items_window_eligible": accounting.items_window_eligible,
        "items_current": accounting.items_current,
        "items_stale": accounting.items_stale,
        "items_unclassified": accounting.items_unclassified,
        "items_pair_relevant": accounting.items_pair_relevant,
        "groups_total": accounting.groups_total,
        "groups_outside_window": accounting.groups_outside_window,
        "groups_without_eligible_evidence": accounting.groups_without_eligible_evidence,
        "groups_pair_irrelevant": accounting.groups_pair_irrelevant,
        "groups_incomplete_semantics": accounting.groups_incomplete_semantics,
        "groups_base_only": accounting.groups_base_only,
        "groups_quote_only": accounting.groups_quote_only,
        "groups_both": accounting.groups_both,
    }


def _empty_state(snapshot: NewsPairEvidenceSnapshot) -> str | None:
    """FX-61 Section 8: distinguishes "no PIT-visible news" / "no
    window-eligible evidence" / "no confirmed pair-relevant stories"
    -- never a single collapsed "No news" state. Returns `None`
    whenever at least one active or withdrawn-only entry exists,
    regardless of semantic coverage (Section 8's own "if a snapshot
    contains both relevant evidence and semantic gaps, show the
    relevant entries and also expose the incomplete coverage")."""
    if snapshot.active_entries or snapshot.withdrawn_only_entries:
        return None
    accounting = snapshot.accounting
    if accounting.items_pit_visible == 0:
        return EMPTY_STATE_NO_PIT_VISIBLE_NEWS
    if accounting.items_window_eligible == 0:
        return EMPTY_STATE_NO_WINDOW_ELIGIBLE_EVIDENCE
    return EMPTY_STATE_NO_RELEVANT_STORIES


def build_news_evidence_view(snapshot: NewsPairEvidenceSnapshot) -> dict[str, Any]:
    """The News Evidence section's own JSON-safe read model. Pure and
    deterministic: the SAME `NewsPairEvidenceSnapshot` object always
    produces the SAME dict -- no clock access, no repository access,
    no re-fetch of any kind."""
    gaps_by_group: dict[str, list[NewsPairSemanticGap]] = {}
    for gap in snapshot.semantic_gaps:
        gaps_by_group.setdefault(gap.canonical_group_key, []).append(gap)

    def _entries_view(entries: tuple[NewsPairEvidenceGroup, ...]) -> list[dict[str, Any]]:
        return [
            _group_view(group, tuple(gaps_by_group.get(group.canonical_group_key, ())))
            for group in entries
        ]

    empty_state = _empty_state(snapshot)
    return {
        "presentation_version": PRESENTATION_VERSION,
        "snapshot_policy_version": snapshot.policy_version,
        "pair": {
            "base_currency": snapshot.base_currency,
            "quote_currency": snapshot.quote_currency,
            "symbol": snapshot.pair.symbol,
        },
        "as_of": snapshot.as_of.value.isoformat(),
        "window_start": snapshot.window_start.value.isoformat(),
        "coverage": snapshot.coverage.value,
        "relevance_explanation_note": RELEVANCE_EXPLANATION_NOTE,
        "accounting": _accounting_view(snapshot.accounting),
        "active_entries": _entries_view(snapshot.active_entries),
        "withdrawn_only_entries": _entries_view(snapshot.withdrawn_only_entries),
        "semantic_gaps": [_semantic_gap_view(g) for g in snapshot.semantic_gaps],
        "empty_state": empty_state,
        "empty_state_message": (None if empty_state is None else EMPTY_STATE_MESSAGES[empty_state]),
    }

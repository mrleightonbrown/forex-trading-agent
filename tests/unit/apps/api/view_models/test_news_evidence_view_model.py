"""FX-61: unit tests for `build_news_evidence_view` -- pure, no I/O.
Every field asserted here must be a direct, renamed passthrough of
FX-60's own evidence; this view model must never interpret it, and
must never flatten away the FX-60H.1 canonical-membership-vs-
eligibility distinction."""

from datetime import UTC, datetime

from forex_agent.application.use_cases.get_news_semantic_state_as_of import NewsSemanticState
from forex_agent.application.use_cases.get_pair_news_evidence_snapshot import (
    NewsPairEvidenceGroup,
    NewsPairEvidenceMember,
    NewsPairEvidenceSnapshot,
    NewsPairSemanticCoverage,
    NewsPairSemanticGap,
    NewsPairSnapshotAccounting,
)
from forex_agent.apps.api.view_models.news_evidence_view_model import (
    EMPTY_STATE_MESSAGES,
    EMPTY_STATE_NO_PIT_VISIBLE_NEWS,
    EMPTY_STATE_NO_RELEVANT_STORIES,
    EMPTY_STATE_NO_WINDOW_ELIGIBLE_EVIDENCE,
    PRESENTATION_VERSION,
    RELEVANCE_EXPLANATION_NOTE,
    build_news_evidence_view,
)
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
from forex_agent.domain.news_canonical_relation_vintage import NewsCanonicalRelationVintage
from forex_agent.domain.news_canonicalization_method import NewsCanonicalizationMethod
from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_pair_relevance import NewsPairRelevanceSide
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp

EURUSD = Instrument(base_currency="EUR", quote_currency="USD")


def _ts(hour: int, minute: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, minute, tzinfo=UTC))


def _classification(
    currency_code: str = "USD", institution: str = "FEDERAL_RESERVE"
) -> NewsSemanticClassification:
    return NewsSemanticClassification(
        entities=(
            NewsEntityAnnotation(
                entity_type=NewsEntityType.INSTITUTION,
                entity_key=institution,
                evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
            ),
            NewsEntityAnnotation(
                entity_type=NewsEntityType.JURISDICTION,
                entity_key="UNITED_STATES",
                evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
            ),
        ),
        topics=(),
        currency_relevance=(
            NewsCurrencyRelevance(
                currency_code=currency_code,
                reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
            ),
        ),
    )


def _member(
    key: str,
    *,
    source_status: NewsSourceStatus = NewsSourceStatus.ACTIVE,
    canonical_url: str | None = None,
    classification: NewsSemanticClassification | None = None,
) -> NewsPairEvidenceMember:
    return NewsPairEvidenceMember(
        news_item_key=key,
        first_seen_at=_ts(9),
        basis_news_item_revision_sequence=0,
        news_vintage_availability=_ts(9),
        semantic_annotation_revision_sequence=0,
        semantic_annotation_availability=_ts(9, 1),
        semantic_algorithm_version="fx59_v1",
        headline=f"Headline for {key}",
        summary=None,
        canonical_url=canonical_url,
        source_content_type=None,
        source_channel="test_channel",
        source_published_at=None,
        source_status=source_status,
        classification=classification or _classification(),
        publisher_institution_entity_key="FEDERAL_RESERVE",
        publisher_jurisdiction_entity_key="UNITED_STATES",
    )


def _singleton_group(
    key: str,
    *,
    side: NewsPairRelevanceSide,
    source_status: NewsSourceStatus = NewsSourceStatus.ACTIVE,
    canonical_url: str | None = None,
) -> NewsPairEvidenceGroup:
    currency = "EUR" if side is NewsPairRelevanceSide.BASE_ONLY else "USD"
    member = _member(
        key,
        source_status=source_status,
        canonical_url=canonical_url,
        classification=_classification(currency_code=currency),
    )
    is_active = source_status is NewsSourceStatus.ACTIVE
    return NewsPairEvidenceGroup(
        canonical_group_key=key,
        story_first_seen_at=_ts(9),
        display_member_news_item_key=key,
        member_news_item_keys=(key,),
        canonical_member_news_item_keys=(key,),
        pair_relevance_side=side,
        base_relevance_reasons=(
            (NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
            if side in (NewsPairRelevanceSide.BASE_ONLY, NewsPairRelevanceSide.BOTH)
            else ()
        ),
        quote_relevance_reasons=(
            (NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
            if side in (NewsPairRelevanceSide.QUOTE_ONLY, NewsPairRelevanceSide.BOTH)
            else ()
        ),
        topics=(),
        entities=member.classification.entities,
        active_relevant_member_keys=(key,) if is_active else (),
        withdrawn_relevant_member_keys=() if is_active else (key,),
        semantic_gap_member_keys=(),
        members=(member,),
        relation_provenance=(),
    )


def _accounting(**overrides: int) -> NewsPairSnapshotAccounting:
    defaults = {
        "items_pit_visible": 1,
        "items_snapshot_eligible": 1,
        "items_window_eligible": 1,
        "items_current": 1,
        "items_stale": 0,
        "items_unclassified": 0,
        "items_pair_relevant": 1,
        "groups_total": 1,
        "groups_outside_window": 0,
        "groups_without_eligible_evidence": 0,
        "groups_pair_irrelevant": 0,
        "groups_incomplete_semantics": 0,
        "groups_base_only": 1,
        "groups_quote_only": 0,
        "groups_both": 0,
    }
    defaults.update(overrides)
    return NewsPairSnapshotAccounting(**defaults)


def _snapshot(
    *,
    active: tuple[NewsPairEvidenceGroup, ...] = (),
    withdrawn: tuple[NewsPairEvidenceGroup, ...] = (),
    gaps: tuple[NewsPairSemanticGap, ...] = (),
    coverage: NewsPairSemanticCoverage = NewsPairSemanticCoverage.COMPLETE,
    accounting: NewsPairSnapshotAccounting | None = None,
    window_start: UtcTimestamp | None = None,
    as_of: UtcTimestamp | None = None,
) -> NewsPairEvidenceSnapshot:
    resolved_window_start = window_start if window_start is not None else _ts(0)
    resolved_as_of = as_of if as_of is not None else _ts(10)
    groups_both = sum(
        1 for g in (*active, *withdrawn) if g.pair_relevance_side is NewsPairRelevanceSide.BOTH
    )
    groups_base = sum(
        1 for g in (*active, *withdrawn) if g.pair_relevance_side is NewsPairRelevanceSide.BASE_ONLY
    )
    groups_quote = sum(
        1
        for g in (*active, *withdrawn)
        if g.pair_relevance_side is NewsPairRelevanceSide.QUOTE_ONLY
    )
    resolved_accounting = accounting or _accounting(
        groups_total=len(active) + len(withdrawn),
        groups_base_only=groups_base,
        groups_quote_only=groups_quote,
        groups_both=groups_both,
        items_pit_visible=sum(
            len(g.canonical_member_news_item_keys) for g in (*active, *withdrawn)
        ),
        items_snapshot_eligible=sum(len(g.member_news_item_keys) for g in (*active, *withdrawn)),
        items_window_eligible=sum(len(g.member_news_item_keys) for g in (*active, *withdrawn)),
        items_current=sum(len(g.members) for g in (*active, *withdrawn)),
        items_pair_relevant=sum(
            len(g.active_relevant_member_keys) + len(g.withdrawn_relevant_member_keys)
            for g in (*active, *withdrawn)
        ),
    )
    return NewsPairEvidenceSnapshot(
        policy_version="fx60_v1",
        pair=EURUSD,
        window_start=resolved_window_start,
        as_of=resolved_as_of,
        coverage=coverage,
        active_entries=active,
        withdrawn_only_entries=withdrawn,
        semantic_gaps=gaps,
        groups_considered=resolved_accounting.groups_total,
        groups_outside_window=resolved_accounting.groups_outside_window,
        groups_without_eligible_evidence=resolved_accounting.groups_without_eligible_evidence,
        groups_pair_irrelevant=resolved_accounting.groups_pair_irrelevant,
        accounting=resolved_accounting,
    )


# --- Section A.1-3: base/quote/both rendering --------------------------------


def test_base_only_group_renders_base_only_side() -> None:
    group = _singleton_group("G1", side=NewsPairRelevanceSide.BASE_ONLY)
    view = build_news_evidence_view(_snapshot(active=(group,)))

    entry = view["active_entries"][0]
    assert entry["pair_relevance_side"] == "BASE_ONLY"
    assert entry["base_relevance_reasons"] == ["SOURCE_JURISDICTION"]
    assert entry["quote_relevance_reasons"] == []


def test_quote_only_group_renders_quote_only_side() -> None:
    group = _singleton_group("G1", side=NewsPairRelevanceSide.QUOTE_ONLY)
    view = build_news_evidence_view(_snapshot(active=(group,)))

    entry = view["active_entries"][0]
    assert entry["pair_relevance_side"] == "QUOTE_ONLY"


def test_both_sides_group_renders_both() -> None:
    member = _member(
        "G1",
        classification=NewsSemanticClassification(
            entities=_classification().entities,
            topics=(),
            currency_relevance=(
                NewsCurrencyRelevance(
                    currency_code="EUR", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
                ),
                NewsCurrencyRelevance(
                    currency_code="USD", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
                ),
            ),
        ),
    )
    group = NewsPairEvidenceGroup(
        canonical_group_key="G1",
        story_first_seen_at=_ts(9),
        display_member_news_item_key="G1",
        member_news_item_keys=("G1",),
        canonical_member_news_item_keys=("G1",),
        pair_relevance_side=NewsPairRelevanceSide.BOTH,
        base_relevance_reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
        quote_relevance_reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
        topics=(),
        entities=member.classification.entities,
        active_relevant_member_keys=("G1",),
        withdrawn_relevant_member_keys=(),
        semantic_gap_member_keys=(),
        members=(member,),
        relation_provenance=(),
    )
    view = build_news_evidence_view(_snapshot(active=(group,)))

    entry = view["active_entries"][0]
    assert entry["pair_relevance_side"] == "BOTH"
    assert entry["base_relevance_reasons"] == ["SOURCE_JURISDICTION"]
    assert entry["quote_relevance_reasons"] == ["SOURCE_JURISDICTION"]


# --- Section A.4: zero directional interpretation ----------------------------


#: Forbidden as a FIELD NAME (dict key) anywhere in this view's own
#: output -- never scanned against prose, which may legitimately
#: mention these words to EXPLAIN their absence (e.g. `relevance_
#: explanation_note` itself says "does not indicate expected currency
#: direction"). This mirrors FX-60's own `test_no_direction_sentiment_
#: or_score_field_exists` precedent (a structural field-name check,
#: never a prose/substring scan).
_FORBIDDEN_FIELD_NAMES = {
    "direction",
    "sentiment",
    "stance",
    "bias",
    "bullish",
    "bearish",
    "hawkish",
    "dovish",
    "importance",
    "importance_score",
    "urgency",
    "severity",
    "confidence_score",
    "impact",
    "impact_score",
    "weight",
    "score",
    "relevance_score",
    "lean",
    "balance",
    "net_evidence",
}


def _all_dict_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(value.keys())
        for v in value.values():
            keys.update(_all_dict_keys(v))
    elif isinstance(value, list):
        for item in value:
            keys.update(_all_dict_keys(item))
    return keys


def _comprehensive_view() -> dict[str, object]:
    member_a = _member("A", classification=_classification(currency_code="EUR"))
    member_b = _member("B", classification=_classification(currency_code="USD"))
    relation = NewsCanonicalRelationVintage(
        left_news_item_key="A",
        right_news_item_key="B",
        revision_sequence=0,
        availability=_ts(9, 30),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        left_item_revision_sequence=0,
        right_item_revision_sequence=0,
        algorithm_version="fx58_v2",
    )
    group = NewsPairEvidenceGroup(
        canonical_group_key="A",
        story_first_seen_at=_ts(9),
        display_member_news_item_key="A",
        member_news_item_keys=("A", "B"),
        canonical_member_news_item_keys=("A", "B"),
        pair_relevance_side=NewsPairRelevanceSide.BOTH,
        base_relevance_reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
        quote_relevance_reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
        topics=(),
        entities=member_a.classification.entities,
        active_relevant_member_keys=("A", "B"),
        withdrawn_relevant_member_keys=(),
        semantic_gap_member_keys=(),
        members=(member_a, member_b),
        relation_provenance=(relation,),
    )
    gap = NewsPairSemanticGap(
        canonical_group_key="A",
        news_item_key="C",
        semantic_state=NewsSemanticState.STALE,
        current_news_revision_sequence=1,
        annotation_basis_revision_sequence=0,
    )
    return build_news_evidence_view(_snapshot(active=(group,), gaps=(gap,)))


def test_view_output_field_names_contain_no_directional_fields() -> None:
    keys = _all_dict_keys(_comprehensive_view())
    for forbidden in _FORBIDDEN_FIELD_NAMES:
        assert forbidden not in keys, f"forbidden field name {forbidden!r} found in view output"


def test_relevance_explanation_note_itself_is_non_directional_prose() -> None:
    """The note is ALLOWED to mention "direction" in prose to disclaim
    it -- this test only checks it never implies an actual lean."""
    lowered = RELEVANCE_EXPLANATION_NOTE.lower()
    for forbidden in ("buy", "sell", "rise", "fall", "bullish", "bearish", "hawkish", "dovish"):
        assert forbidden not in lowered


# --- Section A.5: grouping and member provenance -----------------------------


def test_group_exposes_both_member_key_fields_separately() -> None:
    group = _singleton_group("G1", side=NewsPairRelevanceSide.BASE_ONLY)
    view = build_news_evidence_view(_snapshot(active=(group,)))

    entry = view["active_entries"][0]
    assert entry["member_news_item_keys"] == ["G1"]
    assert entry["canonical_member_news_item_keys"] == ["G1"]
    assert len(entry["members"]) == 1
    assert entry["members"][0]["news_item_key"] == "G1"


# --- Section A.6: deterministic ordering (passthrough) -----------------------


def test_active_entries_preserve_snapshot_order() -> None:
    g1 = _singleton_group("G1", side=NewsPairRelevanceSide.BASE_ONLY)
    g2 = _singleton_group("G2", side=NewsPairRelevanceSide.QUOTE_ONLY)
    # FX-60 Section 41 already orders active_entries newest-first,
    # canonical-group-key tie-broken -- this view never re-sorts.
    view = build_news_evidence_view(_snapshot(active=(g2, g1)))

    keys = [e["canonical_group_key"] for e in view["active_entries"]]
    assert keys == ["G2", "G1"]


# --- Section A.9: empty and incomplete states --------------------------------


def test_empty_state_no_pit_visible_news() -> None:
    acc = _accounting(
        items_pit_visible=0,
        items_snapshot_eligible=0,
        items_window_eligible=0,
        items_current=0,
        items_pair_relevant=0,
        groups_total=0,
        groups_base_only=0,
    )
    view = build_news_evidence_view(_snapshot(accounting=acc))

    assert view["empty_state"] == EMPTY_STATE_NO_PIT_VISIBLE_NEWS
    assert view["empty_state_message"] == EMPTY_STATE_MESSAGES[EMPTY_STATE_NO_PIT_VISIBLE_NEWS]
    assert view["active_entries"] == []


def test_empty_state_no_window_eligible_evidence() -> None:
    acc = _accounting(
        items_pit_visible=1,
        items_snapshot_eligible=1,
        items_window_eligible=0,
        items_current=0,
        items_pair_relevant=0,
        groups_total=1,
        groups_outside_window=1,
        groups_base_only=0,
    )
    view = build_news_evidence_view(_snapshot(accounting=acc))

    assert view["empty_state"] == EMPTY_STATE_NO_WINDOW_ELIGIBLE_EVIDENCE


def test_empty_state_no_relevant_stories() -> None:
    acc = _accounting(
        items_pit_visible=1,
        items_snapshot_eligible=1,
        items_window_eligible=1,
        items_current=1,
        items_pair_relevant=0,
        groups_total=1,
        groups_pair_irrelevant=1,
        groups_base_only=0,
    )
    view = build_news_evidence_view(_snapshot(accounting=acc))

    assert view["empty_state"] == EMPTY_STATE_NO_RELEVANT_STORIES


def test_incomplete_semantics_does_not_suppress_existing_entries() -> None:
    """Section 8: a snapshot with BOTH relevant evidence and semantic
    gaps must show the relevant entries AND expose incomplete
    coverage -- never collapse to an empty-looking state."""
    group = _singleton_group("G1", side=NewsPairRelevanceSide.BASE_ONLY)
    gap = NewsPairSemanticGap(
        canonical_group_key="OTHER",
        news_item_key="X",
        semantic_state=NewsSemanticState.UNCLASSIFIED,
        current_news_revision_sequence=0,
        annotation_basis_revision_sequence=None,
    )
    view = build_news_evidence_view(
        _snapshot(
            active=(group,), gaps=(gap,), coverage=NewsPairSemanticCoverage.INCOMPLETE_SEMANTICS
        )
    )

    assert view["coverage"] == "INCOMPLETE_SEMANTICS"
    assert view["empty_state"] is None
    assert len(view["active_entries"]) == 1
    assert len(view["semantic_gaps"]) == 1


# --- Section A.10: accurate accounting passthrough ---------------------------


def test_accounting_is_a_direct_passthrough() -> None:
    acc = _accounting(
        items_pit_visible=42,
        items_snapshot_eligible=40,
        items_window_eligible=30,
        items_current=25,
        items_stale=3,
        items_unclassified=2,
        items_pair_relevant=10,
        groups_total=20,
        groups_outside_window=5,
        groups_without_eligible_evidence=2,
        groups_pair_irrelevant=11,
        groups_incomplete_semantics=1,
        groups_base_only=1,
        groups_quote_only=0,
        groups_both=0,
    )
    group = _singleton_group("G1", side=NewsPairRelevanceSide.BASE_ONLY)
    view = build_news_evidence_view(_snapshot(active=(group,), accounting=acc))

    assert view["accounting"] == {
        "items_pit_visible": 42,
        "items_snapshot_eligible": 40,
        "items_window_eligible": 30,
        "items_current": 25,
        "items_stale": 3,
        "items_unclassified": 2,
        "items_pair_relevant": 10,
        "groups_total": 20,
        "groups_outside_window": 5,
        "groups_without_eligible_evidence": 2,
        "groups_pair_irrelevant": 11,
        "groups_incomplete_semantics": 1,
        "groups_base_only": 1,
        "groups_quote_only": 0,
        "groups_both": 0,
    }


# --- Section A.11: active vs withdrawn-only separation -----------------------


def test_withdrawn_only_entries_are_kept_separate_from_active() -> None:
    active_group = _singleton_group("G1", side=NewsPairRelevanceSide.BASE_ONLY)
    withdrawn_group = _singleton_group(
        "G2", side=NewsPairRelevanceSide.QUOTE_ONLY, source_status=NewsSourceStatus.WITHDRAWN
    )
    view = build_news_evidence_view(_snapshot(active=(active_group,), withdrawn=(withdrawn_group,)))

    assert [e["canonical_group_key"] for e in view["active_entries"]] == ["G1"]
    assert [e["canonical_group_key"] for e in view["withdrawn_only_entries"]] == ["G2"]
    assert view["active_entries"][0]["active_relevant_member_keys"] == ["G1"]
    assert view["withdrawn_only_entries"][0]["withdrawn_relevant_member_keys"] == ["G2"]


# --- Section A.12: unsafe source URLs are never rendered as links -----------


def test_javascript_scheme_url_is_dropped() -> None:
    group = _singleton_group(
        "G1", side=NewsPairRelevanceSide.BASE_ONLY, canonical_url="javascript:alert(1)"
    )
    view = build_news_evidence_view(_snapshot(active=(group,)))

    assert view["active_entries"][0]["members"][0]["canonical_url"] is None


def test_data_scheme_url_is_dropped() -> None:
    group = _singleton_group(
        "G1",
        side=NewsPairRelevanceSide.BASE_ONLY,
        canonical_url="data:text/html,<script>1</script>",
    )
    view = build_news_evidence_view(_snapshot(active=(group,)))

    assert view["active_entries"][0]["members"][0]["canonical_url"] is None


def test_https_url_is_preserved() -> None:
    group = _singleton_group(
        "G1", side=NewsPairRelevanceSide.BASE_ONLY, canonical_url="https://example.com/story"
    )
    view = build_news_evidence_view(_snapshot(active=(group,)))

    assert view["active_entries"][0]["members"][0]["canonical_url"] == "https://example.com/story"


# --- UTC serialization / presentation metadata -------------------------------


def test_timestamps_serialize_as_iso_utc() -> None:
    group = _singleton_group("G1", side=NewsPairRelevanceSide.BASE_ONLY)
    view = build_news_evidence_view(_snapshot(active=(group,)))

    assert view["as_of"] == "2026-01-01T10:00:00+00:00"
    assert view["window_start"] == "2026-01-01T00:00:00+00:00"
    assert view["active_entries"][0]["story_first_seen_at"] == "2026-01-01T09:00:00+00:00"


def test_presentation_metadata() -> None:
    group = _singleton_group("G1", side=NewsPairRelevanceSide.BASE_ONLY)
    view = build_news_evidence_view(_snapshot(active=(group,)))

    assert view["presentation_version"] == PRESENTATION_VERSION
    assert view["snapshot_policy_version"] == "fx60_v1"
    assert view["pair"] == {"base_currency": "EUR", "quote_currency": "USD", "symbol": "EUR_USD"}
    assert view["relevance_explanation_note"] == RELEVANCE_EXPLANATION_NOTE
    for forbidden in ("expected to rise", "expected to fall", "buy", "sell"):
        assert forbidden not in RELEVANCE_EXPLANATION_NOTE.lower()


# --- Deterministic filtering helpers (topic/source sets) --------------------


def test_source_channels_are_derivable_per_entry_for_client_side_filtering() -> None:
    group = _singleton_group("G1", side=NewsPairRelevanceSide.BASE_ONLY)
    view = build_news_evidence_view(_snapshot(active=(group,)))

    assert view["active_entries"][0]["source_channels"] == ["test_channel"]


def test_has_semantic_gaps_flag_reflects_group_field() -> None:
    group = _singleton_group("G1", side=NewsPairRelevanceSide.BASE_ONLY)
    view = build_news_evidence_view(_snapshot(active=(group,)))

    assert view["active_entries"][0]["has_semantic_gaps"] is False


def test_relation_provenance_passthrough() -> None:
    member_a = _member("A", classification=_classification(currency_code="EUR"))
    member_b = _member("B", classification=_classification(currency_code="USD"))
    relation = NewsCanonicalRelationVintage(
        left_news_item_key="A",
        right_news_item_key="B",
        revision_sequence=0,
        availability=_ts(9, 30),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        left_item_revision_sequence=0,
        right_item_revision_sequence=0,
        algorithm_version="fx58_v2",
    )
    group = NewsPairEvidenceGroup(
        canonical_group_key="A",
        story_first_seen_at=_ts(9),
        display_member_news_item_key="A",
        member_news_item_keys=("A", "B"),
        canonical_member_news_item_keys=("A", "B"),
        pair_relevance_side=NewsPairRelevanceSide.BOTH,
        base_relevance_reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
        quote_relevance_reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
        topics=(),
        entities=member_a.classification.entities,
        active_relevant_member_keys=("A", "B"),
        withdrawn_relevant_member_keys=(),
        semantic_gap_member_keys=(),
        members=(member_a, member_b),
        relation_provenance=(relation,),
    )
    view = build_news_evidence_view(_snapshot(active=(group,)))

    provenance = view["active_entries"][0]["relation_provenance"]
    assert len(provenance) == 1
    assert provenance[0]["left_news_item_key"] == "A"
    assert provenance[0]["right_news_item_key"] == "B"
    assert provenance[0]["relation_kind"] == "SAME_STORY"
    assert provenance[0]["availability"] == "2026-01-01T09:30:00+00:00"


# --- No-network / no-ORM contract (Section 11.D) -----------------------------


def test_view_model_module_makes_no_network_calls_and_defines_no_orm_model() -> None:
    import pathlib

    from forex_agent.apps.api.view_models import news_evidence_view_model as module

    assert module.__file__ is not None
    source = pathlib.Path(module.__file__).read_text()
    assert "import sqlalchemy" not in source.lower()
    assert "from sqlalchemy" not in source.lower()
    for forbidden_token in ("httpx", "requests.", "aiohttp", "urllib.request", "fetch("):
        assert forbidden_token not in source

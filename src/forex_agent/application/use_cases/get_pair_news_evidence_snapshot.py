"""FX-60: "as of this instant, what CURRENT, pair-relevant news
evidence did FTA know for this currency pair, within this explicit
news window?" -- a derived, ON-DEMAND read model over FX-56/57's own
PIT-safe news storage, FX-58's own canonical story groups, and
FX-59's own semantic annotation state. It introduces NO new
persistent table, NO migration, NO snapshot write repository, and NO
append-only snapshot vintage of its own (Section 2) -- every call
recomputes the answer fresh from the three existing evidence layers,
using the SAME explicit `as_of` across every constituent query
(Section 7), so the same historical instant always reproduces the
same answer.

**What this is NOT (Section 1)**: it never decides whether a
currency is bullish/bearish, never computes importance/impact, and
never recommends a trade. `NewsPairRelevanceSide` (`domain.news_
pair_relevance`) is purely categorical location evidence --
`BASE_ONLY`/`QUOTE_ONLY`/`BOTH` never mean "buy"/"sell"/"conflicting."

**Canonicalize before presenting (Section 8/9)**: this use case
reuses FX-58's own `derive_canonical_groups` directly over the SAME
`list_items_seen_as_of`/`list_latest_relation_states_as_of` data
`GetCanonicalNewsGroupsAsOf` itself would use (Section 8's own
explicit "or equivalent existing FX-58 behavior" allowance) -- so the
item list already needed for the window-anchor lookup (Section 13)
is fetched once, not duplicated by also calling that use case. A
canonical group never produces more than ONE pair-evidence entry;
canonical group identity itself remains entirely derived, never
persisted here (Section 9).

**Snapshot-eligible members only (Section 10/11)**: a group member
with no qualifying evidence-eligible vintage contributes nothing --
no pair evidence, no window-anchor contribution, no semantic-gap
diagnostic. `include_backfill` defaults to `False`, exactly like
FX-56/58/59's own prospective-evidence default.

**Story age is `NewsItem.first_seen_at` alone (Section 12)** -- never
`source_published_at`, `source_updated_at`, semantic annotation
availability, or any vintage's own `availability`. `story_first_seen_
at` is the MINIMUM `first_seen_at` among a group's own SNAPSHOT-
ELIGIBLE members only (Section 13) -- a backfill-only member that
would otherwise be the earliest member of a group is excluded from
this computation entirely, so an excluded historical member can never
make a genuinely prospective story look artificially old (Section 68).

**Pair relevance comes ONLY from FX-59's own `currency_relevance`
(Section 22-23)**, via `domain.news_pair_relevance.classify_pair_
relevance` -- this use case never re-runs institution/jurisdiction/
alias/text-search logic of its own. Only `NewsSemanticState.CURRENT`
members may contribute relevance/topics/entities (Section 17) --
`STALE`/`UNCLASSIFIED` mean UNKNOWN relevance, never "irrelevant"
(Section 18), and are instead surfaced as `NewsPairSemanticGap`
diagnostics (Section 20) with `NewsPairSemanticCoverage.
INCOMPLETE_SEMANTICS` (Section 19).

**FX-60H hardening (this story), preserving every rule above
unchanged:**

- **H1 (complete snapshot accounting)**: `NewsPairEvidenceSnapshot`
  gains a new `accounting: NewsPairSnapshotAccounting` field --
  additive only, every pre-existing field is preserved with its exact
  original meaning. `NewsPairSnapshotAccounting` is a fully self-
  reconciling item/group population breakdown: every one of the
  `groups_total` canonical groups this snapshot considered falls into
  EXACTLY ONE mutually-exclusive disposition bucket (`groups_outside_
  window`/`groups_without_eligible_evidence`/`groups_pair_irrelevant`/
  `groups_incomplete_semantics`/`groups_base_only`/`groups_quote_
  only`/`groups_both`), enforced structurally in its own `__post_
  init__`. **A real gap this hardening pass closes**: FX-60's own
  original implementation never counted a group that had a semantic
  gap but NO confirmed pair-relevant member anywhere at all -- such a
  group's own disposition was previously implicit (visible only via
  `len(semantic_gaps)`, never reconciled against `groups_considered`).
  `groups_incomplete_semantics` now names that bucket explicitly, so
  "groups with unresolved semantic relevance are never counted as
  confirmed irrelevant" is a structural invariant, not a convention.
- **H2 (canonical relation provenance)**: `NewsPairEvidenceGroup`
  gains a new `relation_provenance: tuple[NewsCanonicalRelationVintage,
  ...]` field -- the REAL FX-58 relation vintage rows (reused
  directly, never a new DTO, never a new persisted relationship)
  whose both endpoints are members of this group, PIT-filtered by the
  SAME `list_latest_relation_states_as_of(as_of)` call this use case
  already makes for grouping itself (no new query). For a singleton
  group this is empty; for a transitive 3-member group (A-SAME-B,
  B-SAME-C, no direct A-C edge) it lists exactly the two REAL edges
  that justify the merge, never a synthesized phantom edge.
- **H3 (query efficiency)**: the N+1-shaped per-member/per-group
  repository access pattern FX-60's own original implementation had
  (one `latest_evidence_eligible_vintage_as_of` call per member, PLUS
  one redundant `latest_annotation_as_of`/`latest_evidence_eligible_
  vintage_as_of` pair per member inside `GetNewsSemanticStatesAsOf`)
  is replaced with exactly TWO batch repository calls for the ENTIRE
  snapshot -- `latest_evidence_eligible_vintages_as_of`/`latest_
  annotations_as_of` (new batch methods on the SAME `NewsRepository`/
  `NewsSemanticRepository` concrete implementations) -- regardless of
  how many items or groups this snapshot considers. The semantic-
  state classification itself (`CURRENT`/`STALE`/`UNCLASSIFIED`) is
  now computed LOCALLY, via `_resolve_semantic_state`, using the
  SAME already-batch-fetched vintage rather than re-fetching it --
  this is MORE consistent than the original per-item path (which
  fetched the vintage TWICE, independently, and only checked
  afterward that the two fetches agreed), and is proven behaviorally
  IDENTICAL to calling `GetNewsSemanticStateAsOf` once per item by a
  dedicated equivalence test suite. `GetNewsSemanticStateAsOf`/
  `GetNewsSemanticStatesAsOf` themselves (FX-59's own files) are
  completely UNTOUCHED by this change -- FX-60H adds a new, parallel,
  more efficient resolution path used ONLY by this use case; it does
  not alter FX-59's own historical semantics or its own single-item
  query surface, which other callers may continue to use unchanged."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from forex_agent.application.ports.news_canonicalization_repository import (
    NewsCanonicalizationRepository,
)
from forex_agent.application.use_cases.get_news_semantic_state_as_of import NewsSemanticState
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.news_canonical_grouping import derive_canonical_groups
from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
from forex_agent.domain.news_canonical_relation_vintage import NewsCanonicalRelationVintage
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_pair_relevance import (
    NewsPairRelevance,
    NewsPairRelevanceSide,
    classify_pair_relevance,
)
from forex_agent.domain.news_semantic_annotation_vintage import NewsSemanticAnnotationVintage
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.news_topic import NewsTopic
from forex_agent.domain.timestamps import UtcTimestamp

SNAPSHOT_POLICY_VERSION = "fx60_v1"


class _VintageLookup(Protocol):
    """FX-60H Section H3: the narrow structural requirement this use
    case actually needs from a `NewsRepository`-shaped collaborator --
    satisfied directly by `SqlAlchemyNewsRepository`, which already
    implements both methods. Deliberately NOT a widening of the
    GLOBAL `application.ports.news_repository.NewsRepository`
    Protocol itself (that Protocol, and every existing fake
    implementing it elsewhere in this codebase, is left completely
    untouched) -- this local Protocol exists only so this one use
    case can declare its own real dependency precisely."""

    async def latest_evidence_eligible_vintages_as_of(
        self,
        news_item_keys: tuple[str, ...],
        as_of: UtcTimestamp,
        *,
        include_backfill: bool = False,
    ) -> dict[str, NewsItemVintage]: ...


class _SemanticAnnotationLookup(Protocol):
    """FX-60H Section H3: the narrow structural requirement this use
    case needs from a `NewsSemanticRepository`-shaped collaborator --
    satisfied directly by `SqlAlchemyNewsSemanticRepository`. Mirrors
    `_VintageLookup`'s own rationale exactly."""

    async def latest_annotations_as_of(
        self, news_item_keys: tuple[str, ...], as_of: UtcTimestamp
    ) -> dict[str, NewsSemanticAnnotationVintage]: ...


class NewsPairSemanticCoverage(Enum):
    """FX-60 Section 19: whether every snapshot-eligible member of
    every IN-WINDOW canonical group has `CURRENT` semantics as of
    this snapshot's own `as_of` -- scoped to in-window, eligible
    members only (a group excluded by the window, or with no
    eligible members at all, never affects this)."""

    COMPLETE = "COMPLETE"
    INCOMPLETE_SEMANTICS = "INCOMPLETE_SEMANTICS"


class NewsPairSnapshotConstructionError(Exception):
    """Raised when assembling the snapshot discovers a structural
    inconsistency that must never be silently papered over (FX-60
    Section 53) -- e.g. a `CURRENT` semantic state whose own basis
    revision does not actually match the vintage it was compared
    against, a semantic annotation whose source-profile publisher/
    jurisdiction entity is malformed (not exactly one), or a
    canonical-group member with no resolvable `NewsItem`. Never
    raised merely because semantics are `STALE`/`UNCLASSIFIED`
    (Section 54) -- those are reported via `NewsPairSemanticGap`."""


@dataclass(frozen=True, slots=True)
class NewsPairSemanticGap:
    """FX-60 Section 20: deterministic, non-directional diagnostic
    for one snapshot-eligible, in-window member whose semantic state
    is NOT `CURRENT` -- never full body text, never a guess at what
    the pair relevance WOULD be."""

    canonical_group_key: str
    news_item_key: str
    semantic_state: NewsSemanticState
    current_news_revision_sequence: int
    annotation_basis_revision_sequence: int | None
    """The OLD annotation's own basis revision for `STALE`; always
    `None` for `UNCLASSIFIED` (Section 20)."""

    def __post_init__(self) -> None:
        if not self.canonical_group_key.strip():
            raise ValueError("canonical_group_key must be a non-empty string")
        if not self.news_item_key.strip():
            raise ValueError("news_item_key must be a non-empty string")
        if self.semantic_state is NewsSemanticState.CURRENT:
            raise ValueError("a semantic gap can never be CURRENT")
        if self.current_news_revision_sequence < 0:
            raise ValueError("current_news_revision_sequence must not be negative")
        if (
            self.semantic_state is NewsSemanticState.UNCLASSIFIED
            and self.annotation_basis_revision_sequence is not None
        ):
            raise ValueError("UNCLASSIFIED gaps must carry a None basis revision")
        if (
            self.semantic_state is NewsSemanticState.STALE
            and self.annotation_basis_revision_sequence is None
        ):
            raise ValueError("STALE gaps must carry the old annotation's own basis revision")


@dataclass(frozen=True, slots=True)
class NewsPairEvidenceMember:
    """FX-60 Section 30: one CURRENT, snapshot-eligible group member's
    own display-safe detail -- deliberately NEVER includes `body_
    text` (the full stored evidence remains available through
    `NewsRepository` directly; this view stays presentation-sized).

    `first_seen_at` is the owning `NewsItem`'s own first-observation
    time (the story-age anchor); `news_vintage_availability` is the
    CURRENT vintage's own `availability` -- two genuinely different
    instants, never conflated."""

    news_item_key: str
    first_seen_at: UtcTimestamp
    basis_news_item_revision_sequence: int
    news_vintage_availability: UtcTimestamp
    semantic_annotation_revision_sequence: int
    semantic_annotation_availability: UtcTimestamp
    semantic_algorithm_version: str

    headline: str
    summary: str | None
    canonical_url: str | None

    source_content_type: str | None
    source_channel: str
    source_published_at: UtcTimestamp | None
    source_status: NewsSourceStatus

    classification: NewsSemanticClassification
    publisher_institution_entity_key: str
    publisher_jurisdiction_entity_key: str

    def __post_init__(self) -> None:
        if not self.news_item_key.strip():
            raise ValueError("news_item_key must be a non-empty string")
        if not self.headline.strip():
            raise ValueError("headline must be a non-empty string")
        if not self.source_channel.strip():
            raise ValueError("source_channel must be a non-empty string")
        if not self.publisher_institution_entity_key.strip():
            raise ValueError("publisher_institution_entity_key must be a non-empty string")
        if not self.publisher_jurisdiction_entity_key.strip():
            raise ValueError("publisher_jurisdiction_entity_key must be a non-empty string")
        if self.basis_news_item_revision_sequence < 0:
            raise ValueError("basis_news_item_revision_sequence must not be negative")
        if self.semantic_annotation_revision_sequence < 0:
            raise ValueError("semantic_annotation_revision_sequence must not be negative")
        if not self.semantic_algorithm_version.strip():
            raise ValueError("semantic_algorithm_version must be a non-empty string")
        if not isinstance(self.source_status, NewsSourceStatus):
            raise TypeError("source_status must be a NewsSourceStatus")


@dataclass(frozen=True, slots=True)
class NewsPairEvidenceGroup:
    """FX-60 Section 38: one canonical story group's own pair-
    evidence entry -- at most ONE per canonical group (Section 8).

    `relation_provenance` (FX-60H Section H2) is the REAL, PIT-
    filtered FX-58 `SAME_STORY` relation vintage(s) connecting this
    group's own members -- empty for a singleton group."""

    canonical_group_key: str
    story_first_seen_at: UtcTimestamp
    display_member_news_item_key: str
    member_news_item_keys: tuple[str, ...]
    """Every snapshot-eligible member this group actually has, NOT
    merely the ones that happen to be pair-relevant -- includes
    `CURRENT` members with no pair relevance at all (visible via
    `members`) alongside gap members (visible via `semantic_gap_
    member_keys`)."""

    pair_relevance_side: NewsPairRelevanceSide
    base_relevance_reasons: tuple[NewsCurrencyRelevanceReason, ...]
    quote_relevance_reasons: tuple[NewsCurrencyRelevanceReason, ...]

    topics: tuple[NewsTopic, ...]
    entities: tuple[NewsEntityAnnotation, ...]

    active_relevant_member_keys: tuple[str, ...]
    withdrawn_relevant_member_keys: tuple[str, ...]
    semantic_gap_member_keys: tuple[str, ...]

    members: tuple[NewsPairEvidenceMember, ...]
    """Every `CURRENT`, snapshot-eligible member -- including ones
    with no pair relevance of their own (Section 30's own "usable
    CURRENT members"); gap members never appear here."""

    relation_provenance: tuple[NewsCanonicalRelationVintage, ...]

    def __post_init__(self) -> None:
        if not self.canonical_group_key.strip():
            raise ValueError("canonical_group_key must be a non-empty string")
        if not self.active_relevant_member_keys and not self.withdrawn_relevant_member_keys:
            raise ValueError("a group entry requires at least one relevant member")

        _require_sorted_unique("member_news_item_keys", self.member_news_item_keys)
        _require_sorted_unique("active_relevant_member_keys", self.active_relevant_member_keys)
        _require_sorted_unique(
            "withdrawn_relevant_member_keys", self.withdrawn_relevant_member_keys
        )
        _require_sorted_unique("semantic_gap_member_keys", self.semantic_gap_member_keys)

        member_key_set = set(self.member_news_item_keys)
        for key in (*self.active_relevant_member_keys, *self.withdrawn_relevant_member_keys):
            if key not in member_key_set:
                raise ValueError(f"relevant member {key!r} is not in member_news_item_keys")
        if self.display_member_news_item_key not in member_key_set:
            raise ValueError(
                f"display_member_news_item_key={self.display_member_news_item_key!r} must "
                "belong to this group's own members"
            )

        member_keys_with_detail = {m.news_item_key for m in self.members}
        if len(member_keys_with_detail) != len(self.members):
            raise ValueError("members must not contain a duplicate news_item_key")
        if member_keys_with_detail | set(self.semantic_gap_member_keys) != member_key_set:
            raise ValueError(
                "member_news_item_keys must be the exact union of members-with-detail and "
                "semantic-gap member keys"
            )
        if tuple(sorted(self.members, key=lambda m: (m.first_seen_at.value, m.news_item_key))) != (
            self.members
        ):
            raise ValueError("members must be sorted by (first_seen_at, news_item_key)")

        topic_list = list(self.topics)
        if len(set(topic_list)) != len(topic_list):
            raise ValueError("topics must not contain a duplicate NewsTopic")
        if tuple(sorted(topic_list, key=lambda t: t.value)) != self.topics:
            raise ValueError("topics must be in canonical sorted order")

        entity_identities = [(e.entity_type, e.entity_key) for e in self.entities]
        if len(set(entity_identities)) != len(entity_identities):
            raise ValueError("entities must not contain a duplicate (entity_type, entity_key)")
        if (
            tuple(sorted(self.entities, key=lambda e: (e.entity_type.value, e.entity_key)))
            != self.entities
        ):
            raise ValueError("entities must be in canonical sorted order")

        _require_sorted_reasons("base_relevance_reasons", self.base_relevance_reasons)
        _require_sorted_reasons("quote_relevance_reasons", self.quote_relevance_reasons)
        has_base, has_quote = bool(self.base_relevance_reasons), bool(self.quote_relevance_reasons)
        if self.pair_relevance_side is NewsPairRelevanceSide.BASE_ONLY and (
            not has_base or has_quote
        ):
            raise ValueError("BASE_ONLY must carry base reasons only")
        if self.pair_relevance_side is NewsPairRelevanceSide.QUOTE_ONLY and (
            not has_quote or has_base
        ):
            raise ValueError("QUOTE_ONLY must carry quote reasons only")
        if self.pair_relevance_side is NewsPairRelevanceSide.BOTH and not (has_base and has_quote):
            raise ValueError("BOTH must carry reasons on both sides")

        for relation in self.relation_provenance:
            if relation.relation_kind is not NewsCanonicalRelationKind.SAME_STORY:
                raise ValueError("relation_provenance must contain only SAME_STORY relations")
            if (
                relation.left_news_item_key not in member_key_set
                or relation.right_news_item_key not in member_key_set
            ):
                raise ValueError("relation_provenance edges must connect this group's own members")
        provenance_identities = [
            (r.left_news_item_key, r.right_news_item_key) for r in self.relation_provenance
        ]
        if len(set(provenance_identities)) != len(provenance_identities):
            raise ValueError("relation_provenance must not contain a duplicate pair")
        if (
            tuple(
                sorted(
                    self.relation_provenance,
                    key=lambda r: (r.left_news_item_key, r.right_news_item_key),
                )
            )
            != self.relation_provenance
        ):
            raise ValueError("relation_provenance must be in canonical sorted order")


@dataclass(frozen=True, slots=True)
class NewsPairSnapshotAccounting:
    """FX-60H Section H1: a complete, self-reconciling breakdown of
    every item and canonical group this snapshot's own computation
    considered -- so a caller/auditor can verify the snapshot's own
    arithmetic directly, rather than merely trust its headline
    entries. Every count is a plain, factual integer; there is no
    score, weight, or ranking anywhere in this type.

    Group-level dispositions are MUTUALLY EXCLUSIVE and reconcile
    exactly to `groups_total` (enforced in `__post_init__`): every
    canonical group this snapshot derived falls into EXACTLY ONE of
    `groups_outside_window`/`groups_without_eligible_evidence`/
    `groups_pair_irrelevant`/`groups_incomplete_semantics`/`groups_
    base_only`/`groups_quote_only`/`groups_both`. In particular,
    `groups_incomplete_semantics` -- a group that is in-window, has
    eligible evidence, but has at least one STALE/UNCLASSIFIED member
    and NO member yet confirms pair relevance -- is counted
    explicitly and separately from `groups_pair_irrelevant`, which is
    reserved for groups whose relevance is FULLY resolved (every
    eligible member is CURRENT) and confirmed absent. A group with
    unresolved semantic relevance is never counted as confirmed
    irrelevant."""

    items_pit_visible: int
    """Every `NewsItem` visible as of `as_of`, before any eligibility,
    grouping, or window filtering (`list_items_seen_as_of`'s own
    count)."""
    items_snapshot_eligible: int
    """Of those, the ones with a qualifying evidence-eligible vintage
    as of `as_of` (Section 10/11) -- regardless of which group they
    belong to, or whether that group falls in-window."""
    items_window_eligible: int
    """Of the snapshot-eligible items, the ones whose OWN canonical
    group's `story_first_seen_at` falls inside `[window_start,
    as_of]`."""

    items_current: int
    items_stale: int
    items_unclassified: int
    """Semantic-state breakdown, scoped to `items_window_eligible`
    only -- these three always sum to `items_window_eligible`
    exactly."""

    items_pair_relevant: int
    """Of `items_current`, the ones whose own FX-59 `currency_
    relevance` named this pair's base and/or quote currency."""

    groups_total: int
    groups_outside_window: int
    groups_without_eligible_evidence: int
    groups_pair_irrelevant: int
    groups_incomplete_semantics: int
    groups_base_only: int
    groups_quote_only: int
    groups_both: int

    def __post_init__(self) -> None:
        for name in (
            "items_pit_visible",
            "items_snapshot_eligible",
            "items_window_eligible",
            "items_current",
            "items_stale",
            "items_unclassified",
            "items_pair_relevant",
            "groups_total",
            "groups_outside_window",
            "groups_without_eligible_evidence",
            "groups_pair_irrelevant",
            "groups_incomplete_semantics",
            "groups_base_only",
            "groups_quote_only",
            "groups_both",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")

        if self.items_snapshot_eligible > self.items_pit_visible:
            raise ValueError("items_snapshot_eligible must not exceed items_pit_visible")
        if self.items_window_eligible > self.items_snapshot_eligible:
            raise ValueError("items_window_eligible must not exceed items_snapshot_eligible")
        if self.items_current + self.items_stale + self.items_unclassified != (
            self.items_window_eligible
        ):
            raise ValueError(
                "items_current + items_stale + items_unclassified must equal items_window_eligible"
            )
        if self.items_pair_relevant > self.items_current:
            raise ValueError("items_pair_relevant must not exceed items_current")

        group_disposition_sum = (
            self.groups_outside_window
            + self.groups_without_eligible_evidence
            + self.groups_pair_irrelevant
            + self.groups_incomplete_semantics
            + self.groups_base_only
            + self.groups_quote_only
            + self.groups_both
        )
        if group_disposition_sum != self.groups_total:
            raise ValueError(
                "mutually exclusive group dispositions must reconcile exactly to groups_total: "
                f"got {group_disposition_sum}, expected {self.groups_total}"
            )


@dataclass(frozen=True, slots=True)
class NewsPairEvidenceSnapshot:
    """FX-60 Section 39: the top-level, on-demand answer. Never
    persisted -- see the module docstring. Every pre-FX-60H field
    below is preserved with its exact original meaning; `accounting`
    (FX-60H Section H1) is the only new field, and is cross-checked
    against the pre-existing counters in `__post_init__` so the two
    can never silently drift apart."""

    policy_version: str
    pair: Instrument
    window_start: UtcTimestamp
    as_of: UtcTimestamp

    coverage: NewsPairSemanticCoverage

    active_entries: tuple[NewsPairEvidenceGroup, ...]
    withdrawn_only_entries: tuple[NewsPairEvidenceGroup, ...]
    semantic_gaps: tuple[NewsPairSemanticGap, ...]

    groups_considered: int
    groups_outside_window: int
    groups_without_eligible_evidence: int
    groups_pair_irrelevant: int

    accounting: NewsPairSnapshotAccounting

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("policy_version must be a non-empty string")
        if self.window_start.value > self.as_of.value:
            raise ValueError("window_start must not be after as_of")
        if self.groups_considered < 0:
            raise ValueError("groups_considered must not be negative")
        if self.groups_outside_window < 0:
            raise ValueError("groups_outside_window must not be negative")
        if self.groups_without_eligible_evidence < 0:
            raise ValueError("groups_without_eligible_evidence must not be negative")
        if self.groups_pair_irrelevant < 0:
            raise ValueError("groups_pair_irrelevant must not be negative")

        if self.accounting.groups_total != self.groups_considered:
            raise ValueError("accounting.groups_total must match groups_considered")
        if self.accounting.groups_outside_window != self.groups_outside_window:
            raise ValueError("accounting.groups_outside_window must match groups_outside_window")
        if self.accounting.groups_without_eligible_evidence != (
            self.groups_without_eligible_evidence
        ):
            raise ValueError(
                "accounting.groups_without_eligible_evidence must match "
                "groups_without_eligible_evidence"
            )
        if self.accounting.groups_pair_irrelevant != self.groups_pair_irrelevant:
            raise ValueError("accounting.groups_pair_irrelevant must match groups_pair_irrelevant")
        if self.accounting.groups_base_only + self.accounting.groups_quote_only + (
            self.accounting.groups_both
        ) != len(self.active_entries) + len(self.withdrawn_only_entries):
            raise ValueError(
                "accounting's own base_only+quote_only+both group counts must match the "
                "total number of active_entries plus withdrawn_only_entries"
            )

    @property
    def base_currency(self) -> str:
        return self.pair.base_currency

    @property
    def quote_currency(self) -> str:
        return self.pair.quote_currency


def _require_sorted_unique(name: str, keys: tuple[str, ...]) -> None:
    if len(set(keys)) != len(keys):
        raise ValueError(f"{name} must not contain duplicates, got {keys!r}")
    if tuple(sorted(keys)) != keys:
        raise ValueError(f"{name} must be in canonical sorted order, got {keys!r}")


def _require_sorted_reasons(name: str, reasons: tuple[NewsCurrencyRelevanceReason, ...]) -> None:
    if len(set(reasons)) != len(reasons):
        raise ValueError(f"{name} must not contain duplicates, got {reasons!r}")
    if tuple(sorted(reasons, key=lambda r: r.value)) != reasons:
        raise ValueError(f"{name} must be in canonical sorted order, got {reasons!r}")


def _source_profile_entity_key(
    classification: NewsSemanticClassification, entity_type: NewsEntityType, news_item_key: str
) -> str:
    """FX-60 Section 32: exactly one `entity_type` entity carrying
    `SOURCE_PROFILE` evidence represents the publisher institution/
    jurisdiction. Fails closed (never guesses) if that structural
    expectation -- already guaranteed by every real `fx59_v1`
    classification -- is somehow violated."""
    candidates = [
        entity
        for entity in classification.entities
        if entity.entity_type is entity_type
        and NewsEntityEvidenceKind.SOURCE_PROFILE in entity.evidence
    ]
    if len(candidates) != 1:
        raise NewsPairSnapshotConstructionError(
            f"news_item_key={news_item_key!r}: expected exactly one {entity_type.value} entity "
            f"carrying SOURCE_PROFILE evidence, found {len(candidates)}"
        )
    return candidates[0].entity_key


def _resolve_semantic_state(
    vintage: NewsItemVintage, annotation: NewsSemanticAnnotationVintage | None
) -> NewsSemanticState:
    """FX-60H Section H3: the EXACT SAME classification rule `GetNews
    SemanticStateAsOf.__call__` applies (CURRENT iff an annotation
    exists whose own basis revision equals `vintage`'s own revision;
    STALE if an annotation exists but disagrees; UNCLASSIFIED if none
    exists) -- applied LOCALLY, in memory, against a vintage and
    annotation already fetched via the batch repository calls in
    `GetPairNewsEvidenceSnapshot.__call__`, rather than via a second,
    independent per-item repository round trip. Proven behaviorally
    equivalent to `GetNewsSemanticStateAsOf` by a dedicated test
    suite; `GetNewsSemanticStateAsOf` itself is untouched."""
    if annotation is None:
        return NewsSemanticState.UNCLASSIFIED
    if annotation.basis_news_item_revision_sequence == vintage.revision_sequence:
        return NewsSemanticState.CURRENT
    return NewsSemanticState.STALE


class GetPairNewsEvidenceSnapshot:
    """FX-60's own derived, on-demand pair-news evidence snapshot --
    see the module docstring."""

    def __init__(
        self,
        news_repository: _VintageLookup,
        canonicalization_repository: NewsCanonicalizationRepository,
        semantic_repository: _SemanticAnnotationLookup,
    ) -> None:
        self._news_repository = news_repository
        self._canonicalization_repository = canonicalization_repository
        self._semantic_repository = semantic_repository

    async def __call__(
        self,
        pair: Instrument,
        window_start: UtcTimestamp,
        as_of: UtcTimestamp,
        *,
        include_backfill: bool = False,
    ) -> NewsPairEvidenceSnapshot:
        """`as_of` is the caller's own single, explicit PIT cut
        (Section 7) -- every constituent query below uses this exact
        instant; this method never calls `UtcTimestamp.now()`.
        `window_start`/`as_of` are the caller's own explicit window
        (Section 6) -- no hidden 24h/48h/72h policy exists here.

        FX-60H Section H3: exactly FOUR repository round trips total,
        regardless of item/group population size -- `list_items_
        seen_as_of`, `list_latest_relation_states_as_of`, `latest_
        evidence_eligible_vintages_as_of` (batch), `latest_
        annotations_as_of` (batch)."""
        if window_start.value > as_of.value:
            raise ValueError("window_start must not be after as_of")

        # FX-60 Section 8/9: canonical grouping, using the EXACT SAME
        # evidence `GetCanonicalNewsGroupsAsOf` itself would use --
        # may raise NewsCanonicalizationInconsistentStateError, which
        # propagates uncaught (Section 52).
        items = await self._canonicalization_repository.list_items_seen_as_of(as_of)
        relation_states = await self._canonicalization_repository.list_latest_relation_states_as_of(
            as_of
        )
        same_story_pairs = tuple(
            (r.left_news_item_key, r.right_news_item_key)
            for r in relation_states
            if r.relation_kind is NewsCanonicalRelationKind.SAME_STORY
        )
        not_same_story_pairs = tuple(
            (r.left_news_item_key, r.right_news_item_key)
            for r in relation_states
            if r.relation_kind is NewsCanonicalRelationKind.NOT_SAME_STORY
        )
        groups = derive_canonical_groups(items, same_story_pairs, not_same_story_pairs)
        first_seen_by_key = {item.news_item_key: item.first_seen_at for item in items}
        same_story_relations_by_pair = {
            (r.left_news_item_key, r.right_news_item_key): r
            for r in relation_states
            if r.relation_kind is NewsCanonicalRelationKind.SAME_STORY
        }

        # FX-60H Section H3: ONE batch vintage fetch for EVERY item
        # across EVERY group -- never one call per member.
        all_member_keys = tuple(
            sorted({key for group in groups for key in group.member_news_item_keys})
        )
        vintages_by_key = await self._news_repository.latest_evidence_eligible_vintages_as_of(
            all_member_keys, as_of, include_backfill=include_backfill
        )
        # ONE batch annotation fetch, scoped to exactly the items that
        # are actually snapshot-eligible (no point fetching semantics
        # for an item with no eligible vintage at all).
        annotations_by_key = await self._semantic_repository.latest_annotations_as_of(
            tuple(sorted(vintages_by_key)), as_of
        )

        items_window_eligible = 0
        items_current = 0
        items_stale = 0
        items_unclassified = 0
        items_pair_relevant = 0
        groups_outside_window = 0
        groups_without_eligible_evidence = 0
        groups_pair_irrelevant = 0
        groups_incomplete_semantics = 0
        groups_base_only = 0
        groups_quote_only = 0
        groups_both = 0
        active_entries: list[NewsPairEvidenceGroup] = []
        withdrawn_only_entries: list[NewsPairEvidenceGroup] = []
        semantic_gaps: list[NewsPairSemanticGap] = []

        for group in groups:
            # Section 10: snapshot-eligible members only -- already
            # resolved via the batch fetch above.
            eligible_vintages = {
                key: vintages_by_key[key]
                for key in group.member_news_item_keys
                if key in vintages_by_key
            }

            if not eligible_vintages:
                groups_without_eligible_evidence += 1
                continue

            # Section 13: story_first_seen_at from ELIGIBLE members only.
            eligible_first_seen: dict[str, UtcTimestamp] = {}
            for member_key in eligible_vintages:
                first_seen = first_seen_by_key.get(member_key)
                if first_seen is None:
                    raise NewsPairSnapshotConstructionError(
                        f"canonical group {group.canonical_group_key!r} references "
                        f"news_item_key={member_key!r}, which has no resolvable NewsItem"
                    )
                eligible_first_seen[member_key] = first_seen
            story_first_seen_at = min(eligible_first_seen.values(), key=lambda t: t.value)

            if not (window_start.value <= story_first_seen_at.value <= as_of.value):
                groups_outside_window += 1
                continue

            items_window_eligible += len(eligible_vintages)

            # Section 17: semantic state, only CURRENT contributes --
            # resolved LOCALLY (FX-60H Section H3), from the SAME
            # already-batch-fetched vintage, never a second fetch.
            current_members: list[tuple[str, NewsSemanticAnnotationVintage]] = []
            group_gaps: list[NewsPairSemanticGap] = []
            for member_key, vintage in eligible_vintages.items():
                annotation = annotations_by_key.get(member_key)
                state = _resolve_semantic_state(vintage, annotation)
                if state is NewsSemanticState.CURRENT:
                    assert annotation is not None
                    # Section 31/53: fail loudly on basis mismatch --
                    # structurally impossible given `_resolve_semantic_
                    # state` compares against this SAME vintage object,
                    # retained as defense-in-depth.
                    if annotation.basis_news_item_revision_sequence != vintage.revision_sequence:
                        raise NewsPairSnapshotConstructionError(
                            f"news_item_key={member_key!r}: CURRENT annotation basis revision "
                            f"{annotation.basis_news_item_revision_sequence} does not match "
                            f"the current evidence-eligible vintage revision "
                            f"{vintage.revision_sequence}"
                        )
                    current_members.append((member_key, annotation))
                    items_current += 1
                else:
                    if state is NewsSemanticState.STALE:
                        items_stale += 1
                    else:
                        items_unclassified += 1
                    basis = annotation.basis_news_item_revision_sequence if annotation else None
                    group_gaps.append(
                        NewsPairSemanticGap(
                            canonical_group_key=group.canonical_group_key,
                            news_item_key=member_key,
                            semantic_state=state,
                            current_news_revision_sequence=vintage.revision_sequence,
                            annotation_basis_revision_sequence=basis,
                        )
                    )

            semantic_gaps.extend(group_gaps)

            # Section 22-26: pair relevance comes only from FX-59.
            relevant: list[tuple[str, NewsPairRelevance]] = []
            for member_key, annotation in current_members:
                relevance = classify_pair_relevance(
                    pair, annotation.classification.currency_relevance
                )
                if relevance is not None:
                    relevant.append((member_key, relevance))
                    items_pair_relevant += 1

            if not relevant:
                if not group_gaps:
                    groups_pair_irrelevant += 1
                else:
                    # FX-60H Section H1: this group's own pair
                    # relevance is UNRESOLVED (at least one gap, no
                    # confirmed-relevant member yet) -- never counted
                    # as confirmed irrelevant.
                    groups_incomplete_semantics += 1
                continue

            # FX-60H Section H2: the REAL SAME_STORY edges connecting
            # this group's own members, PIT-filtered already (same
            # `relation_states` fetched once above).
            relation_provenance = tuple(
                sorted(
                    (
                        relation
                        for (left, right), relation in same_story_relations_by_pair.items()
                        if left in eligible_vintages and right in eligible_vintages
                    ),
                    key=lambda r: (r.left_news_item_key, r.right_news_item_key),
                )
            )

            entry = _build_group_entry(
                group.canonical_group_key,
                story_first_seen_at,
                eligible_vintages,
                eligible_first_seen,
                current_members,
                dict(relevant),
                group_gaps,
                relation_provenance,
            )
            if entry.pair_relevance_side is NewsPairRelevanceSide.BASE_ONLY:
                groups_base_only += 1
            elif entry.pair_relevance_side is NewsPairRelevanceSide.QUOTE_ONLY:
                groups_quote_only += 1
            else:
                groups_both += 1
            if entry.active_relevant_member_keys:
                active_entries.append(entry)
            else:
                withdrawn_only_entries.append(entry)

        # Section 41: story_first_seen_at descending, canonical_group_key
        # ascending tie-break -- a two-pass stable sort avoids any
        # float-precision risk from negating a datetime for a single
        # composite sort key.
        active_entries.sort(key=lambda g: g.canonical_group_key)
        active_entries.sort(key=lambda g: g.story_first_seen_at.value, reverse=True)
        withdrawn_only_entries.sort(key=lambda g: g.canonical_group_key)
        withdrawn_only_entries.sort(key=lambda g: g.story_first_seen_at.value, reverse=True)
        semantic_gaps.sort(key=lambda g: (g.canonical_group_key, g.news_item_key))

        coverage = (
            NewsPairSemanticCoverage.COMPLETE
            if not semantic_gaps
            else NewsPairSemanticCoverage.INCOMPLETE_SEMANTICS
        )

        accounting = NewsPairSnapshotAccounting(
            items_pit_visible=len(items),
            items_snapshot_eligible=len(vintages_by_key),
            items_window_eligible=items_window_eligible,
            items_current=items_current,
            items_stale=items_stale,
            items_unclassified=items_unclassified,
            items_pair_relevant=items_pair_relevant,
            groups_total=len(groups),
            groups_outside_window=groups_outside_window,
            groups_without_eligible_evidence=groups_without_eligible_evidence,
            groups_pair_irrelevant=groups_pair_irrelevant,
            groups_incomplete_semantics=groups_incomplete_semantics,
            groups_base_only=groups_base_only,
            groups_quote_only=groups_quote_only,
            groups_both=groups_both,
        )

        return NewsPairEvidenceSnapshot(
            policy_version=SNAPSHOT_POLICY_VERSION,
            pair=pair,
            window_start=window_start,
            as_of=as_of,
            coverage=coverage,
            active_entries=tuple(active_entries),
            withdrawn_only_entries=tuple(withdrawn_only_entries),
            semantic_gaps=tuple(semantic_gaps),
            groups_considered=len(groups),
            groups_outside_window=groups_outside_window,
            groups_without_eligible_evidence=groups_without_eligible_evidence,
            groups_pair_irrelevant=groups_pair_irrelevant,
            accounting=accounting,
        )


def _build_group_entry(
    canonical_group_key: str,
    story_first_seen_at: UtcTimestamp,
    eligible_vintages: dict[str, NewsItemVintage],
    eligible_first_seen: dict[str, UtcTimestamp],
    current_members: list[tuple[str, NewsSemanticAnnotationVintage]],
    relevant_by_key: dict[str, NewsPairRelevance],
    group_gaps: list[NewsPairSemanticGap],
    relation_provenance: tuple[NewsCanonicalRelationVintage, ...],
) -> NewsPairEvidenceGroup:
    active_relevant: list[str] = []
    withdrawn_relevant: list[str] = []
    base_reason_union: set[NewsCurrencyRelevanceReason] = set()
    quote_reason_union: set[NewsCurrencyRelevanceReason] = set()
    side_has_base = False
    side_has_quote = False
    topic_union: set[NewsTopic] = set()
    entity_evidence_union: dict[tuple[NewsEntityType, str], set[NewsEntityEvidenceKind]] = {}
    members: list[NewsPairEvidenceMember] = []

    for member_key, annotation in current_members:
        vintage = eligible_vintages[member_key]
        classification = annotation.classification

        for topic_annotation in classification.topics:
            topic_union.add(topic_annotation.topic)
        for entity in classification.entities:
            entity_evidence_union.setdefault((entity.entity_type, entity.entity_key), set()).update(
                entity.evidence
            )

        members.append(
            NewsPairEvidenceMember(
                news_item_key=member_key,
                first_seen_at=eligible_first_seen[member_key],
                basis_news_item_revision_sequence=vintage.revision_sequence,
                news_vintage_availability=vintage.availability,
                semantic_annotation_revision_sequence=annotation.revision_sequence,
                semantic_annotation_availability=annotation.availability,
                semantic_algorithm_version=annotation.algorithm_version,
                headline=vintage.headline,
                summary=vintage.summary,
                canonical_url=vintage.canonical_url,
                source_content_type=vintage.source_content_type,
                source_channel=vintage.source_channel,
                source_published_at=vintage.source_published_at,
                source_status=vintage.source_status,
                classification=classification,
                publisher_institution_entity_key=_source_profile_entity_key(
                    classification, NewsEntityType.INSTITUTION, member_key
                ),
                publisher_jurisdiction_entity_key=_source_profile_entity_key(
                    classification, NewsEntityType.JURISDICTION, member_key
                ),
            )
        )

        relevance = relevant_by_key.get(member_key)
        if relevance is not None:
            base_reason_union.update(relevance.base_relevance_reasons)
            quote_reason_union.update(relevance.quote_relevance_reasons)
            if relevance.side in (NewsPairRelevanceSide.BASE_ONLY, NewsPairRelevanceSide.BOTH):
                side_has_base = True
            if relevance.side in (NewsPairRelevanceSide.QUOTE_ONLY, NewsPairRelevanceSide.BOTH):
                side_has_quote = True
            if vintage.source_status is NewsSourceStatus.ACTIVE:
                active_relevant.append(member_key)
            else:
                withdrawn_relevant.append(member_key)

    if side_has_base and side_has_quote:
        side = NewsPairRelevanceSide.BOTH
    elif side_has_base:
        side = NewsPairRelevanceSide.BASE_ONLY
    else:
        side = NewsPairRelevanceSide.QUOTE_ONLY

    entities = tuple(
        sorted(
            (
                NewsEntityAnnotation(
                    entity_type=entity_type,
                    entity_key=entity_key,
                    evidence=tuple(sorted(kinds, key=lambda k: k.value)),
                )
                for (entity_type, entity_key), kinds in entity_evidence_union.items()
            ),
            key=lambda e: (e.entity_type.value, e.entity_key),
        )
    )
    topics = tuple(sorted(topic_union, key=lambda t: t.value))

    member_news_item_keys = tuple(sorted(eligible_vintages))

    # Section 37: ACTIVE relevant members first, else WITHDRAWN
    # relevant members, earliest NewsItem.first_seen_at, then
    # lexicographically smallest news_item_key -- purely a stable
    # display choice, never "best source"/"highest trust."
    display_candidates = active_relevant or withdrawn_relevant
    display_member = min(display_candidates, key=lambda k: (eligible_first_seen[k].value, k))

    return NewsPairEvidenceGroup(
        canonical_group_key=canonical_group_key,
        story_first_seen_at=story_first_seen_at,
        display_member_news_item_key=display_member,
        member_news_item_keys=member_news_item_keys,
        pair_relevance_side=side,
        base_relevance_reasons=tuple(sorted(base_reason_union, key=lambda r: r.value)),
        quote_relevance_reasons=tuple(sorted(quote_reason_union, key=lambda r: r.value)),
        topics=topics,
        entities=entities,
        active_relevant_member_keys=tuple(sorted(active_relevant)),
        withdrawn_relevant_member_keys=tuple(sorted(withdrawn_relevant)),
        semantic_gap_member_keys=tuple(sorted(g.news_item_key for g in group_gaps)),
        members=tuple(sorted(members, key=lambda m: (m.first_seen_at.value, m.news_item_key))),
        relation_provenance=relation_provenance,
    )

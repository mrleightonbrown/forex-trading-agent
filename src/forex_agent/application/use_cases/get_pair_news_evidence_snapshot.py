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
with no qualifying `NewsRepository.latest_evidence_eligible_vintage_
as_of` result contributes nothing -- no pair evidence, no semantic-
gap diagnostic, no window-anchor contribution. `include_backfill`
defaults to `False`, exactly like FX-56/58/59's own prospective-
evidence default.

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
INCOMPLETE_SEMANTICS` (Section 19)."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.news_canonicalization_repository import (
    NewsCanonicalizationRepository,
)
from forex_agent.application.ports.news_repository import NewsRepository
from forex_agent.application.ports.news_semantic_repository import NewsSemanticRepository
from forex_agent.application.use_cases.get_news_semantic_state_as_of import (
    GetNewsSemanticStatesAsOf,
    NewsSemanticState,
)
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.news_canonical_grouping import derive_canonical_groups
from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
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
    evidence entry -- at most ONE per canonical group (Section 8)."""

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


@dataclass(frozen=True, slots=True)
class NewsPairEvidenceSnapshot:
    """FX-60 Section 39: the top-level, on-demand answer. Never
    persisted -- see the module docstring."""

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


class GetPairNewsEvidenceSnapshot:
    """FX-60's own derived, on-demand pair-news evidence snapshot --
    see the module docstring."""

    def __init__(
        self,
        news_repository: NewsRepository,
        canonicalization_repository: NewsCanonicalizationRepository,
        semantic_repository: NewsSemanticRepository,
    ) -> None:
        self._news_repository = news_repository
        self._canonicalization_repository = canonicalization_repository
        self._get_semantic_states = GetNewsSemanticStatesAsOf(semantic_repository, news_repository)

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
        (Section 6) -- no hidden 24h/48h/72h policy exists here."""
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

        groups_outside_window = 0
        groups_without_eligible_evidence = 0
        groups_pair_irrelevant = 0
        active_entries: list[NewsPairEvidenceGroup] = []
        withdrawn_only_entries: list[NewsPairEvidenceGroup] = []
        semantic_gaps: list[NewsPairSemanticGap] = []

        for group in groups:
            # Section 10: snapshot-eligible members only.
            eligible_vintages: dict[str, NewsItemVintage] = {}
            for member_key in group.member_news_item_keys:
                vintage = await self._news_repository.latest_evidence_eligible_vintage_as_of(
                    member_key, as_of, include_backfill=include_backfill
                )
                if vintage is not None:
                    eligible_vintages[member_key] = vintage

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

            # Section 17: semantic state, only CURRENT contributes.
            eligible_keys = tuple(sorted(eligible_vintages))
            states = await self._get_semantic_states(
                eligible_keys, as_of, include_backfill=include_backfill
            )

            current_members: list[tuple[str, NewsSemanticAnnotationVintage]] = []
            group_gaps: list[NewsPairSemanticGap] = []
            for state in states:
                member_key = state.news_item_key
                vintage = eligible_vintages[member_key]
                if state.state is NewsSemanticState.CURRENT:
                    assert state.annotation is not None
                    # Section 31/53: fail loudly on basis mismatch.
                    if (
                        state.annotation.basis_news_item_revision_sequence
                        != vintage.revision_sequence
                    ):
                        raise NewsPairSnapshotConstructionError(
                            f"news_item_key={member_key!r}: CURRENT annotation basis revision "
                            f"{state.annotation.basis_news_item_revision_sequence} does not "
                            f"match the current evidence-eligible vintage revision "
                            f"{vintage.revision_sequence}"
                        )
                    current_members.append((member_key, state.annotation))
                else:
                    basis = (
                        state.annotation.basis_news_item_revision_sequence
                        if state.annotation is not None
                        else None
                    )
                    group_gaps.append(
                        NewsPairSemanticGap(
                            canonical_group_key=group.canonical_group_key,
                            news_item_key=member_key,
                            semantic_state=state.state,
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

            if not relevant:
                if not group_gaps:
                    groups_pair_irrelevant += 1
                continue

            entry = _build_group_entry(
                group.canonical_group_key,
                story_first_seen_at,
                eligible_vintages,
                eligible_first_seen,
                current_members,
                dict(relevant),
                group_gaps,
            )
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
        )


def _build_group_entry(
    canonical_group_key: str,
    story_first_seen_at: UtcTimestamp,
    eligible_vintages: dict[str, NewsItemVintage],
    eligible_first_seen: dict[str, UtcTimestamp],
    current_members: list[tuple[str, NewsSemanticAnnotationVintage]],
    relevant_by_key: dict[str, NewsPairRelevance],
    group_gaps: list[NewsPairSemanticGap],
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
    )

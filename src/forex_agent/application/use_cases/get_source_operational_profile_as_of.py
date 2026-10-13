"""FX-63 Section 8/10: `GetSourceOperationalProfileAsOf` -- a pure,
deterministic, PIT-safe read-model combining FX-63's own append-only
acquisition observations with FX-56/57's own already-durable
`NewsItem`/`NewsItemVintage` evidence, and reusing FX-62's PIT
identity/publisher resolution for descriptive display only. Never
writes anything; never computes a credibility/trust/reputation score,
a composite rank, or a PASS/FAIL judgment (`fx63_v1`'s own
`SourceOperationalProfile` structurally has no such field).

**Two genuinely different evidence bases, kept explicit, never
merged into one blanket judgment**: acquisition metrics (Section 8.1)
come ONLY from `SourceOperationalObservation` rows this story itself
records going forward. Content metrics (Section 8.2) come ONLY from
FX-56/57's own already-complete, durable evidence -- a successfully
ingested `NewsItemVintage` IS the durable record of "this was
retrieved and parsed," so no second, independently-maintained
"successful parse" observation is needed for THAT fact; `coverage` is
`OBSERVED` whenever this technical source_key has any source-native
evidence at all, `NOT_APPLICABLE` when it has none.

**FX-63H Section H2 -- acquisition coverage is truthful, never
inferred from a single earliest timestamp.** An observation existing
before a window's own `window_start` does NOT prove the window was
continuously instrumented: this codebase has no heartbeat/liveness
signal, only discrete attempt events, so "instrumentation existed
earlier" and "this window was exhaustively observed" are genuinely
different claims. `AcquisitionMetrics.coverage` is `UNAVAILABLE` when
zero attempts were recorded anywhere in the requested window, and
`PARTIAL` when at least one was -- `OBSERVED` is reserved for a
future, explicit complete-coverage contract (e.g. a dedicated
instrumentation-liveness record) and is DELIBERATELY never emitted by
this method today; building that larger monitoring subsystem is
out of scope for this correction (see ADR 0011's own FX-63H
addendum). `success_rate`/other descriptive attempt metrics and their
own denominators are unaffected by this change.

**Technical feed identity, never publisher judgment (Section 5)**:
`source_key` throughout this module is ALWAYS the technical feed
(e.g. `"BOE"`) -- acquisition failures belong to it, never to the
resolved publisher. A descriptive publisher association is resolved,
at most once per profile, via FX-62's own `ResolvePublisherForNewsItem
AsOf` against this source's own most-recently-first-seen item -- never
per acquisition attempt, and never substituted for the technical
feed's own identity when unresolved."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from forex_agent.application.ports.source_operational_observation_repository import (
    SourceOperationalObservationRepository,
)
from forex_agent.application.use_cases.resolve_publisher_for_news_item_as_of import (
    PublisherResolutionStatus,
    ResolvePublisherForNewsItemAsOf,
)
from forex_agent.application.use_cases.resolve_source_identity_as_of import (
    ResolveSourceIdentityAsOf,
    SourceIdentityResolution,
)
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_revision_fact import NewsSourceRevisionKind
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.operational_metric_coverage import OperationalMetricCoverage
from forex_agent.domain.source_acquisition_outcome import SourceAcquisitionOutcome
from forex_agent.domain.timestamps import UtcTimestamp

PROFILE_POLICY_VERSION = "fx63_v1"


class InvalidOperationalWindowError(Exception):
    """Raised when `window_start` is after `as_of` -- a structurally
    empty, nonsensical window, rejected before any repository call."""

    def __init__(self, window_start: UtcTimestamp, as_of: UtcTimestamp) -> None:
        self.window_start = window_start
        self.as_of = as_of
        super().__init__(
            f"window_start={window_start.value.isoformat()} is after "
            f"as_of={as_of.value.isoformat()} -- refusing to evaluate an empty window"
        )


class _ContentLookup(Protocol):
    """The narrow structural requirement this use case needs from a
    `NewsRepository`-shaped collaborator -- satisfied directly by
    `SqlAlchemyNewsRepository`, mirroring FX-60H's own `_VintageLookup`
    precedent exactly (narrow local Protocol, never a widening of the
    global `application.ports.news_repository.NewsRepository`)."""

    async def list_item_keys_for_source(self, source_key: str) -> tuple[str, ...]: ...

    async def list_vintages_for_items(
        self, news_item_keys: tuple[str, ...]
    ) -> dict[str, tuple[NewsItemVintage, ...]]: ...


@dataclass(frozen=True, slots=True)
class AcquisitionMetrics:
    """Section 8.1 -- an FTA acquisition metric, never a publisher
    availability score (see the module docstring)."""

    coverage: OperationalMetricCoverage
    """`UNAVAILABLE` when zero attempts were recorded in this window;
    `PARTIAL` when at least one was -- `OBSERVED` is never emitted for
    acquisition metrics today (FX-63H Section H2; see `Operational
    MetricCoverage.OBSERVED`'s own docstring)."""
    recorded_runs: int
    """The count of DISTINCT `run_id`s represented in this window --
    never requiring a run's own first attempt to itself fall inside
    the window (FX-63H Section H3)."""
    recorded_attempts: int
    successful_attempts: int
    failed_attempts: int
    retry_attempts: int
    """Count of in-window observations with `attempt_number > 1` --
    each one IS a retry by definition, even when its own preceding
    attempt(s) fall outside this window (FX-63H Section H3); never
    reconstructed from an in-window run's own attempt COUNT, which
    would undercount a run whose first attempt was observed earlier."""
    outcome_breakdown: dict[SourceAcquisitionOutcome, int]
    http_status_breakdown: dict[int, int]
    success_rate: Decimal | None
    """`successful_attempts / recorded_attempts`, or `None` when
    `recorded_attempts == 0` -- NEVER reported as `0` in that case
    (Section 8.1's own explicit "no recorded attempts -> explicit
    no-data state, not 0%" rule)."""


@dataclass(frozen=True, slots=True)
class ContentMetrics:
    """Section 8.2/8.3 -- derived purely from FX-56/57's own already-
    durable evidence (see the module docstring)."""

    coverage: OperationalMetricCoverage
    items_first_observed_in_window: int
    revisions_observed_in_window: int
    withdrawals_observed_in_window: int
    corrections_observed_in_window: int
    unclassified_changes_in_window: int
    distinct_items_known_as_of: int
    first_fta_observation: UtcTimestamp | None
    last_fta_observation: UtcTimestamp | None


@dataclass(frozen=True, slots=True)
class LatencySample:
    """Section 9 -- descriptive only; never a universal publisher-
    latency SLA. `population_size` is items in-window with a USABLE
    provider-asserted publication timestamp; `excluded_missing_
    timestamp`/`excluded_backfill` account for every in-window item
    NOT in that population, so the denominator is always explicit."""

    coverage: OperationalMetricCoverage
    population_size: int
    excluded_missing_timestamp: int
    excluded_backfill: int
    mean_seconds: Decimal | None
    min_seconds: Decimal | None
    max_seconds: Decimal | None
    anomalous_negative_count: int
    """Items where `availability` is BEFORE the provider's own claimed
    publish time -- preserved as an anomaly, never silently clamped
    or discarded (Section 9's own explicit rule)."""


@dataclass(frozen=True, slots=True)
class SourceOperationalProfile:
    source_key: str
    window_start: UtcTimestamp
    as_of: UtcTimestamp
    policy_version: str
    feed_display_name: str | None
    publisher_source_key: str | None
    publisher_display_name: str | None
    publisher_resolution_status: PublisherResolutionStatus | None
    """`None` only when this source has no source-native items at all
    to resolve a publisher against (Section 5 -- never substituted for
    the technical feed's own identity)."""
    acquisition: AcquisitionMetrics
    content: ContentMetrics
    latency: LatencySample


class GetSourceOperationalProfileAsOf:
    def __init__(
        self,
        observation_repository: SourceOperationalObservationRepository,
        content_repository: _ContentLookup,
        resolve_identity: ResolveSourceIdentityAsOf,
        resolve_publisher: ResolvePublisherForNewsItemAsOf,
    ) -> None:
        self._observation_repository = observation_repository
        self._content_repository = content_repository
        self._resolve_identity = resolve_identity
        self._resolve_publisher = resolve_publisher

    async def __call__(
        self, source_key: str, window_start: UtcTimestamp, as_of: UtcTimestamp
    ) -> SourceOperationalProfile:
        if window_start.value > as_of.value:
            raise InvalidOperationalWindowError(window_start, as_of)

        acquisition = await self._build_acquisition_metrics(source_key, window_start, as_of)
        item_keys = await self._content_repository.list_item_keys_for_source(source_key)
        vintages_by_item = await self._content_repository.list_vintages_for_items(item_keys)
        content = _build_content_metrics(vintages_by_item, window_start, as_of)
        latency = _build_latency_sample(vintages_by_item, window_start, as_of)

        feed_display_name = None
        identity_resolution = await self._resolve_identity(source_key, as_of)
        if identity_resolution.resolution is SourceIdentityResolution.KNOWN:
            assert identity_resolution.identity_vintage is not None
            feed_display_name = identity_resolution.identity_vintage.display_name

        publisher_source_key: str | None = None
        publisher_display_name: str | None = None
        publisher_status: PublisherResolutionStatus | None = None
        representative_item_key = _most_recently_first_seen_item(vintages_by_item, as_of)
        if representative_item_key is not None:
            publisher_resolution = await self._resolve_publisher(representative_item_key, as_of)
            publisher_status = publisher_resolution.status
            if publisher_resolution.status is PublisherResolutionStatus.CONFIRMED:
                assert publisher_resolution.publisher is not None
                publisher_source_key = publisher_resolution.publisher.source_key
                if publisher_resolution.publisher_identity_vintage is not None:
                    publisher_display_name = (
                        publisher_resolution.publisher_identity_vintage.display_name
                    )

        return SourceOperationalProfile(
            source_key=source_key,
            window_start=window_start,
            as_of=as_of,
            policy_version=PROFILE_POLICY_VERSION,
            feed_display_name=feed_display_name,
            publisher_source_key=publisher_source_key,
            publisher_display_name=publisher_display_name,
            publisher_resolution_status=publisher_status,
            acquisition=acquisition,
            content=content,
            latency=latency,
        )

    async def _build_acquisition_metrics(
        self, source_key: str, window_start: UtcTimestamp, as_of: UtcTimestamp
    ) -> AcquisitionMetrics:
        """FX-63H Section H2: coverage is truthful, never inferred from
        an earliest-ever-recorded timestamp alone (an observation
        existing before `window_start` does NOT prove the window was
        continuously instrumented -- this codebase has no heartbeat/
        liveness signal, only discrete attempt events). `PARTIAL` when
        at least one attempt was recorded IN this window; `UNAVAILABLE`
        when none was. `OBSERVED` is reserved for a future complete-
        coverage contract (e.g. an explicit instrumentation-liveness
        record) and is never emitted by this method today -- see the
        module docstring and ADR 0011's own FX-63H addendum."""
        observations = await self._observation_repository.list_observations_for_source_as_of(
            source_key, window_start, as_of
        )
        if not observations:
            return AcquisitionMetrics(
                coverage=OperationalMetricCoverage.UNAVAILABLE,
                recorded_runs=0,
                recorded_attempts=0,
                successful_attempts=0,
                failed_attempts=0,
                retry_attempts=0,
                outcome_breakdown={},
                http_status_breakdown={},
                success_rate=None,
            )

        recorded_attempts = len(observations)
        successful_attempts = sum(
            1 for o in observations if o.outcome is SourceAcquisitionOutcome.SUCCESS
        )
        failed_attempts = recorded_attempts - successful_attempts

        # FX-63H Section H3: `recorded_runs` is the count of distinct
        # run identifiers REPRESENTED in this window (never requiring
        # a run's own first attempt to itself be in-window). A retry
        # is identified directly from `attempt_number > 1` -- an
        # observation's own recorded attempt number already proves it
        # is a retry, even when its preceding attempt(s) fall outside
        # this window; no extra query reconstructs runs that began
        # earlier.
        recorded_runs = len({observation.run_id for observation in observations})
        retry_attempts = sum(1 for observation in observations if observation.attempt_number > 1)

        outcome_breakdown: dict[SourceAcquisitionOutcome, int] = {}
        http_status_breakdown: dict[int, int] = {}
        for observation in observations:
            outcome_breakdown[observation.outcome] = (
                outcome_breakdown.get(observation.outcome, 0) + 1
            )
            if observation.http_status is not None:
                http_status_breakdown[observation.http_status] = (
                    http_status_breakdown.get(observation.http_status, 0) + 1
                )

        success_rate = (
            Decimal(successful_attempts) / Decimal(recorded_attempts)
            if recorded_attempts > 0
            else None
        )

        return AcquisitionMetrics(
            coverage=OperationalMetricCoverage.PARTIAL,
            recorded_runs=recorded_runs,
            recorded_attempts=recorded_attempts,
            successful_attempts=successful_attempts,
            failed_attempts=failed_attempts,
            retry_attempts=retry_attempts,
            outcome_breakdown=outcome_breakdown,
            http_status_breakdown=http_status_breakdown,
            success_rate=success_rate,
        )


def _eligible_vintages_as_of(
    vintages: tuple[NewsItemVintage, ...], as_of: UtcTimestamp
) -> tuple[NewsItemVintage, ...]:
    return tuple(v for v in vintages if v.availability.value <= as_of.value)


def _most_recently_first_seen_item(
    vintages_by_item: dict[str, tuple[NewsItemVintage, ...]], as_of: UtcTimestamp
) -> str | None:
    """Section 5's own "at most one, descriptive, representative
    publisher resolution per profile" -- picks the item whose own
    revision-0 vintage is both known as of `as_of` and the LATEST such
    first-seen instant, so the profile's descriptive publisher reflects
    this source's own most RECENT known provenance, never an
    arbitrary or oldest one."""
    best_key: str | None = None
    best_availability: UtcTimestamp | None = None
    for item_key, vintages in vintages_by_item.items():
        first = next((v for v in vintages if v.revision_sequence == 0), None)
        if first is None or first.availability.value > as_of.value:
            continue
        if best_availability is None or first.availability.value > best_availability.value:
            best_availability = first.availability
            best_key = item_key
    return best_key


def _build_content_metrics(
    vintages_by_item: dict[str, tuple[NewsItemVintage, ...]],
    window_start: UtcTimestamp,
    as_of: UtcTimestamp,
) -> ContentMetrics:
    if not vintages_by_item:
        return ContentMetrics(
            coverage=OperationalMetricCoverage.NOT_APPLICABLE,
            items_first_observed_in_window=0,
            revisions_observed_in_window=0,
            withdrawals_observed_in_window=0,
            corrections_observed_in_window=0,
            unclassified_changes_in_window=0,
            distinct_items_known_as_of=0,
            first_fta_observation=None,
            last_fta_observation=None,
        )

    items_first_observed = 0
    revisions_observed = 0
    withdrawals_observed = 0
    corrections_observed = 0
    unclassified_observed = 0
    distinct_items_known = 0
    all_availabilities: list[UtcTimestamp] = []

    for vintages in vintages_by_item.values():
        eligible = _eligible_vintages_as_of(vintages, as_of)
        if eligible:
            distinct_items_known += 1
        all_availabilities.extend(v.availability for v in eligible)

        in_window = tuple(v for v in eligible if window_start.value <= v.availability.value)
        for vintage in in_window:
            is_withdrawal = vintage.source_status is NewsSourceStatus.WITHDRAWN or any(
                fact.kind is NewsSourceRevisionKind.WITHDRAWAL
                for fact in vintage.source_revision_metadata
            )
            is_correction = any(
                fact.kind is NewsSourceRevisionKind.CORRECTION
                for fact in vintage.source_revision_metadata
            )
            if vintage.revision_sequence == 0:
                items_first_observed += 1
                if is_withdrawal:
                    withdrawals_observed += 1
                continue
            revisions_observed += 1
            if is_withdrawal:
                withdrawals_observed += 1
            elif is_correction:
                corrections_observed += 1
            else:
                unclassified_observed += 1

    first_fta_observation = min(
        (ts for ts in all_availabilities), key=lambda ts: ts.value, default=None
    )
    last_fta_observation = max(
        (ts for ts in all_availabilities), key=lambda ts: ts.value, default=None
    )

    return ContentMetrics(
        coverage=OperationalMetricCoverage.OBSERVED,
        items_first_observed_in_window=items_first_observed,
        revisions_observed_in_window=revisions_observed,
        withdrawals_observed_in_window=withdrawals_observed,
        corrections_observed_in_window=corrections_observed,
        unclassified_changes_in_window=unclassified_observed,
        distinct_items_known_as_of=distinct_items_known,
        first_fta_observation=first_fta_observation,
        last_fta_observation=last_fta_observation,
    )


def _build_latency_sample(
    vintages_by_item: dict[str, tuple[NewsItemVintage, ...]],
    window_start: UtcTimestamp,
    as_of: UtcTimestamp,
) -> LatencySample:
    if not vintages_by_item:
        return LatencySample(
            coverage=OperationalMetricCoverage.NOT_APPLICABLE,
            population_size=0,
            excluded_missing_timestamp=0,
            excluded_backfill=0,
            mean_seconds=None,
            min_seconds=None,
            max_seconds=None,
            anomalous_negative_count=0,
        )

    deltas: list[Decimal] = []
    excluded_missing = 0
    excluded_backfill = 0
    anomalous_negative = 0

    for vintages in vintages_by_item.values():
        eligible = _eligible_vintages_as_of(vintages, as_of)
        in_window = tuple(v for v in eligible if window_start.value <= v.availability.value)
        for vintage in in_window:
            if vintage.observation_mode is NewsObservationMode.BACKFILL:
                excluded_backfill += 1
                continue
            if vintage.source_published_at is None:
                excluded_missing += 1
                continue
            delta = Decimal(
                (vintage.availability.value - vintage.source_published_at.value).total_seconds()
            )
            if delta < 0:
                anomalous_negative += 1
            deltas.append(delta)

    if not deltas:
        return LatencySample(
            coverage=OperationalMetricCoverage.UNAVAILABLE,
            population_size=0,
            excluded_missing_timestamp=excluded_missing,
            excluded_backfill=excluded_backfill,
            mean_seconds=None,
            min_seconds=None,
            max_seconds=None,
            anomalous_negative_count=0,
        )

    return LatencySample(
        coverage=OperationalMetricCoverage.OBSERVED,
        population_size=len(deltas),
        excluded_missing_timestamp=excluded_missing,
        excluded_backfill=excluded_backfill,
        mean_seconds=sum(deltas, Decimal(0)) / Decimal(len(deltas)),
        min_seconds=min(deltas),
        max_seconds=max(deltas),
        anomalous_negative_count=anomalous_negative,
    )

"""FX-63 Section 13.B/C/D/E: tests for `GetSourceOperationalProfileAsOf`
-- acquisition metrics, content metrics, PIT semantics, and coverage
truthfulness. The architect's own stated review priorities (provenance,
truthful coverage, correct attribution, historical immutability) are
each covered by at least one dedicated test here."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.use_cases.get_source_operational_profile_as_of import (
    GetSourceOperationalProfileAsOf,
    InvalidOperationalWindowError,
)
from forex_agent.application.use_cases.record_source_attribution import RecordSourceAttribution
from forex_agent.application.use_cases.record_source_identity_vintage import (
    RecordSourceIdentityVintage,
)
from forex_agent.application.use_cases.record_source_operational_observation import (
    RecordSourceOperationalObservation,
)
from forex_agent.application.use_cases.resolve_publisher_for_news_item_as_of import (
    PublisherResolutionStatus,
    ResolvePublisherForNewsItemAsOf,
)
from forex_agent.application.use_cases.resolve_source_identity_as_of import (
    ResolveSourceIdentityAsOf,
)
from forex_agent.domain.intelligence_source_kind import IntelligenceSourceKind
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_revision_fact import (
    NewsSourceRevisionFact,
    NewsSourceRevisionKind,
)
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.operational_metric_coverage import OperationalMetricCoverage
from forex_agent.domain.source_acquisition_outcome import SourceAcquisitionOutcome
from forex_agent.domain.source_attribution_role import SourceAttributionRole
from forex_agent.domain.source_attribution_status import SourceAttributionStatus
from forex_agent.domain.source_evidence_kind import SourceEvidenceKind
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.news_content_lookup import FakeNewsContentLookup
from tests.fakes.source_operational_observation_repository import (
    FakeSourceOperationalObservationRepository,
)
from tests.fakes.source_registry_repository import FakeSourceRegistryRepository


def _ts(hour: int, minute: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, minute, tzinfo=UTC))


def _evidence(description: str = "test") -> SourceProvenanceEvidence:
    return SourceProvenanceEvidence(
        evidence_kind=SourceEvidenceKind.ADAPTER_CONFIGURATION, description=description
    )


class _Harness:
    def __init__(self) -> None:
        self.observation_repo = FakeSourceOperationalObservationRepository()
        self.content_repo = FakeNewsContentLookup()
        self.registry_repo = FakeSourceRegistryRepository()
        self.record_observation = RecordSourceOperationalObservation(self.observation_repo)
        self.record_identity = RecordSourceIdentityVintage(self.registry_repo)
        self.record_attribution = RecordSourceAttribution(self.registry_repo)
        self.get_profile = GetSourceOperationalProfileAsOf(
            self.observation_repo,
            self.content_repo,
            ResolveSourceIdentityAsOf(self.registry_repo),
            ResolvePublisherForNewsItemAsOf(self.registry_repo),
        )

    async def record_attempt(
        self,
        source_key: str,
        channel: str,
        run_id: str,
        attempt_number: int,
        outcome: SourceAcquisitionOutcome,
        availability: UtcTimestamp,
        http_status: int | None = 200,
    ) -> None:
        await self.record_observation(
            source_key=source_key,
            source_channel=channel,
            run_id=run_id,
            attempt_number=attempt_number,
            outcome=outcome,
            availability=availability,
            http_status=http_status,
        )

    def add_item_vintage(self, source_key: str, vintage: NewsItemVintage) -> None:
        self.content_repo.add_vintage(source_key, vintage)


def _vintage(
    news_item_key: str,
    revision_sequence: int,
    availability: UtcTimestamp,
    *,
    headline: str = "H",
    source_status: NewsSourceStatus = NewsSourceStatus.ACTIVE,
    source_revision_metadata: tuple[NewsSourceRevisionFact, ...] = (),
    observation_mode: NewsObservationMode = NewsObservationMode.PROSPECTIVE,
    source_published_at: UtcTimestamp | None = None,
) -> NewsItemVintage:
    return NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=revision_sequence,
        availability=availability,
        observation_mode=observation_mode,
        headline=headline,
        source_channel="press_monetary",
        observed_source_channels=("press_monetary",),
        source_status=source_status,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        source_revision_metadata=source_revision_metadata,
        source_published_at=source_published_at,
    )


# --- B. Acquisition metrics --------------------------------------------------


@pytest.mark.asyncio
async def test_all_success_window() -> None:
    h = _Harness()
    await h.record_attempt(
        "FED", "press_monetary", "run-1", 1, SourceAcquisitionOutcome.SUCCESS, _ts(9)
    )
    await h.record_attempt(
        "FED", "press_monetary", "run-2", 1, SourceAcquisitionOutcome.SUCCESS, _ts(10)
    )

    profile = await h.get_profile("FED", _ts(9), _ts(12))

    assert profile.acquisition.coverage is OperationalMetricCoverage.OBSERVED
    assert profile.acquisition.recorded_attempts == 2
    assert profile.acquisition.successful_attempts == 2
    assert profile.acquisition.failed_attempts == 0
    assert profile.acquisition.success_rate == 1


@pytest.mark.asyncio
async def test_mixed_success_failure_window() -> None:
    h = _Harness()
    await h.record_attempt(
        "FED", "press_monetary", "run-1", 1, SourceAcquisitionOutcome.HTTP_FAILURE, _ts(9), 503
    )
    await h.record_attempt(
        "FED", "press_monetary", "run-2", 1, SourceAcquisitionOutcome.SUCCESS, _ts(10)
    )

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.acquisition.recorded_attempts == 2
    assert profile.acquisition.successful_attempts == 1
    assert profile.acquisition.failed_attempts == 1
    assert profile.acquisition.success_rate == 0.5


@pytest.mark.asyncio
async def test_multiple_retries_in_one_logical_run() -> None:
    h = _Harness()
    await h.record_attempt(
        "FED", "press_monetary", "run-1", 1, SourceAcquisitionOutcome.HTTP_FAILURE, _ts(9), 503
    )
    await h.record_attempt(
        "FED", "press_monetary", "run-1", 2, SourceAcquisitionOutcome.HTTP_FAILURE, _ts(9), 503
    )
    await h.record_attempt(
        "FED", "press_monetary", "run-1", 3, SourceAcquisitionOutcome.SUCCESS, _ts(9)
    )

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.acquisition.recorded_runs == 1
    assert profile.acquisition.recorded_attempts == 3
    assert profile.acquisition.retry_attempts == 2


@pytest.mark.asyncio
async def test_same_outcome_distinct_attempt_identifiers_both_counted() -> None:
    h = _Harness()
    await h.record_attempt(
        "FED", "press_monetary", "run-1", 1, SourceAcquisitionOutcome.SUCCESS, _ts(9)
    )
    await h.record_attempt(
        "FED", "press_monetary", "run-2", 1, SourceAcquisitionOutcome.SUCCESS, _ts(10)
    )

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.acquisition.recorded_attempts == 2
    assert profile.acquisition.recorded_runs == 2


@pytest.mark.asyncio
async def test_duplicate_event_delivery_is_idempotent_at_the_profile_level() -> None:
    h = _Harness()
    for _ in range(3):
        await h.record_attempt(
            "FED", "press_monetary", "run-1", 1, SourceAcquisitionOutcome.SUCCESS, _ts(9)
        )

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.acquisition.recorded_attempts == 1


@pytest.mark.asyncio
async def test_zero_recorded_attempts_yields_unavailable_not_zero_percent() -> None:
    h = _Harness()
    h.add_item_vintage("FED", _vintage("ITEM-1", 0, _ts(9)))  # content exists, no acquisition data

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.acquisition.coverage is OperationalMetricCoverage.UNAVAILABLE
    assert profile.acquisition.success_rate is None
    assert profile.acquisition.recorded_attempts == 0


@pytest.mark.asyncio
async def test_outcome_breakdown_totals_reconcile() -> None:
    h = _Harness()
    await h.record_attempt(
        "FED", "press_monetary", "run-1", 1, SourceAcquisitionOutcome.HTTP_FAILURE, _ts(9), 503
    )
    await h.record_attempt(
        "FED", "press_monetary", "run-1", 2, SourceAcquisitionOutcome.TIMEOUT, _ts(9), None
    )
    await h.record_attempt(
        "FED", "press_monetary", "run-1", 3, SourceAcquisitionOutcome.SUCCESS, _ts(9)
    )

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert (
        sum(profile.acquisition.outcome_breakdown.values()) == profile.acquisition.recorded_attempts
    )


# --- C. Content metrics ------------------------------------------------------


@pytest.mark.asyncio
async def test_source_native_items_counted_once() -> None:
    h = _Harness()
    h.add_item_vintage("FED", _vintage("ITEM-1", 0, _ts(9)))
    h.add_item_vintage("FED", _vintage("ITEM-2", 0, _ts(10)))

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.content.items_first_observed_in_window == 2
    assert profile.content.distinct_items_known_as_of == 2


@pytest.mark.asyncio
async def test_revisions_counted_from_actual_vintages() -> None:
    h = _Harness()
    h.add_item_vintage("FED", _vintage("ITEM-1", 0, _ts(9)))
    h.add_item_vintage("FED", _vintage("ITEM-1", 1, _ts(10), headline="Updated"))

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.content.items_first_observed_in_window == 1
    assert profile.content.revisions_observed_in_window == 1
    assert profile.content.distinct_items_known_as_of == 1


@pytest.mark.asyncio
async def test_withdrawal_identified_from_source_native_status() -> None:
    h = _Harness()
    h.add_item_vintage("FED", _vintage("ITEM-1", 0, _ts(9)))
    h.add_item_vintage(
        "FED", _vintage("ITEM-1", 1, _ts(10), source_status=NewsSourceStatus.WITHDRAWN)
    )

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.content.withdrawals_observed_in_window == 1
    assert profile.content.corrections_observed_in_window == 0


@pytest.mark.asyncio
async def test_ordinary_revision_not_classified_as_correction() -> None:
    h = _Harness()
    h.add_item_vintage("FED", _vintage("ITEM-1", 0, _ts(9)))
    h.add_item_vintage("FED", _vintage("ITEM-1", 1, _ts(10), headline="Minor edit"))

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.content.corrections_observed_in_window == 0
    assert profile.content.withdrawals_observed_in_window == 0
    assert profile.content.unclassified_changes_in_window == 1


@pytest.mark.asyncio
async def test_explicit_correction_metadata_is_classified_as_correction() -> None:
    h = _Harness()
    h.add_item_vintage("FED", _vintage("ITEM-1", 0, _ts(9)))
    h.add_item_vintage(
        "FED",
        _vintage(
            "ITEM-1",
            1,
            _ts(10),
            source_revision_metadata=(
                NewsSourceRevisionFact(kind=NewsSourceRevisionKind.CORRECTION),
            ),
        ),
    )

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.content.corrections_observed_in_window == 1
    assert profile.content.unclassified_changes_in_window == 0


@pytest.mark.asyncio
async def test_backfilled_item_counted_by_fta_availability_not_publisher_time() -> None:
    h = _Harness()
    published_at = UtcTimestamp(datetime(2020, 1, 1, tzinfo=UTC))
    h.add_item_vintage(
        "FED",
        _vintage(
            "ITEM-1",
            0,
            _ts(9),
            observation_mode=NewsObservationMode.BACKFILL,
            source_published_at=published_at,
        ),
    )

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    # Counted in-window by its OWN availability (_ts(9)), never by the
    # provider's own ancient published_at.
    assert profile.content.items_first_observed_in_window == 1


@pytest.mark.asyncio
async def test_no_article_inferred_from_absent_data() -> None:
    h = _Harness()

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.content.coverage is OperationalMetricCoverage.NOT_APPLICABLE
    assert profile.content.items_first_observed_in_window == 0
    assert profile.content.distinct_items_known_as_of == 0


@pytest.mark.asyncio
async def test_multiple_items_for_one_feed_handled_deterministically() -> None:
    h = _Harness()
    for i in range(5):
        h.add_item_vintage("FED", _vintage(f"ITEM-{i}", 0, _ts(9)))

    first = await h.get_profile("FED", _ts(0), _ts(12))
    second = await h.get_profile("FED", _ts(0), _ts(12))

    assert first.content == second.content


# --- D. PIT tests -------------------------------------------------------------


@pytest.mark.asyncio
async def test_observation_exactly_at_t_is_included() -> None:
    h = _Harness()
    await h.record_attempt(
        "FED", "press_monetary", "run-1", 1, SourceAcquisitionOutcome.SUCCESS, _ts(9)
    )

    profile = await h.get_profile("FED", _ts(0), _ts(9))

    assert profile.acquisition.recorded_attempts == 1


@pytest.mark.asyncio
async def test_observation_after_t_is_excluded() -> None:
    h = _Harness()
    await h.record_attempt(
        "FED", "press_monetary", "run-1", 1, SourceAcquisitionOutcome.SUCCESS, _ts(10)
    )

    profile = await h.get_profile("FED", _ts(0), _ts(9))

    assert profile.acquisition.recorded_attempts == 0
    # Instrumentation itself only started at _ts(10), AFTER this
    # profile's own as_of -- honestly UNAVAILABLE, not a true zero.
    assert profile.acquisition.coverage is OperationalMetricCoverage.UNAVAILABLE


@pytest.mark.asyncio
async def test_future_retries_do_not_change_historical_attempt_counts() -> None:
    h = _Harness()
    await h.record_attempt(
        "FED", "press_monetary", "run-1", 1, SourceAcquisitionOutcome.SUCCESS, _ts(9)
    )

    before_future = await h.get_profile("FED", _ts(0), _ts(9, 30))
    await h.record_attempt(
        "FED", "press_monetary", "run-2", 1, SourceAcquisitionOutcome.HTTP_FAILURE, _ts(11), 503
    )
    after_future_recorded = await h.get_profile("FED", _ts(0), _ts(9, 30))

    assert before_future.acquisition.recorded_attempts == 1
    assert after_future_recorded.acquisition.recorded_attempts == 1
    assert before_future == after_future_recorded


@pytest.mark.asyncio
async def test_future_item_revisions_do_not_change_earlier_content_counts() -> None:
    h = _Harness()
    h.add_item_vintage("FED", _vintage("ITEM-1", 0, _ts(9)))

    before = await h.get_profile("FED", _ts(0), _ts(9, 30))
    h.add_item_vintage("FED", _vintage("ITEM-1", 1, _ts(11), headline="Later edit"))
    after = await h.get_profile("FED", _ts(0), _ts(9, 30))

    assert before.content == after.content


@pytest.mark.asyncio
async def test_later_source_identity_changes_do_not_alter_earlier_profile_metadata() -> None:
    h = _Harness()
    await h.record_identity(
        source_key="FED",
        source_kind=IntelligenceSourceKind.TECHNICAL_FEED,
        registered_at=_ts(9),
        availability=_ts(9),
        algorithm_version="fx62_v1",
        display_name="Federal Reserve (feed)",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=_evidence(),
    )

    before = await h.get_profile("FED", _ts(0), _ts(9, 30))
    await h.record_identity(
        source_key="FED",
        source_kind=IntelligenceSourceKind.TECHNICAL_FEED,
        registered_at=_ts(9),
        availability=_ts(11),
        algorithm_version="fx62_v1",
        display_name="Federal Reserve (renamed feed)",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=_evidence("rename evidence"),
    )
    after = await h.get_profile("FED", _ts(0), _ts(9, 30))

    assert before.feed_display_name == "Federal Reserve (feed)"
    assert after.feed_display_name == "Federal Reserve (feed)"


@pytest.mark.asyncio
async def test_historical_publisher_mapping_correction_remains_pit_safe() -> None:
    h = _Harness()
    h.add_item_vintage("FED", _vintage("ITEM-1", 0, _ts(8)))
    for org_key, name in (("ORG_A", "Org A"), ("ORG_B", "Org B")):
        await h.record_identity(
            source_key=org_key,
            source_kind=IntelligenceSourceKind.ORGANIZATION,
            registered_at=_ts(8),
            availability=_ts(8),
            algorithm_version="fx62_v1",
            display_name=name,
            aliases=(),
            authoritative_identifier=None,
            canonical_website=None,
            evidence=_evidence(f"registering {name}"),
        )
    await h.record_attribution(
        news_item_key="ITEM-1",
        role=SourceAttributionRole.PUBLISHER,
        availability=_ts(9),
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.CONFIRMED,
        attributed_source_key="ORG_A",
        evidence_basis_revision_sequence=0,
        evidence=_evidence("T2: confirmed A"),
    )

    at_t2 = await h.get_profile("FED", _ts(0), _ts(9, 30))

    await h.record_attribution(
        news_item_key="ITEM-1",
        role=SourceAttributionRole.PUBLISHER,
        availability=_ts(10),
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.CONFIRMED,
        attributed_source_key="ORG_B",
        evidence_basis_revision_sequence=0,
        evidence=_evidence("T3: correction, actually B"),
        corrects_revision_sequence=0,
    )

    at_t2_again = await h.get_profile("FED", _ts(0), _ts(9, 30))
    at_t3 = await h.get_profile("FED", _ts(0), _ts(10, 30))

    assert at_t2.publisher_source_key == "ORG_A"
    assert at_t2_again.publisher_source_key == "ORG_A"
    assert at_t3.publisher_source_key == "ORG_B"


@pytest.mark.asyncio
async def test_rerun_earlier_profile_after_adding_future_events_is_deterministic() -> None:
    h = _Harness()
    await h.record_attempt(
        "FED", "press_monetary", "run-1", 1, SourceAcquisitionOutcome.SUCCESS, _ts(9)
    )
    h.add_item_vintage("FED", _vintage("ITEM-1", 0, _ts(9)))

    first = await h.get_profile("FED", _ts(0), _ts(9, 30))
    await h.record_attempt(
        "FED", "press_monetary", "run-2", 1, SourceAcquisitionOutcome.HTTP_FAILURE, _ts(20), 500
    )
    h.add_item_vintage("FED", _vintage("ITEM-2", 0, _ts(20)))
    second = await h.get_profile("FED", _ts(0), _ts(9, 30))

    assert first == second


@pytest.mark.asyncio
async def test_window_start_after_as_of_is_rejected() -> None:
    h = _Harness()
    with pytest.raises(InvalidOperationalWindowError):
        await h.get_profile("FED", _ts(10), _ts(9))


def test_naive_timestamp_is_rejected_by_utc_timestamp_itself() -> None:
    with pytest.raises(ValueError, match="naive"):
        UtcTimestamp(datetime(2026, 1, 1, 9))  # noqa: DTZ001


# --- E. Coverage tests --------------------------------------------------------


@pytest.mark.asyncio
async def test_fully_observed_bounded_window() -> None:
    h = _Harness()
    await h.record_attempt(
        "FED", "press_monetary", "run-1", 1, SourceAcquisitionOutcome.SUCCESS, _ts(1)
    )

    profile = await h.get_profile("FED", _ts(1), _ts(12))

    assert profile.acquisition.coverage is OperationalMetricCoverage.OBSERVED


@pytest.mark.asyncio
async def test_partial_instrumentation_coverage() -> None:
    h = _Harness()
    # Instrumentation only started at _ts(5), AFTER this profile's own
    # window_start (_ts(0)) -- the window is only PARTIALLY covered.
    await h.record_attempt(
        "FED", "press_monetary", "run-1", 1, SourceAcquisitionOutcome.SUCCESS, _ts(5)
    )

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.acquisition.coverage is OperationalMetricCoverage.PARTIAL


@pytest.mark.asyncio
async def test_no_instrumentation_before_instrumentation_start() -> None:
    h = _Harness()

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.acquisition.coverage is OperationalMetricCoverage.UNAVAILABLE
    assert profile.acquisition.recorded_attempts == 0


@pytest.mark.asyncio
async def test_missing_provider_timestamps_excluded_with_explicit_denominator() -> None:
    h = _Harness()
    h.add_item_vintage("FED", _vintage("ITEM-1", 0, _ts(9), source_published_at=None))

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.latency.population_size == 0
    assert profile.latency.excluded_missing_timestamp == 1
    assert profile.latency.coverage is OperationalMetricCoverage.UNAVAILABLE


@pytest.mark.asyncio
async def test_backfill_latency_excluded_separately() -> None:
    h = _Harness()
    h.add_item_vintage(
        "FED",
        _vintage(
            "ITEM-1",
            0,
            _ts(9),
            observation_mode=NewsObservationMode.BACKFILL,
            source_published_at=UtcTimestamp(datetime(2020, 1, 1, tzinfo=UTC)),
        ),
    )

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.latency.excluded_backfill == 1
    assert profile.latency.population_size == 0


@pytest.mark.asyncio
async def test_usable_latency_sample_reports_population_and_stats() -> None:
    h = _Harness()
    h.add_item_vintage("FED", _vintage("ITEM-1", 0, _ts(9), source_published_at=_ts(8, 30)))

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.latency.coverage is OperationalMetricCoverage.OBSERVED
    assert profile.latency.population_size == 1
    assert profile.latency.mean_seconds == 1800
    assert profile.latency.anomalous_negative_count == 0


@pytest.mark.asyncio
async def test_negative_latency_preserved_as_anomaly_not_discarded() -> None:
    h = _Harness()
    # Provider claims a publish time AFTER FTA's own observation --
    # an anomaly, preserved, never silently dropped or clamped to 0.
    h.add_item_vintage("FED", _vintage("ITEM-1", 0, _ts(9), source_published_at=_ts(10)))

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.latency.population_size == 1
    assert profile.latency.anomalous_negative_count == 1


@pytest.mark.asyncio
async def test_unsupported_correction_metadata_never_fabricates_an_error_rate() -> None:
    h = _Harness()
    h.add_item_vintage("FED", _vintage("ITEM-1", 0, _ts(9)))
    h.add_item_vintage("FED", _vintage("ITEM-1", 1, _ts(10)))  # no revision metadata at all

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.content.corrections_observed_in_window == 0
    assert profile.content.unclassified_changes_in_window == 1


@pytest.mark.asyncio
async def test_never_falls_back_to_technical_feed_for_unresolved_publisher() -> None:
    h = _Harness()
    h.add_item_vintage("FED", _vintage("ITEM-1", 0, _ts(9)))
    # No attribution ever recorded for ITEM-1.

    profile = await h.get_profile("FED", _ts(0), _ts(12))

    assert profile.publisher_resolution_status is PublisherResolutionStatus.NOT_RECORDED
    assert profile.publisher_source_key is None

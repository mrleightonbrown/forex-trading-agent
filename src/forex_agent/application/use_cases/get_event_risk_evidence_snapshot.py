"""FX-54: "given this FX pair, at this exact point in time, what
economic-event TIMING evidence did the system know?" -- a deterministic,
provider-neutral evidence snapshot built entirely on FX-51/FX-51H/
FX-51H.1's existing point-in-time repository and FX-52A/FX-52AH/
FX-52AH.1's existing canonical indicator registry and occurrence model.

This is EVIDENCE, not POLICY (FX-54 Section 3): it reports which
pair-relevant events are scheduled, whether release evidence is known,
and how far away/how recently, using timezone-correct exact-vs-date-
only semantics inherited unchanged from FX-51H/FX-52AH.1. It NEVER
computes a risk score, an importance label, a trade veto, a blackout
window, or any directional/bullish/bearish interpretation -- those are
Decision/Risk-Engine concerns that may CONSUME this evidence later,
never something this use case decides itself.

FX-54 is explicitly TIMING-ONLY (per this story's own authorization):
it never reads consensus, forecast, or actual numeric values, and never
computes a surprise -- FX-52 (commercial consensus/surprise ingestion)
remains DEFER and FX-53 (surprise/post-release-drift research) remains
BLOCKED; this use case does not revive either indirectly.

Coverage is deliberately partial (FX-52A's own honest gap: EUR has no
adopted source at all; BLS is implemented but currently blocked by a
live HTTP 403). An empty `upcoming_schedule_groups`/
`recent_release_groups` therefore means "no PIT-visible, pair-relevant
event among currently-tracked indicators falls in this window" -- NOT
"there is no economic-event risk." `EventCoverageEvidence` (always
present on the returned snapshot) is this use case's own answer to
"how would a caller know the difference" -- see that type's own
docstring.

Performs NO network I/O and NO live-source polling of any kind -- this
is a pure read over already-ingested canonical event data; source
collection remains the ingestion layer's job (FX-52A's adapters), never
this use case's.
"""

from datetime import timedelta

from forex_agent.application.ports.economic_event_repository import EconomicEventRepository
from forex_agent.domain.economic_indicator_registry import indicator_by_key
from forex_agent.domain.event_coverage_evidence import (
    EventCoverageEvidence,
    build_coverage_evidence,
)
from forex_agent.domain.event_release_evidence import build_release_evidence, group_release_evidence
from forex_agent.domain.event_risk_evidence_snapshot import EventRiskEvidenceSnapshot
from forex_agent.domain.event_schedule_evidence import (
    build_schedule_evidence,
    group_schedule_evidence,
)
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.pair_currency_role import pair_role_by_indicator_key
from forex_agent.domain.timestamps import UtcTimestamp


class GetEventRiskEvidenceSnapshot:
    """FX-54's timing-only evidence use case -- see the module
    docstring."""

    def __init__(self, repository: EconomicEventRepository) -> None:
        self._repository = repository

    async def __call__(
        self,
        instrument: Instrument,
        as_of: UtcTimestamp,
        lookahead: timedelta,
        lookback: timedelta,
    ) -> EventRiskEvidenceSnapshot:
        """`as_of` is the caller's own explicit reproducibility anchor
        (FX-54 Section 4) -- this method never calls `datetime.now()`
        or any other current-clock source itself. `lookahead`/
        `lookback` are the caller's own explicit horizons, never a
        hidden 15/30/60-minute policy default invented here. Raises
        `ValueError` if either horizon is negative."""
        if lookahead < timedelta(0):
            raise ValueError(f"lookahead must not be negative, got {lookahead}")
        if lookback < timedelta(0):
            raise ValueError(f"lookback must not be negative, got {lookback}")

        role_by_indicator_key = pair_role_by_indicator_key(instrument)

        window_end = UtcTimestamp(as_of.value + lookahead)
        window_start = UtcTimestamp(as_of.value - lookback)

        schedule_results = await self._repository.known_events_in_window(as_of, window_end, as_of)
        release_results = await self._repository.known_releases_in_window(
            window_start, as_of, as_of
        )

        schedule_evidence = []
        for occurrence, schedule in schedule_results:
            role = role_by_indicator_key.get(occurrence.indicator_key)
            if role is None:
                continue  # not pair-relevant -- neither this pair's base nor quote currency
            indicator = indicator_by_key(occurrence.indicator_key)
            assert indicator is not None  # a pair-relevant key always resolves in the registry
            schedule_evidence.append(
                build_schedule_evidence(occurrence, schedule, indicator, role, as_of)
            )

        release_evidence = []
        for occurrence, release in release_results:
            role = role_by_indicator_key.get(occurrence.indicator_key)
            if role is None:
                continue
            indicator = indicator_by_key(occurrence.indicator_key)
            assert indicator is not None
            release_evidence.append(
                build_release_evidence(occurrence, release, indicator, role, as_of)
            )

        coverage: EventCoverageEvidence = build_coverage_evidence(
            instrument.base_currency, instrument.quote_currency
        )

        return EventRiskEvidenceSnapshot(
            instrument=instrument,
            as_of=as_of,
            lookahead=lookahead,
            lookback=lookback,
            upcoming_schedule_groups=group_schedule_evidence(schedule_evidence),
            recent_release_groups=group_release_evidence(release_evidence),
            coverage=coverage,
        )

"""FX-44: applies `domain.policy_rate_release_timing_registry`'s cited
release-timing rules to the real policy-rate change points FX-43
backfilled, replacing provisional timing ONLY where the registry
actually resolves a date -- through `MacroObservationRepository.
replace_provisional_release_timing`, never a direct UPDATE.

This is the first real caller of `replace_provisional_release_timing`
(FX-43H built the mechanism; FX-43H.1 made it atomic; this story is
what actually uses it). Idempotent by construction (FX-44 section 5):
re-running this use case against vintages it already classified finds
nothing left to write for them (see `_classify_one`'s pre-check) and
reports them with `newly_applied=False`, never as an error and never
attempting to rewrite them.
"""

from dataclasses import dataclass, field
from enum import Enum

from forex_agent.application.ports.macro_observation_repository import MacroObservationRepository
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.policy_rate_release_timing_registry import (
    ReleaseTimingResolution,
    UnresolvedTiming,
    resolve_release_timing,
)
from forex_agent.domain.release_timing_rule import ReleaseTimingConfidence
from forex_agent.domain.timestamps import UtcTimestamp


class ChangePointOutcome(Enum):
    """Which of FX-44 section 6's report buckets one stored change
    point falls into, independent of whether THIS run is what put it
    there (see `ChangePointVerification.newly_applied`)."""

    EXACT = "EXACT"
    """The registry resolves this date with EXACT confidence, and the
    stored vintage matches that resolution (`released_at_is_verified`)."""

    CONSERVATIVE_SAFE = "CONSERVATIVE_SAFE"
    """The registry resolves this date with CONSERVATIVE_SAFE_BOUND
    confidence, and the stored vintage matches that resolution
    (`released_at_is_conservative_bound`)."""

    UNRESOLVED = "UNRESOLVED"
    """No registry rule covers this date (an unresolved era, or a
    known irregular/emergency action) -- the vintage remains fully
    provisional, exactly as FX-44 section 2 requires."""

    CONFLICTING = "CONFLICTING"
    """The vintage is already classified (exact or conservative), but
    with a DIFFERENT timing than the registry now resolves for this
    date -- refused; the stored vintage is left completely untouched.
    Can only arise if the registry's own rules changed between two
    runs (e.g. a citation was corrected) -- reported, never silently
    overwritten and never silently ignored."""


@dataclass(frozen=True, slots=True)
class ChangePointVerification:
    """The per-change-point detail behind one `CurrencyReleaseTimingReport`."""

    series_key: str
    observation_period: UtcTimestamp
    outcome: ChangePointOutcome
    newly_applied: bool
    reason: str
    citation: str | None = None
    """The registry rule's citation, when `outcome` is EXACT,
    CONSERVATIVE_SAFE, or CONFLICTING (a resolution was found either
    way) -- `None` only for UNRESOLVED, which has no rule to cite.
    Kept as its own field (not parsed back out of `reason`) so a
    report generator can list sources accurately regardless of whether
    THIS run or an earlier one is what applied the classification."""


@dataclass(frozen=True, slots=True)
class CurrencyReleaseTimingReport:
    """FX-44 section 6's per-currency research-safe coverage report,
    before any JSON serialization."""

    currency: str
    series_key: str
    change_points: tuple[ChangePointVerification, ...] = field(default_factory=tuple)

    def _by_outcome(self, outcome: ChangePointOutcome) -> tuple[ChangePointVerification, ...]:
        return tuple(cp for cp in self.change_points if cp.outcome is outcome)

    @property
    def total_change_points(self) -> int:
        return len(self.change_points)

    @property
    def exact_verified(self) -> tuple[ChangePointVerification, ...]:
        return self._by_outcome(ChangePointOutcome.EXACT)

    @property
    def conservative_safe(self) -> tuple[ChangePointVerification, ...]:
        return self._by_outcome(ChangePointOutcome.CONSERVATIVE_SAFE)

    @property
    def unresolved(self) -> tuple[ChangePointVerification, ...]:
        return self._by_outcome(ChangePointOutcome.UNRESOLVED)

    @property
    def conflicting(self) -> tuple[ChangePointVerification, ...]:
        return self._by_outcome(ChangePointOutcome.CONFLICTING)

    @property
    def research_safe_dates(self) -> tuple[UtcTimestamp, ...]:
        return tuple(
            cp.observation_period for cp in (*self.exact_verified, *self.conservative_safe)
        )

    @property
    def earliest_research_safe_date(self) -> UtcTimestamp | None:
        dates = self.research_safe_dates
        return min(dates, key=lambda ts: ts.value) if dates else None

    @property
    def latest_research_safe_date(self) -> UtcTimestamp | None:
        dates = self.research_safe_dates
        return max(dates, key=lambda ts: ts.value) if dates else None


@dataclass(frozen=True, slots=True)
class VerifyPolicyRateReleaseTiming:
    """Runs FX-44's registry against every stored change point of one
    currency's canonical policy-rate series, replacing provisional
    timing only where the registry resolves a date -- through
    `repository.replace_provisional_release_timing`, never a direct
    UPDATE (FX-44 section 5)."""

    repository: MacroObservationRepository

    async def __call__(self, currency: str, series_key: str) -> CurrencyReleaseTimingReport:
        vintages = await self.repository.list_all_for_series(series_key)
        # Deterministic order -- report content must not depend on
        # storage/scan order (mirrors FX-41H's point-in-time tie-break
        # discipline, applied here to report ordering instead).
        ordered = sorted(vintages, key=lambda v: (v.observation_period.value, v.revision_sequence))

        results = [await self._classify_one(currency, v) for v in ordered]
        return CurrencyReleaseTimingReport(
            currency=currency, series_key=series_key, change_points=tuple(results)
        )

    async def _classify_one(
        self, currency: str, vintage: MacroObservationVintage
    ) -> ChangePointVerification:
        resolution = resolve_release_timing(currency, vintage.observation_period)

        if isinstance(resolution, UnresolvedTiming):
            return ChangePointVerification(
                series_key=vintage.series_key,
                observation_period=vintage.observation_period,
                outcome=ChangePointOutcome.UNRESOLVED,
                newly_applied=False,
                reason=resolution.reason,
            )

        outcome = (
            ChangePointOutcome.EXACT
            if resolution.confidence is ReleaseTimingConfidence.EXACT
            else ChangePointOutcome.CONSERVATIVE_SAFE
        )

        if vintage.released_at_is_verified or vintage.released_at_is_conservative_bound:
            # Already classified by a previous run -- idempotency check
            # (FX-44 section 5). Compare against what the registry
            # resolves to NOW, without attempting any write either way.
            if _matches(vintage, resolution):
                return ChangePointVerification(
                    series_key=vintage.series_key,
                    observation_period=vintage.observation_period,
                    outcome=outcome,
                    newly_applied=False,
                    reason=(
                        f"already classified {resolution.confidence.value} with the same "
                        f"timing (released_at={vintage.released_at.value.isoformat()}) -- "
                        "rerun is a no-op"
                    ),
                    citation=resolution.citation,
                )
            return ChangePointVerification(
                series_key=vintage.series_key,
                observation_period=vintage.observation_period,
                outcome=ChangePointOutcome.CONFLICTING,
                newly_applied=False,
                reason=(
                    "already classified with a DIFFERENT timing than the registry now "
                    f"resolves (stored released_at="
                    f"{vintage.released_at.value.isoformat()}, registry now resolves "
                    f"{resolution.released_at.value.isoformat()}) -- refusing to "
                    "overwrite; left untouched"
                ),
                citation=resolution.citation,
            )

        await self.repository.replace_provisional_release_timing(
            vintage.series_key,
            vintage.observation_period,
            vintage.revision_sequence,
            resolution.released_at,
            resolution.effective_at,
            resolution.confidence,
        )
        return ChangePointVerification(
            series_key=vintage.series_key,
            observation_period=vintage.observation_period,
            outcome=outcome,
            newly_applied=True,
            reason=f"resolved {resolution.confidence.value} via {resolution.citation}",
            citation=resolution.citation,
        )


def _matches(vintage: MacroObservationVintage, resolution: ReleaseTimingResolution) -> bool:
    if resolution.confidence is ReleaseTimingConfidence.EXACT:
        if not vintage.released_at_is_verified:
            return False
    elif not vintage.released_at_is_conservative_bound:
        return False
    if vintage.released_at.value != resolution.released_at.value:
        return False
    stored_effective = None if vintage.effective_at is None else vintage.effective_at.value
    resolved_effective = None if resolution.effective_at is None else resolution.effective_at.value
    return stored_effective == resolved_effective

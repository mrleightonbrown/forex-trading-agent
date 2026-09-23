"""FX-44H: a deliberate, auditable correction path for vintages FX-44
already classified `released_at_is_verified=True` with a value later
found to be wrong -- the modern USD change points being the concrete
case (FX-44's original resolver conflated the stored effective date
with the FOMC announcement date; see `docs.DECISIONS.md`'s FX-44H
entry).

This is a SEPARATE use case from `VerifyPolicyRateReleaseTiming` on
purpose, not a mode of it: `VerifyPolicyRateReleaseTiming` treats an
already-classified row it disagrees with as `CONFLICTING` and leaves
it untouched -- exactly right for its routine, non-destructive role.
Remediation is the opposite: a human runs this DELIBERATELY, after
fixing the registry itself, specifically to correct rows the registry
now disagrees with. It goes through `MacroObservationRepository.
correct_verified_release_timing`, never a direct UPDATE, so the same
atomic, auditable guarantees apply here as everywhere else in this
codebase.

Idempotent by construction: a vintage already matching what the
registry currently resolves to is reported `ALREADY_CORRECT` and
nothing is written for it.
"""

from dataclasses import dataclass
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


class RemediationOutcome(Enum):
    CORRECTED = "CORRECTED"
    """The stored released_at/effective_at did not match what the
    registry currently resolves to -- corrected via `correct_verified_
    release_timing`."""

    ALREADY_CORRECT = "ALREADY_CORRECT"
    """The stored values already match the registry's current
    resolution -- nothing written. This is what makes a rerun
    idempotent."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    """Out of this mechanism's scope: the vintage is not currently
    `released_at_is_verified=True` (nothing to correct within the EXACT
    tier), or the registry no longer resolves this date to EXACT
    confidence at all (a confidence-TIER change is a different kind of
    conflict than a within-tier value correction, and is left to
    `VerifyPolicyRateReleaseTiming`'s CONFLICTING reporting instead)."""


@dataclass(frozen=True, slots=True)
class RemediationRecord:
    """One vintage's remediation outcome -- the auditable detail behind
    a `RemediateReleaseTiming` run."""

    series_key: str
    observation_period: UtcTimestamp
    outcome: RemediationOutcome
    previous_released_at: UtcTimestamp | None
    previous_effective_at: UtcTimestamp | None
    corrected_released_at: UtcTimestamp | None
    corrected_effective_at: UtcTimestamp | None
    reason: str


@dataclass(frozen=True, slots=True)
class RemediateReleaseTiming:
    """Compares every currently-`released_at_is_verified=True` vintage
    of one currency's series against what `domain.policy_rate_release_
    timing_registry` resolves NOW, and corrects any mismatch through
    `repository.correct_verified_release_timing`."""

    repository: MacroObservationRepository

    async def __call__(self, currency: str, series_key: str) -> tuple[RemediationRecord, ...]:
        vintages = await self.repository.list_all_for_series(series_key)
        ordered = sorted(vintages, key=lambda v: (v.observation_period.value, v.revision_sequence))
        records = [await self._remediate_one(currency, v) for v in ordered]
        return tuple(r for r in records if r is not None)

    async def _remediate_one(
        self, currency: str, vintage: MacroObservationVintage
    ) -> RemediationRecord | None:
        if not vintage.released_at_is_verified:
            return None  # out of scope -- this mechanism only ever corrects the EXACT tier

        resolution = resolve_release_timing(currency, vintage.observation_period)
        if isinstance(resolution, UnresolvedTiming):
            return RemediationRecord(
                series_key=vintage.series_key,
                observation_period=vintage.observation_period,
                outcome=RemediationOutcome.NOT_APPLICABLE,
                previous_released_at=vintage.released_at,
                previous_effective_at=vintage.effective_at,
                corrected_released_at=None,
                corrected_effective_at=None,
                reason=f"registry no longer resolves this date at all: {resolution.reason}",
            )
        if resolution.confidence is not ReleaseTimingConfidence.EXACT:
            return RemediationRecord(
                series_key=vintage.series_key,
                observation_period=vintage.observation_period,
                outcome=RemediationOutcome.NOT_APPLICABLE,
                previous_released_at=vintage.released_at,
                previous_effective_at=vintage.effective_at,
                corrected_released_at=None,
                corrected_effective_at=None,
                reason=(
                    "registry now resolves this date to "
                    f"{resolution.confidence.value}, not EXACT -- a confidence-tier "
                    "change is not a within-tier correction; not remediated here"
                ),
            )

        if _matches(vintage, resolution):
            return RemediationRecord(
                series_key=vintage.series_key,
                observation_period=vintage.observation_period,
                outcome=RemediationOutcome.ALREADY_CORRECT,
                previous_released_at=vintage.released_at,
                previous_effective_at=vintage.effective_at,
                corrected_released_at=vintage.released_at,
                corrected_effective_at=vintage.effective_at,
                reason="stored timing already matches the registry's current resolution",
            )

        await self.repository.correct_verified_release_timing(
            vintage.series_key,
            vintage.observation_period,
            vintage.revision_sequence,
            expected_current_released_at=vintage.released_at,
            expected_current_effective_at=vintage.effective_at,
            corrected_released_at=resolution.released_at,
            corrected_effective_at=resolution.effective_at,
        )
        return RemediationRecord(
            series_key=vintage.series_key,
            observation_period=vintage.observation_period,
            outcome=RemediationOutcome.CORRECTED,
            previous_released_at=vintage.released_at,
            previous_effective_at=vintage.effective_at,
            corrected_released_at=resolution.released_at,
            corrected_effective_at=resolution.effective_at,
            reason=f"corrected to match the registry via {resolution.citation}",
        )


def _matches(vintage: MacroObservationVintage, resolution: ReleaseTimingResolution) -> bool:
    if vintage.released_at.value != resolution.released_at.value:
        return False
    stored_effective = None if vintage.effective_at is None else vintage.effective_at.value
    resolved_effective = None if resolution.effective_at is None else resolution.effective_at.value
    return stored_effective == resolved_effective

"""FX-44H: deliberately, auditably corrects the USD `MacroObservation
Vintage` rows FX-44 already classified `released_at_is_verified=True`
with a value later found to be wrong -- FX-44's original resolver
conflated the stored (operational EFFECTIVE) date with the FOMC
announcement date, and set effective_at=None. See docs/DECISIONS.md's
FX-44H entry for the full finding and its verification.

This is a SEPARATE, deliberate operation from `scripts/verify_policy_
rate_release_timing.py` -- it does not run automatically as part of
routine verification. A human runs this specifically to correct rows
the (now-fixed) registry disagrees with, going through `Macro
ObservationRepository.correct_verified_release_timing` (never a
direct UPDATE) so the same atomic, auditable guarantees apply as
everywhere else in this codebase.

Idempotent: re-running finds nothing left to correct for any row
already matching the registry's current resolution.

Run:
    uv run python scripts/remediate_usd_release_timing.py

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
    - FX-44's verification already run at least once (this script only
      ever corrects rows already released_at_is_verified=True; it does
      not classify a provisional row -- run scripts/verify_policy_
      rate_release_timing.py first/again for that).

Writes:
    - `released_at`/`effective_at` on already-EXACT USD vintage rows
      whose stored values no longer match the registry, via
      `MacroObservationRepository.correct_verified_release_timing`.
    - `research_results/fx44h/usd_release_timing_remediation.json` --
      an explicit, auditable record of every row examined and what
      (if anything) changed.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.use_cases.remediate_release_timing import (
    RemediateReleaseTiming,
    RemediationRecord,
)
from forex_agent.domain.policy_rate_registry import canonical_series_for_currency
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.macro_observation_repository import (
    SqlAlchemyMacroObservationRepository,
)
from forex_agent.infrastructure.db.session import get_engine

REPORT_PATH = Path("research_results/fx44h/usd_release_timing_remediation.json")
CURRENCY = "USD"


async def main() -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    series = canonical_series_for_currency(CURRENCY)
    series_key = series.key if series is not None else ""

    async with session_factory() as session:
        repository = SqlAlchemyMacroObservationRepository(session)
        remediate = RemediateReleaseTiming(repository=repository)
        print(f"{CURRENCY} ({series_key}): remediating already-classified EXACT rows ...")
        records = await remediate(CURRENCY, series_key)

    corrected = [r for r in records if r.outcome.value == "CORRECTED"]
    already_correct = [r for r in records if r.outcome.value == "ALREADY_CORRECT"]
    not_applicable = [r for r in records if r.outcome.value == "NOT_APPLICABLE"]
    print(
        f"  {len(records)} EXACT rows examined: {len(corrected)} corrected, "
        f"{len(already_correct)} already correct, {len(not_applicable)} not applicable"
    )
    for record in corrected:
        print(
            f"    {record.observation_period.value.date()}: "
            f"{_iso_or_none(record.previous_released_at)} -> "
            f"{_iso_or_none(record.corrected_released_at)}"
        )

    _write_report(records)
    print(f"\nRemediation report written to {REPORT_PATH}")


def _write_report(records: tuple[RemediationRecord, ...]) -> None:
    payload: dict[str, Any] = {
        "story": "FX-44H",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "currency": CURRENCY,
        "records": [_record_to_dict(r) for r in records],
        "summary": {
            "examined": len(records),
            "corrected": sum(1 for r in records if r.outcome.value == "CORRECTED"),
            "already_correct": sum(1 for r in records if r.outcome.value == "ALREADY_CORRECT"),
            "not_applicable": sum(1 for r in records if r.outcome.value == "NOT_APPLICABLE"),
        },
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = REPORT_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n")
    tmp_path.replace(REPORT_PATH)  # atomic write -- matches FX-43/FX-44's report precedent


def _record_to_dict(record: RemediationRecord) -> dict[str, Any]:
    return {
        "observation_period": record.observation_period.value.isoformat(),
        "outcome": record.outcome.value,
        "previous_released_at": _iso_or_none(record.previous_released_at),
        "previous_effective_at": _iso_or_none(record.previous_effective_at),
        "corrected_released_at": _iso_or_none(record.corrected_released_at),
        "corrected_effective_at": _iso_or_none(record.corrected_effective_at),
        "reason": record.reason,
    }


def _iso_or_none(timestamp: UtcTimestamp | None) -> str | None:
    return None if timestamp is None else timestamp.value.isoformat()


if __name__ == "__main__":
    asyncio.run(main())

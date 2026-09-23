"""FX-45: reports which historical windows are CURRENTLY usable for
`ComputePolicyRateDifferential` -- for EUR/USD, GBP/USD, USD/CAD, per
rate semantics (`ANNOUNCED`/`EFFECTIVE`).

This is a coverage/availability diagnostic ONLY. It does NOT compute,
report, or imply FX returns, expectancy, correlation, statistical
significance, or trading performance of any kind -- see FX-45's own
non-goals. Its sole purpose is to tell a human, with evidence, exactly
which historical instants a differential request currently succeeds or
fails for, and why, so a future story (FX-46, not started by this one)
can decide -- from evidence, not guesswork -- which of the still-
unresolved crisis-era observations (FX-44/FX-44H/FX-44H.1's own
`*_IRREGULAR_DATES`, deliberately left untouched by this story per
FX-45 section 11) are actually worth individually researching before
historical rate-differential research begins.

For each pair, every REAL stored change point's own `released_at`
(across every currency, every confidence tier -- exact, conservative,
and provisional alike, since probing exactly where the provisional
ones block things is the point) is used as a candidate `as_of`. Each
candidate is queried once per `RateSemantics` through the same
`ComputePolicyRateDifferential` use case FX-45 exercises everywhere
else -- no bespoke coverage logic that could silently diverge from
what the real feature actually does.

Run:
    uv run python scripts/report_policy_rate_differential_coverage.py

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
    - the real policy-rate backfill/verification/remediation already run
      (see tests/integration/test_compute_policy_rate_differential.py's
      own docstring for the exact script order -- all idempotent).

Writes:
    - `research_results/fx45/policy_rate_differential_coverage.json`
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.ports.macro_observation_repository import MacroObservationRepository
from forex_agent.application.use_cases.compute_policy_rate_differential import (
    ComputePolicyRateDifferential,
)
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.policy_rate_differential import DifferentialUnavailable, RateSemantics
from forex_agent.domain.policy_rate_registry import canonical_series_for_currency
from forex_agent.domain.research_readiness import ResearchIntervalNotReadyError
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.macro_observation_repository import (
    SqlAlchemyMacroObservationRepository,
)
from forex_agent.infrastructure.db.session import get_engine

REPORT_PATH = Path("research_results/fx45/policy_rate_differential_coverage.json")

#: FX-45 section 3's own required first pairs.
PAIRS: tuple[tuple[str, str], ...] = (("EUR", "USD"), ("GBP", "USD"), ("USD", "CAD"))


async def main() -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async with session_factory() as session:
        repository = SqlAlchemyMacroObservationRepository(session)
        use_case = ComputePolicyRateDifferential(repository=repository)

        report: dict[str, Any] = {}
        for base, quote in PAIRS:
            pair_key = f"{base}/{quote}"
            print(f"{pair_key}: scanning coverage ...")
            report[pair_key] = await _scan_pair(repository, use_case, base, quote)
            for semantics_name, semantics_report in report[pair_key]["rate_semantics"].items():
                print(
                    f"  {semantics_name}: {semantics_report['usable_points']} usable, "
                    f"{semantics_report['blocked_points']} blocked, "
                    f"earliest_research_ready={semantics_report['earliest_research_ready']}"
                )

    _write_report(report)
    print(f"\nCoverage report written to {REPORT_PATH}")


async def _scan_pair(
    repository: MacroObservationRepository,
    use_case: ComputePolicyRateDifferential,
    base: str,
    quote: str,
) -> dict[str, Any]:
    base_series = canonical_series_for_currency(base)
    quote_series = canonical_series_for_currency(quote)
    base_history = await repository.list_all_for_series(base_series.key) if base_series else ()
    quote_history = await repository.list_all_for_series(quote_series.key) if quote_series else ()

    candidates = _candidate_instants(base_history, quote_history)
    instrument = Instrument(base, quote)

    semantics_report = {
        semantics.value: await _scan_semantics(use_case, instrument, candidates, semantics)
        for semantics in (RateSemantics.ANNOUNCED, RateSemantics.EFFECTIVE)
    }

    return {
        "base_currency": base,
        "quote_currency": quote,
        "earliest_available_history": _iso_or_none(
            _earliest_joint_history(base_history, quote_history)
        ),
        "candidate_instants_scanned": len(candidates),
        "rate_semantics": semantics_report,
    }


async def _scan_semantics(
    use_case: ComputePolicyRateDifferential,
    instrument: Instrument,
    candidates: list[UtcTimestamp],
    semantics: RateSemantics,
) -> dict[str, Any]:
    earliest_ready: UtcTimestamp | None = None
    usable_count = 0
    blocked: list[dict[str, Any]] = []

    for as_of in candidates:
        try:
            result = await use_case(instrument, as_of, semantics)
        except ResearchIntervalNotReadyError as exc:
            blocked.append(
                {
                    "as_of": as_of.value.isoformat(),
                    "reason": "missing_baseline" if exc.no_baseline else "provisional_timing",
                    "offending_observations": [
                        {
                            "series_key": v.series_key,
                            "observation_period": v.observation_period.value.isoformat(),
                        }
                        for v in exc.provisional_vintages
                    ],
                }
            )
            continue

        if isinstance(result, DifferentialUnavailable):
            blocked.append(
                {
                    "as_of": as_of.value.isoformat(),
                    "reason": "missing_rate_state",
                    "detail": result.reason,
                }
            )
            continue

        usable_count += 1
        if earliest_ready is None:
            earliest_ready = as_of

    return {
        "earliest_research_ready": _iso_or_none(earliest_ready),
        "usable_points": usable_count,
        "blocked_points": len(blocked),
        "blocked": blocked,
    }


def _candidate_instants(
    base_history: tuple[MacroObservationVintage, ...],
    quote_history: tuple[MacroObservationVintage, ...],
) -> list[UtcTimestamp]:
    """Every real change point's own `released_at`, across BOTH legs
    and EVERY confidence tier (exact, conservative, and provisional
    alike -- probing exactly where the provisional ones block things
    is this diagnostic's whole purpose), deduplicated and sorted."""
    seen = {v.released_at.value for v in (*base_history, *quote_history)}
    return [UtcTimestamp(value) for value in sorted(seen)]


def _earliest_joint_history(
    base_history: tuple[MacroObservationVintage, ...],
    quote_history: tuple[MacroObservationVintage, ...],
) -> UtcTimestamp | None:
    """The earliest instant BOTH legs have ANY stored history at all --
    the later of the two currencies' own earliest observation_period,
    since a pair differential structurally needs both legs to exist."""
    if not base_history or not quote_history:
        return None
    earliest_base = min(v.observation_period.value for v in base_history)
    earliest_quote = min(v.observation_period.value for v in quote_history)
    return UtcTimestamp(max(earliest_base, earliest_quote))


def _iso_or_none(timestamp: UtcTimestamp | None) -> str | None:
    return None if timestamp is None else timestamp.value.isoformat()


def _write_report(report: dict[str, Any]) -> None:
    payload: dict[str, Any] = {
        "story": "FX-45",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "method": (
            "For each pair, every real stored change point's own released_at (both legs, "
            "every confidence tier) is used as a candidate as_of and queried once per "
            "rate_semantics through ComputePolicyRateDifferential -- the same use case the "
            "real feature uses, not bespoke coverage logic. This report contains no FX "
            "returns, expectancy, correlation, significance, or trading-performance figures."
        ),
        "pairs": report,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = REPORT_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n")
    tmp_path.replace(
        REPORT_PATH
    )  # atomic write -- matches this epic's established report precedent


if __name__ == "__main__":
    asyncio.run(main())

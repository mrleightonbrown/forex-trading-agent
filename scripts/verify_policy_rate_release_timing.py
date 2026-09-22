"""FX-44: applies the cited release-timing rules in `domain.
policy_rate_release_timing_registry` to every USD/EUR/GBP/CAD
policy-rate change point FX-43 backfilled, replacing provisional
timing where -- and only where -- the registry actually resolves a
date, through `MacroObservationRepository.replace_provisional_release_
timing` (never a direct UPDATE).

JPY is deliberately not attempted -- out of scope per FX-44 itself.

Idempotent: re-running this script finds nothing left to write for any
change point it already classified (`VerifyPolicyRateReleaseTiming`'s
own pre-check) -- safe to re-run, and reported explicitly rather than
silently.

Run:
    uv run python scripts/verify_policy_rate_release_timing.py

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
    - FX-43's backfill already run (this script reads existing vintages;
      it does not fetch from any provider itself).

Writes:
    - `released_at`/`effective_at`/`released_at_is_verified`/
      `released_at_is_conservative_bound` on qualifying
      `MacroObservationVintage` rows, via `MacroObservationRepository`.
    - `research_results/fx44/policy_rate_release_verification.json` --
      the explicit, per-currency research-safe coverage report FX-44
      section 6 requires.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.use_cases.verify_policy_rate_release_timing import (
    ChangePointVerification,
    CurrencyReleaseTimingReport,
    VerifyPolicyRateReleaseTiming,
)
from forex_agent.domain.policy_rate_registry import canonical_series_for_currency
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.macro_observation_repository import (
    SqlAlchemyMacroObservationRepository,
)
from forex_agent.infrastructure.db.session import get_engine

REPORT_PATH = Path("research_results/fx44/policy_rate_release_verification.json")

#: FX-44's own scope -- JPY is explicitly excluded, per the story text
#: ("JPY remains out of scope").
CURRENCIES: tuple[str, ...] = ("USD", "EUR", "GBP", "CAD")

METHOD_SUMMARY = (
    "Per-currency, per-change-point release timing is resolved by "
    "domain.policy_rate_release_timing_registry: a hand-researched, "
    "cited set of documented central-bank release-time conventions "
    "(EXACT confidence) and, where the exact minute is not confidently "
    "citable but a same-day/business-hours convention is confirmed, a "
    "deliberately conservative end-of-day bound guaranteed no earlier "
    "than the true release (CONSERVATIVE_SAFE_BOUND confidence). "
    "Known irregular/inter-meeting/emergency-action dates, and eras "
    "whose announcement/effective-date relationship was not "
    "confidently established, are excluded from both and remain "
    "fully provisional. No timestamp in this report is inferred "
    "merely from the daily rate series' change-point date."
)


async def main() -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async with session_factory() as session:
        repository = SqlAlchemyMacroObservationRepository(session)
        use_case = VerifyPolicyRateReleaseTiming(repository=repository)

        reports: dict[str, CurrencyReleaseTimingReport] = {}
        for currency in CURRENCIES:
            series = canonical_series_for_currency(currency)
            series_key = series.key if series is not None else ""
            print(f"{currency} ({series_key}): verifying release timing ...")
            report = await use_case(currency, series_key)
            reports[currency] = report
            newly = sum(1 for cp in report.change_points if cp.newly_applied)
            print(
                f"  {report.total_change_points} change points: "
                f"{len(report.exact_verified)} exact, "
                f"{len(report.conservative_safe)} conservative-safe, "
                f"{len(report.unresolved)} unresolved, "
                f"{len(report.conflicting)} conflicting "
                f"({newly} newly classified this run)"
            )
            for cp in report.conflicting:
                print(f"  CONFLICT: {cp.observation_period.value.isoformat()} -- {cp.reason}")

    _write_report(reports)
    print(f"\nRelease-timing verification report written to {REPORT_PATH}")


def _write_report(reports: dict[str, CurrencyReleaseTimingReport]) -> None:
    payload: dict[str, Any] = {
        "story": "FX-44",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "method": METHOD_SUMMARY,
        "currencies": {currency: _currency_to_dict(report) for currency, report in reports.items()},
        "provider_mapping_promotion": {
            "any_mapping_promoted_to_point_in_time_safe": False,
            "reason": (
                "FX-44 section 7: a ProviderSeriesMapping may be promoted to "
                "POINT_IN_TIME_SAFE only if the ENTIRE research interval it will be "
                "applied to satisfies point-in-time requirements -- not merely because "
                "some observations within it are verified. No currency above has zero "
                "unresolved_provisional change points across its full stored history, so "
                "no mapping is promoted here. Interval-specific safety is represented "
                "explicitly instead, per currency, via earliest_research_safe_date/"
                "latest_research_safe_date/unresolved_dates above -- a future research "
                "use case must select its own interval and pass the vintages it actually "
                "intends to use through domain.research_readiness."
                "require_research_ready_interval, which fails closed on any single "
                "still-provisional observation regardless of this report."
            ),
        },
        "jpy_out_of_scope": True,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = REPORT_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n")
    tmp_path.replace(REPORT_PATH)  # atomic write -- matches FX-43's report precedent


def _currency_to_dict(report: CurrencyReleaseTimingReport) -> dict[str, Any]:
    sources = sorted(
        {
            cp.citation
            for cp in (*report.exact_verified, *report.conservative_safe)
            if cp.citation is not None
        }
    )
    return {
        "series_key": report.series_key,
        "total_change_points": report.total_change_points,
        "exact_verified": len(report.exact_verified),
        "conservative_safe": len(report.conservative_safe),
        "unresolved_provisional": len(report.unresolved),
        "conflicting": len(report.conflicting),
        "earliest_research_safe_date": _iso_or_none(report.earliest_research_safe_date),
        "latest_research_safe_date": _iso_or_none(report.latest_research_safe_date),
        "unresolved_dates": [
            {
                "observation_period": cp.observation_period.value.isoformat(),
                "reason": cp.reason,
            }
            for cp in report.unresolved
        ],
        "conflicting_dates": [_verification_to_dict(cp) for cp in report.conflicting],
        "sources": sources,
    }


def _verification_to_dict(cp: ChangePointVerification) -> dict[str, Any]:
    return {
        "observation_period": cp.observation_period.value.isoformat(),
        "outcome": cp.outcome.value,
        "reason": cp.reason,
    }


def _iso_or_none(timestamp: UtcTimestamp | None) -> str | None:
    return None if timestamp is None else timestamp.value.isoformat()


if __name__ == "__main__":
    asyncio.run(main())

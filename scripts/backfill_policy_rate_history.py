"""FX-43: backfills real, external policy-rate history for every
currency in the FX-42/FX-42H/FX-42H.1 registry, against a live Postgres
and the real FRED / ECB Data Portal / Bank of England / Bank of Canada
public APIs (no API key required for any of them).

This wires up already-tested machinery (`BackfillPolicyRateHistory`,
`SqlAlchemyMacroObservationRepository`, the four provider clients under
`infrastructure.policy_rate_providers`) rather than adding new
behaviour, so it has no dedicated test suite of its own -- same
precedent as `scripts/build_research_dataset.py`.

JPY is deliberately NOT configured with a provider (per FX-42H.1, its
provider mapping remains entirely unresolved) -- it still appears in
the report, with every era marked `provider_configured: false`, rather
than being silently omitted.

Idempotent: every vintage this script writes goes through
`MacroObservationRepository.add_vintage`, which is a no-op for an exact
duplicate (FX-41H) -- safe to re-run.

`released_at` for every ingested vintage is set to the date a
provider's raw daily series shows a genuine value CHANGE -- an
EFFECTIVE-DATE proxy, not a verified announcement/publication
timestamp. No mapping is promoted to `PointInTimeSafety.
POINT_IN_TIME_SAFE` as a result of running this script -- see
`docs/DECISIONS.md`'s FX-43 entry for why establishing a genuine
announcement timestamp is out of scope here.

Run:
    uv run python scripts/backfill_policy_rate_history.py

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
    - Network access to fred.stlouisfed.org, data-api.ecb.europa.eu,
      www.bankofengland.co.uk, and www.bankofcanada.ca -- no API key
      needed for any of them.

Writes:
    - `MacroObservationVintage` rows via `MacroObservationRepository`.
    - `reports/policy_rate_backfill_report.json` -- the explicit,
      per-currency data-quality report this story requires.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.use_cases.backfill_policy_rate_history import (
    BackfillPolicyRateHistory,
    CurrencyBackfillReport,
    EraBackfillReport,
)
from forex_agent.domain.policy_rate_registry import REQUIRED_CURRENCIES
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.macro_observation_repository import (
    SqlAlchemyMacroObservationRepository,
)
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.policy_rate_providers.boc_client import (
    BocPolicyRateHistoryProvider,
)
from forex_agent.infrastructure.policy_rate_providers.boe_client import (
    BoePolicyRateHistoryProvider,
)
from forex_agent.infrastructure.policy_rate_providers.ecb_client import (
    EcbPolicyRateHistoryProvider,
)
from forex_agent.infrastructure.policy_rate_providers.fred_client import (
    FredPolicyRateHistoryProvider,
)

REPORT_PATH = Path("reports/policy_rate_backfill_report.json")

KNOWN_GAPS = [
    "CAD: no daily target-rate source was found via the Bank of Canada Valet API for "
    "1999-02-01 through 2009-04-20 (V39079 and four other candidate series all either start "
    "2009-04-21 or measure a different concept) -- not backfilled in this run.",
    "JPY: provider mapping remains entirely unresolved (FX-42H.1) -- not attempted in this run.",
    "All currencies: released_at is set to the date a provider's raw series shows a value "
    "change (an effective-date proxy), not a verified announcement/publication timestamp -- "
    "no mapping is point-in-time-safe as a result of this run. See docs/DECISIONS.md's FX-43 "
    "entry.",
]


async def main() -> None:
    as_of = UtcTimestamp(datetime.now(UTC).replace(microsecond=0))
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    fred = FredPolicyRateHistoryProvider()
    ecb = EcbPolicyRateHistoryProvider()
    boe = BoePolicyRateHistoryProvider()
    boc = BocPolicyRateHistoryProvider()
    try:
        async with session_factory() as session:
            backfill = BackfillPolicyRateHistory(
                providers={
                    "FRED": fred,
                    "ECB_SDW": ecb,
                    "BOE_DATABASE": boe,
                    "BOC_VALET": boc,
                    # No entry for "BOJ_TIME_SERIES_DATA_SEARCH" -- JPY is
                    # deliberately left unconfigured, per FX-42H.1.
                },
                repository=SqlAlchemyMacroObservationRepository(session),
            )

            reports: dict[str, CurrencyBackfillReport] = {}
            for currency in sorted(REQUIRED_CURRENCIES):
                print(f"{currency}: backfilling as of {as_of.value.isoformat()} ...")
                report = await backfill(currency, as_of)
                reports[currency] = report
                for era in report.eras:
                    if not era.provider_configured:
                        print(f"  {era.instrument_name}: no provider configured -- skipped")
                    elif era.fetch_error is not None:
                        print(f"  {era.instrument_name}: FETCH FAILED -- {era.fetch_error}")
                    else:
                        print(
                            f"  {era.instrument_name} ({era.provider}): "
                            f"{era.change_points_found} change points, "
                            f"{era.vintages_ingested} vintages ingested, "
                            f"{len(era.skipped_dates)} dates skipped, "
                            f"{len(era.conflicts)} conflicts"
                        )
    finally:
        await fred.aclose()
        await ecb.aclose()
        await boe.aclose()
        await boc.aclose()

    _write_report(reports, as_of)
    print(f"\nData-quality report written to {REPORT_PATH}")


def _write_report(reports: dict[str, CurrencyBackfillReport], as_of: UtcTimestamp) -> None:
    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "as_of": as_of.value.isoformat(),
        "currencies": {
            currency: {
                "series_key": report.series_key,
                "total_vintages_ingested": report.total_vintages_ingested,
                "coverage_start": _iso_or_none(report.coverage_start),
                "coverage_end": _iso_or_none(report.coverage_end),
                "eras": [_era_to_dict(era) for era in report.eras],
            }
            for currency, report in reports.items()
        },
        "known_gaps": KNOWN_GAPS,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = REPORT_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n")
    tmp_path.replace(REPORT_PATH)  # atomic write -- matches FX-40's index.json precedent


def _era_to_dict(era: EraBackfillReport) -> dict[str, Any]:
    return {
        "instrument_name": era.instrument_name,
        "provider": era.provider,
        "provider_series_ids": list(era.provider_series_ids),
        "requested_start": era.requested_start.value.isoformat(),
        "requested_end": era.requested_end.value.isoformat(),
        "change_points_found": era.change_points_found,
        "vintages_ingested": era.vintages_ingested,
        "skipped_dates": [ts.value.isoformat() for ts in era.skipped_dates],
        "conflicts": list(era.conflicts),
        "provider_configured": era.provider_configured,
        "fetch_error": era.fetch_error,
        "earliest_change_point": _iso_or_none(era.earliest_change_point),
        "latest_change_point": _iso_or_none(era.latest_change_point),
    }


def _iso_or_none(timestamp: UtcTimestamp | None) -> str | None:
    return None if timestamp is None else timestamp.value.isoformat()


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UtcTimestamp):
        return value.value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


if __name__ == "__main__":
    asyncio.run(main())

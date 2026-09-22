"""Bank of Canada Valet API adapter implementing
`PolicyRateHistoryProvider` (FX-43).

No API key required or used. Confirmed live against this endpoint
before writing this adapter:
- `https://www.bankofcanada.ca/valet/observations/{series_id}/json
  ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` returns
  `{"observations": [{"d": "YYYY-MM-DD", "{series_id}": {"v": "0.25"}},
  ...]}` for exactly the requested range.
- `V39079` ("Target for the overnight rate (business daily)") is
  confirmed correct -- unchanged from FX-42H -- but its own live data
  only starts 2009-04-21, materially later than the registry's
  documented `valid_from` (1999-02-01) for CAD's Overnight Rate
  Target definition. Checked for an earlier-history alternative under
  this adapter's own series (`V122514` "Overnight rate" is a market/
  achieved rate, not the announced target; `STATIC_ATABLE_V39079`/
  `BR.CDN`/`B114039` all also only start 2009-04-21 via this API) --
  none found. This is a genuine provider-availability gap for
  1999-02-01 through 2009-04-20, not something this adapter works
  around -- see `docs/DECISIONS.md`'s FX-43 entry; it is reported by
  the backfill use case's data-quality report, never silently filled.
"""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from forex_agent.application.ports.policy_rate_history_provider import (
    PolicyRateProviderUnavailableError,
)
from forex_agent.domain.timestamps import UtcTimestamp

_BASE_URL = "https://www.bankofcanada.ca"
_TIMEOUT_SECONDS = 30.0


class BocPolicyRateHistoryProvider:
    """Implements `PolicyRateHistoryProvider` against the Bank of
    Canada's Valet API. No API key required or used."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=_BASE_URL, timeout=_TIMEOUT_SECONDS)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_daily_series(
        self, provider_series_id: str, start: UtcTimestamp, end: UtcTimestamp
    ) -> list[tuple[UtcTimestamp, Decimal]]:
        try:
            response = await self._client.get(
                f"/valet/observations/{provider_series_id}/json",
                params={
                    "start_date": start.value.date().isoformat(),
                    "end_date": end.value.date().isoformat(),
                },
            )
        except httpx.RequestError as exc:
            raise PolicyRateProviderUnavailableError(
                f"failed to reach the Bank of Canada Valet API for series "
                f"{provider_series_id!r}: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise PolicyRateProviderUnavailableError(
                f"Bank of Canada Valet API request for series {provider_series_id!r} failed "
                f"with status {response.status_code}"
            )

        try:
            payload = response.json()
            return _parse_observations(payload, provider_series_id)
        except (KeyError, ValueError, InvalidOperation) as exc:
            raise PolicyRateProviderUnavailableError(
                f"unexpected Bank of Canada Valet API response shape for series "
                f"{provider_series_id!r}: {exc}"
            ) from exc


def _parse_observations(
    payload: dict[str, Any], provider_series_id: str
) -> list[tuple[UtcTimestamp, Decimal]]:
    observations = payload["observations"]
    results: list[tuple[UtcTimestamp, Decimal]] = []
    for row in observations:
        observation_date = datetime.strptime(row["d"], "%Y-%m-%d").replace(tzinfo=UTC)
        results.append((UtcTimestamp(observation_date), Decimal(row[provider_series_id]["v"])))
    return results

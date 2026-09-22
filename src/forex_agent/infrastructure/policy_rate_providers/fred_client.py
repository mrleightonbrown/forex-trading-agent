"""FRED (Federal Reserve Economic Data) adapter implementing
`PolicyRateHistoryProvider` (FX-43).

Uses FRED's public `fredgraph.csv` endpoint -- the same no-API-key CSV
download FRED uses for its own graph embeds. Confirmed live against
this endpoint before writing this adapter:
- `https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}
  &cosd={start}&coed={end}` returns `observation_date,{series_id}`
  rows for exactly the requested closed date range.
- A missing observation (a date FRED has no value for) is rendered as
  a literal `.` in the value column, not an absent row -- skipped, not
  treated as a change or fabricated as zero.
- `DFEDTAR` (single target rate) covers 1954-07-01 onward in the raw
  series; `DFEDTARU`/`DFEDTARL` (target range upper/lower bound) cover
  2008-12-16 onward. This adapter fetches whatever range it is asked
  for -- `policy_rate_registry`'s own `valid_from`/`valid_to`
  boundaries are what actually restrict which portion gets ingested,
  not this client.
"""

import csv
import io
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx

from forex_agent.application.ports.policy_rate_history_provider import (
    PolicyRateProviderUnavailableError,
)
from forex_agent.domain.timestamps import UtcTimestamp

_BASE_URL = "https://fred.stlouisfed.org"
_TIMEOUT_SECONDS = 30.0
_MISSING_VALUE_MARKER = "."


class FredPolicyRateHistoryProvider:
    """Implements `PolicyRateHistoryProvider` against FRED's public
    `fredgraph.csv` endpoint. No API key required or used."""

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
                "/graph/fredgraph.csv",
                params={
                    "id": provider_series_id,
                    "cosd": start.value.date().isoformat(),
                    "coed": end.value.date().isoformat(),
                },
            )
        except httpx.RequestError as exc:
            raise PolicyRateProviderUnavailableError(
                f"failed to reach FRED for series {provider_series_id!r}: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise PolicyRateProviderUnavailableError(
                f"FRED request for series {provider_series_id!r} failed with status "
                f"{response.status_code}"
            )

        try:
            return _parse_csv(response.text, provider_series_id)
        except (KeyError, ValueError, InvalidOperation) as exc:
            raise PolicyRateProviderUnavailableError(
                f"unexpected FRED response shape for series {provider_series_id!r}: {exc}"
            ) from exc


def _parse_csv(text: str, provider_series_id: str) -> list[tuple[UtcTimestamp, Decimal]]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or provider_series_id not in reader.fieldnames:
        raise KeyError(f"expected a {provider_series_id!r} column, got {reader.fieldnames!r}")

    results: list[tuple[UtcTimestamp, Decimal]] = []
    for row in reader:
        raw_value = row[provider_series_id]
        if raw_value == _MISSING_VALUE_MARKER:
            continue  # FRED's own "no observation for this date" marker -- skip, never fabricate
        observation_date = datetime.strptime(row["observation_date"], "%Y-%m-%d").replace(
            tzinfo=UTC
        )
        results.append((UtcTimestamp(observation_date), Decimal(raw_value)))
    return results

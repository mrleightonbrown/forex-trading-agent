"""ECB Data Portal adapter implementing `PolicyRateHistoryProvider`
(FX-43).

Uses `data-api.ecb.europa.eu`, the ECB's current SDMX REST API. No API
key required or used. Confirmed live against this endpoint before
writing this adapter:
- The older `sdw-wsrest.ecb.europa.eu` host (guessed as this series'
  documented host in FX-42/FX-42H) is unreachable -- superseded by
  `data-api.ecb.europa.eu`. The series KEY itself,
  `FM.D.U2.EUR.4F.KR.MRR_RT.LEV`, is correct and unchanged.
- `.../service/data/FM/{key}?format=csvdata&startPeriod=...
  &endPeriod=...` returns one row per date within an inclusive range,
  with many metadata columns -- only `TIME_PERIOD` and `OBS_VALUE` are
  used here, located by column NAME (the header row), not position, so
  a column-order change upstream doesn't silently misparse.
- `MRR_RT` ("Main refinancing operations - Minimum bid rate/fixed
  rate") is confirmed to track the ECB's headline MRO rate
  continuously across the 2000-2008 variable-rate-tender period,
  unlike `MRR_FR` ("...fixed rate" only), which has NO rows during
  that period (fixed-rate tenders were not in use then). This
  continuity is exactly why FX-42H's original choice of `MRR_RT` was
  correct -- `MRR_FR` would have been a genuine gap in raw provider
  data disguised as a clean series.
- A query for a valid series with no observations in range (e.g. a
  window entirely before the series began) returns HTTP 200 with an
  empty body, not an error -- treated as zero rows, not a failure. An
  invalid/nonexistent series key returns HTTP 404 instead -- treated
  as `PolicyRateProviderUnavailableError`, since that indicates a
  genuinely wrong `provider_series_id`, not merely an empty window.
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

_BASE_URL = "https://data-api.ecb.europa.eu"
_TIMEOUT_SECONDS = 30.0


class EcbPolicyRateHistoryProvider:
    """Implements `PolicyRateHistoryProvider` against the ECB Data
    Portal's SDMX REST API. No API key required or used."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=_BASE_URL, timeout=_TIMEOUT_SECONDS)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_daily_series(
        self, provider_series_id: str, start: UtcTimestamp, end: UtcTimestamp
    ) -> list[tuple[UtcTimestamp, Decimal]]:
        # The registry stores the FULL key as ECB itself cites it (and as the
        # response's own KEY column echoes it back), e.g.
        # "FM.D.U2.EUR.4F.KR.MRR_RT.LEV" -- but the REST path already names
        # the "FM" dataflow as its own segment, so the leading "FM." must be
        # stripped here or the request 400s on a doubled dataflow ID
        # (confirmed live: /service/data/FM/FM.D.U2...  fails,
        # /service/data/FM/D.U2... succeeds).
        series_key = provider_series_id.removeprefix("FM.")
        try:
            response = await self._client.get(
                f"/service/data/FM/{series_key}",
                params={
                    "format": "csvdata",
                    "startPeriod": start.value.date().isoformat(),
                    "endPeriod": end.value.date().isoformat(),
                },
            )
        except httpx.RequestError as exc:
            raise PolicyRateProviderUnavailableError(
                f"failed to reach the ECB Data Portal for series {provider_series_id!r}: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise PolicyRateProviderUnavailableError(
                f"ECB Data Portal request for series {provider_series_id!r} failed with status "
                f"{response.status_code}: {response.text[:200]}"
            )
        if not response.text.strip():
            return []  # a valid, in-range query with no observations -- confirmed live: HTTP 200,
            # empty body (an invalid/nonexistent series key is HTTP 404, handled above instead)

        try:
            return _parse_csv(response.text)
        except (KeyError, ValueError, InvalidOperation) as exc:
            raise PolicyRateProviderUnavailableError(
                f"unexpected ECB Data Portal response shape for series "
                f"{provider_series_id!r}: {exc}"
            ) from exc


def _parse_csv(text: str) -> list[tuple[UtcTimestamp, Decimal]]:
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or ()
    if "TIME_PERIOD" not in fieldnames or "OBS_VALUE" not in fieldnames:
        raise KeyError(f"expected TIME_PERIOD and OBS_VALUE columns, got {fieldnames!r}")

    results: list[tuple[UtcTimestamp, Decimal]] = []
    for row in reader:
        observation_date = datetime.strptime(row["TIME_PERIOD"], "%Y-%m-%d").replace(tzinfo=UTC)
        results.append((UtcTimestamp(observation_date), Decimal(row["OBS_VALUE"])))
    return results

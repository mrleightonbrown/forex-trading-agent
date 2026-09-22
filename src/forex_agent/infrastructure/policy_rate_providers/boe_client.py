"""Bank of England Interactive Statistical Database (IADB) adapter
implementing `PolicyRateHistoryProvider` (FX-43).

No API key required or used. Confirmed live against this endpoint
before writing this adapter:
- `https://www.bankofengland.co.uk/boeapps/database/
  _iadb-fromshowcolumns.asp?csv.x=yes&Datefrom={DD/Mon/YYYY}
  &Dateto={DD/Mon/YYYY}&SeriesCodes={code}&UsingCodes=Y&CSVF=TN&VPD=Y`
  returns `DATE,{code}` rows for exactly the requested range, dates
  formatted `DD Mon YYYY` (e.g. `02 Jan 1990`) -- a different format
  from the `Datefrom`/`Dateto` REQUEST params (`DD/Mon/YYYY`, with
  slashes) and from every other provider client in this package.
- `IUDBEDR` (Bank Rate) is confirmed correct -- unchanged from FX-42H.
- The BoE's WAF returns HTTP 403 for httpx's own default `User-Agent`
  (and presumably other recognized HTTP-library signatures), even
  though the request is otherwise identical to one that succeeds --
  confirmed by reproducing the exact same request with only the
  `User-Agent` header changed. This client sends a descriptive,
  identifying `User-Agent` instead (not a spoofed browser string) to
  avoid that block.
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

_BASE_URL = "https://www.bankofengland.co.uk"
_TIMEOUT_SECONDS = 30.0
_REQUEST_DATE_FORMAT = "%d/%b/%Y"
_RESPONSE_DATE_FORMAT = "%d %b %Y"
# The BoE's WAF returns 403 for default HTTP-library User-Agent strings
# (confirmed live: httpx's own default is blocked; curl's default and any
# other non-library-signature string are not) -- a descriptive, honest
# identifier avoids that block without impersonating a browser.
_USER_AGENT = "forex-agent-research/1.0 (+https://github.com/mrleightonbrown/forex-trading-agent)"


class BoePolicyRateHistoryProvider:
    """Implements `PolicyRateHistoryProvider` against the Bank of
    England's IADB. No API key required or used."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=_TIMEOUT_SECONDS,
            headers={"User-Agent": _USER_AGENT},
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_daily_series(
        self, provider_series_id: str, start: UtcTimestamp, end: UtcTimestamp
    ) -> list[tuple[UtcTimestamp, Decimal]]:
        try:
            response = await self._client.get(
                "/boeapps/database/_iadb-fromshowcolumns.asp",
                params={
                    "csv.x": "yes",
                    "Datefrom": start.value.strftime(_REQUEST_DATE_FORMAT),
                    "Dateto": end.value.strftime(_REQUEST_DATE_FORMAT),
                    "SeriesCodes": provider_series_id,
                    "UsingCodes": "Y",
                    "CSVF": "TN",
                    "VPD": "Y",
                },
            )
        except httpx.RequestError as exc:
            raise PolicyRateProviderUnavailableError(
                f"failed to reach the Bank of England database for series "
                f"{provider_series_id!r}: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise PolicyRateProviderUnavailableError(
                f"Bank of England database request for series {provider_series_id!r} failed "
                f"with status {response.status_code}"
            )

        try:
            return _parse_csv(response.text, provider_series_id)
        except (KeyError, ValueError, InvalidOperation) as exc:
            raise PolicyRateProviderUnavailableError(
                f"unexpected Bank of England database response shape for series "
                f"{provider_series_id!r}: {exc}"
            ) from exc


def _parse_csv(text: str, provider_series_id: str) -> list[tuple[UtcTimestamp, Decimal]]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or provider_series_id not in reader.fieldnames:
        raise KeyError(f"expected a {provider_series_id!r} column, got {reader.fieldnames!r}")

    results: list[tuple[UtcTimestamp, Decimal]] = []
    for row in reader:
        observation_date = datetime.strptime(row["DATE"], _RESPONSE_DATE_FORMAT).replace(tzinfo=UTC)
        results.append((UtcTimestamp(observation_date), Decimal(row[provider_series_id])))
    return results

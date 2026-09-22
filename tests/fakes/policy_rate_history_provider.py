"""In-memory `PolicyRateHistoryProvider` test double (FX-43)."""

from decimal import Decimal

from forex_agent.application.ports.policy_rate_history_provider import (
    PolicyRateProviderUnavailableError,
)
from forex_agent.domain.timestamps import UtcTimestamp


class FakePolicyRateHistoryProvider:
    """Structurally satisfies `PolicyRateHistoryProvider` (a
    `Protocol`) — no inheritance needed. Backed by a plain dict of
    canned series, keyed by `provider_series_id`; unregistered IDs
    raise `PolicyRateProviderUnavailableError` like a real adapter
    would for an unknown/invalid series."""

    def __init__(self, series: dict[str, list[tuple[UtcTimestamp, Decimal]]] | None = None) -> None:
        self._series = series or {}

    async def fetch_daily_series(
        self, provider_series_id: str, start: UtcTimestamp, end: UtcTimestamp
    ) -> list[tuple[UtcTimestamp, Decimal]]:
        if provider_series_id not in self._series:
            raise PolicyRateProviderUnavailableError(
                f"no canned data for series {provider_series_id!r}"
            )
        return [
            (ts, value)
            for ts, value in self._series[provider_series_id]
            if start.value <= ts.value <= end.value
        ]

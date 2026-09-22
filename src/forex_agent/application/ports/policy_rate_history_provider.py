from decimal import Decimal
from typing import Protocol

from forex_agent.domain.timestamps import UtcTimestamp


class PolicyRateProviderUnavailableError(Exception):
    """Raised when a `PolicyRateHistoryProvider` fails to reach its
    provider (network failure, non-2xx response, or a response shape
    that doesn't match what the adapter expects) — mirrors
    `BrokerUnavailableError`'s role for `BrokerPort`/`MarketDataPort`.
    """


class PolicyRateHistoryProvider(Protocol):
    """Port for fetching one raw historical daily series from a
    specific external provider (FX-43).

    Deliberately the narrowest possible surface: one provider-specific
    series identifier in, one list of raw `(date, value)` pairs out.
    No canonicalization, no `RateTransformation`, no
    `MacroObservationVintage` construction, no change-point extraction
    -- those are `domain.policy_rate_change_extraction` and the
    `BackfillPolicyRateHistory` use case's job, kept deliberately
    separate so this port stays a thin, swappable fetch step. A
    concrete implementation talks HTTP to exactly one provider (FRED,
    the ECB Data Portal, the BoE database, the BoC Valet API, ...);
    nothing above this port needs to know which.

    Returns RAW values as published by the provider, unmodified except
    for `Decimal` parsing -- no interpolation, no forward-filling, no
    smoothing. A date the provider does not report is simply absent
    from the result; it is never synthesized.
    """

    async def fetch_daily_series(
        self, provider_series_id: str, start: UtcTimestamp, end: UtcTimestamp
    ) -> list[tuple[UtcTimestamp, Decimal]]:
        """All raw `(date, value)` pairs the provider reports for
        `provider_series_id` within `[start, end]` (inclusive both
        ends -- provider APIs are queried by calendar date, not a
        half-open instant range), sorted ascending by date.

        Raises `PolicyRateProviderUnavailableError` if the provider
        cannot be reached or returns something this adapter cannot
        parse.
        """
        ...

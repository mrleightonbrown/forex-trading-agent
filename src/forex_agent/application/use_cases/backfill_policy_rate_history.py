"""FX-43: backfill real, external policy-rate history into
`MacroObservationRepository`, using the FX-42/FX-42H/FX-42H.1 registry
to know WHAT to fetch and HOW to canonicalize it, and
`domain.policy_rate_change_extraction` to turn a provider's raw daily
series into genuine change points -- never a fabricated daily series.

This is the first use case in this codebase that ingests real
fundamental data. Deliberately narrow: one currency's registered
`PolicyRateDefinition`s in, one `MacroObservationVintage` per genuine
policy-rate change out. No pair-relative differential, no carry
framing, no strategy, no decision logic.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from forex_agent.application.ports.macro_observation_repository import (
    MacroObservationRepository,
    MacroVintageConflictError,
)
from forex_agent.application.ports.policy_rate_history_provider import (
    PolicyRateHistoryProvider,
    PolicyRateProviderUnavailableError,
)
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.policy_rate_change_extraction import extract_change_points
from forex_agent.domain.policy_rate_definition import PolicyRateDefinition
from forex_agent.domain.policy_rate_registry import definitions_for_currency
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class EraBackfillReport:
    """The outcome of backfilling one `PolicyRateDefinition` (one
    effective-dated era of one currency's canonical series)."""

    instrument_name: str
    provider: str
    provider_series_ids: tuple[str, ...]
    requested_start: UtcTimestamp
    requested_end: UtcTimestamp
    change_points_found: int
    vintages_ingested: int
    skipped_dates: tuple[UtcTimestamp, ...]
    conflicts: tuple[str, ...]
    provider_configured: bool
    fetch_error: str | None = None
    # The ACTUAL span of change points found -- distinct from
    # requested_start/requested_end, which is only what was asked for.
    # A provider's real data can start materially later than the
    # registry's own valid_from (see CAD's documented gap) -- reporting
    # only the requested window here would silently overstate coverage.
    earliest_change_point: UtcTimestamp | None = None
    latest_change_point: UtcTimestamp | None = None


@dataclass(frozen=True, slots=True)
class CurrencyBackfillReport:
    """The outcome of backfilling every registered era of one
    currency -- the explicit, per-currency data-quality report this
    story requires."""

    currency: str
    series_key: str
    eras: tuple[EraBackfillReport, ...] = field(default_factory=tuple)

    @property
    def total_vintages_ingested(self) -> int:
        return sum(era.vintages_ingested for era in self.eras)

    @property
    def coverage_start(self) -> UtcTimestamp | None:
        """The earliest `observation_period` actually ingested across
        every era -- NOT the earliest date this run asked a provider
        for. A currency whose provider data starts materially later
        than its registry `valid_from` (e.g. CAD) is reported here by
        its true data coverage, not its requested window."""
        found = [era.earliest_change_point for era in self.eras if era.earliest_change_point]
        return min(found, key=lambda ts: ts.value) if found else None

    @property
    def coverage_end(self) -> UtcTimestamp | None:
        """The latest `observation_period` actually ingested across
        every era -- see `coverage_start`."""
        found = [era.latest_change_point for era in self.eras if era.latest_change_point]
        return max(found, key=lambda ts: ts.value) if found else None

    @property
    def unconfigured_eras(self) -> tuple[EraBackfillReport, ...]:
        """Eras this run could not attempt at all -- no
        `PolicyRateHistoryProvider` was supplied for that era's
        `ProviderSeriesMapping.provider`. Reported explicitly rather
        than silently skipped."""
        return tuple(era for era in self.eras if not era.provider_configured)


@dataclass(frozen=True, slots=True)
class BackfillPolicyRateHistory:
    """Backfills every registered `PolicyRateDefinition` for one
    currency, using whichever `PolicyRateHistoryProvider`s are
    supplied for the providers its registry entries name.

    `providers`: a mapping of `ProviderSeriesMapping.provider` (e.g.
    "FRED", "ECB_SDW") to a concrete `PolicyRateHistoryProvider` for
    that provider. A currency whose registry entries name a provider
    NOT present in this mapping is not silently skipped -- it is
    recorded in the report's `unconfigured_eras` so the caller can see
    exactly what was and was not attempted (e.g. JPY, whose provider
    mapping remains entirely unresolved per FX-42H.1, is expected to be
    entirely unconfigured until a future story establishes it).
    """

    providers: dict[str, PolicyRateHistoryProvider]
    repository: MacroObservationRepository

    async def __call__(self, currency: str, as_of: UtcTimestamp) -> CurrencyBackfillReport:
        definitions = definitions_for_currency(currency)
        series_key = definitions[0].series.key if definitions else ""

        eras: list[EraBackfillReport] = []
        for definition in definitions:
            if definition.valid_from.value > as_of.value:
                continue  # this era hasn't started yet as of `as_of` -- nothing to backfill
            window_end = (
                as_of
                if definition.valid_to is None or definition.valid_to.value > as_of.value
                else definition.valid_to
            )
            eras.append(await self._backfill_era(definition, definition.valid_from, window_end))

        return CurrencyBackfillReport(currency=currency, series_key=series_key, eras=tuple(eras))

    async def _backfill_era(
        self, definition: PolicyRateDefinition, start: UtcTimestamp, end: UtcTimestamp
    ) -> EraBackfillReport:
        # FX-43 scope: exactly one provider mapping per definition is
        # attempted, matching the registry's current shape (every
        # definition has exactly one mapping today). A future story
        # adding a second candidate mapping per definition would need
        # this to choose between them, not attempt all blindly.
        mapping = definition.provider_mappings[0]
        provider = self.providers.get(mapping.provider)

        if provider is None:
            return EraBackfillReport(
                instrument_name=definition.instrument_name,
                provider=mapping.provider,
                provider_series_ids=mapping.provider_series_ids,
                requested_start=start,
                requested_end=end,
                change_points_found=0,
                vintages_ingested=0,
                skipped_dates=(),
                conflicts=(),
                provider_configured=False,
            )

        try:
            fetched: list[tuple[tuple[UtcTimestamp, Decimal], ...]] = []
            for series_id in mapping.provider_series_ids:
                fetched.append(tuple(await provider.fetch_daily_series(series_id, start, end)))
            raw_series = tuple(fetched)
        except PolicyRateProviderUnavailableError as exc:
            # A fetch failure for one era must not silently look like "zero
            # change points found" -- report it explicitly rather than
            # either crashing the whole currency backfill or pretending
            # nothing was wrong.
            return EraBackfillReport(
                instrument_name=definition.instrument_name,
                provider=mapping.provider,
                provider_series_ids=mapping.provider_series_ids,
                requested_start=start,
                requested_end=end,
                change_points_found=0,
                vintages_ingested=0,
                skipped_dates=(),
                conflicts=(),
                provider_configured=True,
                fetch_error=str(exc),
            )

        extraction = extract_change_points(raw_series, definition.transformation)

        vintages_ingested = 0
        conflicts: list[str] = []
        for change in extraction.changes:
            vintage = MacroObservationVintage(
                series_key=definition.series.key,
                observation_period=change.observation_period,
                value=change.value,
                released_at=change.observation_period,
                effective_at=None,
                revision_sequence=0,
                source=mapping.provider,
            )
            try:
                await self.repository.add_vintage(vintage)
                vintages_ingested += 1
            except MacroVintageConflictError as exc:
                conflicts.append(str(exc))

        return EraBackfillReport(
            instrument_name=definition.instrument_name,
            provider=mapping.provider,
            provider_series_ids=mapping.provider_series_ids,
            requested_start=start,
            requested_end=end,
            change_points_found=len(extraction.changes),
            vintages_ingested=vintages_ingested,
            skipped_dates=extraction.skipped_dates,
            conflicts=tuple(conflicts),
            provider_configured=True,
            earliest_change_point=(
                extraction.changes[0].observation_period if extraction.changes else None
            ),
            latest_change_point=(
                extraction.changes[-1].observation_period if extraction.changes else None
            ),
        )

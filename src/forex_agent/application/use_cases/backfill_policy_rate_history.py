"""FX-43: backfill real, external policy-rate history into
`MacroObservationRepository`, using the FX-42/FX-42H/FX-42H.1 registry
to know WHAT to fetch and HOW to canonicalize it, and
`domain.policy_rate_change_extraction` to turn a provider's raw daily
series into genuine change points -- never a fabricated daily series.
Hardened FX-43H: half-open era boundaries are enforced against the
provider fetch itself (not merely assumed from provider behavior),
raw provider coverage is reported separately from change-point span,
`add_vintage`'s INSERTED/ALREADY_PRESENT outcome is reported
accurately, and every ingested vintage is explicitly marked
`released_at_is_verified=False`.

This is the first use case in this codebase that ingests real
fundamental data. Deliberately narrow: one currency's registered
`PolicyRateDefinition`s in, one `MacroObservationVintage` per genuine
policy-rate change out. No pair-relative differential, no carry
framing, no strategy, no decision logic.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from forex_agent.application.ports.macro_observation_repository import (
    MacroObservationRepository,
    MacroVintageConflictError,
    VintageWriteOutcome,
)
from forex_agent.application.ports.policy_rate_history_provider import (
    PolicyRateHistoryProvider,
    PolicyRateProviderUnavailableError,
)
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.policy_rate_change_extraction import (
    ConflictingRawObservationError,
    extract_change_points,
)
from forex_agent.domain.policy_rate_definition import PolicyRateDefinition
from forex_agent.domain.policy_rate_registry import definitions_for_currency
from forex_agent.domain.timestamps import UtcTimestamp

_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class EraBackfillReport:
    """The outcome of backfilling one `PolicyRateDefinition` (one
    effective-dated era of one currency's canonical series).

    Two DIFFERENT spans are tracked, deliberately never conflated
    (FX-43H):
      - `earliest_raw_observation`/`latest_raw_observation`: the actual
        span of raw provider data received for this era, regardless of
        whether any of it represented a rate CHANGE. A stable rate
        that never moves still has a provider publishing data for it
        every day -- that data range is real coverage, even with zero
        change points.
      - `earliest_change_point`/`latest_change_point`: the span of
        genuine policy-rate CHANGES found -- typically narrower than
        the raw span, since a rate can (and usually does) stay flat
        for stretches between the raw series' start and end.
    """

    instrument_name: str
    provider: str
    provider_series_ids: tuple[str, ...]
    requested_start: UtcTimestamp
    requested_end: UtcTimestamp
    change_points_found: int
    vintages_inserted: int
    vintages_already_present: int
    skipped_dates: tuple[UtcTimestamp, ...]
    conflicts: tuple[str, ...]
    provider_configured: bool
    fetch_error: str | None = None
    data_integrity_error: str | None = None
    earliest_raw_observation: UtcTimestamp | None = None
    latest_raw_observation: UtcTimestamp | None = None
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
    def total_vintages_inserted(self) -> int:
        return sum(era.vintages_inserted for era in self.eras)

    @property
    def total_vintages_already_present(self) -> int:
        return sum(era.vintages_already_present for era in self.eras)

    @property
    def coverage_start(self) -> UtcTimestamp | None:
        """The earliest date this run actually RECEIVED raw provider
        data for, across every era -- NOT the earliest date requested,
        and NOT the earliest policy CHANGE (FX-43H: see
        `EraBackfillReport`'s own docstring for why these three are
        kept distinct). A currency whose provider data starts
        materially later than its registry `valid_from` (e.g. CAD) is
        reported here by its true data coverage, not its requested
        window."""
        found = [era.earliest_raw_observation for era in self.eras if era.earliest_raw_observation]
        return min(found, key=lambda ts: ts.value) if found else None

    @property
    def coverage_end(self) -> UtcTimestamp | None:
        """The latest date this run actually RECEIVED raw provider data
        for, across every era -- see `coverage_start`. Distinct from
        the latest CHANGE POINT: a rate that has been stable for months
        still has raw coverage extending to the present."""
        found = [era.latest_raw_observation for era in self.eras if era.latest_raw_observation]
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
            window_end = self._fetch_end(definition, as_of)
            eras.append(await self._backfill_era(definition, definition.valid_from, window_end))

        return CurrencyBackfillReport(currency=currency, series_key=series_key, eras=tuple(eras))

    @staticmethod
    def _fetch_end(definition: PolicyRateDefinition, as_of: UtcTimestamp) -> UtcTimestamp:
        """The last date to request from the provider for this era --
        FX-43H's half-open-era fix.

        Registry validity is `[valid_from, valid_to)` -- `valid_to`
        itself belongs to the NEXT era, not this one. Provider APIs are
        queried by INCLUSIVE calendar-date range (`PolicyRateHistory
        Provider`'s own documented contract), so requesting `end=
        valid_to` would ask a provider for `valid_to`'s own date too --
        wrongly, since that date's raw observation (if the provider
        happens to publish one) belongs to the era that STARTS there,
        not this one. This must not rely on a provider's own behavior
        happening to stop publishing the day before (e.g. FRED's
        DFEDTAR does, but that is a fact about FRED, not a guarantee
        this method may lean on) -- the fetch window itself is clamped
        to `valid_to - 1 day` whenever this era's window would
        otherwise reach or pass `valid_to`.
        """
        if definition.valid_to is None or definition.valid_to.value > as_of.value:
            return as_of
        return UtcTimestamp(definition.valid_to.value - _ONE_DAY)

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
                vintages_inserted=0,
                vintages_already_present=0,
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
                vintages_inserted=0,
                vintages_already_present=0,
                skipped_dates=(),
                conflicts=(),
                provider_configured=True,
                fetch_error=str(exc),
            )

        all_raw_dates = [timestamp for series in raw_series for timestamp, _ in series]
        earliest_raw = min(all_raw_dates, key=lambda ts: ts.value) if all_raw_dates else None
        latest_raw = max(all_raw_dates, key=lambda ts: ts.value) if all_raw_dates else None

        try:
            extraction = extract_change_points(raw_series, definition.transformation)
        except ConflictingRawObservationError as exc:
            # FX-43H: never "last value wins" -- a genuine data-integrity
            # problem in the raw feed is reported, not silently resolved.
            return EraBackfillReport(
                instrument_name=definition.instrument_name,
                provider=mapping.provider,
                provider_series_ids=mapping.provider_series_ids,
                requested_start=start,
                requested_end=end,
                change_points_found=0,
                vintages_inserted=0,
                vintages_already_present=0,
                skipped_dates=(),
                conflicts=(),
                provider_configured=True,
                data_integrity_error=str(exc),
                earliest_raw_observation=earliest_raw,
                latest_raw_observation=latest_raw,
            )

        vintages_inserted = 0
        vintages_already_present = 0
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
                # FX-43H: explicit, not implicit -- released_at above is an
                # effective-date proxy (the date the raw series' value
                # changed), not a confirmed announcement timestamp.
                released_at_is_verified=False,
            )
            try:
                outcome = await self.repository.add_vintage(vintage)
                if outcome is VintageWriteOutcome.INSERTED:
                    vintages_inserted += 1
                else:
                    vintages_already_present += 1
            except MacroVintageConflictError as exc:
                conflicts.append(str(exc))

        return EraBackfillReport(
            instrument_name=definition.instrument_name,
            provider=mapping.provider,
            provider_series_ids=mapping.provider_series_ids,
            requested_start=start,
            requested_end=end,
            change_points_found=len(extraction.changes),
            vintages_inserted=vintages_inserted,
            vintages_already_present=vintages_already_present,
            skipped_dates=extraction.skipped_dates,
            conflicts=tuple(conflicts),
            provider_configured=True,
            earliest_raw_observation=earliest_raw,
            latest_raw_observation=latest_raw,
            earliest_change_point=(
                extraction.changes[0].observation_period if extraction.changes else None
            ),
            latest_change_point=(
                extraction.changes[-1].observation_period if extraction.changes else None
            ),
        )

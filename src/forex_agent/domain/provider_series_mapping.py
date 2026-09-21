from dataclasses import dataclass

from forex_agent.domain.point_in_time_safety import PointInTimeSafety


@dataclass(frozen=True, slots=True)
class ProviderSeriesMapping:
    """Maps one specific provider/source's own identifier(s) onto a
    canonical `PolicyRateDefinition` (FX-42).

    This is the explicit split FX-41 deferred: canonical series
    IDENTITY (`MacroSeriesDefinition`) must stay provider-independent,
    but something still has to record which real-world provider a
    future ingestion story reads from and what that provider calls the
    series. This type is that record -- deliberately data only, no
    HTTP client, no fetch logic. `provider_series_ids` is a tuple
    (not a single string) because some canonical scalars are derived
    from more than one raw provider series (e.g. a target range's
    upper and lower bound) -- see `RateTransformation`.

    `point_in_time_safety` lives HERE, not on `MacroSeriesDefinition`,
    because point-in-time trustworthiness is a property of a SOURCE,
    not of the abstract economic concept: the same canonical "USD
    policy rate" concept could in principle be sourced from a
    vintage-preserving archive (potentially POINT_IN_TIME_SAFE) or a
    scraped current-value-only page (LATEST_ONLY) -- the concept does
    not change, but which mapping is safe for historical research
    does. FX-42H made this the SOLE place point-in-time safety is
    tracked at all: `MacroSeriesDefinition` (FX-41) originally carried
    its own `point_in_time_safety` field too, defaulting to `UNKNOWN`,
    but FX-42H removed it -- a canonical concept is provider-
    independent by construction and has no source of its own to
    classify.

    Point-in-time safety alone is not enough to trust a mapping for
    research, though: `verified` -- whether `provider_series_ids` has
    actually been confirmed against the live provider -- is an
    independent dimension. A human can believe a source type is
    point-in-time-safe in the abstract without having confirmed this
    specific identifier resolves to real data at all. FX-42H's
    `require_research_usable_mapping` (below) is the fail-closed guard
    over BOTH dimensions together: a mapping is research-usable only
    when `verified is True` AND `point_in_time_safety is
    POINT_IN_TIME_SAFE`.

    Every mapping in the FX-42/FX-42H registry is
    `PointInTimeSafety.UNKNOWN` and `verified=False` -- this story
    records candidate providers and identifiers researched in good
    faith, it does not call a live provider API to confirm them.
    Central-bank policy RATE decisions are official record and
    essentially never revised after the fact (unlike survey-based
    series such as CPI/GDP), so the primary point-in-time risk for this
    data is release-timing (the exact announcement timestamp), not
    revision -- but that is a reason a future verification is *likely*
    to succeed, not a reason to assume it has already happened.
    FX-42H is explicit that daily effective-date observations alone are
    NOT sufficient grounds to mark a mapping `POINT_IN_TIME_SAFE`: an
    H1 no-lookahead backtest needs the exact `released_at` timestamp
    (e.g. the FOMC statement's release time), and how a provider
    actually exposes that is exactly what FX-43 must verify before
    promoting any mapping to `POINT_IN_TIME_SAFE`/`verified=True`.

    Fields:
        provider: a short, stable label for the source (e.g. "FRED",
            "ECB_SDW", "BOE_DATABASE"). Not a URL or client class name.
        provider_series_ids: the provider's own series identifier(s)
            this mapping reads from, in the order a `RateTransformation`
            expects them (e.g. (upper, lower) for
            `TARGET_RANGE_MIDPOINT`). Always at least one.
        point_in_time_safety: see above. Defaults to `UNKNOWN`.
        verified: whether `provider_series_ids` has actually been
            confirmed against the live provider (an API call was made
            and the series was found to exist and match expectations).
            `False` for every mapping this story adds -- see above.
        notes: free-text provenance/confidence context, e.g. what
            still needs confirming, or why a given provider was chosen
            over an alternative.
    """

    provider: str
    provider_series_ids: tuple[str, ...]
    point_in_time_safety: PointInTimeSafety = PointInTimeSafety.UNKNOWN
    verified: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError(f"provider must be a non-empty string, got {self.provider!r}")
        if not isinstance(self.provider_series_ids, tuple) or not self.provider_series_ids:
            raise ValueError(
                f"provider_series_ids must be a non-empty tuple, got {self.provider_series_ids!r}"
            )
        for series_id in self.provider_series_ids:
            if not isinstance(series_id, str) or not series_id.strip():
                raise ValueError(
                    f"every provider_series_ids entry must be a non-empty string, got {series_id!r}"
                )
        if not isinstance(self.point_in_time_safety, PointInTimeSafety):
            raise TypeError(
                "point_in_time_safety must be a PointInTimeSafety, "
                f"got {type(self.point_in_time_safety)!r}"
            )
        if not isinstance(self.verified, bool):
            raise TypeError(f"verified must be a bool, got {type(self.verified)!r}")
        if not isinstance(self.notes, str):
            raise TypeError(f"notes must be a str, got {type(self.notes)!r}")


def require_research_usable_mapping(mapping: ProviderSeriesMapping) -> None:
    """Fail closed (FX-42H): raise unless `mapping` is BOTH `verified`
    AND classified `POINT_IN_TIME_SAFE`.

    This is the sole point-in-time-safety gate for historical research
    -- FX-42H deliberately made `ProviderSeriesMapping` the only place
    this classification lives (see this module's and
    `MacroSeriesDefinition`'s docstrings) and combined it with
    `verified` into one guard, because either condition alone is
    insufficient: `point_in_time_safety is POINT_IN_TIME_SAFE` without
    `verified` is an unconfirmed belief about a source TYPE, not a
    confirmed fact about this specific mapping; `verified` without
    `POINT_IN_TIME_SAFE` only confirms the identifier resolves to real
    data, not that historical as-of queries against it would be safe.
    A future research/ingestion consumer must call this against the
    specific mapping it intends to rely on.

    No caller of this guard exists yet -- FX-42/FX-42H are the registry
    and its safety invariant, not a research/ingestion consumer of it.
    """
    failures = []
    if not mapping.verified:
        failures.append("not verified")
    if mapping.point_in_time_safety is not PointInTimeSafety.POINT_IN_TIME_SAFE:
        failures.append(f"point_in_time_safety is {mapping.point_in_time_safety.value}")
    if failures:
        raise ValueError(
            f"provider mapping {mapping.provider!r} {mapping.provider_series_ids!r} "
            f"is not research-usable ({'; '.join(failures)}); refusing to use it for "
            "historical research"
        )

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
    does. `MacroSeriesDefinition.point_in_time_safety` (FX-41) is left
    at its own default (`UNKNOWN`) for every series in this registry;
    it is not derived from, or kept in sync with, any mapping's own
    classification here.

    Every mapping in FX-42's registry is `PointInTimeSafety.UNKNOWN`
    and `verified=False` -- this story records candidate providers and
    identifiers researched in good faith, it does not call a live
    provider API to confirm them. Central-bank policy RATE decisions
    are official record and essentially never revised after the fact
    (unlike survey-based series such as CPI/GDP), so the primary
    point-in-time risk for this data is release-timing (the exact
    announcement timestamp), not revision -- but that is a reason a
    future verification is *likely* to succeed, not a reason to assume
    it has already happened. Fail closed, per FX-41: promoting a
    mapping to `POINT_IN_TIME_SAFE` and `verified=True` is FX-43's job,
    once it has actually confirmed the provider's release-timestamp
    behavior.

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


def require_point_in_time_safe_mapping(mapping: ProviderSeriesMapping) -> None:
    """Fail closed: raise unless `mapping` is classified
    `POINT_IN_TIME_SAFE`.

    Mirrors `macro_series_definition.require_point_in_time_safe`
    (FX-41) at the mapping level -- a future research/ingestion
    consumer must call this against the specific mapping it intends to
    rely on, not against the mapping's canonical series (which carries
    its own, independent, always-`UNKNOWN` classification -- see
    `ProviderSeriesMapping`'s docstring).
    """
    if mapping.point_in_time_safety is not PointInTimeSafety.POINT_IN_TIME_SAFE:
        raise ValueError(
            f"provider mapping {mapping.provider!r} {mapping.provider_series_ids!r} "
            f"is not point-in-time safe (classified "
            f"{mapping.point_in_time_safety.value}); refusing to use it for "
            "historical research"
        )

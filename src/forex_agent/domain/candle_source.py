from enum import Enum


class CandleSource(Enum):
    """Provenance of a `Candle` (FX-24): did it come directly from the
    broker (`NATIVE`), or was it produced by `aggregate_candles` from
    finer-granularity candles (`AGGREGATED`)?

    Exists specifically so a native H4 candle and a self-aggregated H4
    candle for the same instrument/start_time can never silently collide
    or overwrite each other in storage — see `infrastructure.db.models.
    candle.CandleRow`'s unique constraint, which includes this field.
    Native and aggregated candles for day-aligned granularities
    (H2/H3/H4/H6/H8/H12/D) are not guaranteed to share the same alignment
    unless produced with the same policy (FX-24's own NY-anchored fix
    makes them match in practice, but nothing enforces that two
    differently-configured aggregation runs would agree) — keeping them
    structurally distinct is the safety net, not a promise they'll always
    differ.
    """

    NATIVE = "NATIVE"
    AGGREGATED = "AGGREGATED"

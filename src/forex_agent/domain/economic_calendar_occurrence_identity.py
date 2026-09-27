"""Deterministic `occurrence_key`/`release_group_key` derivation for
official-calendar ingestion (FX-52A).

`occurrence_key` is a PURE function of `(source, external_event_id,
indicator_key)` -- deliberately not a separately persisted mapping
table. This still satisfies FX-51H's own "provider IDs must never
replace canonical occurrence identity": the resulting string is this
project's OWN identifier, namespaced by source and indicator so two
different sources' external IDs can never collide, never the raw
external ID used bare. It is a documented simplification, not a
weakening of that rule -- if a future story needs genuine many-to-one
remapping (Section 15/26's own "multiple provider identifiers may
eventually need to map to one canonical occurrence"), a persisted
mapping table can be introduced later without disturbing any
occurrence_key already in storage, since nothing depends on HOW an
existing occurrence_key was originally derived, only on its stability
going forward.

A single official calendar item can identify MORE THAN ONE canonical
indicator at once (FX-52A Section 11's own "Employment Situation"
example -- one BLS calendar entry, two canonical occurrences:
`US_NONFARM_PAYROLLS` and `US_UNEMPLOYMENT_RATE`). Each gets its OWN
`occurrence_key` (via `build_occurrence_key`, one call per indicator)
but shares one `release_group_key` (via `build_release_group_key`,
one call per SOURCE ITEM, not per indicator) -- exactly
`EconomicEventOccurrence.release_group_key`'s own contract: a
descriptive tag shared across occurrences published together, never
part of any single occurrence's own identity.
"""


def build_occurrence_key(source: str, external_event_id: str, indicator_key: str) -> str:
    """The canonical `occurrence_key` for one canonical indicator's
    occurrence, as observed via `external_event_id` from `source`.
    Stable across repeated polls and across a reschedule -- neither
    `source`, `external_event_id`, nor `indicator_key` ever changes
    for the SAME real-world occurrence, so this function always
    returns the same string for it, regardless of what its schedule
    currently says."""
    if not source.strip() or not external_event_id.strip() or not indicator_key.strip():
        raise ValueError(
            "source, external_event_id, and indicator_key must all be non-empty, got "
            f"source={source!r}, external_event_id={external_event_id!r}, "
            f"indicator_key={indicator_key!r}"
        )
    return f"{source}:{external_event_id}:{indicator_key}"


def build_release_group_key(source: str, external_event_id: str) -> str:
    """The shared `release_group_key` for every canonical occurrence
    derived from the SAME source item -- deliberately independent of
    `indicator_key`, so every occurrence built from one official
    release package (e.g. BLS's "Employment Situation") shares the
    identical group tag."""
    if not source.strip() or not external_event_id.strip():
        raise ValueError(
            f"source and external_event_id must both be non-empty, got source={source!r}, "
            f"external_event_id={external_event_id!r}"
        )
    return f"{source}:{external_event_id}"

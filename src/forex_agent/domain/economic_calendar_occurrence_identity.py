"""Provider-neutral internal occurrence identity, plus
`release_group_key` derivation, for official-calendar ingestion
(FX-52A; identity model corrected by FX-52AH).

FX-52A's original design derived `occurrence_key` as a PURE function of
`(source, external_event_id, indicator_key)` -- a documented
simplification at the time, but WRONG on inspection: `source` and
`external_event_id` are still baked directly into the resulting
string, so `source + external_event_id` was still functioning as
canonical identity in every way that matters, merely string-
concatenated with a namespace prefix rather than used bare. It also
made it IMPOSSIBLE for two different sources' external IDs to ever
resolve to the same occurrence -- exactly the "multiple provider
identifiers may eventually need to map to one canonical occurrence"
case this project's own FX-51H Section 15 already anticipated, and
which FX-52A itself needs immediately: Bank of Canada's ICS schedule
feed and RSS press-release feed use two completely independent
external IDs for the SAME real announcement.

FX-52AH's correction: `mint_occurrence_key` produces a genuinely
provider-neutral internal identity (an indicator-tagged UUID4 suffix,
readable for debugging but never derived from or equal to any source's
own identifier). The association between an external `(source,
external_event_id, indicator_key)` triple and the `occurrence_key` it
resolves to is now tracked in a real, persisted table
(`application.ports.economic_event_source_mapping_repository.
EconomicEventSourceMappingRepository`), not recomputed from a pure
function -- exactly the "persistent and idempotent" mapping FX-51H
Section 26 always intended, supporting genuine many-to-one resolution.

`build_release_group_key` is UNCHANGED and remains a pure function:
`release_group_key` is a descriptive tag, never occurrence identity,
so deriving it from `(source, external_event_id)` never had the
identity-collapsing problem `occurrence_key` did.
"""

from uuid import uuid4


def mint_occurrence_key(indicator_key: str) -> str:
    """A fresh, genuinely provider-neutral internal `occurrence_key`
    for a NEW occurrence of `indicator_key` -- never derived from any
    source's own identifier. The `indicator_key` prefix is for human
    debugging only (grep-ability in logs/DB browsing); nothing in this
    codebase parses an `occurrence_key` back apart. Call this ONCE per
    genuinely new real-world occurrence; every subsequent reference to
    that SAME occurrence must go through the persisted source-mapping
    repository, never a second call to this function."""
    if not indicator_key.strip():
        raise ValueError(f"indicator_key must be non-empty, got {indicator_key!r}")
    return f"{indicator_key}:{uuid4()}"


def build_release_group_key(source: str, external_event_id: str) -> str:
    """The shared `release_group_key` for every canonical occurrence
    derived from the SAME source item -- deliberately independent of
    `indicator_key`, so every occurrence built from one official
    release package (e.g. BLS's "Employment Situation") shares the
    identical group tag. Unlike `occurrence_key` (see the module
    docstring), this is legitimately a pure function: `release_group_
    key` is a descriptive tag, never occurrence identity."""
    if not source.strip() or not external_event_id.strip():
        raise ValueError(
            f"source and external_event_id must both be non-empty, got source={source!r}, "
            f"external_event_id={external_event_id!r}"
        )
    return f"{source}:{external_event_id}"

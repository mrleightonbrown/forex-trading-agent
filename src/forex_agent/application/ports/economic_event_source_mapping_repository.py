"""Port for the persisted external-source-to-occurrence mapping table
(FX-52AH).

Records, durably, which `occurrence_key` a `(source, external_event_id,
indicator_key)` triple resolves to -- the correction to FX-52A's
original design, which recomputed a source-derived `occurrence_key` via
a pure function instead of tracking this association explicitly. See
`domain.economic_calendar_occurrence_identity`'s own module docstring
for the full reasoning.

Supports genuine many-to-one resolution: two different `(source,
external_event_id)` pairs -- even from entirely different sources --
can map to the SAME `occurrence_key`, which is exactly what letting
Bank of Canada's ICS schedule feed and RSS press-release feed resolve
to one shared occurrence requires (FX-52AH's own motivating case).
Nothing about this port makes the REVERSE true: one `(source,
external_event_id, indicator_key)` triple must always resolve to
exactly one `occurrence_key`, enforced by this port's own conflict
error, mirroring every other `add_*`-shaped write in this project's
economic-event ports (`EconomicEventOccurrenceConflictError`,
`EconomicEventVintageConflictError`).
"""

from typing import Protocol


class EconomicEventSourceMappingConflictError(Exception):
    """Raised by `record_mapping` when `(source, external_event_id,
    indicator_key)` already resolves to a DIFFERENT `occurrence_key`
    than the one being recorded. An exact repeat of an already-recorded
    mapping is NOT an error (idempotent, see `record_mapping`); only a
    genuine conflict -- the same external identity resolving to two
    different internal occurrences -- is."""

    def __init__(
        self,
        source: str,
        external_event_id: str,
        indicator_key: str,
        existing_occurrence_key: str,
        incoming_occurrence_key: str,
    ) -> None:
        self.source = source
        self.external_event_id = external_event_id
        self.indicator_key = indicator_key
        self.existing_occurrence_key = existing_occurrence_key
        self.incoming_occurrence_key = incoming_occurrence_key
        super().__init__(
            f"mapping (source={source!r}, external_event_id={external_event_id!r}, "
            f"indicator_key={indicator_key!r}) already resolves to "
            f"occurrence_key={existing_occurrence_key!r}, cannot also record "
            f"occurrence_key={incoming_occurrence_key!r}"
        )


class EconomicEventSourceMappingRepository(Protocol):
    """Port for the persisted external-source-to-occurrence mapping
    table -- see the module docstring."""

    async def get_occurrence_key(
        self, source: str, external_event_id: str, indicator_key: str
    ) -> str | None:
        """The `occurrence_key` this exact triple already resolves to,
        or `None` if no mapping has been recorded for it yet."""
        ...

    async def record_mapping(
        self, source: str, external_event_id: str, indicator_key: str, occurrence_key: str
    ) -> None:
        """Durably associate `(source, external_event_id,
        indicator_key)` with `occurrence_key`. Idempotent for an exact
        repeat; raises `EconomicEventSourceMappingConflictError` if this
        exact triple already resolves to a DIFFERENT `occurrence_key`.
        Never overwrites an existing mapping -- once recorded, a
        mapping is permanent for as long as this triple keeps appearing
        in a source feed."""
        ...

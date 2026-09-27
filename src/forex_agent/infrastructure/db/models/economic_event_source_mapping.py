from sqlalchemy import ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EconomicEventSourceMappingRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persisted `(source, external_event_id, indicator_key) ->
    occurrence_key` mapping (FX-52AH) -- see `application.ports.
    economic_event_source_mapping_repository`'s own module docstring
    for why this exists instead of FX-52A's original pure-function
    derivation.

    FX-52AH.1: `occurrence_key` now carries a genuine `FOREIGN KEY`
    onto `economic_event_occurrences.occurrence_key`, added by
    migration `ecdb152af0a8` -- FX-52AH's own original "deliberately no
    FOREIGN KEY" design let a mapping row reference an occurrence_key
    that no occurrence actually exists for, with only this repository's
    own application-level conflict check (`record_mapping`) standing
    between that and silent data corruption. Both ingestion use cases
    (`IngestOfficialCalendarSchedule`/`IngestOfficialCalendarRelease`)
    already call `EconomicEventRepository.add_occurrence` and commit it
    BEFORE calling `record_mapping` (see each use case's own
    `_resolve_occurrence_key`), and this repository's own commit-per-
    call discipline means that occurrence row is durably committed in
    its own prior transaction by the time this table's own INSERT
    statement runs -- so this FK is satisfiable with no deferred-
    constraint machinery needed.
    """

    __tablename__ = "economic_event_source_mappings"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "external_event_id",
            "indicator_key",
            name="uq_economic_event_source_mappings_identity",
        ),
        Index(
            "ix_economic_event_source_mappings_occurrence_key",
            "occurrence_key",
        ),
        ForeignKeyConstraint(
            ["occurrence_key"],
            ["economic_event_occurrences.occurrence_key"],
            name="fk_economic_event_source_mappings_occurrence",
        ),
    )

    source: Mapped[str] = mapped_column(String, nullable=False)
    external_event_id: Mapped[str] = mapped_column(String, nullable=False)
    indicator_key: Mapped[str] = mapped_column(String, nullable=False)
    occurrence_key: Mapped[str] = mapped_column(String, nullable=False)

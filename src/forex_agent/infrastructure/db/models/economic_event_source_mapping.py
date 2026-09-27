from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EconomicEventSourceMappingRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persisted `(source, external_event_id, indicator_key) ->
    occurrence_key` mapping (FX-52AH) -- see `application.ports.
    economic_event_source_mapping_repository`'s own module docstring
    for why this exists instead of FX-52A's original pure-function
    derivation. Deliberately no `FOREIGN KEY` onto `economic_event_
    occurrences.occurrence_key`: a mapping may legitimately be recorded
    in the SAME transaction as the occurrence it points to is created
    (see `IngestOfficialCalendarSchedule`/`IngestOfficialCalendarRelease`),
    and requiring strict FK ordering here would add ceremony this
    story's own scope does not need -- referential correctness is
    enforced by this repository's own application-level conflict check
    (`record_mapping`), not by the database schema.
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
    )

    source: Mapped[str] = mapped_column(String, nullable=False)
    external_event_id: Mapped[str] = mapped_column(String, nullable=False)
    indicator_key: Mapped[str] = mapped_column(String, nullable=False)
    occurrence_key: Mapped[str] = mapped_column(String, nullable=False)

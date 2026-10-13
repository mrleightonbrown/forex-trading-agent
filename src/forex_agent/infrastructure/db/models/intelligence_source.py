from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class IntelligenceSourceRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FTA's own durable source identity (`domain.intelligence_source.
    IntelligenceSource`, FX-62 Section 4.1) -- `source_key` alone is
    unique, never reassigned to a different `source_kind` (enforced at
    the application layer by `RecordSourceIdentityVintage`; `source_
    kind` itself is written exactly once, by `SqlAlchemySourceRegistry
    Repository.register_source_with_first_identity_vintage`'s own
    atomic registration, and never updated afterward by any other code
    path -- mirrors `NewsItemRow`'s own "written exactly once" shape
    exactly.

    `registered_at` is FTA's OWN registration instant -- a distinct
    concept from `TimestampMixin.created_at` (raw row-insertion time,
    bookkeeping only) and from any `SourceIdentityVintage.availability`
    (an EVOLVING knowledge instant); never backdated."""

    __tablename__ = "intelligence_sources"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_intelligence_sources_source_key"),
        CheckConstraint(
            "source_kind IN ('ORGANIZATION', 'PERSON', 'PUBLICATION', 'TECHNICAL_FEED')",
            name="ck_intelligence_sources_source_kind",
        ),
    )

    source_key: Mapped[str] = mapped_column(String, nullable=False)
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

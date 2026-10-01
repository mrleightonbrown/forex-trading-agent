from sqlalchemy import ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class NewsSourceMappingRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persisted `(source_key, external_item_id) -> news_item_key`
    mapping (FX-56).

    `uq_news_source_mappings_identity` enforces one external identity
    resolving to exactly one internal item. `uq_news_source_mappings_
    news_item_key` additionally enforces the REVERSE -- one internal
    item has exactly one external source identity (FX-56 Section 10) --
    deliberately stricter than `EconomicEventSourceMappingRow`'s own
    shape, which intentionally allows several external identities to
    resolve to ONE occurrence (its own many-to-one BoC ICS/RSS case).
    FX-56 has no such case: a news item models exactly one source
    item, and cross-source correlation is explicitly FX-58's future
    job, never this table's.

    `news_item_key` carries a genuine `FOREIGN KEY` onto
    `news_items.news_item_key`, satisfiable from the FIRST write
    (unlike `EconomicEventSourceMappingRow`'s own FK, added two
    migrations after the fact) because `SqlAlchemyNewsRepository.
    register_source_item` inserts the owning `NewsItemRow` and this
    mapping row in the SAME uncommitted transaction before either is
    committed -- see that repository's own module docstring.
    """

    __tablename__ = "news_source_mappings"
    __table_args__ = (
        UniqueConstraint(
            "source_key",
            "external_item_id",
            name="uq_news_source_mappings_identity",
        ),
        UniqueConstraint(
            "news_item_key",
            name="uq_news_source_mappings_news_item_key",
        ),
        ForeignKeyConstraint(
            ["news_item_key"],
            ["news_items.news_item_key"],
            name="fk_news_source_mappings_news_item",
        ),
    )

    source_key: Mapped[str] = mapped_column(String, nullable=False)
    external_item_id: Mapped[str] = mapped_column(String, nullable=False)
    news_item_key: Mapped[str] = mapped_column(String, nullable=False)

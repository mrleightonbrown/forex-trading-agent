from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class NewsItemRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FTA's own internal identity for one source news item (FX-56).

    `news_item_key` alone is unique -- an item's natural identity (see
    `domain.news_item.NewsItem`), never a source's own external ID,
    URL, or timestamp. `first_seen_at`/`first_observation_mode` are
    written exactly once, by `SqlAlchemyNewsRepository.
    register_source_item`/`register_source_item_with_first_vintage`'s
    own atomic registration, and never updated afterward by any other
    code path in this codebase.

    `ck_news_items_first_observation_mode` (FX-56H) mirrors `domain.
    news_observation_mode.NewsObservationMode`'s own two members in
    storage, so the invariant holds even for a row written by a
    future path that bypasses the domain enum.
    """

    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("news_item_key", name="uq_news_items_news_item_key"),
        CheckConstraint(
            "first_observation_mode IN ('PROSPECTIVE', 'BACKFILL')",
            name="ck_news_items_first_observation_mode",
        ),
    )

    news_item_key: Mapped[str] = mapped_column(String, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_observation_mode: Mapped[str] = mapped_column(String, nullable=False)

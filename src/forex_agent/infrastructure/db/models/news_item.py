from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class NewsItemRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FTA's own internal identity for one source news item (FX-56).

    `news_item_key` alone is unique -- an item's natural identity (see
    `domain.news_item.NewsItem`), never a source's own external ID,
    URL, or timestamp. `first_seen_at`/`first_observation_mode` are
    written exactly once, by `SqlAlchemyNewsRepository.
    register_source_item`'s own atomic registration, and never updated
    afterward by any other code path in this codebase.
    """

    __tablename__ = "news_items"
    __table_args__ = (UniqueConstraint("news_item_key", name="uq_news_items_news_item_key"),)

    news_item_key: Mapped[str] = mapped_column(String, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_observation_mode: Mapped[str] = mapped_column(String, nullable=False)

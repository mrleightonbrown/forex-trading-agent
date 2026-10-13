from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ForecastClaimRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FX-64: the minimal, durable identity of one structured-forecast
    claim (`domain.forecast_claim.ForecastClaim`) -- mirrors `Intelligence
    SourceRow`'s own shape exactly. Never updated; every evolving fact
    lives on `structured_forecast_vintages` instead."""

    __tablename__ = "forecast_claims"
    __table_args__ = (
        UniqueConstraint("claim_key", name="uq_forecast_claims_claim_key"),
        CheckConstraint("claim_key <> ''", name="ck_forecast_claims_claim_key"),
    )

    claim_key: Mapped[str] = mapped_column(String, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

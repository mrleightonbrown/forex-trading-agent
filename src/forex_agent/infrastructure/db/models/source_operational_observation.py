from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SourceOperationalObservationRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable, append-only FX-63 acquisition-attempt observation
    (`domain.source_operational_observation.SourceOperationalObservation`).
    No application code path ever UPDATEs an existing row -- a retried
    attempt is simply another row, never a revision of an earlier one
    (unlike every FX-56/58/59/62 vintage table, this one has no
    revision/correction concept at all).

    `(source_key, run_id, attempt_number)` is unique -- the stable
    idempotency key Section 6 requires, grounded in a caller-minted
    `run_id` rather than a timestamp. Deliberately NO foreign key onto
    `intelligence_sources`: this table must keep recording forward-
    looking acquisition evidence regardless of whether FX-62's own
    bootstrap has registered this technical feed yet (Section 5 --
    "do not change FX-62 records to make measurement more
    convenient"); reuse of FX-62 identity happens at READ time only,
    in `GetSourceOperationalProfileAsOf`."""

    __tablename__ = "source_operational_observations"
    __table_args__ = (
        UniqueConstraint(
            "source_key",
            "run_id",
            "attempt_number",
            name="uq_soo_natural_key",
        ),
        Index(
            "ix_soo_source_availability",
            "source_key",
            "availability",
        ),
        CheckConstraint(
            "attempt_number >= 1",
            name="ck_soo_attempt_number",
        ),
        CheckConstraint(
            "source_key <> ''",
            name="ck_soo_source_key",
        ),
        CheckConstraint(
            "source_channel <> ''",
            name="ck_soo_source_channel",
        ),
        CheckConstraint(
            "run_id <> ''",
            name="ck_soo_run_id",
        ),
        CheckConstraint(
            "kind IN ('ACQUISITION_ATTEMPT')",
            name="ck_soo_kind",
        ),
        CheckConstraint(
            "outcome IN ('SUCCESS', 'HTTP_FAILURE', 'TIMEOUT', 'NETWORK_FAILURE')",
            name="ck_soo_outcome",
        ),
        CheckConstraint(
            "http_status IS NULL OR (http_status >= 100 AND http_status <= 599)",
            name="ck_soo_http_status",
        ),
        CheckConstraint(
            "policy_version <> ''",
            name="ck_soo_policy_version",
        ),
    )

    source_key: Mapped[str] = mapped_column(String, nullable=False)
    source_channel: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    availability: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_version: Mapped[str] = mapped_column(String, nullable=False)

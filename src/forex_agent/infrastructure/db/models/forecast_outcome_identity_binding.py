from sqlalchemy import CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ForecastOutcomeIdentityBindingRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FX-65H.2: the durable, exclusive claim that `outcome_key` is
    the sole holder of the measurement identity `(definition_key,
    target_period_key, outcome_type, unit)`
    (`domain.forecast_outcome_identity.ForecastOutcomeIdentityBinding`).

    TWO separate unique constraints enforce BOTH durable invariants
    atomically, at the database layer:
    - `uq_outcome_identity_binding_identity`: one identity belongs to
      AT MOST ONE `outcome_key` (H1).
    - `uq_outcome_identity_binding_key`: one `outcome_key` refers to
      EXACTLY ONE identity throughout its history (H2) -- a SECOND
      row for the SAME `outcome_key` but a DIFFERENT identity can
      never be inserted.

    `unit` is NOT NULL (using `NO_UNIT_SENTINEL` for `CATEGORICAL_
    EVENT`) specifically so the first constraint is never silently
    defeated by SQL's own NULL-is-distinct-from-NULL semantics, which
    a nullable `unit` column would otherwise allow.

    Deliberately carries NO foreign key onto `forecast_outcome_
    vintages` -- that table's own `(outcome_key, revision_sequence)`
    uniqueness means `outcome_key` ALONE is never unique there, so no
    FK is possible in either direction; the binding and the write
    sequence that creates it are the ONLY mechanism connecting them
    (see `RecordForecastOutcome`)."""

    __tablename__ = "forecast_outcome_identity_bindings"
    __table_args__ = (
        UniqueConstraint(
            "definition_key",
            "target_period_key",
            "outcome_type",
            "unit",
            name="uq_outcome_identity_binding_identity",
        ),
        UniqueConstraint("outcome_key", name="uq_outcome_identity_binding_key"),
        CheckConstraint("definition_key <> ''", name="ck_outcome_identity_binding_definition_key"),
        CheckConstraint(
            "target_period_key <> ''", name="ck_outcome_identity_binding_target_period_key"
        ),
        CheckConstraint(
            "outcome_type IN ('NUMERIC_POINT', 'CATEGORICAL_EVENT')",
            name="ck_outcome_identity_binding_outcome_type",
        ),
        CheckConstraint("unit <> ''", name="ck_outcome_identity_binding_unit"),
        CheckConstraint("outcome_key <> ''", name="ck_outcome_identity_binding_outcome_key"),
    )

    definition_key: Mapped[str] = mapped_column(String, nullable=False)
    target_period_key: Mapped[str] = mapped_column(String, nullable=False)
    outcome_type: Mapped[str] = mapped_column(String, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    outcome_key: Mapped[str] = mapped_column(String, nullable=False)

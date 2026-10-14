"""FX-65H.2: the durable MEASUREMENT IDENTITY an outcome_key is bound
to for its entire history -- `(definition_key, target_period,
outcome_type, unit)`. Two outcome_keys must never share this identity
(H1); one outcome_key must never change it across its own revisions
(H2).

`canonical_target_period_key` is a PURE, side-effect-free function
producing a stable string encoding of a `ForecastTargetPeriod` --
used ONLY as part of the outcome-identity-binding uniqueness key
persisted in `forecast_outcome_identity_bindings`. It is NEVER
persisted on, derived from, or used to reconstruct any FX-64 table or
type -- `ForecastTargetPeriod` itself is untouched by this story.

The exact string format below is part of this story's own frozen,
load-bearing contract: migration `80877afdbe75` backfills existing
real rows using this SAME format (duplicated inline there,
deliberately, per Alembic's own "migrations stay self-contained"
convention) -- any FUTURE change to this function's own output format
would silently desynchronize newly-computed keys from already-
migrated ones, breaking the uniqueness guarantee. Treat this format as
immutable once any real data depends on it.

**FX-65H.3 (H3) correction**: the `SPECIFIC_DATE` branch originally
used `datetime.isoformat()` directly, which OMITS the fractional-
second component whenever `microsecond == 0` -- `80877afdbe75`'s own
SQL `to_char(...)` equivalent, by contrast, ALWAYS discarded fractional
seconds entirely, regardless of value. Two genuinely distinct instants
differing only in their fractional second (or a zero-microsecond
instant and a real migration-backfilled one) could therefore
canonicalize to two DIFFERENT strings at runtime while a migration
would have backfilled a THIRD, lossy string for either -- a real
parity break, not merely a cosmetic one. Fixed by making the
microsecond component UNCONDITIONALLY present and fixed-width (6
digits, zero-padded) on BOTH sides -- see migration `3b03a0c4f0ba`
for the corrected SQL equivalent, the conflict pre-check it runs
before correcting any pre-existing `SPECIFIC_DATE` binding row, and
why no real row needed correcting (zero `SPECIFIC_DATE` rows existed
when it was written)."""

from dataclasses import dataclass

from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType

NO_UNIT_SENTINEL = "__NO_UNIT__"
"""Stored in place of `unit IS NULL` (a `CATEGORICAL_EVENT` outcome)
in `forecast_outcome_identity_bindings.unit` -- that column is NOT
NULL specifically so its own uniqueness constraint is never silently
defeated by SQL's own NULL-is-distinct-from-NULL semantics."""


def canonical_target_period_key(period: ForecastTargetPeriod) -> str:
    if period.period_kind is ForecastTargetPeriodKind.CALENDAR_YEAR:
        return f"CALENDAR_YEAR:{period.calendar_year}"
    if period.period_kind is ForecastTargetPeriodKind.CALENDAR_QUARTER:
        return f"CALENDAR_QUARTER:{period.calendar_year}:{period.calendar_quarter}"
    if period.period_kind is ForecastTargetPeriodKind.CALENDAR_MONTH:
        assert period.calendar_month is not None
        return f"CALENDAR_MONTH:{period.calendar_year}:{period.calendar_month:02d}"
    if period.period_kind is ForecastTargetPeriodKind.SPECIFIC_DATE:
        assert period.specific_date is not None
        dt = period.specific_date.value
        return f"SPECIFIC_DATE:{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{dt.microsecond:06d}+00:00"
    assert period.period_kind is ForecastTargetPeriodKind.POLICY_MEETING
    return f"POLICY_MEETING:{period.policy_meeting_identifier}"


@dataclass(frozen=True, slots=True)
class ForecastOutcomeIdentityBinding:
    """FX-65H.2: one row of `forecast_outcome_identity_bindings` --
    the durable, exclusive claim that `outcome_key` is the sole
    holder of the measurement identity `(definition_key, target_
    period_key, outcome_type, unit)`. `target_period_key` is always
    `canonical_target_period_key`'s own output; `unit` is `NO_UNIT_
    SENTINEL` for `CATEGORICAL_EVENT`, never the Python `None` FX-64/
    65's own vintage types use elsewhere -- this type is intentionally
    NOT reused for anything outside this one binding table."""

    definition_key: str
    target_period_key: str
    outcome_type: ForecastType
    unit: str
    outcome_key: str

    def __post_init__(self) -> None:
        for name, value in (
            ("definition_key", self.definition_key),
            ("target_period_key", self.target_period_key),
            ("unit", self.unit),
            ("outcome_key", self.outcome_key),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string, got {value!r}")
        if not isinstance(self.outcome_type, ForecastType):
            raise TypeError(
                f"outcome_type must be a ForecastType, got {type(self.outcome_type).__name__}"
            )

    def shares_identity_with(self, other: "ForecastOutcomeIdentityBinding") -> bool:
        """`True` iff `other` describes the SAME measurement identity
        (ignoring `outcome_key`) -- never compares `outcome_key`
        itself, since that is precisely the field H1/H2 are about."""
        return (
            self.definition_key == other.definition_key
            and self.target_period_key == other.target_period_key
            and self.outcome_type == other.outcome_type
            and self.unit == other.unit
        )

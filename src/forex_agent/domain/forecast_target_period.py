from dataclasses import dataclass

from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.timestamps import UtcTimestamp

_YEAR_RANGE = range(1900, 2200)


@dataclass(frozen=True, slots=True)
class ForecastTargetPeriod:
    """FX-64 Section 10: the EXACT period or event one structured
    forecast concerns -- structurally constrained so exactly the
    fields matching `period_kind` are populated, and every other
    field is `None`. There is no "default" period; a candidate with
    an ambiguous or unstated target period must be rejected by the
    capture-eligibility check (Section 11), never defaulted here.

    Fields:
        period_kind: which of the five supported shapes this period
            uses.
        calendar_year: the target calendar year -- required for
            `CALENDAR_YEAR`, `CALENDAR_QUARTER`, and `CALENDAR_MONTH`
            (all three are anchored to a specific year); `None`
            otherwise.
        calendar_quarter: 1-4 -- required for `CALENDAR_QUARTER` only.
        calendar_month: 1-12 -- required for `CALENDAR_MONTH` only.
        specific_date: an exact observation instant -- required for
            `SPECIFIC_DATE` only.
        policy_meeting_identifier: a stable, independently-grounded
            meeting identity (Section 10) -- required for `POLICY_
            MEETING` only.
    """

    period_kind: ForecastTargetPeriodKind
    calendar_year: int | None = None
    calendar_quarter: int | None = None
    calendar_month: int | None = None
    specific_date: UtcTimestamp | None = None
    policy_meeting_identifier: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.period_kind, ForecastTargetPeriodKind):
            raise TypeError(
                f"period_kind must be a ForecastTargetPeriodKind, got "
                f"{type(self.period_kind).__name__}"
            )

        def _require_year() -> None:
            if not isinstance(self.calendar_year, int) or isinstance(self.calendar_year, bool):
                raise TypeError("calendar_year must be an int for this period_kind")
            if self.calendar_year not in _YEAR_RANGE:
                raise ValueError(f"calendar_year is implausible: {self.calendar_year}")

        if self.period_kind is ForecastTargetPeriodKind.CALENDAR_YEAR:
            _require_year()
            self._require_none("calendar_quarter", "calendar_month")
            self._require_none("specific_date", "policy_meeting_identifier")
        elif self.period_kind is ForecastTargetPeriodKind.CALENDAR_QUARTER:
            _require_year()
            if self.calendar_quarter not in (1, 2, 3, 4):
                raise ValueError(f"calendar_quarter must be 1-4, got {self.calendar_quarter!r}")
            self._require_none("calendar_month", "specific_date", "policy_meeting_identifier")
        elif self.period_kind is ForecastTargetPeriodKind.CALENDAR_MONTH:
            _require_year()
            if self.calendar_month not in range(1, 13):
                raise ValueError(f"calendar_month must be 1-12, got {self.calendar_month!r}")
            self._require_none("calendar_quarter", "specific_date", "policy_meeting_identifier")
        elif self.period_kind is ForecastTargetPeriodKind.SPECIFIC_DATE:
            if not isinstance(self.specific_date, UtcTimestamp):
                raise TypeError("specific_date must be a UtcTimestamp for this period_kind")
            self._require_none(
                "calendar_year", "calendar_quarter", "calendar_month", "policy_meeting_identifier"
            )
        elif self.period_kind is ForecastTargetPeriodKind.POLICY_MEETING:
            if (
                not isinstance(self.policy_meeting_identifier, str)
                or not self.policy_meeting_identifier.strip()
            ):
                raise ValueError(
                    "policy_meeting_identifier must be a non-empty string for this period_kind"
                )
            self._require_none(
                "calendar_year", "calendar_quarter", "calendar_month", "specific_date"
            )

    def _require_none(self, *field_names: str) -> None:
        for name in field_names:
            if getattr(self, name) is not None:
                raise ValueError(
                    f"{name} must be None for period_kind={self.period_kind.value!r}, "
                    f"got {getattr(self, name)!r}"
                )

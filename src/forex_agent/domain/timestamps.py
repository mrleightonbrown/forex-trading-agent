from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class UtcTimestamp:
    """A timezone-aware timestamp, normalized to UTC.

    CLAUDE.md: "All persisted timestamps use timezone-aware UTC values.
    Naive datetimes must be rejected." A tz-aware datetime in another zone
    is accepted and converted; only a naive one is rejected outright.
    """

    value: datetime

    def __post_init__(self) -> None:
        if self.value.tzinfo is None:
            raise ValueError("naive datetimes are not permitted; value must be timezone-aware")
        object.__setattr__(self, "value", self.value.astimezone(UTC))

    @classmethod
    def now(cls) -> "UtcTimestamp":
        return cls(datetime.now(UTC))

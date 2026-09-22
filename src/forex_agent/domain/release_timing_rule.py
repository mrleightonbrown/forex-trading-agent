"""FX-44: converts a documented central-bank release-timing RULE (a
local time-of-day, an IANA timezone, and a validity window) into an
exact UTC instant for a specific calendar date -- the mechanism that
turns real, cited institutional research into a `released_at`/
`effective_at` value, without ever inventing a timestamp the research
does not actually support.

Deliberately pure: `zoneinfo` (Python's own historical IANA timezone
database) does all DST/offset arithmetic, so a rule expressed once
(e.g. "14:00 local, America/New_York") converts correctly across every
year it covers without this module encoding a single DST transition
date itself. This is domain-layer, not infrastructure -- `zoneinfo` is
part of the Python standard library, not a network client, database
driver, or web framework; CLAUDE.md's domain-boundary rules name
FastAPI/SQLAlchemy/broker SDKs/HTTP clients/env vars specifically, none
of which this is.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from zoneinfo import ZoneInfo

from forex_agent.domain.timestamps import UtcTimestamp


class ReleaseTimingConfidence(Enum):
    """How strongly a `ReleaseTimingRule` is evidenced (FX-44 section 3).

    - EXACT: the rule's local time-of-day is a specific, documented
      institutional convention -- a primary-source policy statement, or
      multiple independent, mutually consistent secondary sources
      describing a stable practice -- for the exact minute an
      announcement is/was released. Applying it produces a genuinely
      defensible timestamp; `released_at_is_verified=True` is an
      honest claim for the result.
    - CONSERVATIVE_SAFE_BOUND: the exact minute is NOT confidently
      established, but the rule's local time-of-day is deliberately
      chosen to be guaranteed no earlier than the true (unknown-exact)
      release -- e.g. "end of the announcement day, local time" when
      only the announcement DATE and a same-day, business-hours
      convention are confirmed. Safe for point-in-time research (can
      never reveal data before it was truly available), but must NOT
      be represented as `released_at_is_verified=True` -- FX-44
      explicitly forbids overloading that field to mean "we guessed a
      safely late time". See `MacroObservationVintage.
      released_at_is_conservative_bound`.
    """

    EXACT = "EXACT"
    CONSERVATIVE_SAFE_BOUND = "CONSERVATIVE_SAFE_BOUND"


@dataclass(frozen=True, slots=True)
class ReleaseTimingRule:
    """One documented, cited release-timing convention for a central
    bank, valid over a specific window of announcement-local calendar
    dates (FX-44).

    Deliberately narrow: this describes ONE institution's practice
    during ONE sub-period -- an institution whose convention changed
    over time (e.g. the Federal Reserve's 2013 shift to a fixed 2:00pm
    ET release) is represented as multiple `ReleaseTimingRule`s with
    adjoining `applies_from`/`applies_to` windows, exactly the way
    `PolicyRateDefinition` already represents an institution's changing
    instrument definitions (see `domain.policy_rate_definition`) rather
    than silently splicing eras together.

    Fields:
        institution: e.g. "Federal Reserve" -- documentation only,
            never branched on by code.
        local_time: the announcement time of day, in `timezone`'s
            local civil time.
        timezone: an IANA timezone name (e.g. "America/New_York") --
            `zoneinfo.ZoneInfo` resolves the correct historical UTC
            offset (DST included) for whatever date `resolve()` is
            given, so this module never encodes a DST transition date
            itself.
        confidence: see `ReleaseTimingConfidence`.
        applies_from: earliest announcement-local DATE this rule
            covers (inclusive).
        applies_to: exclusive upper bound on the announcement-local
            DATE this rule covers, or `None` if still current.
        citation: a specific, checkable source for this rule (a URL,
            or a named primary document) -- never a bare assertion.
        notes: free-text methodology/confidence context.
    """

    institution: str
    local_time: time
    timezone: str
    confidence: ReleaseTimingConfidence
    applies_from: date
    applies_to: date | None
    citation: str
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.institution, str) or not self.institution.strip():
            raise ValueError(f"institution must be a non-empty string, got {self.institution!r}")
        if not isinstance(self.local_time, time):
            raise TypeError(f"local_time must be a time, got {type(self.local_time)!r}")
        if not isinstance(self.timezone, str) or not self.timezone.strip():
            raise ValueError(f"timezone must be a non-empty string, got {self.timezone!r}")
        ZoneInfo(self.timezone)  # raises ZoneInfoNotFoundError immediately for a bad name
        if not isinstance(self.confidence, ReleaseTimingConfidence):
            raise TypeError(
                f"confidence must be a ReleaseTimingConfidence, got {type(self.confidence)!r}"
            )
        if not isinstance(self.applies_from, date):
            raise TypeError(f"applies_from must be a date, got {type(self.applies_from)!r}")
        if self.applies_to is not None:
            if not isinstance(self.applies_to, date):
                raise TypeError(f"applies_to must be a date or None, got {type(self.applies_to)!r}")
            if self.applies_to <= self.applies_from:
                raise ValueError(
                    f"applies_to ({self.applies_to}) must be after applies_from "
                    f"({self.applies_from})"
                )
        if not isinstance(self.citation, str) or not self.citation.strip():
            raise ValueError(f"citation must be a non-empty string, got {self.citation!r}")
        if not isinstance(self.notes, str):
            raise TypeError(f"notes must be a str, got {type(self.notes)!r}")

    def covers(self, local_date: date) -> bool:
        """Whether `local_date` falls within this rule's validity
        window: `applies_from <= local_date < applies_to` (or
        `local_date >= applies_from` when `applies_to` is `None`)."""
        if local_date < self.applies_from:
            return False
        return self.applies_to is None or local_date < self.applies_to

    def resolve(self, local_date: date) -> UtcTimestamp:
        """Convert `local_date` at this rule's `local_time`/`timezone`
        into an exact UTC instant.

        `zoneinfo` resolves the correct historical UTC offset (DST
        included) for `local_date` ITSELF, not today's offset -- the
        same local wall-clock time on a summer date and a winter date
        in the same zone correctly produce different UTC instants
        where DST applies.
        """
        naive = datetime.combine(local_date, self.local_time)
        localized = naive.replace(tzinfo=ZoneInfo(self.timezone))
        return UtcTimestamp(localized)

from enum import Enum


class EconomicEventStatus(Enum):
    """The lifecycle status a schedule vintage records for one economic
    event occurrence, AT THAT VINTAGE'S OWN POINT IN TIME (FX-51).

    Deliberately small, and deliberately does NOT include a
    `RESCHEDULED` member: a reschedule is represented as a NEW schedule
    vintage (a later `availability`, a new `scheduled_date`/
    `scheduled_time`, still `SCHEDULED`) rather than a status of its
    own -- the fact that a reschedule happened is recoverable from the
    vintage HISTORY (comparing consecutive vintages' scheduled dates),
    never from a status label on any single row. Likewise there is no
    `TENTATIVE`/`TIME_UNKNOWN` member: an unknown release time is
    represented by `EconomicEventScheduleVintage.scheduled_time` being
    `None`, a scheduling-QUALITY fact orthogonal to lifecycle status,
    not a status itself -- an event can be `SCHEDULED` with a known
    date and an unknown time simultaneously.

    `POSTPONED` and `CANCELLED` are not permanent terminal states
    either: a later vintage can set status back to `SCHEDULED` (e.g. a
    postponed event is reinstated with a new date) -- "reinstatement"
    (FX-51's own story, Section 5.3) is simply the next vintage in the
    same history, not a fourth status.
    """

    SCHEDULED = "SCHEDULED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"

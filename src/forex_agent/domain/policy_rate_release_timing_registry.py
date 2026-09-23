"""FX-44: hand-researched, cited release-timing rules for the real
policy-rate change points FX-43 backfilled, per currency -- the
domain-layer answer to "when did the market actually learn this rate
had changed?" for USD/EUR/GBP/CAD (JPY is explicitly out of scope).

This is deliberately NOT a generic "infer timing from a daily series"
algorithm -- FX-44's own instruction is "do not infer an exact
timestamp merely from the daily rate series." Every rule below is a
documented institutional convention with a citation, applied only to
the specific dates researched to genuinely be regular, scheduled
decisions; every change-point date NOT covered by a rule here (an
unresolved era, or a known irregular/emergency/inter-meeting action)
is deliberately left for `resolve_release_timing` to report as
unresolved -- callers must leave those vintages PROVISIONAL, per FX-44
section 2's explicit instruction not to convert "released sometime on
[date]" into a fabricated exact timestamp.

Research method and every citation are recorded here, next to the
rule each supports, rather than only in `docs/DECISIONS.md` -- so the
evidence for any one timestamp this story produces is one file away
from the code that computes it.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from forex_agent.domain.release_timing_rule import ReleaseTimingConfidence, ReleaseTimingRule
from forex_agent.domain.timestamps import UtcTimestamp

_SIX_DAYS = timedelta(days=6)


def _date_only_as_utc_midnight(value: date) -> UtcTimestamp:
    """Represents a DATE-ONLY fact (e.g. an operational effective date)
    as a `UtcTimestamp` at 00:00:00 UTC (FX-44H.1).

    This is a NORMALIZATION CONVENTION for fitting a date-only fact
    into this domain's `UtcTimestamp`-typed `effective_at` field --
    the same convention `observation_period` itself already uses
    elsewhere in this codebase (FX-41) to represent "this calendar
    date." It is explicitly NOT a claim that 00:00 UTC is itself a
    source-verified operational instant: every primary source this
    registry cites for an effective date establishes a DATE the target
    range took effect, never an intraday time, and none is claimed
    here. A caller reading `effective_at.value.time()` as anything
    other than this normalization artifact is misreading it.
    """
    return UtcTimestamp(datetime.combine(value, time(0, 0, 0), tzinfo=UTC))


@dataclass(frozen=True, slots=True)
class ReleaseTimingResolution:
    """What FX-44's registry determined should replace one stored,
    provisional change point's timing -- ready to pass straight to
    `MacroObservationRepository.replace_provisional_release_timing`."""

    released_at: UtcTimestamp
    effective_at: UtcTimestamp | None
    confidence: ReleaseTimingConfidence
    citation: str


@dataclass(frozen=True, slots=True)
class UnresolvedTiming:
    """Why `resolve_release_timing` is deliberately NOT proposing a
    replacement for one stored change point -- the vintage must stay
    PROVISIONAL. `reason` is written into the FX-44 report verbatim."""

    reason: str


@dataclass(frozen=True, slots=True)
class UsdPolicyTiming:
    """One individually-researched USD FOMC change point's full timing
    picture (FX-44H.1) -- three INDEPENDENT dates, never assumed equal
    to one another by a formula.

    FX-44H's original `USD_EFFECTIVE_TO_DECISION_DATE: dict[date,
    date]` assumed the provider-stored change-point date always equals
    the genuine operational EFFECTIVE date, so only a DECISION date
    needed recovering (via this same explicit-mapping discipline, at
    least -- FX-44H never used a formula for that part either). That
    assumption was itself wrong for two rows: 2015-12-16 ("liftoff")
    and 2016-12-14 (the second post-crisis hike) both have their TRUE
    effective date one day AFTER the stored date -- FX-44H had instead
    modeled a same-day (0-day) gap for exactly these two, because
    nothing distinguished "the provider's stored date" from "the
    genuine effective date" as separately-verifiable facts. This type
    exists so that distinction is structural, not assumed: a future
    discrepancy between provider date and true effective date (for
    ANY USD meeting, not only these two) cannot silently reintroduce
    the same class of bug.

    Fields:
        stored_date: the date the raw provider series (FRED) shows the
            value change on -- i.e. `observation_period`'s own date.
            Never rewritten; kept here purely so each record is
            self-describing and the lookup key is unambiguous.
        decision_date: the actual FOMC meeting day the change was
            decided/announced on.
        effective_date: the actual date the new target range took
            operational effect, per a primary Federal Reserve source
            (typically the FOMC's own "Implementation Note") -- NOT
            assumed equal to `stored_date`.
        citation: a specific, checkable primary source establishing
            `effective_date` (and, where the same source covers it,
            `decision_date` too).
        notes: free-text methodology/confidence context.
    """

    stored_date: date
    decision_date: date
    effective_date: date
    citation: str
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.stored_date, date):
            raise TypeError(f"stored_date must be a date, got {type(self.stored_date)!r}")
        if not isinstance(self.decision_date, date):
            raise TypeError(f"decision_date must be a date, got {type(self.decision_date)!r}")
        if not isinstance(self.effective_date, date):
            raise TypeError(f"effective_date must be a date, got {type(self.effective_date)!r}")
        if self.effective_date < self.decision_date:
            raise ValueError(
                f"effective_date ({self.effective_date}) must not be before "
                f"decision_date ({self.decision_date})"
            )
        if not isinstance(self.citation, str) or not self.citation.strip():
            raise ValueError(f"citation must be a non-empty string, got {self.citation!r}")
        if not isinstance(self.notes, str):
            raise TypeError(f"notes must be a str, got {type(self.notes)!r}")


# ---------------------------------------------------------------------------
# USD -- Federal Reserve (FOMC), source=FRED
# ---------------------------------------------------------------------------
#
# Research finding: the Fed's OWN March 13, 2013 announcement
# ("Federal Reserve issues FOMC statement" press release) states that,
# going forward, "Committee policy statements for all regularly
# scheduled meetings" would be released at 2:00pm Eastern Time, and
# that this REDUCED the prior gap to the (quarterly) press conference
# from a previous 2:15pm statement release -- but that same research
# also surfaced that the 2:15pm figure documented in secondary sources
# specifically describes the 2011-2012 press-conference-meeting
# schedule, and that non-press-conference 2011-2012 statements were in
# fact released at 12:30pm ET, not 2:15pm -- i.e. the exact minute
# genuinely varied within 2011-2012 by meeting type. Given that
# instability is directly evidenced (not merely unconfirmed), this
# story does NOT extend an exact-minute claim back before the Fed's
# own explicit rule -- only 2013-03-19 (the first meeting after the
# March 13, 2013 announcement) onward is treated as EXACT.
#
# For 1994-02-04 (the first immediate post-meeting announcement) through
# the day before that rule, every source consistently agrees the
# statement was released same-day, during US business hours, in the
# afternoon -- but not at a single confidently-citable exact minute
# across the whole 17-year span. Per FX-44 section 3, this is
# represented as a CONSERVATIVE_SAFE_BOUND: end of the announcement
# day, US Eastern time -- guaranteed no earlier than the true release,
# never claimed as the exact moment.
USD_CONSERVATIVE_RULE = ReleaseTimingRule(
    institution="Federal Reserve",
    local_time=time(23, 59, 59),
    timezone="America/New_York",
    confidence=ReleaseTimingConfidence.CONSERVATIVE_SAFE_BOUND,
    applies_from=date(1994, 2, 4),
    applies_to=date(2013, 3, 19),
    citation="https://www.federalreserve.gov/fomc/19940204default.htm ; "
    "https://www.federalreserve.gov/newsevents/pressreleases/monetary20130313a.htm",
    notes=(
        "FOMC statements in this era were consistently released same-day, in the "
        "afternoon, US Eastern time -- but the exact minute is not confidently "
        "citable as a single stable convention across this whole span (evidence "
        "found includes a 12:30pm ET statement release time for some 2011-2012 "
        "meetings, distinct from the 2:15pm figure describing others) -- so this "
        "story uses a conservative end-of-day bound rather than an exact minute."
    ),
)

# FX-44H.1: NOT necessarily the same date as the stored proxy for
# modern (2013-03-19 onward) meetings, in EITHER direction -- FX-44H
# fixed the assumption that the stored date always equals the
# ANNOUNCEMENT date, but still assumed it always equals the EFFECTIVE
# date. That second assumption was ALSO wrong for two rows: the Fed's
# own Implementation Notes (a document distinct from the main
# statement; the URL pattern `.../pressreleases/<YYYYMMDD>a1.htm`
# already existed in 2015-2016, not only "since ~2019" as FX-44H
# guessed) place BOTH 2015-12-16's and 2016-12-14's effective date ONE
# DAY AFTER the stored/decision date -- FX-44H had instead modeled a
# same-day (0-day) gap for exactly these two. `UsdPolicyTiming` keeps
# `stored_date`/`decision_date`/`effective_date` as three genuinely
# independent, individually-populated facts specifically so this class
# of bug (silently assuming any two of the three coincide) cannot
# recur unnoticed for a future USD meeting.
#
# The 28 entries below not individually re-cited this story were
# established in FX-44H by cross-referencing every USD EXACT change
# point against the Fed's own published FOMC meeting-date calendar
# (fomccalendars.htm, fomchistorical2015.htm through
# fomchistorical2019.htm) and are carried forward UNCHANGED (per this
# story's own instruction: "retain the already-verified decision/
# effective relationships unless primary-source review finds another
# discrepancy") -- for all 28, `stored_date == effective_date`, and
# `decision_date` is one day earlier. Resolution for the EXACT tier
# uses ONLY this explicit table, never a computed offset: a USD date
# -- including any future one a later backfill run ingests -- that is
# not a key here is UNRESOLVED, even if it would "look like" it fits
# the usual +1-day pattern.
_USD_STANDARD_PATTERN_CITATION = (
    "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm ; "
    "https://www.federalreserve.gov/monetarypolicy/fomchistorical2015.htm (and "
    "fomchistorical2016.htm through fomchistorical2019.htm) -- decision date "
    "cross-referenced against each meeting's own two-day calendar entry "
    "(FX-44H); effective date follows the FOMC's Implementation Note "
    "mechanism, e.g. https://www.federalreserve.gov/newsevents/pressreleases/"
    "20151216a1.htm: 'Effective [date], the Federal Open Market Committee "
    "directs the Desk to undertake open market operations...' -- confirmed "
    "one day after the decision date for every meeting below not "
    "individually re-cited (FX-44H.1)."
)


def _standard_pattern(stored_and_decision: tuple[date, date]) -> UsdPolicyTiming:
    stored_date, decision_date = stored_and_decision
    return UsdPolicyTiming(
        stored_date=stored_date,
        decision_date=decision_date,
        effective_date=stored_date,  # unchanged from FX-44H for these 28
        citation=_USD_STANDARD_PATTERN_CITATION,
    )


USD_POLICY_TIMINGS: dict[date, UsdPolicyTiming] = {
    date(2015, 12, 16): UsdPolicyTiming(
        stored_date=date(2015, 12, 16),
        decision_date=date(2015, 12, 16),
        effective_date=date(2015, 12, 17),  # FX-44H.1 correction -- was wrongly 2015-12-16
        citation=(
            "https://www.federalreserve.gov/newsevents/pressreleases/20151216a1.htm "
            '("Implementation Note issued December 16, 2015"): "Effective December 17, '
            "2015, the Federal Open Market Committee directs the Desk to undertake open "
            'market operations..."'
        ),
        notes=(
            "'Liftoff' -- the first hike since 2006. FX-44H had wrongly assumed a "
            "same-day (0-day) stored/effective gap for this meeting; FX-44H.1 corrects "
            "it using the FOMC's own Implementation Note, which was already being "
            "published in this exact form in December 2015, not only 'since ~2019' as "
            "FX-44H's own research note guessed."
        ),
    ),
    date(2016, 12, 14): UsdPolicyTiming(
        stored_date=date(2016, 12, 14),
        decision_date=date(2016, 12, 14),
        effective_date=date(2016, 12, 15),  # FX-44H.1 correction -- was wrongly 2016-12-14
        citation=(
            "https://www.federalreserve.gov/newsevents/pressreleases/20161214a1.htm "
            '("Implementation Note issued December 14, 2016"): "Effective December 15, '
            "2016, the Federal Open Market Committee directs the Desk to undertake open "
            'market operations..."'
        ),
        notes=(
            "The second post-crisis hike. FX-44H had wrongly assumed a same-day "
            "(0-day) stored/effective gap for this meeting too; FX-44H.1 corrects it "
            "the same way as 2015-12-16, above."
        ),
    ),
    **{
        stored: _standard_pattern((stored, decision))
        for stored, decision in (
            (date(2017, 3, 16), date(2017, 3, 15)),
            (date(2017, 6, 15), date(2017, 6, 14)),
            (date(2017, 12, 14), date(2017, 12, 13)),
            (date(2018, 3, 22), date(2018, 3, 21)),
            (date(2018, 6, 14), date(2018, 6, 13)),
            (date(2018, 9, 27), date(2018, 9, 26)),
            (date(2018, 12, 20), date(2018, 12, 19)),
            (date(2019, 8, 1), date(2019, 7, 31)),
            (date(2019, 9, 19), date(2019, 9, 18)),
            (date(2019, 10, 31), date(2019, 10, 30)),
            (date(2022, 3, 17), date(2022, 3, 16)),
            (date(2022, 5, 5), date(2022, 5, 4)),
            (date(2022, 6, 16), date(2022, 6, 15)),
            (date(2022, 7, 28), date(2022, 7, 27)),
            (date(2022, 9, 22), date(2022, 9, 21)),
            (date(2022, 11, 3), date(2022, 11, 2)),
            (date(2022, 12, 15), date(2022, 12, 14)),
            (date(2023, 2, 2), date(2023, 2, 1)),
            (date(2023, 3, 23), date(2023, 3, 22)),
            (date(2023, 5, 4), date(2023, 5, 3)),
            (date(2023, 7, 27), date(2023, 7, 26)),
            (date(2024, 9, 19), date(2024, 9, 18)),
            (date(2024, 11, 8), date(2024, 11, 7)),
            (date(2024, 12, 19), date(2024, 12, 18)),
            (date(2025, 9, 18), date(2025, 9, 17)),
            (date(2025, 10, 30), date(2025, 10, 29)),
            (date(2025, 12, 11), date(2025, 12, 10)),
            (date(2026, 9, 17), date(2026, 9, 16)),  # this story's own worked example
        )
    },
}

_USD_EXACT_DECISION_TIME_RULE = ReleaseTimingRule(
    institution="Federal Reserve",
    local_time=time(14, 0, 0),
    timezone="America/New_York",
    confidence=ReleaseTimingConfidence.EXACT,
    applies_from=date(2013, 3, 19),
    applies_to=None,
    citation="https://www.federalreserve.gov/newsevents/pressreleases/monetary20130313a.htm",
    notes=(
        "Federal Reserve Board press release, March 13, 2013: 'Committee policy "
        "statements for all regularly scheduled meetings will be released at 2:00 "
        "p.m. Eastern Time.' Effective starting the next scheduled meeting. Applied "
        "to each USD_POLICY_TIMINGS entry's own decision_date, never to the stored "
        "proxy directly."
    ),
)

# Known irregular/inter-meeting/emergency USD change points -- NOT
# regularly scheduled FOMC meeting decisions, so neither the
# conservative rule's window nor USD_POLICY_TIMINGS's meeting-day
# framing applies; the true announcement date and/or time for each of
# these differs from (or is not confidently identifiable from) the
# stored effective-date proxy. Left provisional.
USD_IRREGULAR_DATES: dict[date, str] = {
    date(1998, 10, 15): "Inter-meeting cut (between the Sep 29 and Nov 17, 1998 meetings, "
    "LTCM/Russia crisis response) -- not a regular meeting-day announcement.",
    date(2001, 1, 3): "Inter-meeting cut, announced by conference call -- not a regular "
    "meeting-day announcement.",
    date(2001, 4, 18): "Inter-meeting cut, announced by conference call -- not a regular "
    "meeting-day announcement.",
    date(2001, 9, 17): "Inter-meeting cut on the day US markets reopened after the "
    "September 11 attacks -- not a regular meeting-day announcement.",
    date(2008, 1, 22): "Inter-meeting 75bp emergency cut, announced by conference call -- "
    "not a regular meeting-day announcement.",
    date(2008, 10, 8): "Globally coordinated inter-meeting cut (with the ECB, BoE, and "
    "other central banks) -- not a regular meeting-day announcement.",
    date(2020, 3, 4): "COVID-19 emergency inter-meeting cut -- stored date is a proxy "
    "(effective-date artifact); true announcement date/time not established here.",
    date(2020, 3, 16): "COVID-19 emergency inter-meeting cut (announced Sunday, March 15, "
    "2020) -- stored date is a next-business-day proxy, not the true announcement date.",
}


def _resolve_usd(observation_period: UtcTimestamp) -> ReleaseTimingResolution | UnresolvedTiming:
    local_date = observation_period.value.date()
    if local_date in USD_IRREGULAR_DATES:
        return UnresolvedTiming(reason=USD_IRREGULAR_DATES[local_date])

    timing = USD_POLICY_TIMINGS.get(local_date)
    if timing is not None:
        # FX-44H.1: released_at comes from timing.decision_date (via the
        # shared time-of-day rule); effective_at comes from timing.
        # effective_at -- an INDEPENDENTLY populated fact, never derived
        # from observation_period/the stored proxy. See UsdPolicyTiming's
        # own docstring for why FX-44H's version of this conflated the
        # two for 2015-12-16 and 2016-12-14 specifically.
        return ReleaseTimingResolution(
            released_at=_USD_EXACT_DECISION_TIME_RULE.resolve(timing.decision_date),
            effective_at=_date_only_as_utc_midnight(timing.effective_date),
            confidence=ReleaseTimingConfidence.EXACT,
            citation=f"{timing.citation} ; {_USD_EXACT_DECISION_TIME_RULE.citation}",
        )

    if USD_CONSERVATIVE_RULE.covers(local_date):
        return ReleaseTimingResolution(
            released_at=USD_CONSERVATIVE_RULE.resolve(local_date),
            effective_at=None,
            confidence=USD_CONSERVATIVE_RULE.confidence,
            citation=USD_CONSERVATIVE_RULE.citation,
        )
    return UnresolvedTiming(
        reason="no FX-44/FX-44H/FX-44H.1 release-timing rule covers this date for USD"
    )


# ---------------------------------------------------------------------------
# GBP -- Bank of England (MPC), source=BOE_DATABASE
# ---------------------------------------------------------------------------
#
# Research finding: the Bank of England's MPC decision is consistently
# and uniformly described, across every source found (the Bank's own
# site and independent market/financial calendars), as announced at
# "12 noon" UK time -- with no evidence found of a different historical
# release time at any point since the MPC's creation. Unlike the Fed
# case above, no conflicting/varying-time evidence was found, so this
# story treats "12:00 Europe/London" as EXACT across the MPC's full
# history for regularly scheduled (Thursday) decisions.
GBP_RULES: tuple[ReleaseTimingRule, ...] = (
    ReleaseTimingRule(
        institution="Bank of England",
        local_time=time(12, 0, 0),
        timezone="Europe/London",
        confidence=ReleaseTimingConfidence.EXACT,
        applies_from=date(1997, 1, 1),
        applies_to=None,
        citation="https://www.bankofengland.co.uk/monetary-policy/the-interest-rate-bank-rate",
        notes=(
            "The Bank of England publishes the MPC's interest rate decision at 12 noon "
            "UK time on decision day -- consistently described this way with no "
            "contradicting historical evidence found."
        ),
    ),
)

GBP_IRREGULAR_DATES: dict[date, str] = {
    date(1997, 6, 2): "Predates the MPC's first meeting (5-6 June 1997) -- a transitional, "
    "pre-independence decision, not a regular MPC Thursday announcement.",
    date(1997, 6, 6): "The MPC's first-ever decision (5-6 June 1997 meeting) -- a Friday, "
    "not the MPC's standard Thursday pattern; not independently re-verified here.",
    date(1999, 9, 8): "A Wednesday, breaking the MPC's standard Thursday pattern -- not "
    "independently investigated in this story.",
    date(2001, 9, 18): "Globally coordinated response in the days after the September 11 "
    "attacks -- not a regular Thursday MPC announcement.",
    date(2008, 10, 8): "Globally coordinated inter-meeting cut (with the Fed, ECB, and "
    "other central banks) -- not a regular Thursday MPC announcement.",
    date(2020, 3, 11): "COVID-19 unscheduled emergency cut -- not a regular Thursday MPC "
    "announcement.",
}


def _resolve_gbp(observation_period: UtcTimestamp) -> ReleaseTimingResolution | UnresolvedTiming:
    local_date = observation_period.value.date()
    if local_date in GBP_IRREGULAR_DATES:
        return UnresolvedTiming(reason=GBP_IRREGULAR_DATES[local_date])
    for rule in GBP_RULES:
        if rule.covers(local_date):
            return ReleaseTimingResolution(
                released_at=rule.resolve(local_date),
                effective_at=None,  # Bank Rate changes take effect same-day as announced
                confidence=rule.confidence,
                citation=rule.citation,
            )
    return UnresolvedTiming(reason="no FX-44 release-timing rule covers this date for GBP")


# ---------------------------------------------------------------------------
# CAD -- Bank of Canada, source=BOC_VALET
# ---------------------------------------------------------------------------
#
# Research finding: the Bank of Canada's fixed-announcement-date system
# (introduced November 2000) began with 9:00am ET releases; current
# (2026) practice is 9:45am ET. Evidence found confirms 9:00am ET was
# still in use as late as October 2011, but the exact date the Bank
# shifted to 9:45am ET within our CAD data's actual range (2009-04-21
# onward, per FX-43H's documented gap) was not established. This
# story does not know, for a specific CAD change point, whether the
# stored date is the announcement date itself or a next-business-day
# effective-date proxy either. Both uncertainties resolve the same
# way: use a conservative end-of-day bound rather than an exact
# minute, which is safe (never earlier than the true release) under
# either time-of-day or either date interpretation.
CAD_RULES: tuple[ReleaseTimingRule, ...] = (
    ReleaseTimingRule(
        institution="Bank of Canada",
        local_time=time(23, 59, 59),
        timezone="America/Toronto",
        confidence=ReleaseTimingConfidence.CONSERVATIVE_SAFE_BOUND,
        applies_from=date(2009, 4, 21),
        applies_to=None,
        citation="https://www.bankofcanada.ca/2000/10/release-dates-bank-rate-actions/ ; "
        "https://www.canada.ca/en/news/archive/2011/10/bank-canada-interest-rate-announcement.html",
        notes=(
            "Fixed announcement dates release at 9:00am ET (introduced Nov 2000, still in "
            "use per an Oct 2011 press release) or 9:45am ET (current, 2026) depending on "
            "period -- the exact transition date within our data's range is not "
            "established, and it is not established whether the raw provider's stored "
            "date is the announcement date itself or a next-business-day effective proxy. "
            "End-of-day, Canada/Eastern, is a safe bound under every one of those "
            "possibilities."
        ),
    ),
)

CAD_IRREGULAR_DATES: dict[date, str] = {
    date(2020, 3, 4): "COVID-19 emergency action period (March 2020) -- not confidently "
    "distinguished here from the two unscheduled cuts below; excluded for consistency.",
    date(2020, 3, 16): "COVID-19 unscheduled emergency cut -- stored date is a proxy "
    "(likely next-business-day after a Friday, March 13, 2020 announcement); true "
    "announcement date/time not established here.",
    date(2020, 3, 27): "COVID-19 unscheduled emergency cut -- not a regular fixed "
    "announcement date.",
}


def _resolve_cad(observation_period: UtcTimestamp) -> ReleaseTimingResolution | UnresolvedTiming:
    local_date = observation_period.value.date()
    if local_date in CAD_IRREGULAR_DATES:
        return UnresolvedTiming(reason=CAD_IRREGULAR_DATES[local_date])
    for rule in CAD_RULES:
        if rule.covers(local_date):
            return ReleaseTimingResolution(
                released_at=rule.resolve(local_date),
                effective_at=None,
                confidence=rule.confidence,
                citation=rule.citation,
            )
    return UnresolvedTiming(reason="no FX-44 release-timing rule covers this date for CAD")


# ---------------------------------------------------------------------------
# EUR -- European Central Bank (Governing Council), source=ECB_SDW
# ---------------------------------------------------------------------------
#
# Research finding, confirmed against the actual ingested EUR change
# points (every stored date from 2006-03-08 onward is a Wednesday,
# with a single exception -- see below): the ECB's own published
# methodology states that, since 10 March 2004, "changes [to the MRO
# rate are] effective from the first main refinancing operation
# following the Governing Council decision" -- and the ECB's Governing
# Council has held its rate-setting meetings on Thursdays throughout
# this period, with the (weekly, at the time) MRO settling the
# following Wednesday. This means the DATE our raw provider series
# shows a value change (what FX-43 stored as the proxy `released_at`)
# is actually the EFFECTIVE date, six days AFTER the true announcement
# -- a genuine, documented announcement-before-effective-date split
# (FX-44 section 4), not merely an imprecise same-day proxy.
#
# The ECB also changed its OWN announcement time within this era.
# FX-44H: replaced the earlier secondary (investinglive.com/tweet)
# citations with the ECB's OWN official press release, "New times for
# ECB's monetary policy decisions and press conference"
# (https://www.ecb.europa.eu/press/pr/date/2022/html/
# ecb.pr220627~73acedf868.en.html, published 27 June 2022), which
# explicitly states: "Starting from 21 July, monetary policy decisions
# will be published at 14:15 CET (instead of 13:45)." This one
# primary document is authoritative for BOTH the old (13:45) and new
# (14:15) times below -- the ECB itself confirms 13:45 was the prior
# convention it is replacing.
#
# This rule is therefore only applied to change points confirmed to
# sit on this Wednesday pattern -- 2006-03-08 onward, with 2006-06-15
# excluded as a specific break in that pattern this story did not
# further investigate. Every EUR change point BEFORE 2006-03-08 uses a
# genuinely different, less-established procedural regime (the ECB's
# own page describes an earlier, PRE-10-March-2004 rule using
# different operational timing) and is left unresolved here rather
# than assuming the same six-day/Wednesday pattern applies.
#
# FX-44H hardening: the six-day transformation is a GENERALIZATION
# from a confirmed pattern, not a proven rule for every date that will
# ever be ingested -- so `_resolve_eur` structurally REQUIRES the
# stored date to actually BE a Wednesday before applying it (`weekday()
# == 2`), rather than relying solely on `EUR_IRREGULAR_DATES` to have
# already enumerated every possible exception. A future anomalous date
# this registry has not seen before (e.g. a new backfill run ingesting
# a genuinely irregular EUR change point) therefore fails closed
# automatically. `EUR_EXPLICIT_DECISION_DATE_OVERRIDES` is the ONLY
# way a non-Wednesday date may still resolve -- an explicit, individually
# researched and cited `date -> decision_date` entry, analogous to
# USD_POLICY_TIMINGS -- never a generic "subtract six days" fallback.
# Empty today: no non-Wednesday EUR date has been individually
# verified in this codebase yet.
_EUR_WEDNESDAY_ERA_START = date(2006, 3, 8)
_EUR_TIME_CHANGE_DECISION_DATE = date(2022, 7, 21)
_WEDNESDAY = 2  # date.weekday(): Monday=0 ... Wednesday=2 ... Sunday=6

_ECB_JUNE_2022_TIMING_CHANGE_CITATION = (
    "https://www.ecb.europa.eu/press/pr/date/2022/html/ecb.pr220627~73acedf868.en.html "
    '("New times for ECB\'s monetary policy decisions and press conference", '
    '27 June 2022: "Starting from 21 July, monetary policy decisions will be '
    'published at 14:15 CET (instead of 13:45).")'
)

EUR_RULES: tuple[ReleaseTimingRule, ...] = (
    ReleaseTimingRule(
        institution="European Central Bank",
        local_time=time(13, 45, 0),
        timezone="Europe/Brussels",
        confidence=ReleaseTimingConfidence.EXACT,
        applies_from=date(2004, 3, 10),
        applies_to=_EUR_TIME_CHANGE_DECISION_DATE,
        citation=_ECB_JUNE_2022_TIMING_CHANGE_CITATION,
        notes="ECB monetary policy decisions published at 13:45 CET, with the press "
        "conference at 14:30 CET, prior to the 21 July 2022 change (below) -- the "
        "\"instead of 13:45\" wording in the ECB's own release is this rule's citation "
        "for the OLD time, not just the new one.",
    ),
    ReleaseTimingRule(
        institution="European Central Bank",
        local_time=time(14, 15, 0),
        timezone="Europe/Brussels",
        confidence=ReleaseTimingConfidence.EXACT,
        applies_from=_EUR_TIME_CHANGE_DECISION_DATE,
        applies_to=None,
        citation=_ECB_JUNE_2022_TIMING_CHANGE_CITATION,
        notes="ECB monetary policy decisions published at 14:15 CET (press conference "
        "14:45 CET), from the 21 July 2022 decision onward.",
    ),
)

EUR_IRREGULAR_DATES: dict[date, str] = {
    date(1999, 1, 1): "The Euro/ECB's own inception rate, fixed in advance of the "
    "currency's 1 January 1999 launch -- not a Governing Council announcement event in "
    "the normal sense.",
    date(2005, 12, 6): "A Tuesday, breaking both the earlier (Friday) and later "
    "(Wednesday) effective-date patterns -- an apparent transition-period exception, "
    "not independently investigated in this story.",
    date(2006, 6, 15): "A Thursday, breaking the 2006-03-08-onward Wednesday "
    "effective-date pattern this story otherwise relies on -- not independently "
    "investigated.",
    date(2001, 9, 18): "Globally coordinated response in the days after the September "
    "11 attacks -- not a regular Governing Council decision.",
}

#: FX-44H: the ONLY sanctioned way a non-Wednesday EUR effective date
#: may still resolve -- each entry is an individually researched,
#: cited `stored_date -> decision_date` override. Empty today.
EUR_EXPLICIT_DECISION_DATE_OVERRIDES: dict[date, date] = {}


def _resolve_eur(observation_period: UtcTimestamp) -> ReleaseTimingResolution | UnresolvedTiming:
    stored_date = observation_period.value.date()
    if stored_date in EUR_IRREGULAR_DATES:
        return UnresolvedTiming(reason=EUR_IRREGULAR_DATES[stored_date])
    if stored_date < _EUR_WEDNESDAY_ERA_START:
        return UnresolvedTiming(
            reason=(
                "before the confirmed 2006-03-08 Wednesday-effective-date pattern -- "
                "this story does not extend the six-day announcement/effective offset "
                "to the ECB's earlier operational regime"
            )
        )

    override = EUR_EXPLICIT_DECISION_DATE_OVERRIDES.get(stored_date)
    if override is not None:
        decision_date = override
    elif stored_date.weekday() == _WEDNESDAY:
        decision_date = stored_date - _SIX_DAYS
    else:
        # FX-44H fail-closed: a date that does not fit the verified
        # Wednesday-effective pattern, and has no explicit override,
        # never gets the generic six-day transformation applied to it
        # -- including a future date this registry has never seen.
        return UnresolvedTiming(
            reason=(
                f"{stored_date.isoformat()} is not a Wednesday and has no explicit "
                "entry in EUR_EXPLICIT_DECISION_DATE_OVERRIDES -- refusing to apply "
                "the generic six-day announcement/effective transformation to an "
                "unverified date pattern"
            )
        )

    for rule in EUR_RULES:
        if rule.covers(decision_date):
            return ReleaseTimingResolution(
                released_at=rule.resolve(decision_date),
                # The stored proxy date IS the genuine effective date (the first MRO
                # operation following the decision) -- kept as-is, at midnight UTC,
                # consistent with how observation_period/the pre-FX-44 proxy already
                # represented "this calendar date" elsewhere in this codebase.
                effective_at=observation_period,
                confidence=rule.confidence,
                citation=rule.citation,
            )
    return UnresolvedTiming(reason="no FX-44 release-timing rule covers this decision date for EUR")


_RESOLVERS = {
    "USD": _resolve_usd,
    "EUR": _resolve_eur,
    "GBP": _resolve_gbp,
    "CAD": _resolve_cad,
}

#: Currencies FX-44 actually covers -- JPY is explicitly out of scope
#: (the story's own instruction), so it deliberately has no resolver.
SUPPORTED_CURRENCIES: frozenset[str] = frozenset(_RESOLVERS)


def resolve_release_timing(
    currency: str, observation_period: UtcTimestamp
) -> ReleaseTimingResolution | UnresolvedTiming:
    """The single entry point this story's use case calls per stored
    change point.

    Returns a `ReleaseTimingResolution` (ready to pass to `replace_
    provisional_release_timing`) when -- and only when -- a cited rule
    above genuinely covers this exact date; otherwise an
    `UnresolvedTiming` explaining why, so the caller leaves that
    vintage PROVISIONAL rather than guessing.

    Raises `ValueError` for a currency this story does not cover (JPY,
    or anything else) -- a programmer error, not a data-quality
    finding to report per-row.
    """
    resolver = _RESOLVERS.get(currency)
    if resolver is None:
        raise ValueError(
            f"currency {currency!r} is not covered by FX-44's release-timing registry "
            f"(supported: {sorted(SUPPORTED_CURRENCIES)})"
        )
    return resolver(observation_period)

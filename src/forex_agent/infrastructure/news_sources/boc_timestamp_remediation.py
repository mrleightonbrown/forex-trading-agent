"""FX-57F: dedicated, explicit remediation for the Bank of Canada's
own known-malformed `dc:date` defect.

**The defect (ADR 0005/FX-55H, live-reconfirmed 2026-10-10)**: the
press-releases feed's own `dc:date` presents America/Toronto LOCAL
wall-clock time, falsely labelled with a literal `+00:00` offset --
e.g. a 09:45 (ET) rate announcement appears as `2026-09-02T09:47:53
+00:00`, which, read literally as UTC, would place the release at
05:47 EDT -- hours before the Bank's own officially-published 09:45
(ET) announcement schedule, and before normal business hours.

**Live re-verification performed BEFORE writing this remediation**
(Section 22/23 -- this story's own explicit instruction not to
blindly preserve an old workaround): three live, directly-observed
2026 press releases, each an officially-scheduled "FAD" (Fixed
Announcement Date) interest-rate decision --

    2026-06-10 dc:date=2026-06-10T09:47:13+00:00
    2026-07-15 dc:date=2026-07-15T09:47:46+00:00
    2026-09-02 dc:date=2026-09-02T09:47:53+00:00

-- were cross-checked against the Bank's OWN officially-published
rate-announcement schedule (a separate, Bank-owned press release,
published months in advance:
`https://www.bankofcanada.ca/2025/08/bank-canada-publishes-2026-
schedule-policy-interest-rate-announcements-other-major-
publications/`), which states plainly: "All interest rate
announcements will take place at 09:45 (ET)," and separately lists
June 10, July 15, and September 2 as 2026's own scheduled dates. Every
one of the three live `dc:date` wall-clock values falls a few seconds
to a few minutes after 09:45 -- consistent with ordinary publishing
lag after a 09:45 ET release, and clearly impossible under the
literal `+00:00` reading. A FOURTH, winter-season (EST) anchor was
also confirmed via the SAME official schedule mechanism: January 28,
2026 is independently documented, by the Bank itself, as that year's
own January rate-announcement date, also at 09:45 (ET) -- the live
feed's own 10-item depth no longer reaches back to that date, so its
own raw `dc:date` string could not be directly re-observed, but the
OFFICIAL schedule confirms the SAME 09:45 (ET) policy applies across
both DST seasons, which is exactly what this module's own America/
Toronto-based (never hardcoded-offset) remediation is built to handle
correctly either way. The defect is RECONFIRMED, unchanged, and the
old workaround is correctly NOT obsolete.

**This result is SOURCE PROVENANCE ONLY (Section 20/37)**: a
remediated `normalized_at` here NEVER becomes FTA's own `observed_at`/
`availability` -- that remains the adapter's own response `retrieved_
at`, always, with no exception. This module performs no I/O and knows
nothing about `IngestNewsSourceOnce`/`RecordNewsObservation`.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from forex_agent.domain.timestamps import UtcTimestamp

_TORONTO = ZoneInfo("America/Toronto")

# The SPECIFIC, live-verified malformed shape this remediation
# targets -- a plain ISO-8601 local-looking timestamp (no fractional
# seconds observed live) suffixed with the literal, known-misleading
# "+00:00". Anything else is an UNRECOGNIZED shape (Section 30) and
# must never have this reinterpretation applied to it.
_MALFORMED_SHAPE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\+00:00$")

_CORRECTED_NOTE = (
    "Bank of Canada dc:date wall-clock reinterpreted as America/Toronto local time "
    "after source-specific, live-verified confirmation (ADR 0005/FX-55H, "
    "re-verified live for FX-57F against the Bank's own officially-published "
    "rate-announcement schedule); the source's own literal +00:00 offset is known "
    "to be misleading and is never treated as the true UTC instant"
)


@dataclass(frozen=True, slots=True)
class BocDcDateRemediation:
    """`normalized_at` is `None` whenever this remediation refuses to
    guess (an unrecognized offset shape, a malformed wall-clock
    portion, or an ambiguous/nonexistent America/Toronto local time)
    -- `normalization_note` always explains why, whether or not
    remediation succeeded."""

    normalized_at: UtcTimestamp | None
    normalization_note: str


def remediate_boc_dc_date(raw: str) -> BocDcDateRemediation:
    """Remediates ONE raw `dc:date` string. Never raises -- an
    unrecognized shape, a malformed wall-clock, or a DST-ambiguous/
    nonexistent local time all resolve to `normalized_at=None` with an
    explanatory note, exactly like every other FX-57 adapter's own
    fail-soft handling of an optional source timestamp (Section 29/
    30/31)."""
    stripped = raw.strip()
    match = _MALFORMED_SHAPE_RE.match(stripped)
    if match is None:
        return BocDcDateRemediation(
            normalized_at=None,
            normalization_note=(
                f"raw dc:date {stripped!r} does not match the specific, live-"
                "verified malformed shape (YYYY-MM-DDTHH:MM:SS+00:00) this "
                "remediation targets -- refusing to apply the old America/Toronto "
                "reinterpretation to an unrecognized or possibly-already-correct "
                "offset; this needs review, especially if the Bank of Canada has "
                "since fixed its own feed's timestamp semantics"
            ),
        )

    naive_part = match.group(1)
    try:
        naive_dt = datetime.fromisoformat(naive_part)
    except ValueError:
        return BocDcDateRemediation(
            normalized_at=None,
            normalization_note=(
                f"raw dc:date {stripped!r} carries the known +00:00 suffix but its "
                "own wall-clock portion did not parse as a valid date/time"
            ),
        )

    resolved = _resolve_toronto_local(naive_dt)
    if resolved is None:
        return BocDcDateRemediation(
            normalized_at=None,
            normalization_note=(
                f"raw dc:date {stripped!r} wall-clock {naive_part!r} is AMBIGUOUS "
                "or NONEXISTENT as an America/Toronto local time (a DST transition "
                "instant) -- refusing to guess which UTC instant was intended"
            ),
        )
    return BocDcDateRemediation(
        normalized_at=UtcTimestamp(resolved),
        normalization_note=_CORRECTED_NOTE,
    )


def _resolve_toronto_local(naive_dt: datetime) -> datetime | None:
    """Returns the correct UTC-aware instant for `naive_dt`
    interpreted as an America/Toronto wall-clock time, or `None` if
    that wall-clock instant is AMBIGUOUS (occurs twice, during the
    autumn DST fold-back) or NONEXISTENT (never occurs, during the
    spring DST gap) -- Section 29: never guessed via an arbitrary
    `fold=0`/`fold=1` choice. DST itself is resolved entirely by the
    `zoneinfo`/IANA database, never a hardcoded UTC offset
    (Section 25)."""
    fold0 = naive_dt.replace(tzinfo=_TORONTO, fold=0)
    fold1 = naive_dt.replace(tzinfo=_TORONTO, fold=1)
    if fold0.utcoffset() != fold1.utcoffset():
        return None  # Ambiguous: this wall-clock time occurs twice.

    utc_instant = fold0.astimezone(UTC)
    round_tripped = utc_instant.astimezone(_TORONTO).replace(tzinfo=None)
    if round_tripped != naive_dt:
        return None  # Nonexistent: this wall-clock time was skipped entirely.

    return utc_instant

from dataclasses import dataclass
from enum import Enum

from forex_agent.domain.timestamps import UtcTimestamp


class NewsSourceRevisionKind(Enum):
    """What kind of source-side revision event a `NewsSourceRevisionFact`
    describes (FX-56 Section 20) -- e.g. one entry of GOV.UK's own
    `change_history`. Deliberately provider-neutral: no GOV.UK-specific
    field names leak past this type."""

    UPDATE = "UPDATE"
    CORRECTION = "CORRECTION"
    WITHDRAWAL = "WITHDRAWAL"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class NewsSourceRevisionFact:
    """One structured fact from a source's own revision/correction
    history (FX-56 Section 20), e.g. one entry of GOV.UK's own
    `change_history`, or a BoC `Retract` flag.

    This is SOURCE-side history only -- it never fabricates an FTA
    vintage FTA did not itself observe (FX-56 Section 19: "correction
    history does not reconstruct unseen history"). A `NewsItemVintage`
    may carry zero, one, or several of these describing what the
    source ITSELF claims happened to an item, entirely independent of
    how many FTA-observed revisions that same item actually has.

    Fields:
        kind: what category of source-side event this is (see
            `NewsSourceRevisionKind`).
        source_timestamp: when the SOURCE claims this event happened,
            as a verified UTC instant, or `None` if the source's own
            timestamp for this event is absent/unverified. Never
            promoted to `NewsItemVintage.availability`.
        raw_timestamp: the source's own literal, unmodified timestamp
            string for this event, if supplied -- preserved
            independently of `source_timestamp` for the same reason
            `NewsSourceTimestampProvenance.raw_value` is (FX-56 Section
            21).
        note: free-form provenance, e.g. the source's own correction
            explanation text. `None` when the source supplied none.
    """

    kind: NewsSourceRevisionKind
    source_timestamp: UtcTimestamp | None = None
    raw_timestamp: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, NewsSourceRevisionKind):
            raise TypeError(
                f"kind must be a NewsSourceRevisionKind, got {type(self.kind).__name__}"
            )
        if self.source_timestamp is not None and not isinstance(
            self.source_timestamp, UtcTimestamp
        ):
            raise TypeError(
                "source_timestamp must be a UtcTimestamp or None, got "
                f"{type(self.source_timestamp).__name__}"
            )
        if self.raw_timestamp is not None and (
            not isinstance(self.raw_timestamp, str) or not self.raw_timestamp.strip()
        ):
            raise ValueError(
                f"raw_timestamp must be a non-empty string or None, got {self.raw_timestamp!r}"
            )
        if self.note is not None and (not isinstance(self.note, str) or not self.note.strip()):
            raise ValueError(f"note must be a non-empty string or None, got {self.note!r}")

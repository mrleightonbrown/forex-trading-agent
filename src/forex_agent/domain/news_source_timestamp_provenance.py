from dataclasses import dataclass

from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class NewsSourceTimestampProvenance:
    """One raw provider timestamp value, preserved exactly as
    transmitted, plus an optional normalized reinterpretation (FX-55H's
    own "raw provider timestamp/provenance" concept; FX-56 Section 21).

    Exists specifically for cases like the Bank of Canada's `dc:date`
    (ADR 0005): a feed field whose literal value is misleading --
    America/Toronto local time falsely labelled `+00:00` -- yet must
    remain queryable in its original, unmodified form even after a
    verified reinterpretation is also recorded, because the raw value
    is itself evidence of what the source actually transmitted (FX-56
    Section 21/53). `normalized_at`, when present, is ALWAYS source
    publication provenance -- never promoted to `NewsItemVintage.
    availability`, which remains FTA's own observation time regardless
    (FX-55H's own invariant; see that type's own docstring).

    Fields:
        field_name: which raw provider field this provenance describes
            (e.g. "dc:date", "pubDate") -- free-form, never branched on
            by domain logic.
        raw_value: the literal, unmodified string the source
            transmitted for this field. Never overwritten by a
            remediation (FX-56 Section 21) -- a remediation adds a
            `normalized_at`/`normalization_note` to this SAME object,
            it never replaces `raw_value`.
        normalized_at: a verified, remediated reinterpretation of
            `raw_value` as a true UTC instant, or `None` if no
            remediation has been established (FX-56 Section 51/52 --
            never fabricate one; `None` is the correct default for an
            absent, malformed, or date-only-precision source value).
        normalization_note: free-form human explanation of WHY
            `normalized_at` was (or, if `None`, was deliberately NOT)
            derived -- e.g. "raw `dc:date` carries America/Toronto
            local time mislabelled as +00:00; reinterpreted per ADR
            0005." `None` when no explanation has been recorded.
    """

    field_name: str
    raw_value: str
    normalized_at: UtcTimestamp | None = None
    normalization_note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.field_name, str) or not self.field_name.strip():
            raise ValueError(f"field_name must be a non-empty string, got {self.field_name!r}")
        if not isinstance(self.raw_value, str) or not self.raw_value.strip():
            raise ValueError(f"raw_value must be a non-empty string, got {self.raw_value!r}")
        if self.normalized_at is not None and not isinstance(self.normalized_at, UtcTimestamp):
            raise TypeError(
                "normalized_at must be a UtcTimestamp or None, got "
                f"{type(self.normalized_at).__name__}"
            )
        if self.normalization_note is not None and (
            not isinstance(self.normalization_note, str) or not self.normalization_note.strip()
        ):
            raise ValueError(
                "normalization_note must be a non-empty string or None, got "
                f"{self.normalization_note!r}"
            )

from dataclasses import dataclass

from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastClaim:
    """FX-64 Section 5: the minimal, durable identity of ONE coherent
    forecast assertion -- mirroring FX-62's own `IntelligenceSource`
    shape exactly (minimal, immutable, written once; everything that
    can evolve or be corrected lives on the append-only `Structured
    ForecastVintage` instead).

    `claim_key` is ALWAYS caller-supplied, built from stable, source-
    backed logical identifiers (Section 5's own explicit requirement)
    -- NEVER minted from the forecast VALUE alone (two forecasters
    predicting the same value are still two distinct claims), and
    NEVER silently invented when the source does not supply enough
    evidence to establish a stable identity (the capture-eligibility
    check, Section 11, rejects/quarantines that candidate instead). A
    revised prediction that is genuinely a NEW forecast issue (e.g. a
    later survey round) uses its OWN distinct `claim_key` -- this type
    has no "latest forecast wins" concept; see the module docstring of
    `application.use_cases.record_structured_forecast` for the full
    append-only/revision-vs-new-issue distinction."""

    claim_key: str
    registered_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.claim_key, str) or not self.claim_key.strip():
            raise ValueError(f"claim_key must be a non-empty string, got {self.claim_key!r}")
        if not isinstance(self.registered_at, UtcTimestamp):
            raise TypeError(
                f"registered_at must be a UtcTimestamp, got {type(self.registered_at).__name__}"
            )

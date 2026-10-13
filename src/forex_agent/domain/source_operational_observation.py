from dataclasses import dataclass

from forex_agent.domain.source_acquisition_outcome import SourceAcquisitionOutcome
from forex_agent.domain.source_operational_observation_kind import SourceOperationalObservationKind
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class SourceOperationalObservation:
    """FX-63: one immutable, append-only fact about ONE acquisition
    attempt FTA itself made against ONE technical feed -- NEVER a
    judgment about the publishing institution (Section 5 of the
    story). Mirrors `NewsItemVintage`'s own "one row per observed
    fact, never mutated" shape, but has no revision/correction concept
    of its own: each attempt is a genuinely distinct, independent
    event, not a revised view of an earlier one.

    `source_key` is ALWAYS the technical-feed identity FTA actually
    used to attempt retrieval (e.g. `"BOE"`), reusing FX-56/57's own
    `domain.news_source_registry` keys verbatim -- never the
    publishing organization's own FX-62 identity (e.g. `"BANK_OF_
    ENGLAND"`); see `SourceAcquisitionOutcome`'s own docstring for why
    this distinction is load-bearing. `run_id` identifies ONE logical
    acquisition run (one call to fetch one channel); `attempt_number`
    (1-based) distinguishes repeated attempts -- including internal
    retries -- WITHIN that same run, so a caller can always tell
    "logical run count" apart from "attempts within a run." The
    natural idempotency key is `(source_key, run_id, attempt_number)`
    -- grounded in a stable identifier, never merely `(source_key,
    availability)`, so a retried delivery of the SAME logical event
    collapses to a no-op rather than minting a duplicate (Section 6).

    `availability` is FTA's OWN observation instant for THIS exact
    attempt -- captured via the SAME injected clock `fetch_text`
    itself uses for a successful response's own `retrieved_at`, never
    a second, independent clock read (see `infrastructure.news_
    sources.http_fetch`'s own module docstring)."""

    source_key: str
    source_channel: str
    run_id: str
    attempt_number: int
    kind: SourceOperationalObservationKind
    outcome: SourceAcquisitionOutcome
    availability: UtcTimestamp
    http_status: int | None
    policy_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_key, str) or not self.source_key.strip():
            raise ValueError(f"source_key must be a non-empty string, got {self.source_key!r}")
        if not isinstance(self.source_channel, str) or not self.source_channel.strip():
            raise ValueError(
                f"source_channel must be a non-empty string, got {self.source_channel!r}"
            )
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError(f"run_id must be a non-empty string, got {self.run_id!r}")
        if not isinstance(self.attempt_number, int) or isinstance(self.attempt_number, bool):
            raise TypeError(
                f"attempt_number must be an int, got {type(self.attempt_number).__name__}"
            )
        if self.attempt_number < 1:
            raise ValueError(f"attempt_number must be >= 1, got {self.attempt_number}")
        if not isinstance(self.kind, SourceOperationalObservationKind):
            raise TypeError(
                f"kind must be a SourceOperationalObservationKind, got {type(self.kind).__name__}"
            )
        if not isinstance(self.outcome, SourceAcquisitionOutcome):
            raise TypeError(
                f"outcome must be a SourceAcquisitionOutcome, got {type(self.outcome).__name__}"
            )
        if not isinstance(self.availability, UtcTimestamp):
            raise TypeError(
                f"availability must be a UtcTimestamp, got {type(self.availability).__name__}"
            )
        if self.http_status is not None and (
            not isinstance(self.http_status, int)
            or isinstance(self.http_status, bool)
            or not (100 <= self.http_status <= 599)
        ):
            raise ValueError(
                f"http_status must be None or an int in [100, 599], got {self.http_status!r}"
            )
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError(
                f"policy_version must be a non-empty string, got {self.policy_version!r}"
            )

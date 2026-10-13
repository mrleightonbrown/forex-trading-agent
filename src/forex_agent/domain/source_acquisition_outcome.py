from enum import Enum


class SourceAcquisitionOutcome(Enum):
    """FX-63: what actually happened on ONE recorded acquisition
    attempt -- an FTA-observed fact about FTA's OWN retrieval, never a
    judgment about the publishing institution's own availability (see
    `SourceOperationalObservation`'s own docstring, Section 5 of the
    story). Deliberately limited to the four outcomes `infrastructure.
    news_sources.http_fetch.FetchAttemptOutcomeKind` can honestly
    distinguish today -- a content-validation or parsing failure is
    NOT a member here (this codebase cannot currently tell a parse
    failure apart from a transport failure after a successful fetch
    without guessing from a string message, which the story explicitly
    forbids); such a category is reserved for a future, finer-grained
    instrumentation story, never fabricated as a member whose real
    outcome this layer cannot actually observe."""

    SUCCESS = "SUCCESS"
    HTTP_FAILURE = "HTTP_FAILURE"
    TIMEOUT = "TIMEOUT"
    NETWORK_FAILURE = "NETWORK_FAILURE"

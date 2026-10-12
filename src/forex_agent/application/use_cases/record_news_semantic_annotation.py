"""FX-59: append-only recording of one semantic-classification result,
following `RecordNewsCanonicalRelation`'s own established shape
(Section 51) -- compare the latest stored state for an item, and only
append a new revision when the basis vintage or algorithm version
genuinely changes.

**Precedence, mirroring FX-56H.1/FX-58's own corrected lesson ("check
ordering FIRST, unconditionally, THEN check identity")**: PIT
ordering is checked before anything else. An incoming annotation whose
`availability` is EARLIER than the item's own latest recorded
annotation always raises `OutOfOrderSemanticAnnotationError` (Section
51) -- an earlier `availability` is itself an assertion about when FTA
ran this classification, and that assertion must be rejected
regardless of content. Equal `availability` is explicitly permitted.

**Section 53/54: a new basis revision OR a new algorithm version ALWAYS
mints a new annotation revision, even when the resulting classification
output is identical** -- the annotation must truthfully pin the EXACT
evidence/policy that was actually classified, never silently reuse an
earlier revision's own provenance for genuinely different evidence.

**Section 55: same basis + same algorithm + a DIFFERENT output is an
impossible state for a deterministic classifier, and is treated as an
error (`NewsSemanticDeterminismError`), never a silently-accepted new
revision** -- minting a revision here would misrepresent two outputs of
the SAME deterministic algorithm over the SAME evidence as both valid,
when at most one can be.

**Section 52: same basis + same algorithm + the SAME output is
UNCHANGED** -- idempotent, mints no new row.

The outcome returned always reflects the actual durable write, never
the pre-insert expectation (mirroring FX-58H Section 18's own
correction): `SemanticAnnotationWriteResult.inserted` is checked after
every real (non-dry-run) write."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.news_semantic_repository import NewsSemanticRepository
from forex_agent.domain.news_semantic_annotation_vintage import NewsSemanticAnnotationVintage
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification
from forex_agent.domain.timestamps import UtcTimestamp


class NewsSemanticAnnotationOutcome(Enum):
    """What `RecordNewsSemanticAnnotation` actually did for one item
    (FX-59 Section 52/53/54)."""

    CREATED = "CREATED"
    REVISION_ADDED = "REVISION_ADDED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True, slots=True)
class NewsSemanticAnnotationRecordResult:
    news_item_key: str
    outcome: NewsSemanticAnnotationOutcome
    annotation: NewsSemanticAnnotationVintage
    """The relevant annotation after this call: the newly-written one
    for `CREATED`/`REVISION_ADDED`, or the EXISTING one for
    `UNCHANGED`."""


class OutOfOrderSemanticAnnotationError(Exception):
    """Raised when an incoming semantic annotation claims an
    `availability` earlier than the item's own latest recorded
    annotation (FX-59 Section 51) -- refusing to append a backdated
    classification, regardless of whether its own content would
    otherwise be a no-op change."""

    def __init__(
        self,
        news_item_key: str,
        latest_availability: UtcTimestamp,
        incoming_availability: UtcTimestamp,
    ) -> None:
        self.news_item_key = news_item_key
        self.latest_availability = latest_availability
        self.incoming_availability = incoming_availability
        super().__init__(
            f"semantic annotation for news_item_key={news_item_key!r} claims availability="
            f"{incoming_availability.value.isoformat()}, earlier than the latest recorded "
            f"annotation's own availability={latest_availability.value.isoformat()} -- "
            "refusing to append a backdated classification"
        )


class NewsSemanticDeterminismError(Exception):
    """Raised when the SAME basis revision, classified under the SAME
    `algorithm_version`, produces a DIFFERENT classification output
    than what is already stored (FX-59 Section 55) -- this should be
    impossible for a deterministic classifier; never minted as a new
    revision, since that would misrepresent two results as both being
    valid outputs of the same deterministic algorithm over the same
    evidence."""

    def __init__(
        self,
        news_item_key: str,
        basis_news_item_revision_sequence: int,
        algorithm_version: str,
        existing: NewsSemanticClassification,
        incoming: NewsSemanticClassification,
    ) -> None:
        self.news_item_key = news_item_key
        self.basis_news_item_revision_sequence = basis_news_item_revision_sequence
        self.algorithm_version = algorithm_version
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            f"news_item_key={news_item_key!r}, basis_news_item_revision_sequence="
            f"{basis_news_item_revision_sequence}, algorithm_version={algorithm_version!r} "
            f"already produced a DIFFERENT classification: existing={existing!r}, "
            f"incoming={incoming!r} -- a deterministic classifier must never produce two "
            "different outputs for the same evidence and the same algorithm version"
        )


class RecordNewsSemanticAnnotation:
    """FX-59's own append-only semantic-annotation-recording use case
    -- see the module docstring."""

    def __init__(self, repository: NewsSemanticRepository) -> None:
        self._repository = repository

    async def __call__(
        self,
        news_item_key: str,
        basis_news_item_revision_sequence: int,
        availability: UtcTimestamp,
        classification: NewsSemanticClassification,
        algorithm_version: str,
        *,
        dry_run: bool = False,
    ) -> NewsSemanticAnnotationRecordResult:
        """`dry_run=True` (FX-59 Section 64) computes and returns the
        EXACT SAME outcome/annotation a real call would, using the
        EXACT SAME decision logic below, but never calls `self._
        repository.add_annotation_vintage`."""
        latest = await self._repository.latest_annotation_for_item(news_item_key)

        if latest is None:
            created = NewsSemanticAnnotationVintage(
                news_item_key=news_item_key,
                revision_sequence=0,
                availability=availability,
                basis_news_item_revision_sequence=basis_news_item_revision_sequence,
                algorithm_version=algorithm_version,
                classification=classification,
            )
            if dry_run:
                return NewsSemanticAnnotationRecordResult(
                    news_item_key, NewsSemanticAnnotationOutcome.CREATED, created
                )
            write_result = await self._repository.add_annotation_vintage(created)
            outcome = (
                NewsSemanticAnnotationOutcome.CREATED
                if write_result.inserted
                else NewsSemanticAnnotationOutcome.UNCHANGED
            )
            return NewsSemanticAnnotationRecordResult(news_item_key, outcome, created)

        if availability.value < latest.availability.value:
            raise OutOfOrderSemanticAnnotationError(
                news_item_key, latest.availability, availability
            )

        if (
            latest.basis_news_item_revision_sequence == basis_news_item_revision_sequence
            and latest.algorithm_version == algorithm_version
        ):
            if latest.classification == classification:
                # Section 52: idempotent re-classification of the SAME
                # evidence under the SAME policy.
                return NewsSemanticAnnotationRecordResult(
                    news_item_key, NewsSemanticAnnotationOutcome.UNCHANGED, latest
                )
            raise NewsSemanticDeterminismError(
                news_item_key,
                basis_news_item_revision_sequence,
                algorithm_version,
                latest.classification,
                classification,
            )

        # Section 53/54: the basis revision and/or algorithm_version
        # changed -- always a new revision, even if the resulting
        # classification output happens to be identical.
        revised = NewsSemanticAnnotationVintage(
            news_item_key=news_item_key,
            revision_sequence=latest.revision_sequence + 1,
            availability=availability,
            basis_news_item_revision_sequence=basis_news_item_revision_sequence,
            algorithm_version=algorithm_version,
            classification=classification,
        )
        if dry_run:
            return NewsSemanticAnnotationRecordResult(
                news_item_key, NewsSemanticAnnotationOutcome.REVISION_ADDED, revised
            )
        write_result = await self._repository.add_annotation_vintage(revised)
        outcome = (
            NewsSemanticAnnotationOutcome.REVISION_ADDED
            if write_result.inserted
            else NewsSemanticAnnotationOutcome.UNCHANGED
        )
        return NewsSemanticAnnotationRecordResult(news_item_key, outcome, revised)

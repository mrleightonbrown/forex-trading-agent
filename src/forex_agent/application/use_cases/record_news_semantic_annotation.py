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

**Section 55 (FX-59H correction): same basis + same algorithm + a
DIFFERENT output is an impossible state for a deterministic
classifier, and is treated as an error (`NewsSemanticDeterminismError`)
-- enforced across this item's ENTIRE stored annotation history, not
merely against whichever row happens to be currently latest.** A
deterministic pair `(basis_news_item_revision_sequence, algorithm_
version)` must never be associated with two different classification
payloads anywhere in an item's history, even if an intervening
revision (a different basis, or a different algorithm_version) has
since become the latest row. FX-59's own original implementation
checked this invariant ONLY against the latest row, which missed the
case where an OLDER algorithm_version becomes current again later
(e.g. `fx59_v1` -> `fx59_v2` -> `fx59_v1`): the historical `fx59_v1`
row proves what `fx59_v1` must deterministically produce, and a
later `fx59_v1` re-classification producing a DIFFERENT output must
still raise, even though the item's own LATEST row at that moment is
a `fx59_v2` row, not a `fx59_v1` one. Minting a revision here would
misrepresent two outputs of the SAME deterministic algorithm over the
SAME evidence as both valid, when at most one can be.

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
    than SOME ALREADY-STORED row for that exact `(basis_news_item_
    revision_sequence, algorithm_version)` pair -- checked against the
    item's ENTIRE stored annotation history (FX-59H), not merely
    whichever row happens to be currently latest, since an older
    algorithm_version can legitimately become current again later
    (e.g. `fx59_v1` -> `fx59_v2` -> `fx59_v1`) while a stale, different
    output for that same old pair would otherwise slip past a latest-
    only check. This should be impossible for a deterministic
    classifier; never minted as a new revision, since that would
    misrepresent two results as both being valid outputs of the same
    deterministic algorithm over the same evidence."""

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
        repository.add_annotation_vintage`.

        **FX-59H conceptual ordering (Section 3), enforced exactly in
        this order**: (1) fetch the item's current latest annotation;
        (2) PIT ordering FIRST, unconditionally -- an incoming
        `availability` earlier than the latest's own is rejected
        regardless of content; (3) the historical determinism
        invariant, checked against the item's ENTIRE stored history,
        not merely whichever row is currently latest (Section 2); (4)
        normal idempotency/revision logic; (5) persist if required."""
        latest = await self._repository.latest_annotation_for_item(news_item_key)

        if latest is not None and availability.value < latest.availability.value:
            raise OutOfOrderSemanticAnnotationError(
                news_item_key, latest.availability, availability
            )

        # FX-59H Section 2/6: the deterministic key is exactly
        # (news_item_key, basis_news_item_revision_sequence,
        # algorithm_version) -- a basis change or an algorithm_version
        # change is a genuinely different input, so it never
        # participates in this check (Section 6's own basis0+v1 vs
        # basis1+v1 example). Checked against EVERY historical row,
        # not only the current latest one, so an older algorithm_
        # version becoming current again later (e.g. fx59_v1 ->
        # fx59_v2 -> fx59_v1) cannot slip a different output past this
        # guard merely because the latest row at that moment is a
        # fx59_v2 one.
        history = await self._repository.list_annotation_vintages_for_item(news_item_key)
        for historical in history:
            if (
                historical.basis_news_item_revision_sequence == basis_news_item_revision_sequence
                and historical.algorithm_version == algorithm_version
                and historical.classification != classification
            ):
                raise NewsSemanticDeterminismError(
                    news_item_key,
                    basis_news_item_revision_sequence,
                    algorithm_version,
                    historical.classification,
                    classification,
                )

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

        if (
            latest.basis_news_item_revision_sequence == basis_news_item_revision_sequence
            and latest.algorithm_version == algorithm_version
        ):
            # Section 52: idempotent re-classification of the SAME
            # evidence under the SAME policy -- the historical check
            # above already proved `classification == latest.
            # classification` here (`latest` is itself part of that
            # same history), so this can never be a determinism
            # violation reaching this point.
            return NewsSemanticAnnotationRecordResult(
                news_item_key, NewsSemanticAnnotationOutcome.UNCHANGED, latest
            )

        # Section 53/54: the basis revision and/or algorithm_version
        # changed RELATIVE TO THE CURRENT LATEST ROW -- always a new
        # revision, even if the resulting classification output
        # happens to be identical to the latest row's own output, and
        # even when an OLDER historical row already recorded this
        # exact (basis, algorithm) pair (already proven consistent
        # above): FTA is genuinely recording that this basis/policy
        # combination is current again (FX-59H Section 4's own worked
        # example -- fx59_v1(A) -> fx59_v2(B) -> fx59_v1(A) is
        # REVISION_ADDED, never UNCHANGED, because the old v1 row is
        # no longer the item's own latest state).
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

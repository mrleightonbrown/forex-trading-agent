from dataclasses import dataclass

from forex_agent.domain._guards import require_revision_sequence
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_revision_fact import NewsSourceRevisionFact
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.news_source_timestamp_provenance import NewsSourceTimestampProvenance
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class NewsItemVintage:
    """One immutable, point-in-time-safe fact: "as of `availability`,
    FTA knew `news_item_key`'s content/state to be exactly this" (FX-56
    Section 12/13).

    Same immutable-fact-per-row shape as every FX-51 economic-event
    vintage and `MacroObservationVintage` before it: a headline edit, a
    body-text correction, a withdrawal, or a quarantine-status change
    is a NEW vintage with a higher `revision_sequence`, never a
    mutation of an earlier one (FX-56 Section 13/15) -- there is no
    repository method anywhere in this codebase that UPDATEs a stored
    vintage row.

    `availability` is ALWAYS FTA's own observation time for THIS EXACT
    revision -- never any source-supplied timestamp, remediated or
    raw, however well-documented (FX-55H's own invariant, extended to
    the revision level here -- see FX-56 Section 6/18/48). Unlike
    `EconomicEventScheduleVintage.availability`, this field is never
    `None`/`UNKNOWN`: a `NewsItemVintage` is only ever constructed from
    an actual FTA observation (prospective) or an explicit backfill
    import, both of which always have a concrete, known FTA instant --
    there is no "we don't know when FTA could have known this" case
    for a type that exists ONLY because FTA observed something.

    For `revision_sequence == 0`, `availability` equals the owning
    `NewsItem.first_seen_at` by construction (FX-56 Section 33).

    Fields:
        news_item_key: the `NewsItem.news_item_key` this vintage
            belongs to.
        revision_sequence: 0 for the first FTA-observed state of this
            item, incrementing for each subsequent FTA-observed change.
            Never a provider's own revision/version number (FX-56
            Section 14) -- those are preserved, if supplied, inside
            `source_revision_metadata` instead.
        availability: FTA's own observation time of THIS exact
            revision (see class docstring).
        observation_mode: whether this revision was observed
            prospectively or via a (currently unused) historical
            backfill (`domain.news_observation_mode.
            NewsObservationMode`).
        headline: the item's headline/title as FTA observed it.
            Required, non-empty -- every adopted source supplies one.
        summary: a short summary/snippet, if the source supplies one.
        body_text: full article body text, if the source supplies one
            -- `None` is expected and normal; FX-56 never fetches a
            linked page to invent one (Section 16).
        canonical_url: the source's own canonical URL for this item at
            observation time, if known. A revision field/provenance
            field, never canonical identity (FX-56 Section 37) -- a
            later URL change is simply a new revision of the SAME
            item, never a new one.
        authors: source-supplied author/speaker names, as descriptive
            provenance only (FX-56 Section 39) -- never assigned a
            credibility/reputation/accuracy score anywhere in this
            codebase.
        language: the source's own stated language code, if supplied.
        source_content_type: a free-form, source-supplied content-type
            discriminator (e.g. "press_release"/"speech"/"minutes"/
            "interview") for a source whose single feed serves several
            types at once, such as ECB's own `pr`/`sp`/`in` URL-slug
            discriminator (ADR 0005). Free-form, not enforced against
            a fixed vocabulary -- the same convention as `Economic
            IndicatorDefinition.unit`.
        source_published_at: when the SOURCE ITSELF claims this
            revision was published, as a verified UTC instant, if
            established -- SOURCE provenance only, NEVER promoted to
            `availability` (FX-56 Section 17; FX-55H's own invariant).
            May legitimately be earlier than `availability` (FX-56
            Section 17's own worked example) -- that is expected, not
            an error.
        source_updated_at: when the SOURCE ITSELF claims this revision
            was last updated, if established -- same provenance-only
            status as `source_published_at` (FX-56 Section 18). A
            source update at time U does not make a new revision
            visible before FTA's own `availability` for that revision,
            however much earlier U is.
        source_timestamp_provenance: raw provider timestamp values
            underlying this revision, preserved exactly as transmitted
            (see `NewsSourceTimestampProvenance`) -- e.g. BoC's raw,
            mislabelled `dc:date` string, independent of any remediated
            reinterpretation of it.
        source_revision_metadata: structured source-side revision/
            correction/withdrawal facts known as of this FTA
            observation (see `NewsSourceRevisionFact`) -- e.g. GOV.UK's
            own `change_history` entries. Describes what the SOURCE
            says happened, never fabricates an FTA-observed revision
            that did not occur (FX-56 Section 19/49).
        source_status: the source's own claimed lifecycle status AS OF
            this revision (`domain.news_source_status.
            NewsSourceStatus`) -- `WITHDRAWN` only on positive source
            evidence, never inferred from absence (FX-56 Section 23/24).
        evidence_disposition: whether THIS revision may be returned by
            an evidence-eligible PIT query (`domain.
            news_evidence_disposition.NewsEvidenceDisposition`) --
            independent of `source_status` (FX-56 Section 65).
        quarantine_reason: required, non-empty, if and only if
            `evidence_disposition` is `QUARANTINED` (enforced below,
            mirroring `domain._guards.require_availability_consistency`'s
            own mutual-exclusivity discipline) -- `None` whenever
            `evidence_disposition` is `EVIDENCE_ELIGIBLE`.
    """

    news_item_key: str
    revision_sequence: int
    availability: UtcTimestamp
    observation_mode: NewsObservationMode
    headline: str
    source_status: NewsSourceStatus
    evidence_disposition: NewsEvidenceDisposition
    summary: str | None = None
    body_text: str | None = None
    canonical_url: str | None = None
    authors: tuple[str, ...] = ()
    language: str | None = None
    source_content_type: str | None = None
    source_published_at: UtcTimestamp | None = None
    source_updated_at: UtcTimestamp | None = None
    source_timestamp_provenance: tuple[NewsSourceTimestampProvenance, ...] = ()
    source_revision_metadata: tuple[NewsSourceRevisionFact, ...] = ()
    quarantine_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.news_item_key, str) or not self.news_item_key.strip():
            raise ValueError(
                f"news_item_key must be a non-empty string, got {self.news_item_key!r}"
            )
        require_revision_sequence(self.revision_sequence)
        if not isinstance(self.availability, UtcTimestamp):
            raise TypeError(
                f"availability must be a UtcTimestamp, got {type(self.availability).__name__}"
            )
        if not isinstance(self.observation_mode, NewsObservationMode):
            raise TypeError(
                f"observation_mode must be a NewsObservationMode, got "
                f"{type(self.observation_mode).__name__}"
            )
        if not isinstance(self.headline, str) or not self.headline.strip():
            raise ValueError(f"headline must be a non-empty string, got {self.headline!r}")
        for optional_text_field in (
            self.summary,
            self.body_text,
            self.canonical_url,
            self.language,
            self.source_content_type,
        ):
            if optional_text_field is not None and not isinstance(optional_text_field, str):
                raise TypeError(
                    f"optional text fields must be str or None, got {type(optional_text_field)!r}"
                )
        if not isinstance(self.authors, tuple):
            raise TypeError(f"authors must be a tuple, got {type(self.authors).__name__}")
        for author in self.authors:
            if not isinstance(author, str) or not author.strip():
                raise ValueError(f"each author must be a non-empty string, got {author!r}")
        for timestamp_field in (self.source_published_at, self.source_updated_at):
            if timestamp_field is not None and not isinstance(timestamp_field, UtcTimestamp):
                raise TypeError(
                    "source_published_at/source_updated_at must be a UtcTimestamp or None, "
                    f"got {type(timestamp_field).__name__}"
                )
        if not isinstance(self.source_timestamp_provenance, tuple):
            raise TypeError(
                "source_timestamp_provenance must be a tuple, got "
                f"{type(self.source_timestamp_provenance).__name__}"
            )
        for provenance in self.source_timestamp_provenance:
            if not isinstance(provenance, NewsSourceTimestampProvenance):
                raise TypeError(
                    "each source_timestamp_provenance entry must be a "
                    f"NewsSourceTimestampProvenance, got {type(provenance).__name__}"
                )
        if not isinstance(self.source_revision_metadata, tuple):
            raise TypeError(
                "source_revision_metadata must be a tuple, got "
                f"{type(self.source_revision_metadata).__name__}"
            )
        for revision_fact in self.source_revision_metadata:
            if not isinstance(revision_fact, NewsSourceRevisionFact):
                raise TypeError(
                    "each source_revision_metadata entry must be a NewsSourceRevisionFact, "
                    f"got {type(revision_fact).__name__}"
                )
        if not isinstance(self.source_status, NewsSourceStatus):
            raise TypeError(
                f"source_status must be a NewsSourceStatus, got {type(self.source_status).__name__}"
            )
        if not isinstance(self.evidence_disposition, NewsEvidenceDisposition):
            raise TypeError(
                "evidence_disposition must be a NewsEvidenceDisposition, got "
                f"{type(self.evidence_disposition).__name__}"
            )
        is_quarantined = self.evidence_disposition is NewsEvidenceDisposition.QUARANTINED
        if is_quarantined and (
            self.quarantine_reason is None
            or not isinstance(self.quarantine_reason, str)
            or not self.quarantine_reason.strip()
        ):
            raise ValueError(
                "quarantine_reason must be a non-empty string when evidence_disposition is "
                "QUARANTINED -- a quarantined revision must always say why"
            )
        if not is_quarantined and self.quarantine_reason is not None:
            raise ValueError(
                "quarantine_reason must be None when evidence_disposition is "
                "EVIDENCE_ELIGIBLE -- an eligible revision must never carry a quarantine reason"
            )

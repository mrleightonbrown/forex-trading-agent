from dataclasses import dataclass

from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class NewsItem:
    """FTA's own internal, provider-neutral identity for one source
    news item (FX-56 Section 3/8) -- e.g. one Federal Reserve press
    release, one GOV.UK news story.

    `news_item_key` alone is identity -- a stable, caller-assigned,
    provider-neutral identifier (see `domain.news_item_identity.
    mint_news_item_key`), deliberately NOT derived from any source's
    own external ID, URL, or timestamp. The association between a
    `domain.news_source_identity.NewsSourceIdentity` and the
    `news_item_key` it resolves to is tracked by a persisted mapping
    (`application.ports.news_repository.NewsRepository.
    register_source_item`), mirroring FX-52AH's own occurrence-
    identity correction for economic events -- except FX-56's own
    registration is atomic by construction (see that port's own
    docstring), which FX-52A/FX-52AH's own two-step mint-then-map
    design was not.

    `first_seen_at` is the single most important field on this type:
    it is ALWAYS FTA's own observation time -- the instant FTA's own
    ingestion process first retrieved this exact source item -- NEVER
    any source-supplied publication timestamp, however well-documented
    or verifiable that source timestamp is (FX-55H's own "FTA
    availability invariant," extended here to item-level identity).
    Immutable forever once set: no code path in this codebase ever
    updates it after the item's first registration.

    Fields:
        news_item_key: this item's own stable internal identity (see
            above).
        first_seen_at: FTA's own observation time of this item's
            EARLIEST known revision -- equal to `NewsItemVintage.
            availability` for the vintage with `revision_sequence ==
            0` of this same item, by construction.
        first_observation_mode: whether that earliest observation was
            genuinely prospective or a (currently unused) historical
            backfill (`domain.news_observation_mode.
            NewsObservationMode`) -- preserved at the item level
            because it describes a one-time fact about how this item
            ENTERED FTA's own record, never revised afterward, exactly
            like `first_seen_at` itself.
    """

    news_item_key: str
    first_seen_at: UtcTimestamp
    first_observation_mode: NewsObservationMode

    def __post_init__(self) -> None:
        if not isinstance(self.news_item_key, str) or not self.news_item_key.strip():
            raise ValueError(
                f"news_item_key must be a non-empty string, got {self.news_item_key!r}"
            )
        if not isinstance(self.first_seen_at, UtcTimestamp):
            raise TypeError(
                f"first_seen_at must be a UtcTimestamp, got {type(self.first_seen_at).__name__}"
            )
        if not isinstance(self.first_observation_mode, NewsObservationMode):
            raise TypeError(
                "first_observation_mode must be a NewsObservationMode, got "
                f"{type(self.first_observation_mode).__name__}"
            )

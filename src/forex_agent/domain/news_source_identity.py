from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NewsSourceIdentity:
    """The external identity of one source item: `(source_key,
    external_item_id)` (FX-56 Section 8/37).

    This pair is FTA's own canonical EXTERNAL identity for a source
    item -- never a URL, never any timestamp (FX-56 Section 8
    explicitly forbids both: a URL can change out from under a stable
    provider ID, and a timestamp is not an identity at all). `source_
    key` identifies the admitted feed/institution (see `domain.
    news_source_registry`); `external_item_id` is that source's own
    stable per-item identifier (an RSS/Atom `guid`, a content API's own
    UUID, ...), opaque to this codebase.

    Deliberately NOT the same object as the internal `NewsItem.
    news_item_key` it resolves to (FX-56 Section 9/36): two different
    `NewsSourceIdentity` values -- even from entirely different
    `source_key`s describing what looks like the same real-world story
    -- always resolve to two SEPARATE `NewsItem`s. FX-56 models one
    SOURCE ITEM, never a real-world story; cross-source clustering is
    FX-58's job, not this type's.
    """

    source_key: str
    external_item_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_key, str) or not self.source_key.strip():
            raise ValueError(f"source_key must be a non-empty string, got {self.source_key!r}")
        if not isinstance(self.external_item_id, str) or not self.external_item_id.strip():
            raise ValueError(
                f"external_item_id must be a non-empty string, got {self.external_item_id!r}"
            )

"""Mints FTA's own internal `NewsItem.news_item_key` (FX-56).

Mirrors `domain.economic_calendar_occurrence_identity.
mint_occurrence_key` exactly, for the identical reason: a genuinely
provider-neutral internal identity must never be derived from, or
equal to, any source's own external identifier, URL, or timestamp
(FX-56 Section 8).
"""

from uuid import uuid4


def mint_news_item_key(source_key: str) -> str:
    """A fresh, genuinely provider-neutral internal `news_item_key`
    for a NEW news item first observed via `source_key`. The
    `source_key` prefix is for human debugging only (grep-ability in
    logs/DB browsing); nothing in this codebase parses a
    `news_item_key` back apart, and the SAME real-world item reported
    by a different source gets its OWN, separate `news_item_key`
    (FX-56 Section 9) -- `source_key` here only ever describes which
    source FIRST caused FTA to mint this key, not an ongoing
    relationship. Call this to produce a CANDIDATE key for a
    registration attempt; `NewsRepository.register_source_item`'s own
    atomic registration decides whether that candidate actually
    becomes the durable identity or is discarded in favour of an
    already-existing one (see that port's own docstring)."""
    if not source_key.strip():
        raise ValueError(f"source_key must be non-empty, got {source_key!r}")
    return f"{source_key}:{uuid4()}"

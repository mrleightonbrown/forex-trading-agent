"""FX-63: a minimal in-memory fake satisfying `GetSourceOperational
ProfileAsOf`'s own narrow `_ContentLookup` Protocol -- NOT a fake of
the full `NewsRepository` port (see `tests/fakes/` for those); this
only ever needs to answer "which items belong to source_key" and
"give me every vintage for these items," exactly the two methods that
Protocol declares."""

from collections import defaultdict

from forex_agent.domain.news_item_vintage import NewsItemVintage


class FakeNewsContentLookup:
    def __init__(self) -> None:
        self._vintages_by_item: dict[str, list[NewsItemVintage]] = defaultdict(list)
        self._item_keys_by_source: dict[str, list[str]] = defaultdict(list)

    def add_item(self, source_key: str, news_item_key: str) -> None:
        if news_item_key not in self._item_keys_by_source[source_key]:
            self._item_keys_by_source[source_key].append(news_item_key)

    def add_vintage(self, source_key: str, vintage: NewsItemVintage) -> None:
        self.add_item(source_key, vintage.news_item_key)
        self._vintages_by_item[vintage.news_item_key].append(vintage)

    async def list_item_keys_for_source(self, source_key: str) -> tuple[str, ...]:
        return tuple(self._item_keys_by_source.get(source_key, ()))

    async def list_vintages_for_items(
        self, news_item_keys: tuple[str, ...]
    ) -> dict[str, tuple[NewsItemVintage, ...]]:
        return {
            key: tuple(self._vintages_by_item.get(key, ()))
            for key in news_item_keys
            if key in self._vintages_by_item
        }

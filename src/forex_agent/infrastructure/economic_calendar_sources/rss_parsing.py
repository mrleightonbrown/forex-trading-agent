"""Minimal, dependency-free RSS 2.0 / RDF-RSS-1.0 `<item>` parser
(FX-52A).

Uses only `xml.etree.ElementTree` (stdlib) -- no `feedparser`
dependency, matching this project's existing preference for a small,
auditable, purpose-built parser over a general-purpose third-party
library (mirrors `ics_parsing`'s own reasoning). Handles exactly the
two real shapes this story's four RSS sources actually produce,
confirmed directly against each live feed:

- RSS 2.0 (ONS, Federal Reserve, Bank of England): `<guid>`, `<title>`,
  `<pubDate>` (RFC 822/2822), `<link>`.
- RDF/RSS 1.0 (Bank of Canada press releases -- the CBWiki "Central
  Bank RSS" schema): `<item rdf:about="...">` (the item's own URI,
  used as its guid), `<title>`, `<dc:date>` (ISO 8601 with an explicit
  UTC offset), `<link>`.

`pub_date` is parsed via `email.utils.parsedate_to_datetime` for RSS
2.0 or `datetime.fromisoformat` for RDF's `dc:date` -- never assumed
to be UTC without checking the string's own offset (FX-52A Section 32:
"Do not assume RSS `pubDate` is the scheduled event time. It may only
be when the feed item was published." -- this parser deliberately
returns `pub_date` under that literal, feed-neutral name, never
`scheduled_*`; each adapter decides what it MEANS for its own specific
feed).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

_RDF_ABOUT_ATTR = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
_DC_DATE_TAG = "{http://purl.org/dc/elements/1.1/}date"


@dataclass(frozen=True, slots=True)
class RssItem:
    guid: str
    title: str
    pub_date: datetime
    link: str


def parse_rss_items(text: str) -> tuple[RssItem, ...]:
    """Every `<item>` in `text` with a parseable date -- an item
    missing an identity (`guid` or `rdf:about`), `title`, or a
    parseable date entirely is omitted (partial-coverage-over-
    invented-certainty, the same discipline `ics_parsing.
    parse_ics_events` applies at per-event granularity)."""
    root = ElementTree.fromstring(text)
    items: list[RssItem] = []
    for item_element in root.iter():
        if _local_name(item_element.tag) != "item":
            continue
        item = _parse_one_item(item_element)
        if item is not None:
            items.append(item)
    return tuple(items)


def _local_name(tag: str) -> str:
    # RDF/RSS 1.0 puts every element in a default namespace (e.g.
    # "http://purl.org/rss/1.0/"), so a bare `.iter("item")`/`.find("title")`
    # never matches -- ElementTree renders a namespaced tag as
    # "{namespace-uri}localname"; strip that prefix so both RSS 2.0
    # (no default namespace) and RDF/RSS 1.0 items/children resolve the
    # same way.
    return tag.rsplit("}", 1)[-1]


def _parse_one_item(item_element: ElementTree.Element) -> RssItem | None:
    guid = _text_of(item_element, "guid") or item_element.get(_RDF_ABOUT_ATTR)
    title = _text_of(item_element, "title")
    link = _text_of(item_element, "link")
    if guid is None or title is None:
        return None

    pub_date = _parse_rss2_pub_date(item_element) or _parse_dc_date(item_element)
    if pub_date is None:
        return None
    return RssItem(guid=guid, title=title, pub_date=pub_date.astimezone(UTC), link=link or "")


def _parse_rss2_pub_date(item_element: ElementTree.Element) -> datetime | None:
    raw = _text_of(item_element, "pubDate")
    if raw is None:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _parse_dc_date(item_element: ElementTree.Element) -> datetime | None:
    child = item_element.find(_DC_DATE_TAG)
    if child is None or child.text is None:
        return None
    try:
        parsed = datetime.fromisoformat(child.text.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _text_of(element: ElementTree.Element, tag: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == tag and child.text is not None:
            return child.text.strip()
    return None

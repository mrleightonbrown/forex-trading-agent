"""Minimal, dependency-free RSS 2.0 / RDF-RSS-1.0 `<item>` parser
(FX-52A; fail-closed/observability hardened by FX-52AH).

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
  UTC offset), `<link>`, and optionally `<cb:news><cb:occurrenceDate>`
  (a date-only field this schema defines specifically for "when the
  underlying event/announcement itself occurred," distinct from
  `dc:date`'s own, less specific "date of the resource").

`pub_date` is parsed via `email.utils.parsedate_to_datetime` for RSS
2.0 or `datetime.fromisoformat` for RDF's `dc:date` -- never assumed
to be UTC without checking the string's own offset (FX-52A Section 32:
"Do not assume RSS `pubDate` is the scheduled event time. It may only
be when the feed item was published." -- this parser deliberately
returns `pub_date` under that literal, feed-neutral name, never
`scheduled_*`/`released_*`; each adapter decides what it MEANS for its
own specific feed -- see `boc_release_source`'s own docstring for why
FX-52AH stopped treating it as an exact release time).

FX-52AH: a response that does not parse as XML at all, or parses but
whose root element is not a recognized RSS/RDF root, now raises
`MalformedFeedError` rather than silently returning zero items
indistinguishable from a genuinely empty, well-formed feed. An
individual item missing required fields is still merely counted and
skipped (`RssParseResult.invalid_count`), not escalated to a whole-feed
failure -- the same event-granularity-vs-document-granularity
distinction `ics_parsing` now applies.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

_RDF_ABOUT_ATTR = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
_DC_DATE_TAG = "{http://purl.org/dc/elements/1.1/}date"
_CB_NS = "http://www.cbwiki.net/wiki/index.php/Specification_1.2/"
_CB_NEWS_TAG = f"{{{_CB_NS}}}news"
_CB_OCCURRENCE_DATE_TAG = f"{{{_CB_NS}}}occurrenceDate"
_RECOGNIZED_ROOT_LOCAL_NAMES = frozenset({"rss", "RDF", "feed"})


class MalformedFeedError(ValueError):
    """Raised when `text` is not a recognizable RSS/RDF document at
    all (FX-52AH) -- e.g. an HTML error page or unrelated content
    returned with an HTTP 200. Distinct from a genuinely empty,
    well-formed feed (a valid root element with zero `<item>`s), which
    is a valid, non-error result. A caller must treat this as a source
    failure, never as "nothing was published.\""""


@dataclass(frozen=True, slots=True)
class RssItem:
    guid: str
    title: str
    pub_date: datetime
    link: str
    occurrence_date: date | None = None


@dataclass(frozen=True, slots=True)
class RssParseResult:
    items: tuple[RssItem, ...]
    invalid_count: int


def parse_rss_items(text: str) -> RssParseResult:
    """Every `<item>` in `text`, plus a count of items skipped for
    missing an identity/title/parseable date. Raises `MalformedFeedError`
    if `text` does not parse as XML, or parses but its root element is
    not a recognized RSS/RDF/Atom root -- see the module docstring."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise MalformedFeedError(f"text does not parse as XML: {exc}") from exc
    if _local_name(root.tag) not in _RECOGNIZED_ROOT_LOCAL_NAMES:
        raise MalformedFeedError(f"root element {root.tag!r} is not a recognized RSS/RDF/Atom root")

    items: list[RssItem] = []
    invalid_count = 0
    for item_element in root.iter():
        if _local_name(item_element.tag) != "item":
            continue
        item = _parse_one_item(item_element)
        if item is None:
            invalid_count += 1
        else:
            items.append(item)
    return RssParseResult(items=tuple(items), invalid_count=invalid_count)


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
    return RssItem(
        guid=guid,
        title=title,
        pub_date=pub_date.astimezone(UTC),
        link=link or "",
        occurrence_date=_parse_occurrence_date(item_element),
    )


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


def _parse_occurrence_date(item_element: ElementTree.Element) -> date | None:
    news = item_element.find(_CB_NEWS_TAG)
    if news is None:
        return None
    child = news.find(_CB_OCCURRENCE_DATE_TAG)
    if child is None or child.text is None:
        return None
    try:
        return date.fromisoformat(child.text.strip())
    except ValueError:
        return None


def _text_of(element: ElementTree.Element, tag: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == tag and child.text is not None:
            return child.text.strip()
    return None

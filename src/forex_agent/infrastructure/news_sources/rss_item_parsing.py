"""FX-57A: a dedicated, minimal RSS 2.0 `<item>` parser for NEWS
evidence -- deliberately NOT a reuse of `economic_calendar_sources.
rss_parsing.parse_rss_items`, because that parser's own item-validity
rule (guid AND title AND a successfully-parsed `pubDate`, else the
WHOLE item is invalid) is wrong for news: a news item's `pubDate` is
source PROVENANCE, never FTA availability (FX-57A Section 3/18), so a
malformed/implausible `pubDate` never invalidates an otherwise-
good item. Reuses only the structural technique (ElementTree,
namespace-local-name stripping, fail-closed root-element validation)
from that module, not its functions.

Shared across every RSS-based news adapter (Fed now; ECB/BoE are also
confirmed RSS 2.0 per ADR 0005, so this is a genuinely reusable piece
for FX-57B/C, not a speculative one) -- nothing here is Fed-specific.

**FX-57AH Section 3: this parses RSS ONLY, never Atom.** An earlier
version of this module also accepted an Atom `<feed>` root as
"recognized" while only ever extracting RSS `<item>` elements -- an
Atom document's own `<entry>` elements were silently ignored, so a
real Atom feed was misread as a valid, empty RSS response (fail-open
silent data loss). The root element must now be exactly `rss`, AND
that root must contain a `<channel>` child (the RSS 2.0 structural
container) -- an RSS root with no `<channel>` at all is malformed, not
a valid empty feed. Statistics Canada's Atom Daily feeds (FX-57E) will
get their own, separate Atom parser when that story is authorized;
this module is never extended to understand Atom.

**The sentinel-pubDate finding (live evidence, FX-57A Section 55)**:
the Federal Reserve's own `testimony.xml` feed contains items whose
`pubDate` is the literal, syntactically-valid-but-impossible value
`"Sat, 30 Dec 1899 ..."` -- almost certainly a CMS default for an
empty date field, NOT a parse failure (`email.utils.parsedate_to_
datetime` parses it without raising). A plausibility floor beyond
ordinary parsing is required to catch this: any parsed `pubDate` with
`year < 1900` is treated as a provider-side sentinel, not a genuine
timestamp -- the raw string is still preserved, but `pub_date` is
`None` with `pub_date_issue` explaining why. `1900` is a generic,
provider-neutral floor (no RSS feed from any adopted FX-EPIC-08 source
genuinely publishes pre-20th-century news), not a Fed-only constant.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

_RSS_ROOT_LOCAL_NAME = "rss"
_SENTINEL_YEAR_FLOOR = 1900


class MalformedNewsFeedError(ValueError):
    """Raised when `text` is not a recognizable RSS document at all --
    bad XML, a parseable document whose root is not `rss` (e.g. an
    Atom `<feed>`, or an HTML WAF/error page returned with HTTP 200),
    or an `<rss>` root with no `<channel>` child at all. Distinct from
    a genuinely empty, well-formed feed (`<rss><channel/></rss>`, zero
    `<item>`s), which is a valid, non-error result (FX-57A Section
    25/26)."""


@dataclass(frozen=True, slots=True)
class NewsRssItem:
    """One `<item>`, exactly as the feed expressed it -- `pub_date`/
    `pub_date_issue` are mutually informative, never both meaningful
    at once: `pub_date` is set when `raw_pub_date` parsed to a
    plausible instant; `pub_date_issue` is set (and `pub_date` is
    `None`) when `raw_pub_date` was present but unusable; both are
    `None` only when the item had no `pubDate` element at all."""

    guid: str
    title: str
    link: str | None
    description: str | None
    raw_pub_date: str | None
    pub_date: datetime | None
    pub_date_issue: str | None


@dataclass(frozen=True, slots=True)
class NewsRssParseResult:
    items: tuple[NewsRssItem, ...]
    invalid_count: int
    invalid_reasons: tuple[str, ...]


def parse_news_rss_items(text: str) -> NewsRssParseResult:
    """Every `<item>` in `text`. An item is invalid ONLY for a missing/
    blank `guid` or `title` (FX-57A Section 3/26 -- identity and
    headline are the sole hard requirements); a missing, malformed, or
    implausible `pubDate` never invalidates an item. Raises
    `MalformedNewsFeedError` if `text` does not parse as XML, its root
    is not exactly `rss` (this parser is RSS-only -- an Atom `<feed>`
    fails closed here, never silently read as an empty RSS response),
    or that `<rss>` root has no `<channel>` child at all."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise MalformedNewsFeedError(f"text does not parse as XML: {exc}") from exc
    if _local_name(root.tag) != _RSS_ROOT_LOCAL_NAME:
        raise MalformedNewsFeedError(
            f"root element {root.tag!r} is not an RSS root (expected 'rss' -- this "
            "parser is RSS-only and never reads an Atom <feed> as a valid response)"
        )
    if not any(_local_name(child.tag) == "channel" for child in root):
        raise MalformedNewsFeedError("<rss> root has no <channel> child -- malformed RSS")

    items: list[NewsRssItem] = []
    invalid_reasons: list[str] = []
    for index, item_element in enumerate(
        element for element in root.iter() if _local_name(element.tag) == "item"
    ):
        item, reason = _parse_one_item(item_element)
        if item is None:
            invalid_reasons.append(f"item at index {index}: {reason}")
        else:
            items.append(item)
    return NewsRssParseResult(
        items=tuple(items),
        invalid_count=len(invalid_reasons),
        invalid_reasons=tuple(invalid_reasons),
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_one_item(item_element: ElementTree.Element) -> tuple[NewsRssItem | None, str | None]:
    guid = _text_of(item_element, "guid")
    if guid is None:
        return None, "missing or blank guid"
    title = _text_of(item_element, "title")
    if title is None:
        return None, "missing or blank title"

    raw_pub_date = _text_of(item_element, "pubDate")
    pub_date, pub_date_issue = _parse_pub_date(raw_pub_date)
    return (
        NewsRssItem(
            guid=guid,
            title=title,
            link=_text_of(item_element, "link"),
            description=_text_of(item_element, "description"),
            raw_pub_date=raw_pub_date,
            pub_date=pub_date,
            pub_date_issue=pub_date_issue,
        ),
        None,
    )


def _parse_pub_date(raw_pub_date: str | None) -> tuple[datetime | None, str | None]:
    if raw_pub_date is None:
        return None, None
    try:
        parsed = parsedate_to_datetime(raw_pub_date)
    except (TypeError, ValueError) as exc:
        return None, f"pubDate did not parse as RFC-822/2822: {exc}"
    if parsed.tzinfo is None:
        return None, "pubDate parsed but carried no timezone"
    if parsed.year < _SENTINEL_YEAR_FLOOR:
        return None, (
            f"pubDate parsed to year {parsed.year}, below the {_SENTINEL_YEAR_FLOOR} "
            "plausibility floor -- treated as a provider-side sentinel/placeholder "
            "value, not a genuine timestamp"
        )
    return parsed.astimezone(UTC), None


def _text_of(element: ElementTree.Element, tag: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == tag and child.text is not None:
            stripped = child.text.strip()
            if stripped:
                return stripped
    return None

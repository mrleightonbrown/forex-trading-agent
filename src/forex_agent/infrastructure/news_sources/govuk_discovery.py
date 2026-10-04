"""FX-57D: a dedicated, minimal Atom DISCOVERY parser for the GOV.UK
"News and communications from HM Treasury" feed.

**This is NOT a general Atom evidence parser.** Its only
responsibility is to extract currently-visible `gov.uk` content paths
worth hydrating through the Content API -- it does not, and must
not, become the source of any stored news evidence itself (ADR 0005:
the Atom feed exposes only `updated`, never `published`, and no
identity, body, or correction history -- insufficient alone). The
existing RSS-only parser (`rss_item_parsing.py`) was deliberately
hardened (FX-57BH) to REJECT Atom; this module does not touch it, and
is not reused by it. FX-57E's own future Statistics Canada adapter
will need its own, separate Atom EVIDENCE parser -- this module is
deliberately not generalized to anticipate that; it only discovers
GOV.UK paths.

**Discovery vs. hydration (FX-57D Section 5/8)**: an entry here
supplies a `path` to hydrate through the Content API, plus `updated`/
`title` purely as discovery-level DIAGNOSTICS -- never promoted to
`NormalizedNewsObservation` fields. The Content API response for that
path is the sole source of actual stored evidence.

**Deduplication within one discovery response (Section 13)**: an
identical repeated path collapses to one entry; the SAME path
appearing twice with a DIFFERING `updated` value fails the whole
discovery result closed (`MalformedGovUkDiscoveryFeedError`) rather
than guessing which one is current -- there is no legitimate reason
for one Atom response to disagree with itself about the same path.

**Path validation (Section 52)**: only `https://www.gov.uk/...`
content links are followed; an external host, an asset host, a
`javascript:`/`data:` URL, an empty link, or a malformed path is
rejected as an invalid discovery entry (counted, never silently
dropped with no trace).
"""

from dataclasses import dataclass
from urllib.parse import urlparse
from xml.etree import ElementTree

_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_GOVUK_HOST = "www.gov.uk"


class MalformedGovUkDiscoveryFeedError(ValueError):
    """Raised when the discovery response is not a recognizable Atom
    feed at all (bad XML, wrong root, an HTML error page masquerading
    as a 200), or when the SAME path appears twice within one
    response with a DIFFERING `updated` value -- fails the whole
    discovery result closed rather than guessing. Distinct from a
    genuinely empty, well-formed feed (valid `<feed>` root, zero
    `<entry>` elements), which is a valid, non-error result."""


@dataclass(frozen=True, slots=True)
class GovUkDiscoveryEntry:
    """One discovered GOV.UK content path, plus discovery-level
    diagnostics only -- `updated_raw`/`title` are NEVER promoted to
    any `NormalizedNewsObservation` field; the Content API response
    for `path` is the sole authoritative evidence source."""

    path: str
    entry_id: str
    updated_raw: str | None
    title: str | None


@dataclass(frozen=True, slots=True)
class GovUkDiscoveryParseResult:
    entries: tuple[GovUkDiscoveryEntry, ...]
    invalid_count: int
    invalid_reasons: tuple[str, ...]


def parse_govuk_discovery_atom(text: str) -> GovUkDiscoveryParseResult:
    """Every usable `<entry>` in `text`. Raises `MalformedGovUkDiscov
    eryFeedError` if `text` does not parse as XML, its root is not an
    Atom `feed`, or the same path appears twice with conflicting
    `updated` values. An entry is invalid (counted, not raising) for
    a missing/blank `id`, a missing/off-domain/malformed content
    link, or a missing/blank `title`."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise MalformedGovUkDiscoveryFeedError(f"text does not parse as XML: {exc}") from exc
    if root.tag != f"{_ATOM_NS}feed":
        raise MalformedGovUkDiscoveryFeedError(
            f"root element {root.tag!r} is not an Atom feed root (expected '{{{_ATOM_NS[1:-1]}}}"
            "feed')"
        )

    entries: list[GovUkDiscoveryEntry] = []
    invalid_reasons: list[str] = []
    by_path: dict[str, GovUkDiscoveryEntry] = {}

    for index, entry_element in enumerate(root.findall(f"{_ATOM_NS}entry")):
        entry, reason = _parse_one_entry(entry_element)
        if entry is None:
            invalid_reasons.append(f"entry at index {index}: {reason}")
            continue

        existing = by_path.get(entry.path)
        if existing is None:
            by_path[entry.path] = entry
            entries.append(entry)
            continue
        if existing.updated_raw == entry.updated_raw:
            continue  # identical repeat of the same path -- dedupe silently
        raise MalformedGovUkDiscoveryFeedError(
            f"path {entry.path!r} appears twice in the same discovery response with "
            f"differing updated values ({existing.updated_raw!r} vs {entry.updated_raw!r}) "
            "-- refusing to guess which is current"
        )

    return GovUkDiscoveryParseResult(
        entries=tuple(entries),
        invalid_count=len(invalid_reasons),
        invalid_reasons=tuple(invalid_reasons),
    )


def _parse_one_entry(
    entry_element: ElementTree.Element,
) -> tuple[GovUkDiscoveryEntry | None, str | None]:
    entry_id = _text_of(entry_element, "id")
    if entry_id is None:
        return None, "missing or blank id"

    title = _text_of(entry_element, "title")
    if title is None:
        return None, "missing or blank title"

    link_href = None
    for child in entry_element.findall(f"{_ATOM_NS}link"):
        if child.get("rel") in (None, "alternate"):
            link_href = child.get("href")
            break
    path = _validate_govuk_path(link_href)
    if path is None:
        return None, f"missing, off-domain, or malformed content link: {link_href!r}"

    updated_raw = _text_of(entry_element, "updated")
    return GovUkDiscoveryEntry(
        path=path, entry_id=entry_id, updated_raw=updated_raw, title=title
    ), None


def _validate_govuk_path(href: str | None) -> str | None:
    if href is None or not href.strip():
        return None
    parsed = urlparse(href.strip())
    if parsed.scheme != "https" or parsed.netloc != _GOVUK_HOST:
        return None
    if not parsed.path or not parsed.path.startswith("/"):
        return None
    return parsed.path


def _text_of(element: ElementTree.Element, tag: str) -> str | None:
    child = element.find(f"{_ATOM_NS}{tag}")
    if child is None or child.text is None:
        return None
    stripped = child.text.strip()
    return stripped or None

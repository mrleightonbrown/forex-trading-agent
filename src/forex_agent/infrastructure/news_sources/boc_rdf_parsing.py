"""FX-57F: a dedicated, minimal RSS 1.0/RDF evidence parser for the
Bank of Canada's own "Press Releases" feed.

**Deliberately NOT a reuse of `rss_item_parsing.py`** (Section 8):
live research confirmed this feed is structurally a DIFFERENT dialect
entirely -- RSS 1.0/RDF (root `<rdf:RDF>`, items namespaced under
`http://purl.org/rss/1.0/`, using the RSS-CB 1.2 central-bank
extension for a `<cb:news>` block), not RSS 2.0's `<rss><channel>
<item>` shape every prior FX-57 RSS adapter (Fed/ECB/BoE) actually
uses. Broadening the shared RSS parser to also accept RDF would mean
teaching it a second document model merely to accommodate one source
-- provider syntax belongs at the adapter boundary, not in the common
parser.

**Live-verified feed shape (2026-10-10, `https://www.bankofcanada.ca/
content_type/press-releases/feed/`)**: root `<rdf:RDF>`; one `<channel
rdf:about="...">` (feed-level metadata only, never promoted to item
provenance); each release is a SIBLING `<item rdf:about="<canonical-
URL>">` of `<channel>`, not nested inside it. `rdf:about` on `<item>`
IS the provider's own identity -- live-confirmed to always equal that
same item's own `<link>` text exactly, though the two are parsed from
genuinely separate fields here (Section 10), never assumed equal by
construction. Fields observed on every sampled item: `<title>` (plain
text), `<link>`, `<description>` (a short snippet), `<dc:date>` (the
known-malformed timestamp -- see `boc_timestamp_remediation.py`),
`<dc:language>` (`"en"`), and a `<cb:news>` block (`cb:simpleTitle`
duplicating `<title>`, `cb:occurrenceDate` a DATE ONLY, no time) --
this module does not read `<cb:news>` at all, since nothing in it adds
information beyond what `<title>`/`<dc:date>` already supply, and
`source_content_type` is deliberately kept at the fixed, non-semantic
`"press_release"` regardless of `cb:news`'s own `rdf:type` value
(Section 9). No `<guid>`, `dc:creator`, or `content:encoded` was ever
found live -- `authors` stays `()` and `body_text` stays `None`
unconditionally.

**No internal duplicate-identity handling here (by design)**: exactly
like `rss_item_parsing.py`/`statcan_atom_parsing.py`, this parser
returns every valid entry as-is; same-identity dedupe-or-conflict
remains the COMMON `IngestNewsSourceOnce` layer's own job, applied
uniformly.

**FX-57FH hardening**: `dc:date` is raw SOURCE provenance (see
`boc_timestamp_remediation.py`) and is now extracted via `_raw_text_
of`, which preserves the exact XML element text with no `.strip()`
normalization -- every other field (`title`/`link`/`description`/
`dc:language`) keeps the ordinary `_text_of` trimming, since the
strict raw-preservation contract applies only to the one field this
story found a live-remediation need for. `dc:language` is also now
parsed and validated, not silently hardcoded by the adapter: every
live-sampled item on this adopted English feed carries `dc:language=
"en"`, pinned here as an exact, narrow shape check (`_EXPECTED_
LANGUAGE`) -- a missing, blank, or unexpected value (e.g. a French
feed's own `"fr"`) is an item-level invalid, never silently accepted
or language-detected."""

from dataclasses import dataclass
from urllib.parse import urlparse
from xml.etree import ElementTree

_RDF_NS = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
_RSS1_NS = "{http://purl.org/rss/1.0/}"
_DC_NS = "{http://purl.org/dc/elements/1.1/}"
_BOC_HOST = "www.bankofcanada.ca"
_EXPECTED_LANGUAGE = "en"


class MalformedBocFeedError(ValueError):
    """Raised when a Bank of Canada feed response is not a
    recognizable RSS 1.0/RDF document at all (bad XML, wrong root, an
    HTML error page masquerading as a 200, an RSS 2.0/Atom document
    where RDF was expected). Distinct from a genuinely empty,
    well-formed feed (valid `<rdf:RDF>` root, zero `<item>` elements),
    which is a valid, non-error result, and distinct from an ordinary
    item-level invalid entry (missing id/title/link), which is counted
    via `invalid_count`, never raised."""


@dataclass(frozen=True, slots=True)
class BocPressReleaseEntry:
    """One validated press-release RDF `<item>`. `entry_id` is the
    provider's own `rdf:about` attribute value, used as-is for
    identity -- never reconstructed from `canonical_url`/`dc_date_raw`/
    title, even though, for every entry accepted here, `entry_id` and
    `canonical_url` happen to be the identical string (live-confirmed:
    `rdf:about` and `<link>` always coincide for this source's own
    items). `dc_date_raw` preserves the exact `<dc:date>` element text
    with no `.strip()` normalization (FX-57FH Section 5) -- unlike
    every other field here, which is ordinarily trimmed. `language`
    is the parsed, validated `<dc:language>` value -- always `"en"`
    for an entry accepted by this parser (FX-57FH Section 7); never
    hardcoded by a caller."""

    entry_id: str
    title: str
    canonical_url: str
    dc_date_raw: str | None
    summary: str | None
    language: str


@dataclass(frozen=True, slots=True)
class BocFeedParseResult:
    entries: tuple[BocPressReleaseEntry, ...]
    invalid_count: int
    invalid_reasons: tuple[str, ...]


def parse_boc_press_releases_rdf(text: str) -> BocFeedParseResult:
    """Every usable press-release `<item>` in `text`. Raises
    `MalformedBocFeedError` if `text` does not parse as XML or its
    root is not an RDF root. An entry is invalid (counted, not
    raising) for a missing/blank `rdf:about` identity, a missing/
    off-host/malformed `<link>`, a missing/blank `<title>`, or a
    missing/blank/unexpected `<dc:language>` (FX-57FH: this adopted
    feed is pinned to exactly `"en"`, never language-detected). A
    missing `<dc:date>` is NOT an item-level invalidity (Section 31) --
    it simply means no source publication provenance is available for
    that entry."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise MalformedBocFeedError(f"text does not parse as XML: {exc}") from exc
    if root.tag != f"{_RDF_NS}RDF":
        raise MalformedBocFeedError(
            f"root element {root.tag!r} is not an RDF root (expected '{{{_RDF_NS[1:-1]}}}RDF')"
        )

    entries: list[BocPressReleaseEntry] = []
    invalid_reasons: list[str] = []

    for index, item_element in enumerate(root.findall(f"{_RSS1_NS}item")):
        entry, reason = _parse_one_item(item_element)
        if entry is None:
            invalid_reasons.append(f"entry at index {index}: {reason}")
            continue
        entries.append(entry)

    return BocFeedParseResult(
        entries=tuple(entries),
        invalid_count=len(invalid_reasons),
        invalid_reasons=tuple(invalid_reasons),
    )


def _parse_one_item(
    item_element: ElementTree.Element,
) -> tuple[BocPressReleaseEntry | None, str | None]:
    entry_id_raw = item_element.get(f"{_RDF_NS}about")
    if entry_id_raw is None or not entry_id_raw.strip():
        return None, "missing or blank rdf:about identity"
    entry_id = entry_id_raw.strip()

    link_raw = _text_of(item_element, f"{_RSS1_NS}link")
    canonical_url = _validate_boc_url(link_raw)
    if canonical_url is None:
        return None, f"missing, off-host, or malformed canonical link: {link_raw!r}"

    title = _text_of(item_element, f"{_RSS1_NS}title")
    if title is None:
        return None, "missing or blank title"

    language = _text_of(item_element, f"{_DC_NS}language")
    if language is None:
        return None, "missing or blank dc:language"
    if language != _EXPECTED_LANGUAGE:
        return (
            None,
            f"unexpected dc:language {language!r} -- this adopted endpoint is pinned to "
            f"{_EXPECTED_LANGUAGE!r} only; a different value is out of this story's own "
            "adopted scope, not language-detected or silently accepted",
        )

    summary = _text_of(item_element, f"{_RSS1_NS}description")
    dc_date_raw = _raw_text_of(item_element, f"{_DC_NS}date")

    return (
        BocPressReleaseEntry(
            entry_id=entry_id,
            title=title,
            canonical_url=canonical_url,
            dc_date_raw=dc_date_raw,
            summary=summary,
            language=language,
        ),
        None,
    )


def _validate_boc_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    stripped = value.strip()
    parsed = urlparse(stripped)
    if parsed.scheme != "https" or parsed.netloc != _BOC_HOST:
        return None
    if not parsed.path or not parsed.path.startswith("/"):
        return None
    return stripped


def _text_of(element: ElementTree.Element, tag: str) -> str | None:
    child = element.find(tag)
    if child is None or child.text is None:
        return None
    stripped = child.text.strip()
    return stripped or None


def _raw_text_of(element: ElementTree.Element, tag: str) -> str | None:
    """Like `_text_of`, but preserves the exact XML element text with
    NO `.strip()` normalization (FX-57FH Section 5) -- `dc:date` is
    raw source provenance and must be stored byte-for-byte as the
    provider supplied it. Only a genuinely missing element (or one
    with no text content at all) collapses to `None`; a present-but-
    whitespace-only value is returned as-is, not treated as absent."""
    child = element.find(tag)
    if child is None or child.text is None:
        return None
    return child.text

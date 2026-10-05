"""FX-57E: a dedicated, minimal Atom EVIDENCE parser for Statistics
Canada's "The Daily" subject feeds.

**This is FTA's first source where Atom itself IS the evidence
surface** -- unlike GOV.UK's own Atom feed (`govuk_discovery.py`),
which is deliberately diagnostics/discovery-only and models no
evidence at all; that module is never reused here. Also deliberately
NOT a reuse of `rss_item_parsing.py`, which is RSS-only by design
(hardened against Atom by FX-57BH). This module owns Atom evidence
parsing for StatCan ONLY -- a future source needing its own Atom
evidence parser (none currently planned) would get its own module,
exactly like every other FX-57 adapter's own dedicated parser.

**Daily-release articles vs recurring product/catalogue references
(live finding, FX-57E research)**: alongside genuine dated "Daily
release" article entries -- whose `<id>` (and `<link>`) are a
`https://www.statcan.gc.ca/daily-quotidien/<YYMMDD>/dq<YYMMDD><letter
(s)>-eng.htm` URL -- three of the four adopted feeds also recur a
SEPARATE kind of entry: a static StatCan "Product/Study" catalogue
reference (e.g. `.../cgi-bin/IPS/display?cat_num=14200001`) that gets
RE-ANNOUNCED with a fresh `<updated>` value every time The Daily
mentions it again, while its own `<id>`/link stay byte-for-byte
identical across every re-announcement (live-confirmed: 7/21/14
repeats of the exact same id in the Labour/Economic-accounts/
International-trade feeds respectively, every single repeat carrying
a DIFFERENT `<updated>` value, zero repeats ever observed among
genuine dq-shaped article ids). Treating this as ordinary Daily
evidence would make the SAME external identity legitimately recur
with a genuinely DIFFERING `source_published_at` on almost every
poll -- not a correction to one article, but a structurally different
kind of content than "The Daily" release bulletin this story adopts.
This parser therefore validates every entry's own `<id>` (not merely
its link) against the Daily-release content-path shape and marks
anything else item-level invalid (counted via `invalid_count`, never
raised as a response-level error, never silently ingested) -- a
narrow, adapter-local content-shape filter, not a change to any
common identity/dedup contract. This also directly satisfies this
story's own Section 26 instruction to validate the canonical link
against "the expected Daily content path shape."

**FX-57EH: the known catalogue-reference exclusion is now its OWN
narrow, exact recognizer, never a loose catch-all.** The ORIGINAL
FX-57E parser treated "any id that fails the Daily-release URL
contract" as presumptively this catalogue-reference noise, which
meant a genuinely NEW, unrecognized non-Daily shape (real source-
schema drift) would silently receive the SAME "likely a recurring
catalogue reference" diagnostic as the live-verified known case --
precisely the kind of drift a `live_source` test exists to catch, but
could not, if it only pattern-matched the word "catalogue" in that
diagnostic string. `is_known_catalogue_reference_id` below is the
EXACT, narrow, live-verified shape check
(`https://www.statcan.gc.ca/cgi-bin/IPS/display?cat_num=<value>`,
confirmed live across every sampled recurrence) -- exported so a
`live_source` test can independently re-verify the SAME contract
this parser itself enforces, never by matching against this parser's
own prose. An id that is neither a Daily-release article NOR this
exact catalogue-reference shape now gets a genuinely DIFFERENT
diagnostic ("unexpected non-Daily StatCan entry id shape"), so a
truly novel non-Daily shape fails any `live_source` assertion built
on this function, loudly, rather than being silently absorbed
alongside the already-understood noise.

**No internal duplicate-identity handling here (by design)**: unlike
`govuk_discovery.py` (which is itself the dedupe/conflict authority
for discovery-only diagnostics), this parser returns every valid
entry as-is, exactly like `rss_item_parsing.parse_news_rss_items` --
same-identity dedupe-or-conflict is the COMMON `IngestNewsSourceOnce`
layer's own job (`_dedupe_observations`), applied uniformly to every
FX-57 adapter's observations, not re-implemented per parser. Live
research found zero within-response duplicates among genuine
dq-shaped ids in any of the four adopted feeds, so this path is
expected to be a no-op in practice -- exactly like Fed/ECB/BoE/
GOV.UK's own "protection, not an observed case" precedent.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlparse
from xml.etree import ElementTree

_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_STATCAN_HOST = "www.statcan.gc.ca"
_DAILY_RELEASE_PATH_RE = re.compile(r"^/daily-quotidien/\d{6}/dq\d{6}[a-z]+-eng\.htm$")
_CATALOGUE_REFERENCE_PATH = "/cgi-bin/IPS/display"
_CATALOGUE_REFERENCE_QUERY_RE = re.compile(r"^cat_num=[A-Za-z0-9-]+$")


class MalformedStatCanAtomFeedError(ValueError):
    """Raised when a StatCan feed response is not a recognizable Atom
    feed at all (bad XML, wrong root, an HTML error page masquerading
    as a 200, an RSS document masquerading as Atom). Distinct from a
    genuinely empty, well-formed feed (valid `<feed>` root, zero
    `<entry>` elements), which is a valid, non-error result, and
    distinct from an ordinary item-level invalid entry (missing id/
    title/link, or an entry that is not a dated Daily-release
    article), which is counted via `invalid_count`, never raised."""


@dataclass(frozen=True, slots=True)
class StatCanAtomEntry:
    """One validated Daily-release Atom entry. `entry_id` is the
    provider's own opaque `<id>` value, used as-is for identity --
    never reconstructed from `canonical_url`/`updated_raw`/sequence
    position, even though, for every entry accepted here, `entry_id`
    and `canonical_url` happen to be the identical string (live-
    confirmed: `<id>` and the `<link href="...">` always coincide for
    StatCan's own Daily-release entries)."""

    entry_id: str
    title: str
    canonical_url: str
    updated_raw: str
    summary: str | None


@dataclass(frozen=True, slots=True)
class StatCanAtomParseResult:
    """`invalid_count`/`invalid_reasons` carry the SAME common
    item-level-invalid meaning every other FX-57 adapter uses --
    but, unlike every other adapter, for StatCan this count also
    includes the KNOWN, understood, adapter-local out-of-scope
    catalogue-reference shape (see `is_known_catalogue_reference_id`
    below), not only genuine malformed/drifted data (FX-57EH Section
    8). No separate `items_excluded` counter was introduced for this
    distinction -- a future observability cleanup could split them if
    that becomes useful; for now, `invalid_reasons` itself always
    distinguishes the two cases by wording."""

    entries: tuple[StatCanAtomEntry, ...]
    invalid_count: int
    invalid_reasons: tuple[str, ...]


def parse_statcan_daily_atom(text: str) -> StatCanAtomParseResult:
    """Every usable Daily-release `<entry>` in `text`. Raises
    `MalformedStatCanAtomFeedError` if `text` does not parse as XML or
    its root is not an Atom `feed`. An entry is invalid (counted, not
    raising) for a missing/blank `id`/`title`/`updated`, a missing or
    off-host/malformed `link`, or an `id` that is not a dated
    Daily-release article URL (e.g. a recurring product/catalogue
    reference -- see the module docstring)."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise MalformedStatCanAtomFeedError(f"text does not parse as XML: {exc}") from exc
    if root.tag != f"{_ATOM_NS}feed":
        raise MalformedStatCanAtomFeedError(
            f"root element {root.tag!r} is not an Atom feed root (expected "
            f"'{{{_ATOM_NS[1:-1]}}}feed')"
        )

    entries: list[StatCanAtomEntry] = []
    invalid_reasons: list[str] = []

    for index, entry_element in enumerate(root.findall(f"{_ATOM_NS}entry")):
        entry, reason = _parse_one_entry(entry_element)
        if entry is None:
            invalid_reasons.append(f"entry at index {index}: {reason}")
            continue
        entries.append(entry)

    return StatCanAtomParseResult(
        entries=tuple(entries),
        invalid_count=len(invalid_reasons),
        invalid_reasons=tuple(invalid_reasons),
    )


def is_known_catalogue_reference_id(entry_id: str) -> bool:
    """Whether `entry_id` matches StatCan's own recurring, live-
    verified "Product/Study" catalogue-reference shape (`https://
    www.statcan.gc.ca/cgi-bin/IPS/display?cat_num=<value>`) -- a
    structurally distinct, genuinely valid StatCan URL that is simply
    OUTSIDE this story's own adopted Daily-release evidence shape,
    never source drift (FX-57EH Section 2). Exported so a `live_
    source` test can independently re-verify this EXACT contract
    against the raw id itself, rather than matching against this
    module's own diagnostic wording."""
    parsed = urlparse(entry_id)
    return (
        parsed.scheme == "https"
        and parsed.netloc == _STATCAN_HOST
        and parsed.path == _CATALOGUE_REFERENCE_PATH
        and bool(_CATALOGUE_REFERENCE_QUERY_RE.match(parsed.query))
    )


def _parse_one_entry(
    entry_element: ElementTree.Element,
) -> tuple[StatCanAtomEntry | None, str | None]:
    entry_id_raw = _text_of(entry_element, "id")
    if entry_id_raw is None:
        return None, "missing or blank id"

    if _validate_daily_release_url(entry_id_raw) is None:
        if is_known_catalogue_reference_id(entry_id_raw):
            return None, (
                "id matches the known recurring StatCan Product/Study "
                "catalogue-reference shape (cgi-bin/IPS/display?cat_num=...), not "
                "a dated Daily-release article -- out of this story's own adopted "
                f"evidence scope, not source drift: {entry_id_raw!r}"
            )
        return None, (
            "unexpected non-Daily StatCan entry id shape -- neither a dated "
            "Daily-release article URL nor the known recurring catalogue-"
            "reference pattern; this may be genuine source-schema drift needing "
            f"review: {entry_id_raw!r}"
        )

    link_el = entry_element.find(f"{_ATOM_NS}link")
    link_href = link_el.get("href") if link_el is not None else None
    canonical_url = _validate_daily_release_url(link_href)
    if canonical_url is None:
        return None, f"missing, off-host, or malformed Daily-release link: {link_href!r}"

    title = _xhtml_text_of(entry_element, "title")
    if title is None:
        return None, "missing or blank title"

    updated_raw = _text_of(entry_element, "updated")
    if updated_raw is None:
        return None, "missing or blank updated"

    summary = _xhtml_text_of(entry_element, "summary")

    return (
        StatCanAtomEntry(
            entry_id=entry_id_raw,
            title=title,
            canonical_url=canonical_url,
            updated_raw=updated_raw,
            summary=summary,
        ),
        None,
    )


def _validate_daily_release_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    stripped = value.strip()
    parsed = urlparse(stripped)
    if parsed.scheme != "https" or parsed.netloc != _STATCAN_HOST:
        return None
    if not _DAILY_RELEASE_PATH_RE.match(parsed.path):
        return None
    return stripped


def _text_of(element: ElementTree.Element, tag: str) -> str | None:
    """The DIRECT text of a plain (non-XHTML-typed) child element,
    e.g. `<id>`/`<updated>`."""
    child = element.find(f"{_ATOM_NS}{tag}")
    if child is None or child.text is None:
        return None
    stripped = child.text.strip()
    return stripped or None


def _xhtml_text_of(element: ElementTree.Element, tag: str) -> str | None:
    """The flattened, whitespace-normalized text of a `type="xhtml"`
    child element (e.g. `<title>`/`<summary>`, each live-confirmed to
    wrap their actual text in a nested `<div xmlns="...xhtml">`,
    sometimes with an inner `<span class="refper">` for the reference
    period) -- never raw markup, since `headline`/`summary` are plain-
    string domain fields, exactly like every other FX-57 adapter's own
    title/summary mapping."""
    child = element.find(f"{_ATOM_NS}{tag}")
    if child is None:
        return None
    flattened = " ".join("".join(child.itertext()).split())
    return flattened or None

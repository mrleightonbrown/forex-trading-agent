"""FX-57F: deterministic fixture tests for `parse_boc_press_releases_rdf`
-- no network access. See tests/integration/test_boc_source_live.py for
live-feed validation. Fixture shapes mirror the real, live-verified
feed at `content_type/press-releases/feed/` (2026-10-10): RDF root,
`<item rdf:about="...">` as a SIBLING of `<channel>`, not nested."""

import pytest

from forex_agent.infrastructure.news_sources.boc_rdf_parsing import (
    MalformedBocFeedError,
    parse_boc_press_releases_rdf,
)

_HOST = "https://www.bankofcanada.ca"
_PATH = "/2026/09/fad-press-release-2026-09-02/"
_OTHER_PATH = "/2026/07/fad-press-release-2026-07-15/"

_NS = (
    "xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#' "
    "xmlns='http://purl.org/rss/1.0/' "
    "xmlns:dc='http://purl.org/dc/elements/1.1/' "
    "xmlns:cb='http://www.cbwiki.net/wiki/index.php/Specification_1.2/'"
)


def _feed(*items_xml: str) -> str:
    body = "".join(items_xml)
    return (
        "<?xml version='1.0'?>"
        f"<rdf:RDF {_NS}>"
        f"<channel rdf:about='{_HOST}/content_type/press-releases/feed/'>"
        "<title>Press Releases - Bank of Canada</title>"
        f"<link>{_HOST}/rss-feeds/</link>"
        "<description>Bank of Canada RSS Feeds</description>"
        "</channel>"
        f"{body}</rdf:RDF>"
    )


def _item(
    path: str | None = _PATH,
    about: str | None = None,
    title: str | None = "Bank of Canada increases its policy rate",
    link: str | None = None,
    dc_date: str | None = "2026-09-02T09:47:53+00:00",
    description: str | None = "Example press release summary.",
    host: str = _HOST,
    include_cb_news: bool = True,
) -> str:
    if about is None:
        about = f"{host}{path}" if path else None
    if link is None:
        link = f"{host}{path}" if path else None
    elif link == "":
        link = None

    about_attr = f" rdf:about='{about}'" if about is not None else ""
    parts = [f"<item{about_attr}>"]
    if title is not None:
        parts.append(f"<title>{title}</title>")
    if link is not None:
        parts.append(f"<link>{link}</link>")
    if description is not None:
        parts.append(f"<description>{description}</description>")
    if dc_date is not None:
        parts.append(f"<dc:date>{dc_date}</dc:date>")
    parts.append("<dc:language>en</dc:language>")
    if include_cb_news:
        parts.append(
            "<cb:news rdf:parseType='Resource'>"
            "<cb:simpleTitle>Bank of Canada increases its policy rate</cb:simpleTitle>"
            "<cb:occurrenceDate>2026-09-02</cb:occurrenceDate>"
            "</cb:news>"
        )
    parts.append("</item>")
    return "".join(parts)


def test_normal_item_parses() -> None:
    result = parse_boc_press_releases_rdf(_feed(_item()))
    assert result.invalid_count == 0
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.entry_id == f"{_HOST}{_PATH}"
    assert entry.canonical_url == f"{_HOST}{_PATH}"
    assert entry.title == "Bank of Canada increases its policy rate"
    assert entry.dc_date_raw == "2026-09-02T09:47:53+00:00"
    assert entry.summary == "Example press release summary."


def test_multiple_items_all_parse() -> None:
    result = parse_boc_press_releases_rdf(
        _feed(_item(path=_PATH), _item(path=_OTHER_PATH, dc_date="2026-07-15T09:47:46+00:00"))
    )
    assert result.invalid_count == 0
    assert len(result.entries) == 2


def test_missing_identity_is_invalid() -> None:
    result = parse_boc_press_releases_rdf(_feed(_item(about="")))
    assert result.invalid_count == 1
    assert result.entries == ()


def test_blank_identity_is_invalid() -> None:
    result = parse_boc_press_releases_rdf(_feed(_item(about="   ")))
    assert result.invalid_count == 1
    assert result.entries == ()


def test_title_present() -> None:
    result = parse_boc_press_releases_rdf(_feed(_item(title="A specific headline")))
    assert result.entries[0].title == "A specific headline"


def test_missing_title_is_invalid() -> None:
    result = parse_boc_press_releases_rdf(_feed(_item(title=None)))
    assert result.invalid_count == 1
    assert result.entries == ()


def test_blank_title_is_invalid() -> None:
    result = parse_boc_press_releases_rdf(
        _feed(
            f"<item rdf:about='{_HOST}{_PATH}'>"
            "<title>   </title>"
            f"<link>{_HOST}{_PATH}</link>"
            "<dc:date>2026-09-02T09:47:53+00:00</dc:date>"
            "</item>"
        )
    )
    assert result.invalid_count == 1
    assert result.entries == ()


def test_missing_link_is_invalid() -> None:
    result = parse_boc_press_releases_rdf(_feed(_item(link="")))
    assert result.invalid_count == 1
    assert result.entries == ()


def test_off_domain_link_is_invalid() -> None:
    result = parse_boc_press_releases_rdf(_feed(_item(link=f"https://evil.example.com{_PATH}")))
    assert result.invalid_count == 1
    assert result.entries == ()


def test_link_with_no_path_is_invalid() -> None:
    result = parse_boc_press_releases_rdf(_feed(_item(link=_HOST)))
    assert result.invalid_count == 1
    assert result.entries == ()


def test_dc_date_absent_is_not_invalid() -> None:
    # Section 31: a missing dc:date is NOT item-invalid -- it simply
    # means no source publication provenance is available.
    result = parse_boc_press_releases_rdf(_feed(_item(dc_date=None)))
    assert result.invalid_count == 0
    assert result.entries[0].dc_date_raw is None


def test_description_present() -> None:
    result = parse_boc_press_releases_rdf(_feed(_item(description="A real summary.")))
    assert result.entries[0].summary == "A real summary."


def test_description_absent_is_none() -> None:
    result = parse_boc_press_releases_rdf(_feed(_item(description=None)))
    assert result.invalid_count == 0
    assert result.entries[0].summary is None


def test_cb_news_block_is_ignored_not_read() -> None:
    # Section 9: cb:news adds nothing this parser uses -- present or
    # absent must not change the parsed result at all.
    with_cb = parse_boc_press_releases_rdf(_feed(_item(include_cb_news=True)))
    without_cb = parse_boc_press_releases_rdf(_feed(_item(include_cb_news=False)))
    assert with_cb.entries == without_cb.entries


# --- within-response duplicates: NOT this parser's job ---------------------


def test_duplicate_identical_identity_both_returned_no_parser_level_dedupe() -> None:
    result = parse_boc_press_releases_rdf(_feed(_item(), _item()))
    assert result.invalid_count == 0
    assert len(result.entries) == 2
    assert result.entries[0].entry_id == result.entries[1].entry_id


# --- one invalid entry does not discard other valid entries ---------------


def test_one_invalid_entry_does_not_discard_other_valid_entries() -> None:
    result = parse_boc_press_releases_rdf(
        _feed(
            _item(path=_PATH),
            _item(about=""),
            _item(path=_OTHER_PATH, dc_date="2026-07-15T09:47:46+00:00"),
        )
    )
    assert result.invalid_count == 1
    assert len(result.entries) == 2


# --- valid empty feed -------------------------------------------------------


def test_valid_empty_feed_is_not_an_error() -> None:
    result = parse_boc_press_releases_rdf(_feed())
    assert result.invalid_count == 0
    assert result.entries == ()


# --- source-level malformed responses --------------------------------------


def test_malformed_xml_raises() -> None:
    with pytest.raises(MalformedBocFeedError):
        parse_boc_press_releases_rdf("<rdf:RDF><item>unterminated")


def test_html_masquerading_as_feed_raises() -> None:
    with pytest.raises(MalformedBocFeedError):
        parse_boc_press_releases_rdf("<html><body>Access Denied</body></html>")


def test_rss2_root_is_not_rdf_and_fails_closed() -> None:
    with pytest.raises(MalformedBocFeedError):
        parse_boc_press_releases_rdf("<rss version='2.0'><channel><title>t</title></channel></rss>")


def test_atom_root_is_not_rdf_and_fails_closed() -> None:
    with pytest.raises(MalformedBocFeedError):
        parse_boc_press_releases_rdf("<feed xmlns='http://www.w3.org/2005/Atom'></feed>")

"""FX-57E: deterministic fixture tests for `parse_statcan_daily_atom`
-- no network access. See tests/integration/test_statcan_source_live.py
for live-feed validation."""

import pytest

from forex_agent.infrastructure.news_sources.statcan_atom_parsing import (
    MalformedStatCanAtomFeedError,
    parse_statcan_daily_atom,
)

_HOST = "https://www.statcan.gc.ca"
_DAILY_PATH = "/daily-quotidien/261002/dq261002b-eng.htm"
_OTHER_DAILY_PATH = "/daily-quotidien/261002/dq261002c-eng.htm"
_CATALOGUE_PATH = "/cgi-bin/IPS/display?cat_num=18-001-X"


def _feed(*entries_xml: str) -> str:
    body = "".join(entries_xml)
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<feed xmlns='http://www.w3.org/2005/Atom'>"
        "<title>Statistics Canada, The Daily: Prices and price indexes</title>"
        f"{body}</feed>"
    )


def _entry(
    path: str | None = _DAILY_PATH,
    entry_id: str | None = None,
    title: str | None = "Example item, <span class='refper'>October 2026</span>",
    updated: str | None = "2026-10-02T08:30:00-04:00",
    summary: str | None = "Example summary.",
    host: str = _HOST,
    link_href: str | None = None,
    use_xhtml_title: bool = True,
) -> str:
    if entry_id is None:
        entry_id = f"{host}{path}" if path else None
    if link_href is None:
        link_href = f"{host}{path}" if path else None
    elif link_href == "":
        link_href = None

    parts = []
    if entry_id is not None:
        parts.append(f"<id>{entry_id}</id>")
    if title is not None:
        if use_xhtml_title:
            parts.append(
                f"<title type='xhtml'><div xmlns='http://www.w3.org/1999/xhtml'>{title}</div>"
                "</title>"
            )
        else:
            parts.append(f"<title>{title}</title>")
    if link_href is not None:
        parts.append(f"<link href='{link_href}'></link>")
    if updated is not None:
        parts.append(f"<updated>{updated}</updated>")
    if summary is not None:
        parts.append(
            f"<summary type='xhtml'><div xmlns='http://www.w3.org/1999/xhtml'>{summary}</div>"
            "</summary>"
        )
    return f"<entry>{''.join(parts)}</entry>"


def test_normal_entry_parses() -> None:
    result = parse_statcan_daily_atom(_feed(_entry()))
    assert result.invalid_count == 0
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.entry_id == f"{_HOST}{_DAILY_PATH}"
    assert entry.canonical_url == f"{_HOST}{_DAILY_PATH}"
    assert entry.title == "Example item, October 2026"
    assert entry.updated_raw == "2026-10-02T08:30:00-04:00"
    assert entry.summary == "Example summary."


def test_multiple_entries_all_parse() -> None:
    result = parse_statcan_daily_atom(
        _feed(
            _entry(path="/daily-quotidien/261002/dq261002a-eng.htm"),
            _entry(path="/daily-quotidien/261002/dq261002b-eng.htm"),
            _entry(path="/daily-quotidien/261001/dq261001c-eng.htm"),
        )
    )
    assert result.invalid_count == 0
    assert len(result.entries) == 3


def test_missing_id_is_invalid() -> None:
    result = parse_statcan_daily_atom(_feed(_entry(entry_id="")))
    assert result.invalid_count == 1
    assert result.entries == ()


def test_blank_id_is_invalid() -> None:
    result = parse_statcan_daily_atom(_feed(_entry(entry_id="   ")))
    assert result.invalid_count == 1
    assert result.entries == ()


def test_missing_title_is_invalid() -> None:
    result = parse_statcan_daily_atom(_feed(_entry(title=None)))
    assert result.invalid_count == 1
    assert result.entries == ()


def test_blank_title_is_invalid() -> None:
    result = parse_statcan_daily_atom(
        _feed(
            "<entry>"
            f"<id>{_HOST}{_DAILY_PATH}</id>"
            "<title type='xhtml'><div xmlns='http://www.w3.org/1999/xhtml'>   </div></title>"
            f"<link href='{_HOST}{_DAILY_PATH}'></link>"
            "<updated>2026-10-02T08:30:00-04:00</updated>"
            "</entry>"
        )
    )
    assert result.invalid_count == 1
    assert result.entries == ()


def test_missing_alternate_link_is_invalid() -> None:
    result = parse_statcan_daily_atom(_feed(_entry(link_href="")))
    assert result.invalid_count == 1
    assert result.entries == ()


def test_off_domain_link_is_invalid() -> None:
    result = parse_statcan_daily_atom(
        _feed(_entry(link_href=f"https://evil.example.com{_DAILY_PATH}"))
    )
    assert result.invalid_count == 1
    assert result.entries == ()


def test_missing_updated_is_invalid() -> None:
    result = parse_statcan_daily_atom(_feed(_entry(updated=None)))
    assert result.invalid_count == 1
    assert result.entries == ()


def test_summary_present() -> None:
    result = parse_statcan_daily_atom(_feed(_entry(summary="A real summary.")))
    assert result.entries[0].summary == "A real summary."


def test_summary_absent_is_none() -> None:
    result = parse_statcan_daily_atom(_feed(_entry(summary=None)))
    assert result.invalid_count == 0
    assert result.entries[0].summary is None


def test_plain_text_title_also_parses() -> None:
    # Not every title is necessarily type="xhtml" -- the flattening
    # helper must also handle an ordinary plain-text title correctly.
    result = parse_statcan_daily_atom(_feed(_entry(title="Plain title", use_xhtml_title=False)))
    assert result.entries[0].title == "Plain title"


# --- Daily-release id-shape validation (adapter-local content filter) ------


def test_catalogue_reference_id_is_invalid_not_a_daily_release() -> None:
    # Live finding: a recurring "Product/Study" catalogue reference
    # shares the SAME id across many Daily mentions, with a DIFFERENT
    # updated value each time -- structurally different from a dated
    # Daily release article, and excluded here, never ingested.
    result = parse_statcan_daily_atom(
        _feed(_entry(path=_CATALOGUE_PATH, title="Product/Study: Something"))
    )
    assert result.invalid_count == 1
    assert "recurring product/catalogue reference" in result.invalid_reasons[0]
    assert result.entries == ()


def test_id_missing_scheme_is_invalid() -> None:
    result = parse_statcan_daily_atom(_feed(_entry(entry_id=_DAILY_PATH)))
    assert result.invalid_count == 1


def test_link_off_host_even_when_id_is_valid_is_invalid() -> None:
    result = parse_statcan_daily_atom(
        _feed(_entry(entry_id=f"{_HOST}{_DAILY_PATH}", link_href="https://evil.example.com/x"))
    )
    assert result.invalid_count == 1


# --- within-response duplicates: NOT this parser's job ---------------------


def test_duplicate_identical_id_both_returned_no_parser_level_dedupe() -> None:
    result = parse_statcan_daily_atom(_feed(_entry(), _entry()))
    assert result.invalid_count == 0
    assert len(result.entries) == 2
    assert result.entries[0].entry_id == result.entries[1].entry_id


def test_duplicate_conflicting_id_both_returned_no_parser_level_raise() -> None:
    result = parse_statcan_daily_atom(
        _feed(
            _entry(title="Version A"),
            _entry(title="Version B"),
        )
    )
    assert result.invalid_count == 0
    assert len(result.entries) == 2
    assert result.entries[0].title == "Version A"
    assert result.entries[1].title == "Version B"


# --- one invalid entry does not discard other valid entries ---------------


def test_one_invalid_entry_does_not_discard_other_valid_entries() -> None:
    result = parse_statcan_daily_atom(
        _feed(
            _entry(path="/daily-quotidien/261002/dq261002a-eng.htm"),
            _entry(entry_id=""),
            _entry(path="/daily-quotidien/261002/dq261002b-eng.htm"),
        )
    )
    assert result.invalid_count == 1
    assert len(result.entries) == 2


# --- valid empty feed -------------------------------------------------------


def test_valid_empty_feed_is_not_an_error() -> None:
    result = parse_statcan_daily_atom(_feed())
    assert result.invalid_count == 0
    assert result.entries == ()


# --- source-level malformed responses --------------------------------------


def test_malformed_xml_raises() -> None:
    with pytest.raises(MalformedStatCanAtomFeedError):
        parse_statcan_daily_atom("<feed><entry>unterminated")


def test_html_masquerading_as_feed_raises() -> None:
    with pytest.raises(MalformedStatCanAtomFeedError):
        parse_statcan_daily_atom("<html><body>Access Denied</body></html>")


def test_rss_root_is_not_atom_and_fails_closed() -> None:
    with pytest.raises(MalformedStatCanAtomFeedError):
        parse_statcan_daily_atom("<rss version='2.0'><channel><title>t</title></channel></rss>")

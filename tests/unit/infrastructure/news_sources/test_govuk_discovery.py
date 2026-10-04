"""FX-57D: deterministic fixture tests for `parse_govuk_discovery_
atom` -- no network access. See tests/integration/
test_govuk_hmt_source_live.py for live-feed validation."""

import pytest

from forex_agent.infrastructure.news_sources.govuk_discovery import (
    MalformedGovUkDiscoveryFeedError,
    parse_govuk_discovery_atom,
)


def _feed(*entries_xml: str) -> str:
    body = "".join(entries_xml)
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<feed xmlns='http://www.w3.org/2005/Atom'>"
        "<title>News and communications from HM Treasury (HMT)</title>"
        f"{body}</feed>"
    )


def _entry(
    path: str = "/government/news/example-item",
    entry_id: str = "tag:www.gov.uk,2005:/government/news/example-item",
    updated: str | None = "2026-10-01T09:24:06+01:00",
    title: str = "Example item",
    host: str = "https://www.gov.uk",
) -> str:
    link = f"{host}{path}" if path else ""
    parts = [f"<id>{entry_id}</id>"]
    if updated is not None:
        parts.append(f"<updated>{updated}</updated>")
    if link:
        parts.append(f"<link rel='alternate' type='text/html' href='{link}'/>")
    parts.append(f"<title>{title}</title>")
    return f"<entry>{''.join(parts)}</entry>"


def test_normal_entry_parses() -> None:
    result = parse_govuk_discovery_atom(_feed(_entry()))
    assert result.invalid_count == 0
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.path == "/government/news/example-item"
    assert entry.updated_raw == "2026-10-01T09:24:06+01:00"
    assert entry.title == "Example item"


def test_multiple_entries_all_parse() -> None:
    result = parse_govuk_discovery_atom(
        _feed(
            _entry(path="/government/news/a", entry_id="tag:a"),
            _entry(path="/government/news/b", entry_id="tag:b"),
            _entry(path="/government/news/c", entry_id="tag:c"),
        )
    )
    assert result.invalid_count == 0
    assert [e.path for e in result.entries] == [
        "/government/news/a",
        "/government/news/b",
        "/government/news/c",
    ]


def test_duplicate_identical_path_dedupes_silently() -> None:
    result = parse_govuk_discovery_atom(
        _feed(
            _entry(path="/government/news/dup", updated="2026-10-01T09:00:00+01:00"),
            _entry(path="/government/news/dup", updated="2026-10-01T09:00:00+01:00"),
        )
    )
    assert result.invalid_count == 0
    assert len(result.entries) == 1


def test_duplicate_path_with_conflicting_updated_fails_closed() -> None:
    with pytest.raises(MalformedGovUkDiscoveryFeedError):
        parse_govuk_discovery_atom(
            _feed(
                _entry(path="/government/news/dup", updated="2026-10-01T09:00:00+01:00"),
                _entry(path="/government/news/dup", updated="2026-10-01T10:00:00+01:00"),
            )
        )


def test_missing_id_is_invalid() -> None:
    xml = _feed(
        "<entry><updated>2026-10-01T09:00:00+01:00</updated>"
        "<link rel='alternate' href='https://www.gov.uk/government/news/x'/>"
        "<title>X</title></entry>"
    )
    result = parse_govuk_discovery_atom(xml)
    assert result.invalid_count == 1
    assert len(result.entries) == 0


def test_missing_title_is_invalid() -> None:
    xml = _feed(
        "<entry><id>tag:x</id><updated>2026-10-01T09:00:00+01:00</updated>"
        "<link rel='alternate' href='https://www.gov.uk/government/news/x'/></entry>"
    )
    result = parse_govuk_discovery_atom(xml)
    assert result.invalid_count == 1
    assert len(result.entries) == 0


def test_off_domain_link_is_invalid() -> None:
    result = parse_govuk_discovery_atom(
        _feed(_entry(path="/some/path", host="https://evil.example.com"))
    )
    assert result.invalid_count == 1
    assert len(result.entries) == 0


def test_missing_link_is_invalid() -> None:
    xml = _feed("<entry><id>tag:x</id><title>No link</title></entry>")
    result = parse_govuk_discovery_atom(xml)
    assert result.invalid_count == 1
    assert len(result.entries) == 0


def test_one_invalid_entry_does_not_discard_other_valid_entries() -> None:
    xml = _feed(
        _entry(path="/government/news/good-1", entry_id="tag:good-1"),
        "<entry><title>No id or link</title></entry>",
        _entry(path="/government/news/good-2", entry_id="tag:good-2"),
    )
    result = parse_govuk_discovery_atom(xml)
    assert result.invalid_count == 1
    assert [e.path for e in result.entries] == [
        "/government/news/good-1",
        "/government/news/good-2",
    ]


def test_valid_empty_feed_is_not_an_error() -> None:
    result = parse_govuk_discovery_atom(_feed())
    assert result.invalid_count == 0
    assert result.entries == ()


def test_malformed_xml_raises() -> None:
    with pytest.raises(MalformedGovUkDiscoveryFeedError):
        parse_govuk_discovery_atom("<feed><entry>unterminated")


def test_html_masquerading_as_feed_raises() -> None:
    with pytest.raises(MalformedGovUkDiscoveryFeedError):
        parse_govuk_discovery_atom("<html><body>Access Denied</body></html>")


def test_rss_root_is_not_atom_and_fails_closed() -> None:
    with pytest.raises(MalformedGovUkDiscoveryFeedError):
        parse_govuk_discovery_atom("<rss version='2.0'><channel><title>t</title></channel></rss>")

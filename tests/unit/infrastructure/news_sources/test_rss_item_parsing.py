"""FX-57A: deterministic fixture tests for `parse_news_rss_items` --
no network access. See tests/integration/test_fed_rss_source_live.py
for live-feed validation."""

from datetime import UTC, datetime

import pytest

from forex_agent.infrastructure.news_sources.rss_item_parsing import (
    MalformedNewsFeedError,
    parse_news_rss_items,
)


def _rss(*items_xml: str) -> str:
    body = "".join(items_xml)
    return (
        "<?xml version='1.0'?><rss version='2.0'><channel>"
        "<title>Test Feed</title><link>https://example.test</link>"
        f"<description>Test</description>{body}</channel></rss>"
    )


def _item(
    guid: str = "guid-1",
    title: str = "A Title",
    link: str = "https://example.test/1",
    description: str | None = "A description",
    pub_date: str | None = "Wed, 16 Sep 2026 18:00:00 GMT",
) -> str:
    parts = [f"<guid>{guid}</guid>", f"<title>{title}</title>", f"<link>{link}</link>"]
    if description is not None:
        parts.append(f"<description>{description}</description>")
    if pub_date is not None:
        parts.append(f"<pubDate>{pub_date}</pubDate>")
    return f"<item>{''.join(parts)}</item>"


def test_one_normal_item_parses_fully() -> None:
    result = parse_news_rss_items(_rss(_item()))
    assert result.invalid_count == 0
    assert len(result.items) == 1
    item = result.items[0]
    assert item.guid == "guid-1"
    assert item.title == "A Title"
    assert item.link == "https://example.test/1"
    assert item.description == "A description"
    assert item.raw_pub_date == "Wed, 16 Sep 2026 18:00:00 GMT"
    assert item.pub_date == datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)
    assert item.pub_date_issue is None


def test_multiple_items_all_parse() -> None:
    result = parse_news_rss_items(_rss(_item(guid="g1"), _item(guid="g2"), _item(guid="g3")))
    assert result.invalid_count == 0
    assert [item.guid for item in result.items] == ["g1", "g2", "g3"]


def test_missing_optional_description_is_none_not_invalid() -> None:
    result = parse_news_rss_items(_rss(_item(description=None)))
    assert result.invalid_count == 0
    assert result.items[0].description is None


def test_malformed_pub_date_does_not_invalidate_item() -> None:
    result = parse_news_rss_items(_rss(_item(pub_date="not a real date")))
    assert result.invalid_count == 0
    item = result.items[0]
    assert item.raw_pub_date == "not a real date"
    assert item.pub_date is None
    assert item.pub_date_issue is not None


def test_sentinel_pub_date_year_below_floor_is_detected() -> None:
    result = parse_news_rss_items(_rss(_item(pub_date="Sat, 30 Dec 1899 15:00:00 GMT")))
    assert result.invalid_count == 0
    item = result.items[0]
    assert item.raw_pub_date == "Sat, 30 Dec 1899 15:00:00 GMT"
    assert item.pub_date is None
    assert item.pub_date_issue is not None
    assert "sentinel" in item.pub_date_issue.lower()


def test_missing_pub_date_entirely_is_not_invalid() -> None:
    result = parse_news_rss_items(_rss(_item(pub_date=None)))
    assert result.invalid_count == 0
    item = result.items[0]
    assert item.raw_pub_date is None
    assert item.pub_date is None
    assert item.pub_date_issue is None


def test_missing_guid_is_invalid() -> None:
    xml = _rss("<item><title>No Guid</title></item>")
    result = parse_news_rss_items(xml)
    assert result.invalid_count == 1
    assert len(result.items) == 0
    assert "guid" in result.invalid_reasons[0]


def test_missing_title_is_invalid() -> None:
    xml = _rss("<item><guid>g1</guid></item>")
    result = parse_news_rss_items(xml)
    assert result.invalid_count == 1
    assert len(result.items) == 0
    assert "title" in result.invalid_reasons[0]


def test_blank_title_is_invalid() -> None:
    xml = _rss("<item><guid>g1</guid><title>   </title></item>")
    result = parse_news_rss_items(xml)
    assert result.invalid_count == 1
    assert len(result.items) == 0


def test_duplicate_guid_within_feed_both_parsed_dedup_is_a_pipeline_concern() -> None:
    # The PARSER itself does not deduplicate -- it reports every
    # structurally valid item as-is; deduplication across identical
    # guids happens at the ingestion-orchestration layer (FX-57A
    # Section 39, see test_ingest_news_source_once.py).
    result = parse_news_rss_items(_rss(_item(guid="dup"), _item(guid="dup", title="Different")))
    assert result.invalid_count == 0
    assert [item.guid for item in result.items] == ["dup", "dup"]


def test_one_malformed_item_does_not_discard_other_valid_items() -> None:
    xml = _rss(_item(guid="good-1"), "<item><title>No Guid</title></item>", _item(guid="good-2"))
    result = parse_news_rss_items(xml)
    assert result.invalid_count == 1
    assert [item.guid for item in result.items] == ["good-1", "good-2"]


def test_valid_empty_feed_is_not_an_error() -> None:
    result = parse_news_rss_items(_rss())
    assert result.invalid_count == 0
    assert result.items == ()


def test_malformed_xml_raises() -> None:
    with pytest.raises(MalformedNewsFeedError):
        parse_news_rss_items("<rss><channel><title>unterminated")


def test_html_masquerading_as_feed_raises() -> None:
    with pytest.raises(MalformedNewsFeedError):
        parse_news_rss_items("<html><body>Access Denied</body></html>")


def test_unrecognized_root_raises() -> None:
    with pytest.raises(MalformedNewsFeedError):
        parse_news_rss_items("<somethingelse/>")

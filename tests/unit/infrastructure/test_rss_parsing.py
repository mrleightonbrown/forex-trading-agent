"""FX-52A: unit tests for the minimal RSS 2.0 / RDF-RSS-1.0 parser.
FX-52AH adds `cb:occurrenceDate` and malformed-document coverage."""

from datetime import UTC, date, datetime

import pytest

from forex_agent.infrastructure.economic_calendar_sources.rss_parsing import (
    MalformedFeedError,
    parse_rss_items,
)

_RSS2_FEED = """<?xml version="1.0"?>
<rss version="2.0">
<channel>
<item>
<title>GDP quarterly national accounts, UK: April to June 2026</title>
<link>https://www.ons.gov.uk/economy/grossdomesticproductgdp/bulletins/quarterlynationalaccounts/apriltojune2026</link>
<guid>https://www.ons.gov.uk/economy/grossdomesticproductgdp/bulletins/quarterlynationalaccounts/apriltojune2026</guid>
<pubDate>Wed, 30 Sep 2026 06:00:00 +0000</pubDate>
</item>
</channel>
</rss>
"""

_RDF_FEED = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<item rdf:about="https://www.bankofcanada.ca/2026/09/rate-announcement/">
<title>Bank of Canada maintains the policy rate at 2&#188;%</title>
<link>https://www.bankofcanada.ca/2026/09/rate-announcement/</link>
<dc:date>2026-09-02T09:47:53+00:00</dc:date>
</item>
</rdf:RDF>
"""

_CB_NS = "http://www.cbwiki.net/wiki/index.php/Specification_1.2/"
_RDF_FEED_WITH_CB_NEWS = f"""<?xml version="1.0"?>
<rdf:RDF
    xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns="http://purl.org/rss/1.0/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:cb="{_CB_NS}">
<item rdf:about="https://www.bankofcanada.ca/2026/09/rate-announcement/">
<title>Bank of Canada maintains the policy rate at 2&#188;%</title>
<link>https://www.bankofcanada.ca/2026/09/rate-announcement/</link>
<dc:date>2026-09-02T09:47:53+00:00</dc:date>
<cb:news rdf:parseType="Resource">
<cb:occurrenceDate>2026-09-02</cb:occurrenceDate>
</cb:news>
</item>
</rdf:RDF>
"""

_MISSING_PUBDATE_FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>No date here</title><guid>x</guid></item>
</channel></rss>
"""

_NAIVE_PUBDATE_FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>Naive date</title><guid>y</guid><pubDate>Wed, 30 Sep 2026 06:00:00</pubDate></item>
</channel></rss>
"""


def test_rss2_item_parsed_with_explicit_utc_offset() -> None:
    result = parse_rss_items(_RSS2_FEED)
    assert len(result.items) == 1
    assert result.invalid_count == 0
    item = result.items[0]
    assert item.title == "GDP quarterly national accounts, UK: April to June 2026"
    assert item.pub_date == datetime(2026, 9, 30, 6, 0, 0, tzinfo=UTC)
    assert "quarterlynationalaccounts" in item.link
    assert item.guid == item.link
    assert item.occurrence_date is None


def test_rdf_item_uses_about_attribute_as_guid_and_dc_date() -> None:
    result = parse_rss_items(_RDF_FEED)
    assert len(result.items) == 1
    item = result.items[0]
    assert item.guid == "https://www.bankofcanada.ca/2026/09/rate-announcement/"
    assert item.pub_date == datetime(2026, 9, 2, 9, 47, 53, tzinfo=UTC)
    assert item.title.startswith("Bank of Canada maintains the policy rate")
    assert item.occurrence_date is None


def test_rdf_item_with_cb_news_extracts_occurrence_date() -> None:
    result = parse_rss_items(_RDF_FEED_WITH_CB_NEWS)
    assert len(result.items) == 1
    item = result.items[0]
    assert item.occurrence_date == date(2026, 9, 2)
    # dc:date remains available too -- both are preserved independently.
    assert item.pub_date == datetime(2026, 9, 2, 9, 47, 53, tzinfo=UTC)


def test_item_missing_pub_date_is_omitted_and_counted_invalid() -> None:
    result = parse_rss_items(_MISSING_PUBDATE_FEED)
    assert result.items == ()
    assert result.invalid_count == 1


def test_naive_pub_date_with_no_offset_is_omitted_and_counted_invalid() -> None:
    result = parse_rss_items(_NAIVE_PUBDATE_FEED)
    assert result.items == ()
    assert result.invalid_count == 1


def test_empty_channel_is_a_valid_empty_result() -> None:
    empty = '<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
    result = parse_rss_items(empty)
    assert result.items == ()
    assert result.invalid_count == 0


# --- FX-52AH: malformed-document detection (distinct from valid-empty) -----


def test_html_error_page_raises_malformed_feed_error() -> None:
    html = "<html><head><title>Access Denied</title></head><body></body></html>"
    with pytest.raises(MalformedFeedError):
        parse_rss_items(html)


def test_non_xml_garbage_raises_malformed_feed_error() -> None:
    with pytest.raises(MalformedFeedError):
        parse_rss_items("this is not xml at all {{{")


def test_valid_xml_but_wrong_root_raises_malformed_feed_error() -> None:
    unrelated_xml = '<?xml version="1.0"?><somethingElse><a>1</a></somethingElse>'
    with pytest.raises(MalformedFeedError):
        parse_rss_items(unrelated_xml)


def test_empty_string_raises_malformed_feed_error() -> None:
    with pytest.raises(MalformedFeedError):
        parse_rss_items("")

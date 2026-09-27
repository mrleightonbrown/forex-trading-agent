"""FX-52A: unit tests for the minimal RSS 2.0 / RDF-RSS-1.0 parser."""

from datetime import UTC, datetime

from forex_agent.infrastructure.economic_calendar_sources.rss_parsing import parse_rss_items

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
    items = parse_rss_items(_RSS2_FEED)
    assert len(items) == 1
    item = items[0]
    assert item.title == "GDP quarterly national accounts, UK: April to June 2026"
    assert item.pub_date == datetime(2026, 9, 30, 6, 0, 0, tzinfo=UTC)
    assert "quarterlynationalaccounts" in item.link
    assert item.guid == item.link


def test_rdf_item_uses_about_attribute_as_guid_and_dc_date() -> None:
    items = parse_rss_items(_RDF_FEED)
    assert len(items) == 1
    item = items[0]
    assert item.guid == "https://www.bankofcanada.ca/2026/09/rate-announcement/"
    assert item.pub_date == datetime(2026, 9, 2, 9, 47, 53, tzinfo=UTC)
    assert item.title.startswith("Bank of Canada maintains the policy rate")


def test_item_missing_pub_date_is_omitted() -> None:
    items = parse_rss_items(_MISSING_PUBDATE_FEED)
    assert items == ()


def test_naive_pub_date_with_no_offset_is_omitted() -> None:
    items = parse_rss_items(_NAIVE_PUBDATE_FEED)
    assert items == ()


def test_empty_channel_returns_empty_tuple() -> None:
    empty = '<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
    assert parse_rss_items(empty) == ()

"""FX-58 Section 53: deterministic normalization matrix for
`normalize_text`/`normalize_canonical_url` -- pure, no I/O."""

from forex_agent.domain.news_text_normalization import normalize_canonical_url, normalize_text

# --- normalize_text ---------------------------------------------------------


def test_case_difference_normalizes_equal() -> None:
    assert normalize_text("Hello World") == normalize_text("hello world")


def test_repeated_whitespace_normalizes_equal() -> None:
    assert normalize_text("hello   world") == normalize_text("hello world")
    assert normalize_text("  hello world  ") == normalize_text("hello world")
    assert normalize_text("hello\n\tworld") == normalize_text("hello world")


def test_unicode_nfkc_equivalent_forms_normalize_equal() -> None:
    # U+FB01 LATIN SMALL LIGATURE FI vs plain "fi".
    assert normalize_text("ﬁle") == normalize_text("file")
    # Fullwidth digits (U+FF10-FF19) vs ASCII digits.
    assert normalize_text("２０２６") == normalize_text("2026")  # noqa: RUF001


def test_html_entities_normalize_equal() -> None:
    assert normalize_text("Bank &amp; Canada") == normalize_text("Bank & Canada")
    assert normalize_text("caf&eacute;") == normalize_text("café")


def test_punctuation_differences_remain_different() -> None:
    assert normalize_text("Hello, World") != normalize_text("Hello World")
    assert normalize_text("rate: 2.25%") != normalize_text("rate 2.25%")


def test_word_order_differences_remain_different() -> None:
    assert normalize_text("Bank of Canada") != normalize_text("Canada of Bank")


# --- normalize_canonical_url ------------------------------------------------


def test_scheme_and_host_case_normalizes() -> None:
    assert normalize_canonical_url("HTTPS://WWW.Example.com/Path") == normalize_canonical_url(
        "https://www.example.com/Path"
    )


def test_fragment_is_ignored() -> None:
    assert normalize_canonical_url("https://example.com/a#frag1") == normalize_canonical_url(
        "https://example.com/a"
    )
    assert normalize_canonical_url("https://example.com/a#frag1") == normalize_canonical_url(
        "https://example.com/a#frag2"
    )


def test_query_string_is_preserved() -> None:
    assert normalize_canonical_url("https://example.com/a?x=1") != normalize_canonical_url(
        "https://example.com/a"
    )


def test_query_order_is_preserved_not_sorted() -> None:
    assert normalize_canonical_url("https://example.com/a?b=2&a=1") != normalize_canonical_url(
        "https://example.com/a?a=1&b=2"
    )


def test_trailing_slash_is_preserved() -> None:
    assert normalize_canonical_url("https://example.com/a/") != normalize_canonical_url(
        "https://example.com/a"
    )


def test_ecb_double_slash_path_is_preserved() -> None:
    url = "https://www.ecb.europa.eu//press/pr/date/2026/html/ecb.pr261002~abc.en.html"
    normalized = normalize_canonical_url(url)
    assert normalized is not None
    assert "//press/" in normalized


def test_different_path_remains_different() -> None:
    assert normalize_canonical_url("https://example.com/a") != normalize_canonical_url(
        "https://example.com/b"
    )


def test_blank_url_returns_none() -> None:
    assert normalize_canonical_url("") is None
    assert normalize_canonical_url("   ") is None


def test_url_with_no_scheme_or_host_returns_none() -> None:
    assert normalize_canonical_url("not a url") is None
    assert normalize_canonical_url("/just/a/path") is None


def test_do_not_remove_www() -> None:
    normalized = normalize_canonical_url("https://www.example.com/a")
    assert normalized is not None
    assert "www." in normalized

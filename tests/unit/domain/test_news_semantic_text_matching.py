from forex_agent.domain.news_semantic_text_matching import find_matched_phrases


def test_exact_phrase_matches() -> None:
    assert find_matched_phrases("The Federal Reserve held rates steady.", ("Federal Reserve",)) == (
        "Federal Reserve",
    )


def test_case_insensitive_match() -> None:
    assert find_matched_phrases("the FEDERAL reserve", ("Federal Reserve",)) == ("Federal Reserve",)


def test_cad_does_not_match_inside_decade() -> None:
    assert find_matched_phrases("growth over the coming decade", ("CAD",)) == ()


def test_rate_does_not_match_unrelated_substring() -> None:
    assert find_matched_phrases("the corporate rating agency", ("rate",)) == ()


def test_rate_matches_as_standalone_word() -> None:
    assert find_matched_phrases("the bank rate was held", ("rate",)) == ("rate",)


def test_multi_word_phrase_matches_with_boundaries() -> None:
    assert find_matched_phrases(
        "announcing today's monetary policy decision", ("monetary policy",)
    ) == ("monetary policy",)


def test_no_match_returns_empty_tuple() -> None:
    assert find_matched_phrases("nothing relevant here", ("Federal Reserve", "CPI")) == ()


def test_multiple_phrases_sorted_and_deduplicated() -> None:
    result = find_matched_phrases(
        "inflation and the consumer price index both rose", ("inflation", "consumer price index")
    )
    assert result == ("consumer price index", "inflation")


def test_phrase_with_period_abbreviation_matches_with_boundary() -> None:
    assert find_matched_phrases("growth in the U.S. economy", ("U.S.",)) == ("U.S.",)


def test_acronym_does_not_match_inside_longer_acronym() -> None:
    # "GDP" must not match inside "GDPR".
    assert find_matched_phrases("compliance with GDPR rules", ("GDP",)) == ()


def test_html_entity_and_whitespace_normalization() -> None:
    assert find_matched_phrases("the&nbsp;&nbsp;Federal   Reserve", ("Federal Reserve",)) == (
        "Federal Reserve",
    )

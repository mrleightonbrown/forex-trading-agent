"""FX-58/FX-58H Section 54/15/16: deterministic matcher matrix for
`classify_candidate_pair` (the AUTOMATIC `fx58_v2` policy -- exact
canonical URL / exact body text ONLY) and `detect_review_candidate`
(the demoted, non-persisted headline+summary signal). Section 26's
own critical anti-overmerge regression (ECB decision/account, speech/
interview) lives here too, alongside FX-58H's own real-data-shaped
BoC/Fed/GOV.UK regressions (Section 15)."""

from datetime import UTC, datetime

import pytest

from forex_agent.domain.news_canonicalization_matching import (
    CanonicalizationCandidate,
    classify_candidate_pair,
    detect_review_candidate,
)
from forex_agent.domain.news_canonicalization_method import NewsCanonicalizationMethod
from forex_agent.domain.news_canonicalization_review import NewsCanonicalizationReviewReason
from forex_agent.domain.timestamps import UtcTimestamp

_TS = UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))


def _candidate(
    key: str,
    *,
    headline: str = "A headline",
    summary: str | None = None,
    body_text: str | None = None,
    canonical_url: str | None = None,
) -> CanonicalizationCandidate:
    return CanonicalizationCandidate(
        news_item_key=key,
        first_seen_at=_TS,
        revision_sequence=0,
        availability=_TS,
        headline=headline,
        summary=summary,
        body_text=body_text,
        canonical_url=canonical_url,
    )


def test_exact_canonical_url_matches() -> None:
    a = _candidate("a", canonical_url="https://example.com/x")
    b = _candidate("b", headline="Different", canonical_url="https://example.com/x")
    assert classify_candidate_pair(a, b) is NewsCanonicalizationMethod.EXACT_CANONICAL_URL


def test_exact_body_over_200_matches() -> None:
    body = "x" * 200
    a = _candidate("a", body_text=body)
    b = _candidate("b", headline="Different", body_text=body)
    assert classify_candidate_pair(a, b) is NewsCanonicalizationMethod.EXACT_BODY_TEXT


def test_same_body_under_200_does_not_match() -> None:
    body = "x" * 199
    a = _candidate("a", body_text=body)
    b = _candidate("b", body_text=body)
    assert classify_candidate_pair(a, b) is None


def test_exact_headline_and_summary_over_80_is_review_only_not_automatic() -> None:
    # FX-58H Section 4/5/10: this signal is NO LONGER an automatic
    # method -- it is demoted to a review-only candidate, a
    # genuinely different TYPE (`NewsCanonicalizationReviewReason`),
    # never a `NewsCanonicalizationMethod`.
    summary = "s" * 80
    a = _candidate("a", headline="Same Headline", summary=summary)
    b = _candidate("b", headline="Same Headline", summary=summary)
    assert classify_candidate_pair(a, b) is None
    assert (
        detect_review_candidate(a, b) is NewsCanonicalizationReviewReason.EXACT_HEADLINE_AND_SUMMARY
    )


def test_exact_headline_and_short_summary_does_not_match_either_function() -> None:
    summary = "s" * 79
    a = _candidate("a", headline="Same Headline", summary=summary)
    b = _candidate("b", headline="Same Headline", summary=summary)
    assert classify_candidate_pair(a, b) is None
    assert detect_review_candidate(a, b) is None


def test_exact_headline_only_does_not_match() -> None:
    a = _candidate("a", headline="Same Headline")
    b = _candidate("b", headline="Same Headline")
    assert classify_candidate_pair(a, b) is None
    assert detect_review_candidate(a, b) is None


def test_exact_summary_only_does_not_match() -> None:
    summary = "s" * 200
    a = _candidate("a", headline="Headline A", summary=summary)
    b = _candidate("b", headline="Headline B", summary=summary)
    assert classify_candidate_pair(a, b) is None
    assert detect_review_candidate(a, b) is None


def test_same_pub_date_only_does_not_match() -> None:
    # Section 22: no time-only heuristic exists at all -- there is
    # nothing in CanonicalizationCandidate for pubDate/retrieved_at
    # to even feed into this function; two otherwise-unrelated
    # candidates never match on timing alone.
    a = _candidate("a", headline="Headline A")
    b = _candidate("b", headline="Headline B")
    assert classify_candidate_pair(a, b) is None
    assert detect_review_candidate(a, b) is None


def test_same_source_content_type_only_does_not_match() -> None:
    # Section 25: source_content_type is not even a field on
    # CanonicalizationCandidate -- confirming it cannot influence
    # matching at all.
    assert not hasattr(_candidate("a"), "source_content_type")


def test_fuzzy_looking_title_does_not_match() -> None:
    a = _candidate("a", headline="Bank of Canada increases its policy rate")
    b = _candidate("b", headline="Bank of Canada raises its policy rate")
    assert classify_candidate_pair(a, b) is None
    assert detect_review_candidate(a, b) is None


def test_related_ecb_decision_and_account_do_not_match() -> None:
    # Section 26's own critical anti-overmerge regression: an ECB
    # monetary-policy decision and the monetary_policy_account
    # published four weeks later about the SAME meeting must remain
    # distinct -- different URL, different (or absent) body/summary,
    # different headline.
    decision = _candidate(
        "ecb-decision",
        headline="Monetary policy decisions",
        canonical_url="https://www.ecb.europa.eu//press/pr/date/2026/html/ecb.pr260910~x.en.html",
        summary=None,
        body_text=None,
    )
    account = _candidate(
        "ecb-account",
        headline="Meeting of 9-10 September 2026",
        canonical_url=(
            "https://www.ecb.europa.eu//press/accounts/2026/html/ecb.mg261008~y.en.html"
        ),
        summary=None,
        body_text=None,
    )
    assert classify_candidate_pair(decision, account) is None
    assert detect_review_candidate(decision, account) is None


def test_related_speech_and_decision_do_not_match() -> None:
    decision = _candidate(
        "ecb-decision-2",
        headline="Monetary policy decisions",
        canonical_url="https://www.ecb.europa.eu//press/pr/date/2026/html/ecb.pr260910~a.en.html",
    )
    speech = _candidate(
        "ecb-speech",
        headline="Christine Lagarde: press conference introductory statement",
        canonical_url=(
            "https://www.ecb.europa.eu//press/key/date/2026/html/ecb.sp260910~b.en.html"
        ),
    )
    assert classify_candidate_pair(decision, speech) is None
    assert detect_review_candidate(decision, speech) is None


def test_related_statcan_cpi_and_boc_speech_do_not_match() -> None:
    cpi = _candidate(
        "statcan-cpi",
        headline="Consumer Price Index, August 2026",
        summary="The Consumer Price Index rose 2.1% in the 12 months to August.",
    )
    speech = _candidate(
        "boc-speech",
        headline="Remarks on inflation and the economic outlook",
        summary="The Bank of Canada discussed recent inflation developments.",
    )
    assert classify_candidate_pair(cpi, speech) is None
    assert detect_review_candidate(cpi, speech) is None


def test_same_pair_matching_multiple_rules_returns_one_strongest_method() -> None:
    body = "x" * 200
    summary = "s" * 80
    a = _candidate(
        "a",
        headline="Same Headline",
        summary=summary,
        body_text=body,
        canonical_url="https://example.com/x",
    )
    b = _candidate(
        "b",
        headline="Same Headline",
        summary=summary,
        body_text=body,
        canonical_url="https://example.com/x",
    )
    # URL, body, AND the (now review-only) headline+summary signal
    # all independently match -- URL must win (precedence), and only
    # ONE automatic method is ever returned. The orchestrator
    # (CanonicalizeNewsOnce), not this pure function, is responsible
    # for never ALSO reporting this pair as needing review once an
    # automatic method already matched (FX-58H Section 12; see
    # test_canonicalize_news_once.py for that control-flow test).
    assert classify_candidate_pair(a, b) is NewsCanonicalizationMethod.EXACT_CANONICAL_URL


def test_self_pair_raises() -> None:
    a = _candidate("a")
    with pytest.raises(ValueError):
        classify_candidate_pair(a, a)
    with pytest.raises(ValueError):
        detect_review_candidate(a, a)


# --- FX-58H Section 15: real-data-shaped false-positive regressions -------


def test_a_boc_rate_decision_style_items_are_review_only_not_automatic() -> None:
    # Three distinct Bank of Canada rate-decision press releases,
    # different dates/URLs, sharing byte-identical boilerplate
    # (unchanged-rate outcome) summary text.
    summary = (
        "The Bank of Canada today held its target for the overnight rate at 2.25%, "
        "with the Bank Rate at 2.5% and the deposit rate at 2.20%."
    )
    headline = "Bank of Canada maintains the policy rate at 2.25%"
    june = _candidate(
        "boc-june",
        headline=headline,
        summary=summary,
        canonical_url="https://www.bankofcanada.ca/2026/06/fad-press-release-2026-06-10/",
    )
    july = _candidate(
        "boc-july",
        headline=headline,
        summary=summary,
        canonical_url="https://www.bankofcanada.ca/2026/07/fad-press-release-2026-07-15/",
    )
    september = _candidate(
        "boc-sept",
        headline=headline,
        summary=summary,
        canonical_url="https://www.bankofcanada.ca/2026/09/fad-press-release-2026-09-02/",
    )
    for pair in ((june, july), (june, september), (july, september)):
        assert classify_candidate_pair(*pair) is None
        assert (
            detect_review_candidate(*pair)
            is NewsCanonicalizationReviewReason.EXACT_HEADLINE_AND_SUMMARY
        )


def test_b_fed_testimony_style_recurring_institutional_text_is_review_only() -> None:
    # Two distinct Federal Reserve testimony dates sharing a standing
    # committee-name boilerplate as their own "summary" field.
    summary = "Testimony Before the Committee on Financial Services, U.S. House of Representatives"
    headline = "Powell, Semiannual Monetary Policy Report to the Congress"
    first = _candidate(
        "fed-2024",
        headline=headline,
        summary=summary,
        canonical_url="https://www.federalreserve.gov/newsevents/testimony/powell20240306a.htm",
    )
    second = _candidate(
        "fed-2025",
        headline=headline,
        summary=summary,
        canonical_url="https://www.federalreserve.gov/newsevents/testimony/powell20250624a.htm",
    )
    assert classify_candidate_pair(first, second) is None
    assert (
        detect_review_candidate(first, second)
        is NewsCanonicalizationReviewReason.EXACT_HEADLINE_AND_SUMMARY
    )


def test_c_govuk_ambiguous_duplicate_slug_pair_is_review_only_never_automatic() -> None:
    # Section 15.C: the GOV.UK pair's own real ambiguity (genuinely
    # the same republished announcement, or two separate ones sharing
    # identical boilerplate) is deliberately NOT resolved either way
    # here -- only that it is review-only, never automatic.
    headline = "More overseas firms enticed to buy British"
    summary = (
        "Overseas buyers will be offered a new UK Export Finance loan guarantee to "
        "incentivise buying goods and services from British companies."
    )
    first = _candidate(
        "govuk-a",
        headline=headline,
        summary=summary,
        canonical_url="https://www.gov.uk/government/news/more-overseas-firms-enticed-to-buy-british",
    )
    second = _candidate(
        "govuk-b",
        headline=headline,
        summary=summary,
        canonical_url=(
            "https://www.gov.uk/government/news/more-overseas-firms-enticed-to-buy-british--2"
        ),
    )
    assert classify_candidate_pair(first, second) is None
    assert (
        detect_review_candidate(first, second)
        is NewsCanonicalizationReviewReason.EXACT_HEADLINE_AND_SUMMARY
    )

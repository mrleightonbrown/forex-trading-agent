"""FX-59 Section 23: deterministic, phrase/token-boundary-safe text
matching -- a SEPARATE concern from `news_text_normalization`'s own
FX-58 exact-match normalization (reused here for case-folding/
whitespace/Unicode consistency), since FX-59 needs substring-WITH-
BOUNDARIES matching, never naive substring containment.

Explicit regressions this module exists to satisfy (Section 23):
`"CAD"` must not match inside `"decade"`; a bare pronoun `"us"` must
not match an (intentionally never-added, see Section 25) bare `"US"`
alias; `"rate"` must not match an unrelated longer word containing it
as a substring. No fuzzy/stemming/tokenization matching of any kind --
a phrase must appear VERBATIM (after normalization), with a non-word
character (or the text boundary) on both sides."""

import re

from forex_agent.domain.news_text_normalization import normalize_text

_NON_WORD_BOUNDARY = r"(?<!\w)"
_NON_WORD_LOOKAHEAD = r"(?!\w)"


def find_matched_phrases(text: str, phrases: tuple[str, ...]) -> tuple[str, ...]:
    """Returns the subset of `phrases` that appear VERBATIM in `text`
    (both normalized via `normalize_text`), each bounded by a non-word
    character or a text edge on both sides -- never a naive substring
    match. The ORIGINAL (not normalized) phrase strings are returned,
    as a canonical sorted, deduplicated tuple, so callers can persist
    them directly as evidence (FX-59 Section 34)."""
    normalized_text = normalize_text(text)
    matched: set[str] = set()
    for phrase in phrases:
        normalized_phrase = normalize_text(phrase)
        if not normalized_phrase:
            continue
        pattern = re.compile(
            _NON_WORD_BOUNDARY + re.escape(normalized_phrase) + _NON_WORD_LOOKAHEAD
        )
        if pattern.search(normalized_text):
            matched.add(phrase)
    return tuple(sorted(matched))

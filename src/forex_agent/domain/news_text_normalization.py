"""FX-58: pure, deterministic normalization helpers used ONLY for
exact-match comparison -- never for display, storage, or any other
purpose. No fuzzy matching anywhere in this module (Section 18/24):
no stemming, no stopword removal, no tokenization, no translation,
no language detection, no embeddings, no edit distance. Low recall is
an accepted, deliberate cost; false equivalence is not.
"""

import html
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

_WHITESPACE_RUN_RE = re.compile(r"\s+")


def normalize_text(raw: str) -> str:
    """Unicode NFKC normalization, HTML entity unescape, outer-
    whitespace trim, internal whitespace-run collapse, casefold
    (Section 18). Used for exact headline/summary/body comparison
    only -- punctuation, word order, and spelling are all left
    exactly as-is, so two texts differing in any of those remain
    different."""
    unescaped = html.unescape(raw)
    normalized_form = unicodedata.normalize("NFKC", unescaped)
    collapsed = _WHITESPACE_RUN_RE.sub(" ", normalized_form.strip())
    return collapsed.casefold()


def normalize_canonical_url(raw: str) -> str | None:
    """Minimal URL normalization for exact-match comparison only
    (Section 17): trim surrounding whitespace, lowercase scheme and
    hostname, discard the fragment -- path (including any duplicate
    slashes, e.g. ECB's own deliberate `//press/...`), query string
    (including its own ordering), and trailing-slash presence are all
    preserved EXACTLY as supplied. Returns `None` if `raw` is blank or
    does not parse as an absolute URL with both a scheme and a host --
    a URL that fails to parse simply does not participate in matching;
    it does NOT make the owning item invalid."""
    stripped = raw.strip()
    if not stripped:
        return None
    try:
        parts = urlsplit(stripped)
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))

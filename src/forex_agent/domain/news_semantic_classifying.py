"""FX-59: the deterministic, local, rule-based `fx59_v1` semantic
classifier (Section 5/6) -- no LLM calls, no embeddings, no
statistical NER, no cloud NLP APIs, no zero-shot classification, no
fuzzy semantic similarity, no web search, no external news metadata
anywhere in this module. Curated source profiles + deterministic
text rules only, so the result is reproducible and auditable.

`classify_news_semantics` is a PURE function (Section 47): no DB, no
clock, no HTTP, no randomness, no OS-level configuration lookup. For
the same
candidate and the SAME registry version below, it always returns an
identical `NewsSemanticClassification`.

Text matching uses ONLY `headline`/`summary`/`body_text` (Section 22)
-- never the canonical URL, external item id, source timestamps, raw
provider payload, or any filename/path token. Source-profile facts
(publisher institution/jurisdiction/primary currency) are never
inferred from text (Section 19); explicit curated aliases (Sections
24/25/29/30) are deliberately conservative, with safe phrase/token
boundaries (`news_semantic_text_matching.find_matched_phrases`) --
never naive substring matching (Section 23)."""

from dataclasses import dataclass

from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification
from forex_agent.domain.news_semantic_source_profile import get_source_semantic_profile
from forex_agent.domain.news_semantic_text_matching import find_matched_phrases
from forex_agent.domain.news_topic import NewsTopic
from forex_agent.domain.news_topic_annotation import NewsTopicAnnotation
from forex_agent.domain.timestamps import UtcTimestamp

# --- Section 17/24: curated institution aliases (conservative, exact
# institutional names only -- no ambiguous bare abbreviations). ------------

INSTITUTION_ALIASES: dict[str, tuple[str, ...]] = {
    "FEDERAL_RESERVE": ("Federal Reserve", "Federal Reserve Board"),
    "FEDERAL_OPEN_MARKET_COMMITTEE": ("Federal Open Market Committee", "FOMC"),
    "EUROPEAN_CENTRAL_BANK": ("European Central Bank", "ECB"),
    "BANK_OF_ENGLAND": ("Bank of England",),
    "HM_TREASURY": ("HM Treasury", "His Majesty's Treasury"),
    "STATISTICS_CANADA": ("Statistics Canada", "StatCan"),
    "BANK_OF_CANADA": ("Bank of Canada",),
}

# --- Section 17/25: curated jurisdiction aliases. Deliberately no bare
# "US" (Section 25: case-folding makes it indistinguishable from the
# pronoun "us"). ------------------------------------------------------------

JURISDICTION_ALIASES: dict[str, tuple[str, ...]] = {
    "UNITED_STATES": ("United States", "U.S."),
    "EURO_AREA": ("euro area", "eurozone"),
    "UNITED_KINGDOM": ("United Kingdom", "U.K.", "Britain", "British"),
    "CANADA": ("Canada", "Canadian"),
}

# --- Section 29: curated, conservative currency-mention aliases. Bare
# "dollar" is deliberately never included (Section 29's own explicit
# prohibition). -------------------------------------------------------------

CURRENCY_ALIASES: dict[str, tuple[str, ...]] = {
    "USD": ("USD", "U.S. dollar", "US dollar", "United States dollar"),
    "EUR": ("EUR", "euro", "euros"),
    "GBP": ("GBP", "sterling", "pound sterling", "British pound"),
    "CAD": ("CAD", "Canadian dollar"),
}

# --- Section 30: explicit institution mention -> associated currency. -----

INSTITUTION_TO_CURRENCY: dict[str, str] = {
    "FEDERAL_RESERVE": "USD",
    "FEDERAL_OPEN_MARKET_COMMITTEE": "USD",
    "EUROPEAN_CENTRAL_BANK": "EUR",
    "BANK_OF_ENGLAND": "GBP",
    "HM_TREASURY": "GBP",
    "STATISTICS_CANADA": "CAD",
    "BANK_OF_CANADA": "CAD",
}

# --- Sections 35-43: the closed v1 topic taxonomy's own curated,
# conservative exact-phrase rules. -------------------------------------

TOPIC_RULES: dict[NewsTopic, tuple[str, ...]] = {
    NewsTopic.MONETARY_POLICY: (
        "monetary policy",
        "federal funds rate",
        "policy rate",
        "bank rate",
        "target for the overnight rate",
        "overnight rate",
        "interest rates",
        "interest rate decision",
    ),
    NewsTopic.INFLATION_PRICES: (
        "inflation",
        "consumer price index",
        "CPI",
        "harmonised index of consumer prices",
        "harmonized index of consumer prices",
        "HICP",
        "PCE inflation",
        "price pressures",
    ),
    NewsTopic.LABOUR_EMPLOYMENT: (
        "labour market",
        "labor market",
        "employment",
        "unemployment",
        "payrolls",
        "nonfarm payrolls",
        "wage growth",
        "wages",
        "earnings growth",
    ),
    NewsTopic.GROWTH_ACTIVITY: (
        "gross domestic product",
        "GDP",
        "economic growth",
        "economic activity",
        "output growth",
        "real GDP",
    ),
    NewsTopic.INTERNATIONAL_TRADE: (
        "international trade",
        "trade balance",
        "exports",
        "imports",
        "current account",
    ),
    NewsTopic.FISCAL_POLICY: (
        "fiscal policy",
        "budget",
        "taxation",
        "public spending",
        "government borrowing",
        "public finances",
        "government debt",
    ),
    NewsTopic.FINANCIAL_STABILITY: (
        "financial stability",
        "systemic risk",
        "financial system",
        "stress test",
        "stress testing",
    ),
    NewsTopic.BANKING_REGULATION: (
        "bank supervision",
        "banking supervision",
        "bank regulation",
        "banking regulation",
        "prudential regulation",
        "capital requirements",
        "liquidity requirements",
    ),
    NewsTopic.EXCHANGE_RATES: (
        "exchange rate",
        "exchange rates",
        "foreign exchange",
        "FX market",
        "currency market",
        "currency markets",
    ),
}


@dataclass(frozen=True, slots=True)
class NewsSemanticClassificationCandidate:
    """The current evidence FTA would classify for one `NewsItem`
    (FX-59 Section 50) -- built from that item's own identity, its
    source_key (for source-profile lookup), and the ONE `NewsItem
    Vintage` actually used (its latest evidence-eligible vintage as of
    the run, mirroring FX-58's own `CanonicalizationCandidate`,
    Section 13). Carries no parsing logic of its own; a repository
    projects this directly from already-persisted, already-validated
    `NewsItem`/`NewsSourceMapping`/`NewsItemVintage` rows."""

    news_item_key: str
    source_key: str
    basis_news_item_revision_sequence: int
    basis_availability: UtcTimestamp
    headline: str
    summary: str | None
    body_text: str | None
    source_content_type: str | None
    source_channel: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.news_item_key, str) or not self.news_item_key.strip():
            raise ValueError(
                f"news_item_key must be a non-empty string, got {self.news_item_key!r}"
            )
        if not isinstance(self.source_key, str) or not self.source_key.strip():
            raise ValueError(f"source_key must be a non-empty string, got {self.source_key!r}")
        if self.basis_news_item_revision_sequence < 0:
            raise ValueError(
                "basis_news_item_revision_sequence must not be negative, got "
                f"{self.basis_news_item_revision_sequence}"
            )
        if not isinstance(self.basis_availability, UtcTimestamp):
            raise TypeError(
                "basis_availability must be a UtcTimestamp, got "
                f"{type(self.basis_availability).__name__}"
            )
        if not isinstance(self.headline, str) or not self.headline.strip():
            raise ValueError(f"headline must be a non-empty string, got {self.headline!r}")


def classify_news_semantics(
    candidate: NewsSemanticClassificationCandidate,
) -> NewsSemanticClassification:
    """The pure `fx59_v1` classifier -- see the module docstring.
    Raises `UnsupportedNewsSemanticSourceError` (Section 20) if
    `candidate.source_key` has no registered `NewsSemanticSourceProfile`."""
    profile = get_source_semantic_profile(candidate.source_key)
    combined_text = " ".join(
        text for text in (candidate.headline, candidate.summary, candidate.body_text) if text
    )

    entity_evidence: dict[tuple[NewsEntityType, str], set[NewsEntityEvidenceKind]] = {}

    def _add_entity(
        entity_type: NewsEntityType, entity_key: str, kind: NewsEntityEvidenceKind
    ) -> None:
        entity_evidence.setdefault((entity_type, entity_key), set()).add(kind)

    # Section 19: source-profile entities are always present, never
    # inferred from text.
    _add_entity(
        NewsEntityType.INSTITUTION,
        profile.institution_entity_key,
        NewsEntityEvidenceKind.SOURCE_PROFILE,
    )
    _add_entity(
        NewsEntityType.JURISDICTION,
        profile.jurisdiction_entity_key,
        NewsEntityEvidenceKind.SOURCE_PROFILE,
    )

    for institution_key, aliases in INSTITUTION_ALIASES.items():
        if find_matched_phrases(combined_text, aliases):
            _add_entity(
                NewsEntityType.INSTITUTION, institution_key, NewsEntityEvidenceKind.TEXT_ALIAS
            )
    for jurisdiction_key, aliases in JURISDICTION_ALIASES.items():
        if find_matched_phrases(combined_text, aliases):
            _add_entity(
                NewsEntityType.JURISDICTION, jurisdiction_key, NewsEntityEvidenceKind.TEXT_ALIAS
            )

    entities = tuple(
        sorted(
            (
                NewsEntityAnnotation(
                    entity_type=entity_type,
                    entity_key=entity_key,
                    evidence=tuple(sorted(kinds, key=lambda k: k.value)),
                )
                for (entity_type, entity_key), kinds in entity_evidence.items()
            ),
            key=lambda e: (e.entity_type.value, e.entity_key),
        )
    )

    currency_reasons: dict[str, set[NewsCurrencyRelevanceReason]] = {}

    def _add_currency(currency_code: str, reason: NewsCurrencyRelevanceReason) -> None:
        currency_reasons.setdefault(currency_code, set()).add(reason)

    # Section 28: every classified item gets its source's own primary
    # currency relevance, always with this one reason.
    _add_currency(profile.primary_currency, NewsCurrencyRelevanceReason.SOURCE_JURISDICTION)

    # Section 29: explicit currency mentions.
    for currency_code, aliases in CURRENCY_ALIASES.items():
        if find_matched_phrases(combined_text, aliases):
            _add_currency(currency_code, NewsCurrencyRelevanceReason.EXPLICIT_CURRENCY_MENTION)

    # Section 30: an explicit TEXT mention of a mapped institution adds
    # its associated currency relevance -- deliberately keyed off
    # TEXT_ALIAS evidence only (never off a bare SOURCE_PROFILE-only
    # institution that the text itself never actually names).
    for (entity_type, entity_key), kinds in entity_evidence.items():
        if entity_type is not NewsEntityType.INSTITUTION:
            continue
        if NewsEntityEvidenceKind.TEXT_ALIAS not in kinds:
            continue
        mapped_currency = INSTITUTION_TO_CURRENCY.get(entity_key)
        if mapped_currency is not None:
            _add_currency(mapped_currency, NewsCurrencyRelevanceReason.EXPLICIT_INSTITUTION_MENTION)

    currency_relevance = tuple(
        sorted(
            (
                NewsCurrencyRelevance(
                    currency_code=code, reasons=tuple(sorted(reasons, key=lambda r: r.value))
                )
                for code, reasons in currency_reasons.items()
            ),
            key=lambda r: r.currency_code,
        )
    )

    topic_annotations = []
    for topic, phrases in TOPIC_RULES.items():
        matched_terms = find_matched_phrases(combined_text, phrases)
        if matched_terms:
            topic_annotations.append(NewsTopicAnnotation(topic=topic, matched_terms=matched_terms))
    topics = tuple(sorted(topic_annotations, key=lambda t: t.topic.value))

    return NewsSemanticClassification(
        entities=entities, topics=topics, currency_relevance=currency_relevance
    )

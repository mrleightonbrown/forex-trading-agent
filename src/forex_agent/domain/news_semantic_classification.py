from dataclasses import dataclass

from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_topic_annotation import NewsTopicAnnotation


@dataclass(frozen=True, slots=True)
class NewsSemanticClassification:
    """One deterministic classification result (FX-59 Section 7/47) --
    what `classify_news_semantics` (a pure function) returns, and what
    `NewsSemanticAnnotationVintage` persists verbatim.

    All three collections are canonical and deterministic (Section
    48): `entities` sorted by `(entity_type, entity_key)`, `topics`
    sorted by `NewsTopic`'s own enum value, `currency_relevance`
    sorted by ISO currency code -- each with no duplicate identity.
    Domain validation rejects a duplicate/noncanonical structure
    outright, rather than relying only on the classifier producing one
    correctly (Section 48's own "domain validation should reject...
    rather than relying only on the classifier").

    `entities`/`currency_relevance` are both required non-empty
    (Section 57's own storage preference, enforced here too): every
    classified item has at least its own source-profile institution +
    jurisdiction, and at least its own source's primary currency.
    `topics` may legitimately be empty (Section 33/81) -- a small,
    deliberately conservative taxonomy will not match every story, and
    that is not a failure."""

    entities: tuple[NewsEntityAnnotation, ...]
    topics: tuple[NewsTopicAnnotation, ...]
    currency_relevance: tuple[NewsCurrencyRelevance, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entities, tuple) or not self.entities:
            raise ValueError(f"entities must be a non-empty tuple, got {self.entities!r}")
        for entity in self.entities:
            if not isinstance(entity, NewsEntityAnnotation):
                raise TypeError(
                    "each entities entry must be a NewsEntityAnnotation, got "
                    f"{type(entity).__name__}"
                )
        entity_identities = [(e.entity_type, e.entity_key) for e in self.entities]
        if len(set(entity_identities)) != len(entity_identities):
            raise ValueError("entities must not contain a duplicate (entity_type, entity_key) pair")
        canonical_entities = tuple(sorted(self.entities, key=_entity_sort_key))
        if self.entities != canonical_entities:
            raise ValueError(
                f"entities must be in canonical sorted order, got {self.entities!r}, "
                f"expected {canonical_entities!r}"
            )

        if not isinstance(self.topics, tuple):
            raise TypeError(f"topics must be a tuple, got {type(self.topics).__name__}")
        for topic_annotation in self.topics:
            if not isinstance(topic_annotation, NewsTopicAnnotation):
                raise TypeError(
                    "each topics entry must be a NewsTopicAnnotation, got "
                    f"{type(topic_annotation).__name__}"
                )
        topic_identities = [t.topic for t in self.topics]
        if len(set(topic_identities)) != len(topic_identities):
            raise ValueError(f"topics must not contain a duplicate NewsTopic, got {self.topics!r}")
        canonical_topics = tuple(sorted(self.topics, key=lambda t: t.topic.value))
        if self.topics != canonical_topics:
            raise ValueError(
                f"topics must be in canonical sorted order, got {self.topics!r}, "
                f"expected {canonical_topics!r}"
            )

        if not isinstance(self.currency_relevance, tuple) or not self.currency_relevance:
            raise ValueError(
                f"currency_relevance must be a non-empty tuple, got {self.currency_relevance!r}"
            )
        for relevance in self.currency_relevance:
            if not isinstance(relevance, NewsCurrencyRelevance):
                raise TypeError(
                    "each currency_relevance entry must be a NewsCurrencyRelevance, got "
                    f"{type(relevance).__name__}"
                )
        currency_codes = [r.currency_code for r in self.currency_relevance]
        if len(set(currency_codes)) != len(currency_codes):
            raise ValueError(
                f"currency_relevance must not contain a duplicate currency_code, got "
                f"{self.currency_relevance!r}"
            )
        canonical_currency_relevance = tuple(
            sorted(self.currency_relevance, key=lambda r: r.currency_code)
        )
        if self.currency_relevance != canonical_currency_relevance:
            raise ValueError(
                f"currency_relevance must be in canonical sorted order, got "
                f"{self.currency_relevance!r}, expected {canonical_currency_relevance!r}"
            )


def _entity_sort_key(entity: NewsEntityAnnotation) -> tuple[str, str]:
    assert isinstance(entity.entity_type, NewsEntityType)
    return (entity.entity_type.value, entity.entity_key)

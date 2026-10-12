from dataclasses import dataclass

from forex_agent.domain._guards import require_currency_code
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason


@dataclass(frozen=True, slots=True)
class NewsCurrencyRelevance:
    """One currency FTA's `fx59_v1` classifier found relevant for one
    `NewsItem`, with canonical, auditable reasons -- no numeric score,
    no confidence percentage, no rank (FX-59 Section 26).

    A currency may carry more than one reason (Section 27); every
    reason it carries is consolidated into THIS one entry's own
    `reasons` tuple -- a currency never appears twice for the same
    item."""

    currency_code: str
    reasons: tuple[NewsCurrencyRelevanceReason, ...]

    def __post_init__(self) -> None:
        require_currency_code("currency_code", self.currency_code)
        if not isinstance(self.reasons, tuple) or not self.reasons:
            raise ValueError(f"reasons must be a non-empty tuple, got {self.reasons!r}")
        for reason in self.reasons:
            if not isinstance(reason, NewsCurrencyRelevanceReason):
                raise TypeError(
                    "each reasons entry must be a NewsCurrencyRelevanceReason, got "
                    f"{type(reason).__name__}"
                )
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError(f"reasons must not contain duplicates, got {self.reasons!r}")
        canonical_reasons = tuple(sorted(self.reasons, key=lambda r: r.value))
        if self.reasons != canonical_reasons:
            raise ValueError(
                f"reasons must be in canonical sorted order, got {self.reasons!r}, "
                f"expected {canonical_reasons!r}"
            )

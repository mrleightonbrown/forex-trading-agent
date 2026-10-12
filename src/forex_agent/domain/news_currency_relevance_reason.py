from enum import Enum


class NewsCurrencyRelevanceReason(Enum):
    """FX-59 Section 27: WHY a currency is considered relevant to one
    `NewsItem` -- categorical, auditable evidence, never a numeric
    score/confidence/rank (Section 26).

    `SOURCE_JURISDICTION`: this is the publishing source's OWN primary
    currency (FX-59 Section 28) -- always present, exactly once per
    classified item.
    `EXPLICIT_CURRENCY_MENTION`: the item's own text explicitly names
    this currency (Section 29), via a curated, conservative alias list.
    `EXPLICIT_INSTITUTION_MENTION`: the item's own text explicitly
    names an institution mapped to this currency (Section 30) -- e.g. a
    Bank of Canada item that explicitly mentions the European Central
    Bank adds EUR with this reason.

    Jurisdiction-mention-alone (e.g. "Canada") never adds a reason on
    its own (Section 31) -- deliberately no `JURISDICTION_MENTION`
    member exists here."""

    SOURCE_JURISDICTION = "SOURCE_JURISDICTION"
    EXPLICIT_CURRENCY_MENTION = "EXPLICIT_CURRENCY_MENTION"
    EXPLICIT_INSTITUTION_MENTION = "EXPLICIT_INSTITUTION_MENTION"

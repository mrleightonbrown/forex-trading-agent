from enum import Enum


class MacroCategory(Enum):
    """The kind of structured macro/fundamental series a
    `MacroSeriesDefinition` describes (FX-41).

    Deliberately a small, closed set matching exactly what
    `docs/DECISIONS.md`'s FX-41 entry names as the architecture's
    initial scope — not a general economic-data taxonomy. Extending
    this enum is cheap (a new member) precisely because nothing else
    in the domain model branches on specific category values; adding
    one is not itself "ingesting a new provider" or "building a new
    strategy."
    """

    POLICY_RATE = "POLICY_RATE"
    INFLATION = "INFLATION"
    EMPLOYMENT = "EMPLOYMENT"
    GROWTH = "GROWTH"

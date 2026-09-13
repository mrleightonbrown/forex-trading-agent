from enum import Enum


class TradeSide(Enum):
    """Direction of a trade. See `Price.entry_price`/`Price.exit_price` for
    the bid/ask convention CLAUDE.md requires for each side."""

    LONG = "LONG"
    SHORT = "SHORT"

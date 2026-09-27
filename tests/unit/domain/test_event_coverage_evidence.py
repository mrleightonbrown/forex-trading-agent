"""FX-54: unit tests for `build_coverage_evidence` -- structural
coverage limitations, derived purely from the canonical indicator
registry (no I/O, no repository access)."""

from forex_agent.domain.event_coverage_evidence import build_coverage_evidence


def test_gbp_usd_reports_tracked_indicators_for_both_sides() -> None:
    coverage = build_coverage_evidence("GBP", "USD")

    assert coverage.base_currency == "GBP"
    assert coverage.quote_currency == "USD"
    assert coverage.tracked_indicator_keys_by_currency == (
        ("GBP", ("GBP_GDP_QOQ",)),
        ("USD", ("US_CPI_YOY", "US_NONFARM_PAYROLLS", "US_UNEMPLOYMENT_RATE")),
    )
    assert coverage.untracked_pair_currencies == ()


def test_usd_cad_reports_tracked_indicators_for_both_sides() -> None:
    coverage = build_coverage_evidence("USD", "CAD")

    assert coverage.tracked_indicator_keys_by_currency == (
        ("USD", ("US_CPI_YOY", "US_NONFARM_PAYROLLS", "US_UNEMPLOYMENT_RATE")),
        ("CAD", ("CAD_POLICY_RATE_DECISION",)),
    )
    assert coverage.untracked_pair_currencies == ()


def test_eur_usd_reports_eur_as_untracked() -> None:
    # FX-54 Section 23/19: EUR has zero adopted source coverage --
    # this must be reported honestly as structural incompleteness, not
    # hidden and not an error, while USD's own real coverage is still
    # returned.
    coverage = build_coverage_evidence("EUR", "USD")

    assert coverage.tracked_indicator_keys_by_currency == (
        ("EUR", ()),
        ("USD", ("US_CPI_YOY", "US_NONFARM_PAYROLLS", "US_UNEMPLOYMENT_RATE")),
    )
    assert coverage.untracked_pair_currencies == ("EUR",)


def test_no_all_clear_or_safe_field_exists() -> None:
    # FX-54 Section 20: this type must never be able to claim
    # "no_event_risk"/"safe_to_trade"/"clear_of_events" -- structurally
    # forbidden fields, checked here so a future edit cannot
    # accidentally reintroduce one.
    forbidden = {
        "clear_of_events",
        "safe_window",
        "no_event_risk",
        "all_clear",
        "safe_to_trade",
    }
    fields = set(build_coverage_evidence("EUR", "USD").__dataclass_fields__)
    assert fields.isdisjoint(forbidden)

from dataclasses import dataclass

from forex_agent.domain.macro_category import MacroCategory
from forex_agent.domain.macro_series_definition import MacroSeriesDefinition
from forex_agent.domain.provider_series_mapping import ProviderSeriesMapping
from forex_agent.domain.rate_transformation import RateTransformation
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class PolicyRateDefinition:
    """One effective-dated, canonical, provider-independent definition
    of a central bank's policy-rate concept (FX-42).

    Central banks do not express monetary policy identically, and the
    same institution's own practice can change over time (a target
    point becoming a target range; a facility rate gaining or losing
    primacy; a currency union's founding; an operating target changing
    from a scalar rate to a quantity and back). `PolicyRateDefinition`
    exists to make each such definition's scope, instrument, and
    derivation fully explicit rather than silently splicing unlike
    concepts into one continuous-looking series: `valid_from`/
    `valid_to` bound exactly when this definition applies, and
    `instrument_name`/`transformation` say precisely what was measured
    and how it became one canonical scalar during that window. Two
    (or more) `PolicyRateDefinition`s sharing one currency and one
    `series.key` -- see `policy_rate_registry` -- is how a genuine
    historical instrument change (e.g. the Federal Reserve's shift
    from a single target rate to a target range in December 2008) is
    represented, instead of quietly reinterpreting history. When the
    operating target itself stops being a scalar rate at all for a
    period (e.g. the Bank of Japan's quantitative-easing eras, which
    targeted a quantity, not a rate), that period is represented as a
    `DeclaredPolicyRateGap` (FX-42H.1) instead of a `PolicyRateDefinition`
    -- see `policy_rate_registry.validate_registry`.

    A single `PolicyRateDefinition` whose `valid_to` is `None` and
    which stays in force for a currency's whole represented history is
    equally valid, and is this story's choice for EUR/GBP/CAD: those
    currencies' primary policy-rate concepts have not changed in a way
    this registry judges to be a genuine semantic splice (see each
    definition's own `notes` in `policy_rate_registry` for the
    institutional history considered). USD and JPY instead need
    multiple effective-dated `PolicyRateDefinition`s -- USD for its
    2008 target-point-to-target-range switch, JPY for several genuine
    operating-target changes (including two eras with no comparable
    scalar rate target at all, represented as declared gaps -- see
    `policy_rate_registry`'s JPY section for the full history).

    Answers, by construction, the six questions FX-42's spec requires
    a canonical definition to be able to answer -- see `summary()`.

    Fields:
        series: the canonical, provider-independent identity (FX-41)
            this definition instantiates. Two definitions for the same
            currency in the registry MUST share one `series.key` --
            enforced by `policy_rate_registry`, not by this class,
            since it is a registry-wide (cross-definition) invariant.
        institution: the central bank's name, e.g. "Federal Reserve".
        instrument_name: the specific rate instrument this definition
            tracks during its validity window, e.g. "Federal Funds
            Target Range Midpoint".
        transformation: how raw provider value(s) become the canonical
            scalar during this window (see `RateTransformation`).
        valid_from: earliest `observation_period` this definition
            applies to (inclusive).
        valid_to: exclusive upper bound on `observation_period`; `None`
            means "still in effect."
        provider_mappings: candidate provider/source mapping(s) that
            can supply this definition's data (see
            `ProviderSeriesMapping`). Always at least one -- an entry
            naming zero providers is not "ready for FX-43 ingestion"
            per this story's Definition of Done.
        notes: free-text documentation of institutional/operational
            history, negative-rate periods, and any other context a
            future ingestion story or researcher needs to use this
            definition correctly.
    """

    series: MacroSeriesDefinition
    institution: str
    instrument_name: str
    transformation: RateTransformation
    valid_from: UtcTimestamp
    valid_to: UtcTimestamp | None
    provider_mappings: tuple[ProviderSeriesMapping, ...]
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.series, MacroSeriesDefinition):
            raise TypeError(f"series must be a MacroSeriesDefinition, got {type(self.series)!r}")
        if self.series.category is not MacroCategory.POLICY_RATE:
            raise ValueError(
                f"series.category must be MacroCategory.POLICY_RATE, got {self.series.category}"
            )
        if not isinstance(self.institution, str) or not self.institution.strip():
            raise ValueError(f"institution must be a non-empty string, got {self.institution!r}")
        if not isinstance(self.instrument_name, str) or not self.instrument_name.strip():
            raise ValueError(
                f"instrument_name must be a non-empty string, got {self.instrument_name!r}"
            )
        if not isinstance(self.transformation, RateTransformation):
            raise TypeError(
                f"transformation must be a RateTransformation, got {type(self.transformation)!r}"
            )
        if not isinstance(self.valid_from, UtcTimestamp):
            raise TypeError(f"valid_from must be a UtcTimestamp, got {type(self.valid_from)!r}")
        if self.valid_to is not None:
            if not isinstance(self.valid_to, UtcTimestamp):
                raise TypeError(
                    f"valid_to must be a UtcTimestamp or None, got {type(self.valid_to)!r}"
                )
            if self.valid_to.value <= self.valid_from.value:
                raise ValueError(
                    f"valid_to ({self.valid_to.value.isoformat()}) must be after "
                    f"valid_from ({self.valid_from.value.isoformat()})"
                )
        if not isinstance(self.provider_mappings, tuple) or not self.provider_mappings:
            raise ValueError(
                f"provider_mappings must be a non-empty tuple, got {self.provider_mappings!r}"
            )
        for mapping in self.provider_mappings:
            if not isinstance(mapping, ProviderSeriesMapping):
                raise TypeError(
                    f"every provider_mappings entry must be a ProviderSeriesMapping, "
                    f"got {type(mapping)!r}"
                )
        if not isinstance(self.notes, str):
            raise TypeError(f"notes must be a str, got {type(self.notes)!r}")

    def covers(self, as_of: UtcTimestamp) -> bool:
        """Whether `as_of` falls within this definition's validity
        window: `valid_from <= as_of < valid_to` (or `as_of >=
        valid_from` when `valid_to` is `None`)."""
        if as_of.value < self.valid_from.value:
            return False
        return self.valid_to is None or as_of.value < self.valid_to.value

    def summary(self) -> dict[str, str]:
        """Render this definition's answers to the six audit questions
        FX-42's spec requires ("What economic concept is this? Which
        currency/economy? What units? What transformation, if any?
        What provider/source mapping supplies it? From what historical
        period is this definition valid?") as plain strings, for
        review and for tests -- not used by any query/ingestion path.
        """
        valid_to_str = "present" if self.valid_to is None else self.valid_to.value.isoformat()
        providers = ", ".join(
            f"{m.provider}:{'/'.join(m.provider_series_ids)}" for m in self.provider_mappings
        )
        return {
            "economic_concept": f"{self.institution} — {self.instrument_name}",
            "currency_economy": f"{self.series.currency} ({self.series.economy})",
            "unit": self.series.unit,
            "transformation": (
                f"{self.transformation.kind.value} ({self.transformation.version}): "
                f"{self.transformation.description}"
            ),
            "provider_mapping": providers,
            "valid_period": f"{self.valid_from.value.isoformat()} to {valid_to_str}",
        }

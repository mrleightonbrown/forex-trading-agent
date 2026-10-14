"""FX-65: port for storing and reading FTA's own outcome definitions
and outcome observations -- two related but distinct append-only
concepts (HOW to measure an outcome, versus WHAT was actually
observed), mirroring FX-64's own cohesive-repository-per-concept
scale."""

from dataclasses import dataclass
from typing import Protocol

from forex_agent.domain.forecast_outcome_definition import ForecastOutcomeDefinition
from forex_agent.domain.forecast_outcome_identity import ForecastOutcomeIdentityBinding
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.forecast_type import ForecastType


@dataclass(frozen=True, slots=True)
class ForecastOutcomeDefinitionWriteResult:
    inserted: bool


@dataclass(frozen=True, slots=True)
class ForecastOutcomeVintageWriteResult:
    inserted: bool


@dataclass(frozen=True, slots=True)
class OutcomeIdentityClaimResult:
    claimed: bool
    """`True` iff THIS call's own binding row AND its own first
    vintage were BOTH inserted together, atomically -- a genuinely
    new identity, a genuinely new `outcome_key`. `False` means the
    attempted binding INSERT conflicted on EITHER unique constraint
    (nothing was written, not even the vintage); the caller must then
    inspect `get_identity_binding_for_key`/`get_identity_binding_for_
    identity` to determine whether this is a legitimate concurrent
    duplicate of the SAME key+identity, or a genuine H1/H2 conflict."""


class ForecastOutcomeRepository(Protocol):
    async def latest_outcome_definition(
        self, definition_key: str
    ) -> ForecastOutcomeDefinition | None:
        """The highest `version_sequence` row for `definition_key`, or
        `None` if it has never been registered."""
        ...

    async def list_outcome_definition_versions(
        self, definition_key: str
    ) -> tuple[ForecastOutcomeDefinition, ...]:
        """Every stored version of this definition, in no particular
        guaranteed order -- used by the full-history determinism
        check."""
        ...

    async def add_outcome_definition_version(
        self, definition: ForecastOutcomeDefinition
    ) -> ForecastOutcomeDefinitionWriteResult:
        """Append-only insert keyed on `(definition_key, version_
        sequence)` -- `ON CONFLICT DO NOTHING` semantics."""
        ...

    async def latest_outcome_vintage(self, outcome_key: str) -> ForecastOutcomeVintage | None:
        """The outcome's own latest vintage by `(availability,
        revision_sequence)`, REGARDLESS of `provenance_mode` -- an
        administrative read used only by `RecordForecastOutcome`'s own
        PIT-ordering/idempotency checks."""
        ...

    async def list_vintages_for_outcome(
        self, outcome_key: str
    ) -> tuple[ForecastOutcomeVintage, ...]:
        """Every stored vintage of this outcome, in no particular
        guaranteed order -- used by the full-history determinism
        check and by `ResolveForecastOutcomeAsOf`."""
        ...

    async def claim_outcome_identity_and_add_first_vintage(
        self, binding: ForecastOutcomeIdentityBinding, first_vintage: ForecastOutcomeVintage
    ) -> OutcomeIdentityClaimResult:
        """FX-65H.2 (H1/H4): ATOMICALLY claims `binding`'s own
        `outcome_key` as the sole holder of its own measurement
        identity AND inserts `first_vintage` TOGETHER -- mirrors
        FX-62/64's own `register_source_with_first_identity_vintage`/
        `register_claim_with_first_vintage` pattern exactly: the
        binding insert is attempted first (no commit yet); a conflict
        on EITHER of the binding table's two unique constraints rolls
        back immediately and returns `claimed=False` with NOTHING
        written (not even the vintage); success inserts the vintage
        in the SAME uncommitted transaction, then commits both
        together. Concurrent callers attempting to claim the SAME
        identity under DIFFERENT `outcome_key`s can never both
        succeed. Used ONLY for a genuinely NEW `outcome_key` -- a
        revision of an already-bound key uses `add_outcome_vintage`
        instead, since its own identity is only being VERIFIED, never
        re-claimed."""
        ...

    async def get_identity_binding_for_key(
        self, outcome_key: str
    ) -> ForecastOutcomeIdentityBinding | None:
        """The ONE measurement identity `outcome_key` is durably bound
        to, or `None` if it has never claimed one."""
        ...

    async def get_identity_binding_for_identity(
        self, definition_key: str, target_period_key: str, outcome_type: ForecastType, unit: str
    ) -> ForecastOutcomeIdentityBinding | None:
        """The `outcome_key` that durably owns this EXACT measurement
        identity, or `None` if no one has claimed it yet."""
        ...

    async def add_outcome_vintage(
        self, vintage: ForecastOutcomeVintage
    ) -> ForecastOutcomeVintageWriteResult:
        """Append-only insert keyed on `(outcome_key, revision_
        sequence)` -- `ON CONFLICT DO NOTHING` semantics."""
        ...

# Forex Agent Development Instructions

## Project objective

Build an autonomous forex research and paper-trading platform.

V1 MUST NOT execute live-money trades.

## Architecture

Python modular monolith.

Core technologies:

- Python
- FastAPI
- PostgreSQL
- SQLAlchemy 2
- Alembic
- Docker / Docker Compose
- pytest
- OANDA Practice API

## Architecture boundaries

Code dependencies flow:

apps -> application -> domain

Infrastructure implements application ports.

The domain layer MUST NOT depend on:

- FastAPI
- SQLAlchemy
- OANDA SDK/API objects
- HTTP clients
- environment variables

Provider-specific objects must not escape infrastructure adapters.

## Safety rules

V1 must never connect to a live brokerage trading endpoint.

Required runtime settings:

TRADING_MODE=PAPER
BROKER_ENVIRONMENT=PRACTICE
LIVE_TRADING_COMPILED=false

If LIVE is selected, execution must fail closed.

No code change may bypass:

- risk approval
- execution intent creation
- kill switches
- account reconciliation

Every executable order must originate from:

trade hypothesis
-> risk decision
-> approved execution intent
-> order

## Financial correctness

Never use float for prices, balances, units or P&L where Decimal is appropriate.

All persisted timestamps use timezone-aware UTC values.

Naive datetimes must be rejected.

Backtests must prevent look-ahead bias.

Long trades:

- enter at ask
- exit at bid

Short trades:

- enter at bid
- exit at ask

Backtests must include spread.

Strategies must only evaluate finalized candles.

## Development rules

For every Jira story:

1. Read the story and acceptance criteria.
2. Inspect existing implementation before editing.
3. Write or update tests first where practical.
4. Implement the smallest change satisfying the requirements.
5. Run relevant unit tests.
6. Run integration tests.
7. Run formatting/lint/type checks.
8. Review the diff.
9. Do not weaken tests merely to make them pass.
10. Commit only when acceptance criteria pass.

Do not silently redesign architecture.

If implementation requires an architectural change:
- document the issue;
- explain the proposed change;
- stop before implementing the architectural change.

## Testing

Use:

pytest

Test categories:

tests/unit
tests/integration
tests/contract
tests/replay
tests/golden_data

Critical behaviours require regression tests.

Tests must specifically protect against:

- look-ahead bias
- duplicate events
- duplicate fills
- invalid bid/ask execution
- risk-limit bypass
- kill-switch bypass
- timezone errors
- provider duplication
- broker reconciliation drift

## Git discipline

Work in small commits.

A typical commit should correspond to one Jira story or coherent portion thereof.

Commit format:

FX-###: concise description

Never commit:

- API keys
- account credentials
- .env
- private tokens
- generated secrets

## Documentation

Architectural decisions go under:

docs/adr/

Strategy specifications go under:

docs/strategy-specifications/

Operational instructions go under:

docs/runbooks/

Update documentation whenever implementation changes behaviour.

## Current project phase

M0-M4.

Current priorities:

1. repository foundation
2. PostgreSQL
3. domain primitives
4. broker adapter abstraction
5. OANDA Practice connectivity
6. historical data ingestion
7. candle aggregation
8. data quality
9. strategy framework
10. backtester
11. regime detection

Do not implement fundamentals, news intelligence, AI decision making or live trading unless explicitly assigned.

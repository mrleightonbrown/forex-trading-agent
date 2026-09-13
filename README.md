# Forex Trading Agent

Autonomous forex research and paper-trading platform. **V1 does not execute
live-money trades** — see [CLAUDE.md](CLAUDE.md) for the full safety, architecture,
and development rules governing this repository.

## Stack

Python 3.12 · FastAPI · PostgreSQL · SQLAlchemy 2 (async) · Alembic ·
Docker Compose · pytest · OANDA Practice API. Dependency/tooling choices are
recorded in [docs/DECISIONS.md](docs/DECISIONS.md).

## Getting started

```bash
# Install uv if you don't have it: https://docs.astral.sh/uv/getting-started/installation/
uv python install 3.12
uv sync                      # creates .venv and installs all dependencies
cp .env.example .env         # then fill in local values — never commit .env

docker compose up -d db      # start PostgreSQL
uv run alembic upgrade head  # apply migrations

uv run uvicorn forex_agent.apps.api.main:app --reload
```

## Development

```bash
uv run pytest                     # all tests
uv run pytest tests/unit          # one category
uv run ruff check .               # lint
uv run ruff format .              # format
uv run mypy .                     # type check
uv run pre-commit install         # one-time: enable local git hooks
```

## Project layout

```
src/forex_agent/
  apps/            # FastAPI entrypoints, routers — depends on application
  application/     # use cases + ports (interfaces) — depends on domain only
  domain/          # entities, value objects, domain services — no external deps
  infrastructure/  # SQLAlchemy repos, OANDA adapter — implements application ports
tests/
  unit/ integration/ contract/ replay/ golden_data/
docs/
  adr/ strategy-specifications/ runbooks/
```

Architecture boundaries and safety rules are non-negotiable — see
[CLAUDE.md](CLAUDE.md) before making structural changes.

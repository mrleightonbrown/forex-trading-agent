"""CLAUDE.md: "The domain layer MUST NOT depend on: FastAPI, SQLAlchemy,
OANDA SDK/API objects, HTTP clients, environment variables."

Turns that rule from a review-time check into an automated one: scans every
module under src/forex_agent/domain/ for forbidden imports and direct
environment-variable access, rather than relying on catching it in review.
"""

from pathlib import Path

import pytest

from tests.contract._boundary import (
    SRC_ROOT,
    assert_does_not_read_environ,
    assert_no_forbidden_imports,
    python_files,
)

FORBIDDEN_TOP_LEVEL_MODULES = {
    "fastapi",
    "starlette",
    "sqlalchemy",
    "alembic",
    "httpx",
    "requests",
    "oandapyV20",  # OANDA's official Python SDK, if it's ever added
    "os",  # environment variables must not be read from domain code
}

DOMAIN_DIR = SRC_ROOT / "domain"


@pytest.mark.parametrize(
    "path",
    python_files(DOMAIN_DIR),
    ids=lambda p: str(p.relative_to(DOMAIN_DIR)),
)
def test_domain_module_has_no_forbidden_imports(path: Path) -> None:
    assert_no_forbidden_imports(path, FORBIDDEN_TOP_LEVEL_MODULES)


@pytest.mark.parametrize(
    "path",
    python_files(DOMAIN_DIR),
    ids=lambda p: str(p.relative_to(DOMAIN_DIR)),
)
def test_domain_module_does_not_read_environ(path: Path) -> None:
    assert_does_not_read_environ(path)

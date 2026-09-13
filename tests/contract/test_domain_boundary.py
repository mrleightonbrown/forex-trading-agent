"""CLAUDE.md: "The domain layer MUST NOT depend on: FastAPI, SQLAlchemy,
OANDA SDK/API objects, HTTP clients, environment variables."

Turns that rule from a review-time check into an automated one: scans every
module under src/forex_agent/domain/ for forbidden imports and direct
environment-variable access, rather than relying on catching it in review.
"""

import ast
from pathlib import Path

import pytest

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

DOMAIN_DIR = Path(__file__).resolve().parents[2] / "src" / "forex_agent" / "domain"


def _domain_python_files() -> list[Path]:
    return sorted(DOMAIN_DIR.rglob("*.py"))


def _top_level_imports(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module.split(".")[0])
    return modules


@pytest.mark.parametrize(
    "path",
    _domain_python_files(),
    ids=lambda p: str(p.relative_to(DOMAIN_DIR)),
)
def test_domain_module_has_no_forbidden_imports(path: Path) -> None:
    tree = ast.parse(path.read_text(), filename=str(path))
    forbidden_found = _top_level_imports(tree) & FORBIDDEN_TOP_LEVEL_MODULES

    assert not forbidden_found, f"{path} imports forbidden module(s): {forbidden_found}"


@pytest.mark.parametrize(
    "path",
    _domain_python_files(),
    ids=lambda p: str(p.relative_to(DOMAIN_DIR)),
)
def test_domain_module_does_not_read_environ(path: Path) -> None:
    source = path.read_text()

    assert "environ" not in source, f"{path} appears to read environment variables directly"
    assert "getenv(" not in source, f"{path} appears to read environment variables directly"

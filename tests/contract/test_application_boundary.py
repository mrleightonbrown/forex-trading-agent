"""CLAUDE.md: "Infrastructure implements application ports" — the dependency
only ever runs infrastructure -> application, never the reverse. That means
`application` must not import concrete infrastructure libraries (FastAPI,
SQLAlchemy, httpx, the OANDA SDK) any more than `domain` may.
"""

from pathlib import Path

import pytest

from tests.contract._boundary import SRC_ROOT, assert_no_forbidden_imports, python_files

FORBIDDEN_TOP_LEVEL_MODULES = {
    "fastapi",
    "starlette",
    "sqlalchemy",
    "alembic",
    "httpx",
    "requests",
    "oandapyV20",  # OANDA's official Python SDK, if it's ever added
}

APPLICATION_DIR = SRC_ROOT / "application"


@pytest.mark.parametrize(
    "path",
    python_files(APPLICATION_DIR),
    ids=lambda p: str(p.relative_to(APPLICATION_DIR)),
)
def test_application_module_has_no_forbidden_imports(path: Path) -> None:
    assert_no_forbidden_imports(path, FORBIDDEN_TOP_LEVEL_MODULES)

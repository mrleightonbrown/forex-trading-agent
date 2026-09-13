"""Shared helpers for architecture-boundary contract tests.

Used by test_domain_boundary.py and test_application_boundary.py to scan a
layer's source files for imports/patterns CLAUDE.md forbids there, without
duplicating the AST-walking logic per layer.
"""

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "forex_agent"


def python_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module.split(".")[0])
    return modules


def assert_no_forbidden_imports(path: Path, forbidden: set[str]) -> None:
    forbidden_found = top_level_imports(path) & forbidden
    assert not forbidden_found, f"{path} imports forbidden module(s): {forbidden_found}"


def assert_does_not_read_environ(path: Path) -> None:
    source = path.read_text()
    assert "environ" not in source, f"{path} appears to read environment variables directly"
    assert "getenv(" not in source, f"{path} appears to read environment variables directly"

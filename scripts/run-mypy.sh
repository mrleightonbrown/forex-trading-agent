#!/usr/bin/env bash
# Wrapper for the local pre-commit mypy hook.
#
# pre-commit's `language: system` hooks run with whatever PATH the invoking
# process has, which for git hooks is often not a login shell's PATH — so a
# uv installed to ~/.local/bin (the default for uv's standalone installer)
# isn't necessarily found. Make sure it is, then delegate to the project's
# own environment so mypy sees the real dependencies (see .pre-commit-config.yaml).
#
# `.pre-commit-config.yaml`'s mypy hook sets `pass_filenames: false`, so `$@`
# is always empty here -- a bare `uv run mypy` with no path argument falls
# back to pyproject.toml's own `[tool.mypy] packages = ["forex_agent"]`
# setting, restricted to src/forex_agent only. CI's typecheck job runs
# `uv run mypy .` instead, which walks the whole repository (tests/,
# scripts/ included) -- a real gap between this hook and CI, found and
# closed 2026-09-24 (see docs/DECISIONS.md's Python 3.13 upgrade
# correction entry). Passing `.` explicitly here matches CI exactly.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
exec uv run mypy . "$@"

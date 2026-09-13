#!/usr/bin/env bash
# Wrapper for the local pre-commit mypy hook.
#
# pre-commit's `language: system` hooks run with whatever PATH the invoking
# process has, which for git hooks is often not a login shell's PATH — so a
# uv installed to ~/.local/bin (the default for uv's standalone installer)
# isn't necessarily found. Make sure it is, then delegate to the project's
# own environment so mypy sees the real dependencies (see .pre-commit-config.yaml).
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
exec uv run mypy "$@"

#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
exec uv run --locked python tests_scripts/part1_local.py check-part1 "$@"

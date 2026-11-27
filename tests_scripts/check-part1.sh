#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
exec uv run --locked python -m tests_scripts.part1_local check-part1 "$@"

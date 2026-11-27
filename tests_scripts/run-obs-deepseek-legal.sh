#!/usr/bin/env bash
set -euo pipefail

MODEL="${DEEPSEEK_MODEL:-}" exec bash "$(dirname -- "${BASH_SOURCE[0]}")/run-chess-agent.sh" \
    --summarize-moves \
    --trajectory "${OBS_LEGAL_TRAJECTORY:-artifacts/part3-legal-moves-deepseek.json}" \
    --result "${OBS_LEGAL_RESULT:-artifacts/part3-legal-moves-deepseek-result.json}" \
    "$@"

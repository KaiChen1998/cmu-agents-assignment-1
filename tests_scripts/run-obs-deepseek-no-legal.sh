#!/usr/bin/env bash
set -euo pipefail

MODEL="${DEEPSEEK_MODEL:-}" exec bash "$(dirname -- "${BASH_SOURCE[0]}")/run-chess-agent.sh" \
    --omit-legal-moves --summarize-moves \
    --trajectory "${OBS_NO_LEGAL_TRAJECTORY:-artifacts/part3-no-legal-moves-deepseek.json}" \
    --result "${OBS_NO_LEGAL_RESULT:-artifacts/part3-no-legal-moves-deepseek-result.json}" \
    "$@"

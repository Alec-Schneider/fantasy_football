#!/usr/bin/env bash
# Rebuild the FFA-073 composite player value ranking CSVs for the two
# schneidbaby 2025 leagues used in the "top 100 valuable players" report.
#
# League-wide by default: every player the provider has stats for counts
# (free agents included), not just players someone rostered -- pass
# --rostered-only to composite_ranking_report.py for the narrower scope.
#
# Run from the repo root:
#   ./scripts/run_composite_ranking_report.sh

set -euo pipefail
cd "$(dirname "$0")/.."

.venv/bin/python scripts/composite_ranking_report.py \
  --league-id 1257477810625196032 --league-name "NWC_FFL_est_2011" \
  --league-id 1260307567133859840 --league-name "New_Wave_Friends_League" \
  --out-dir scripts/output \
  --phase all

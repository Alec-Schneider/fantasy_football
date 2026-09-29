#!/usr/bin/env bash
# Rank rest-of-season waiver-wire free agents (FFA-091/092/093) for the three
# schneidbaby 2026 leagues, one CSV/text report per league.
#
# league_ids are the 2026-season IDs from scripts/draft_league_presets.py
# (Sleeper mints a new league_id every season). The two 2026 leagues
# deliberately excluded from the draft-report pipeline (NWC Guillotine '26,
# BBC weird league) are excluded here too, for the same reasons.
#
# Usage (run from the repo root, or anywhere -- it cd's to the repo root):
#   ./scripts/run_free_agent_rankings.sh --week 1 [--season 2026] [--top 50] \
#       [--position WR] [--format text|json]
#
# --week is required: it is the last *completed* NFL week (rest-of-season is
# projected from after it), and changes every time you run this, so it is
# never defaulted. Check the current week with:
#   curl -s https://api.sleeper.app/v1/state/nfl
#
# Output: scripts/output/free_agents/<league>_week<week>.<txt|json>, one
# per league (that directory is gitignored, same as scripts/output/).

set -euo pipefail
cd "$(dirname "$0")/.."

SEASON=2026
TOP=50
FORMAT=text
POSITION=""
WEEK=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --week) WEEK="$2"; shift 2 ;;
    --season) SEASON="$2"; shift 2 ;;
    --top) TOP="$2"; shift 2 ;;
    --position) POSITION="$2"; shift 2 ;;
    --format) FORMAT="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$WEEK" ]]; then
  echo "Usage: $0 --week <last completed week> [--season 2026] [--top 50] [--position POS] [--format text|json]" >&2
  echo "  (check the current NFL week with: curl -s https://api.sleeper.app/v1/state/nfl)" >&2
  exit 1
fi

declare -A LEAGUES=(
  [nwc]="1389350137481932800"
  [new-wave]="1389754945892274176"
  [zipline]="1389707229824815104"
)

OUT_DIR="scripts/output/free_agents"
mkdir -p "$OUT_DIR"

EXT="txt"
[[ "$FORMAT" == "json" ]] && EXT="json"

for name in nwc new-wave zipline; do
  league_id="${LEAGUES[$name]}"
  out_file="${OUT_DIR}/${name}_week${WEEK}.${EXT}"

  cmd=(.venv/bin/fantasy-analyzer free-agents "$league_id"
       --season "$SEASON" --week "$WEEK" --top "$TOP" --format "$FORMAT")
  [[ -n "$POSITION" ]] && cmd+=(--position "$POSITION")

  echo "Running free-agent rankings for ${name} (league_id=${league_id}) -> ${out_file}"
  "${cmd[@]}" > "$out_file"
done

echo "Done. Reports in ${OUT_DIR}/"

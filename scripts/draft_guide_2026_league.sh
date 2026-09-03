#!/usr/bin/env bash
# Build a 2026 draft guide (FFA-075 market data + FFA-076 board, same as
# docs/draft-board-2026.md) for one of schneidbaby's two 10-team leagues
# whose 2026 draft order Sleeper has not assigned yet: New Wave Friends
# League and Just Here For The Zipline.
#
# The FFA-073 2025 retrospective prior CSVs (the 25%-weight input to the
# board) are already built and checked into scripts/output/draft2026/ --
# they don't depend on draft slot, so there's nothing to regenerate there
# unless the 2025 fact table itself changes. To rebuild them:
#   .venv/bin/python scripts/composite_ranking_report.py \
#     --league-id 1260307567133859840 --league-name "New_Wave_2025_prior" \
#     --league-id 1262800342051999744 --league-name "Zipline_2025_prior" \
#     --out-dir scripts/output/draft2026 --phase all --top 2000
#
# Once Sleeper (or your league chat) tells you your actual 2026 draft slot,
# run this with the league and that slot:
#
#   ./scripts/draft_guide_2026_league.sh new-wave --slot 5
#   ./scripts/draft_guide_2026_league.sh zipline --slot 3
#
# Any extra arguments are forwarded to draft_guide_2026.py as-is (e.g.
# --no-market-refresh, --exclude-id <player_id> for a rostered keeper).
#
# Output lands in scripts/output/draft2026/ as
# <prefix>_2026_slot<N>of10_board.csv and *_availability.csv, plus the
# pick-by-pick console report -- identical shape to the NWC FFL board.

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 {new-wave|zipline} --slot N [extra draft_guide_2026.py args...]" >&2
  exit 1
fi

league="$1"
shift

# 2-FLEX 10-team lineup shared by both leagues; only rounds (bench depth)
# differ. See AGENTS.md / this repo's Sleeper league settings for the source.
ROSTER_2FLEX_15="QB,RB,RB,WR,WR,TE,FLEX,FLEX,K,DEF,BN,BN,BN,BN,BN"
ROSTER_2FLEX_16="QB,RB,RB,WR,WR,TE,FLEX,FLEX,K,DEF,BN,BN,BN,BN,BN,BN"

case "$league" in
  new-wave)
    prior_csv="scripts/output/draft2026/New_Wave_2025_prior_1260307567133859840.csv"
    scoring="ppr"          # league scoring_settings.rec = 1.0 (full PPR)
    rounds=15
    roster_positions="$ROSTER_2FLEX_15"
    out_prefix="NewWave"
    ;;
  zipline)
    prior_csv="scripts/output/draft2026/Zipline_2025_prior_1262800342051999744.csv"
    scoring="half-ppr"     # league scoring_settings.rec = 0.5 (half PPR)
    rounds=16
    roster_positions="$ROSTER_2FLEX_16"
    out_prefix="Zipline"
    ;;
  *)
    echo "Unknown league '$league' -- expected 'new-wave' or 'zipline'." >&2
    exit 1
    ;;
esac

.venv/bin/python scripts/draft_guide_2026.py \
  --season 2026 --teams 10 --rounds "$rounds" --scoring "$scoring" \
  --roster-positions "$roster_positions" \
  --prior-csv "$prior_csv" \
  --out-dir scripts/output/draft2026 --out-prefix "$out_prefix" \
  "$@"

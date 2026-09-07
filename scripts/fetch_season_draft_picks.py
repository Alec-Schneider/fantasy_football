"""Fetch and normalize one or more leagues' completed drafts to CSV.

A small, generic counterpart to ``draft_report_2026.py``'s draft-fetching
step (FFA-077's :func:`~fantasy_analyzer.league.draft.load_league_draft` /
:func:`~fantasy_analyzer.league.draft.build_normalized_draft_picks`), but
usable for *any* season's ``league_id`` -- not just the current one.

Built to source the 2025 draft-slot -> realized-production dataset the
draft points-value curve (FFA-08x) is fit from: this script's output
(``pick_no``, ``sleeper_player_id``, ``round``) is joined downstream onto
that league's FFA-073 composite ranking CSV (``sleeper_player_id`` ->
realized ``points_above_replacement``) to build the curve.

Example::

    .venv/bin/python scripts/fetch_season_draft_picks.py \\
        --league-id 1257477810625196032 --name NWC_FFL --season 2025 \\
        --league-id 1260307567133859840 --name New_Wave --season 2025 \\
        --league-id 1262800342051999744 --name Zipline --season 2025 \\
        --out-dir scripts/output/draft2026

Network: hits Sleeper once per league (users, rosters, league, drafts,
draft picks). No nflverse access.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from fantasy_analyzer.league.draft import (
    build_normalized_draft_picks,
    load_league_draft,
)
from fantasy_analyzer.league.snapshot import load_league_snapshot
from fantasy_analyzer.sleeper.client import SleeperClient
from fantasy_analyzer.sleeper.exceptions import SleeperAPIError


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fetch_season_draft_picks.py",
        description=(
            "Fetch and normalize one or more leagues' completed drafts to CSV."
        ),
    )
    parser.add_argument(
        "--league-id",
        action="append",
        required=True,
        help="Sleeper league_id for the season being fetched. Repeatable.",
    )
    parser.add_argument(
        "--name",
        action="append",
        default=[],
        help="Display name for the matching --league-id (used in the output filename).",
    )
    parser.add_argument(
        "--season",
        type=int,
        required=True,
        help="Season year to stamp onto every row (e.g. 2025).",
    )
    parser.add_argument(
        "--out-dir",
        default="scripts/output",
        help="Directory to write CSVs into (default: scripts/output).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    league_ids = args.league_id
    names = args.name + league_ids[len(args.name) :]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = SleeperClient()

    for league_id, name in zip(league_ids, names):
        try:
            snapshot = load_league_snapshot(client, league_id)
            raw_draft, raw_picks = load_league_draft(client, league_id)
            picks_df = build_normalized_draft_picks(
                raw_picks,
                snapshot.teams_df,
                season=args.season,
                league_id=league_id,
                draft_id=raw_draft["draft_id"],
            )
        except (SleeperAPIError, ValueError, KeyError) as exc:
            print(f"Error fetching {name} ({league_id}): {exc}", file=sys.stderr)
            continue

        safe_name = "".join(c if c.isalnum() else "_" for c in name).strip("_")
        out_path = out_dir / f"{safe_name}_{args.season}_draft_{league_id}.csv"
        picks_df.to_csv(out_path, index=False)
        print(f"{name}: wrote {len(picks_df)} picks -> {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

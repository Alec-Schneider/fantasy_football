"""Build the FFA-073 league-wide composite player value ranking for one or
more leagues and write each league's full ranked pool to CSV.

Thin composition script, same pattern as ``player_analysis.py``: it defines
no new metrics, it just calls that script's ``load_analytics`` (Sleeper +
nflverse -> ``PlayerAnalytics``) and writes out
``PlayerAnalytics.player_ranking_df`` (FFA-073, five-component blend --
value, shrunk rate, reliability, upside, positional scarcity).

By default this pulls in free agents too -- every player the provider has
stats for that week, not just players someone in the league rostered --
via ``load_analytics(..., include_free_agents=True)``, which uses
:func:`~fantasy_analyzer.players.player_week.build_league_wide_player_week_fact_table`
instead of the rostered-only fact table. A high-scoring player nobody
rostered still counts toward the replacement baseline and can still appear
in the ranking (his own row just has no ``roster_id``/``fantasy_team``).
Pass ``--rostered-only`` to go back to the original rostered-players-only
scope.

Example::

    .venv/bin/python scripts/composite_ranking_report.py \\
        --league-id 1257477810625196032 --league-name "NWC FFL, est. 2011" \\
        --league-id 1260307567133859840 --league-name "N(ew Wave) F(riends) L(eague)" \\
        --out-dir scripts/output

Network: hits Sleeper once per league/week and nflverse once per season,
same as ``player_analysis.py``. Both are cached under ``.cache/``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

# scripts/ is not a package; import the sibling script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from player_analysis import load_analytics  # noqa: E402

from fantasy_analyzer.sleeper.client import SleeperClient  # noqa: E402
from fantasy_analyzer.sleeper.exceptions import SleeperAPIError  # noqa: E402

RANKING_REPORT_COLUMNS = [
    "league_rank",
    "player_name",
    "position",
    "nfl_team",
    "games_played",
    "points_per_game",
    "total_points",
    "points_above_replacement",
    "cv",
    "scoring_ceiling",
    "ranking_score",
    "position_rank",
    "league_percentile",
    "rostered",
]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="composite_ranking_report.py",
        description=(
            "Build FFA-073's league-wide composite player value ranking "
            "for one or more leagues and write each to CSV."
        ),
    )
    parser.add_argument(
        "--league-id",
        action="append",
        required=True,
        help="Sleeper league_id. Repeatable to build multiple leagues in one run.",
    )
    parser.add_argument(
        "--league-name",
        action="append",
        default=[],
        help=(
            "Display name for the matching --league-id (same position in the "
            "argument list). Defaults to the league_id itself if omitted."
        ),
    )
    parser.add_argument(
        "--total-weeks",
        type=int,
        default=18,
        help="Total weeks in the season (default: 18).",
    )
    parser.add_argument(
        "--phase",
        choices=["regular", "playoffs", "all"],
        default="regular",
        help="Which weeks to include (default: regular).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=100,
        help="Row cap per league (default: 100). Leagues with fewer ranked "
        "players write their full pool.",
    )
    parser.add_argument(
        "--out-dir",
        default="scripts/output",
        help="Directory to write CSVs into (default: scripts/output).",
    )
    parser.add_argument(
        "--rostered-only",
        action="store_true",
        help=(
            "Score only players someone in the league rostered (the original, "
            "narrower scope). Default is league-wide: every player the provider "
            "has stats for counts, including free agents."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    league_ids = args.league_id
    names = args.league_name + league_ids[len(args.league_name) :]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = SleeperClient()

    for league_id, name in zip(league_ids, names):
        try:
            analytics, unsupported = load_analytics(
                client,
                league_id,
                total_weeks=args.total_weeks,
                phase=args.phase,
                include_free_agents=not args.rostered_only,
            )
        except (SleeperAPIError, ValueError, KeyError) as exc:
            print(f"Error building {name} ({league_id}): {exc}", file=sys.stderr)
            continue

        if unsupported:
            print(
                f"WARNING [{name}]: fantasy_points omits unmapped scoring rules: "
                + ", ".join(unsupported),
                file=sys.stderr,
            )

        # A player is "rostered" if any week of the raw fact table shows a
        # non-null roster_id -- true for every row when --rostered-only was
        # passed, and false for a free-agent-only player otherwise.
        ever_rostered = (
            analytics.player_weekly_df.dropna(subset=["roster_id"])["sleeper_player_id"]
            .unique()
        )
        rankings = (
            analytics.player_ranking_df.sort_values("league_rank").head(args.top).copy()
        )
        rankings["rostered"] = rankings["sleeper_player_id"].isin(ever_rostered)

        safe_name = "".join(c if c.isalnum() else "_" for c in name).strip("_")
        out_path = out_dir / f"{safe_name}_{league_id}.csv"
        rankings[RANKING_REPORT_COLUMNS].to_csv(out_path, index=False)
        n_free_agents = (~rankings["rostered"]).sum()
        print(
            f"{name}: wrote {len(rankings)} ranked players "
            f"({n_free_agents} free agents) -> {out_path}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Audit whether every Sleeper player is accounted for, across the dashboard's leagues.

Runs :mod:`fantasy_analyzer.players.coverage`'s two audits (FFA-109) for each
league in ``draft_league_presets.LEAGUES``:

- the **forward** audit -- every Sleeper catalog player at QB/RB/WR/TE/K/DEF
  plus every rostered player, each with one ``coverage_reason``;
- the **reverse** audit -- every nflverse player with season production
  whose ``gsis_id`` maps to no Sleeper id, scored with the league's own
  scoring settings.

Both run twice, against the robust crosswalk alone (**before**) and with the
FFA-109 name fallback applied (**after**), so every run re-measures what
the fallback buys rather than asserting it once. It also measures the two
population fixes that landed alongside: FFA-103's team guard (free agents
removed) and ``build_player_universe`` (rostered players the old
``build_free_agent_pool([], ...)`` population dropped).

Inputs: live rosters and league settings from Sleeper
(``SleeperClient().get_rosters`` / ``get_league``), plus the local caches --
the Sleeper catalog, DynastyProcess's ID table, and nflverse player stats
for ``--season`` and the season before. Refresh those caches first; none is
TTL-checked.

Outputs, under ``--out-dir`` (default ``scripts/output/coverage/``):

- ``forward_<slug>.csv`` -- forward audit, after the fallback;
- ``reverse_<slug>.csv`` -- reverse audit, after the fallback;
- ``reverse_<slug>_before.csv`` -- reverse audit, before it;
- ``name_matches.csv`` -- every name-fallback mapping, with its tier;
- ``summary.txt`` -- the printed summary.

Example::

    .venv/bin/python scripts/player_coverage_report.py --season 2026
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from draft_league_presets import LEAGUES  # noqa: E402

from fantasy_analyzer.players.coverage import (  # noqa: E402
    build_forward_coverage_audit,
    build_reverse_coverage_audit,
)
from fantasy_analyzer.players.crosswalk import (  # noqa: E402
    build_name_match_crosswalk,
    build_robust_id_crosswalk,
    extend_crosswalk_with_name_matches,
)
from fantasy_analyzer.players.free_agents import (  # noqa: E402
    build_free_agent_pool,
    build_player_universe,
)
from fantasy_analyzer.players.nflverse_cache import (
    get_player_stats_cached,  # noqa: E402
)
from fantasy_analyzer.players.nflverse_client import NflverseClient  # noqa: E402
from fantasy_analyzer.sleeper.cache import get_players_cached  # noqa: E402
from fantasy_analyzer.sleeper.client import SleeperClient  # noqa: E402

DEFAULT_SEASON = 2026
DEFAULT_OUT_DIR = Path("scripts/output/coverage")

#: Scorers this deep are "fantasy relevant" for the top-N check.
TOP_SCORERS = 100


def _reverse_measures(reverse: pd.DataFrame) -> tuple[int, int, float, list[str]]:
    """``(players, active player-weeks, their points, unmapped top-N names)``."""
    if reverse.empty:
        return 0, 0, 0.0, []
    active = reverse[reverse["active_player_weeks"] > 0]
    top = reverse[reverse["points_rank"] <= TOP_SCORERS]
    top_names = [
        f"{row.player_name} ({row.position}, #{row.points_rank})"
        for row in top.itertuples()
    ]
    return (
        len(active),
        int(active["active_player_weeks"].sum()),
        float(active["fantasy_points"].sum()),
        top_names,
    )


def _rostered_without_gsis(forward: pd.DataFrame) -> list[str]:
    """Rostered non-DEF players with no ``gsis_id``, labeled."""
    rows = forward[
        forward["is_rostered"]
        & forward["gsis_id"].isna()
        & (forward["position"] != "DEF")
    ]
    return [
        f"{row.full_name} ({row.position}, {row.team}, {row.sleeper_player_id})"
        for row in rows.itertuples()
    ]


def build_report(season: int, league_slugs: Sequence[str], out_dir: Path) -> list[str]:
    """Run every audit, write the CSVs, and return the summary lines."""
    client = SleeperClient()
    catalog = get_players_cached(client)
    nflverse = NflverseClient()
    stats = pd.concat(
        [
            get_player_stats_cached(nflverse, season),
            get_player_stats_cached(nflverse, season - 1),
        ],
        ignore_index=True,
    )

    before = build_robust_id_crosswalk(catalog)
    matches = build_name_match_crosswalk(catalog, stats, before)
    after = extend_crosswalk_with_name_matches(before, catalog, stats)

    out_dir.mkdir(parents=True, exist_ok=True)
    matches.to_csv(out_dir / "name_matches.csv", index=False)

    lines = [
        f"Player coverage report -- season {season}",
        f"Sleeper catalog: {len(catalog):,} entries; "
        f"crosswalk {len(before):,} rows before, {len(after):,} after "
        f"({len(matches)} name-fallback matches).",
        "",
        "Name-fallback matches (gsis_id -> Sleeper id):",
    ]
    lines += [
        f"  {row.gsis_id} -> {row.sleeper_player_id}  {row.full_name} "
        f"({row.position}, {row.team}) [{row.match_method}]"
        for row in matches.itertuples()
    ] or ["  (none)"]

    for slug in league_slugs:
        league_id = LEAGUES[slug]["league_id"]
        league = client.get_league(league_id)
        rosters = client.get_rosters(league_id)
        positions = league["roster_positions"]
        scoring = league["scoring_settings"]

        universe = build_player_universe(rosters, catalog, positions, crosswalk=after)
        pool = build_free_agent_pool(rosters, catalog, positions)
        unguarded = build_free_agent_pool(
            rosters, catalog, positions, require_nfl_team=False
        )
        old_population = build_free_agent_pool(
            [], catalog, positions, require_nfl_team=False
        )
        rostered = universe[universe["is_rostered"]]
        dropped = rostered[~rostered["player_id"].isin(old_population["player_id"])]

        forward_before = build_forward_coverage_audit(
            catalog, rosters, positions, before, stats, season
        )
        forward = build_forward_coverage_audit(
            catalog, rosters, positions, after, stats, season
        )
        reverse_before = build_reverse_coverage_audit(stats, before, season, scoring)
        reverse = build_reverse_coverage_audit(stats, after, season, scoring)

        forward.to_csv(out_dir / f"forward_{slug}.csv", index=False)
        reverse.to_csv(out_dir / f"reverse_{slug}.csv", index=False)
        reverse_before.to_csv(out_dir / f"reverse_{slug}_before.csv", index=False)

        reasons = (
            pd.crosstab(
                forward["coverage_reason"],
                forward["is_rostered"].map({True: "rostered", False: "free agent"}),
            )
            .reindex(columns=["rostered", "free agent"], fill_value=0)
            .to_string()
        )
        counts = rostered["position"].value_counts().to_dict()
        players_b, weeks_b, points_b, top_b = _reverse_measures(reverse_before)
        players_a, weeks_a, points_a, top_a = _reverse_measures(reverse)
        no_gsis_before = _rostered_without_gsis(forward_before)
        no_gsis_after = _rostered_without_gsis(forward)

        lines += [
            "",
            f"== {league.get('name')} [{slug}] ({len(rosters)} rosters) ==",
            f"Universe: {len(universe)} players -- {len(rostered)} rostered "
            f"({', '.join(f'{k} {v}' for k, v in sorted(counts.items()))}), "
            f"{len(universe) - len(rostered)} free agents.",
            f"FFA-103: free-agent pool {len(unguarded)} -> {len(pool)} "
            f"({len(unguarded) - len(pool)} teamless players removed).",
            f"Rostered players the old build_free_agent_pool([], ...) population "
            f"dropped ({len(dropped)}): "
            + (", ".join(dropped["full_name"].astype(str)) or "none"),
            "Forward audit (after), coverage_reason x rostered:",
            reasons,
            f"(a) Unmapped {season} nflverse players with activity: "
            f"before {players_b} players / {weeks_b} player-weeks / "
            f"{points_b:.1f} pts; after {players_a} / {weeks_a} / {points_a:.1f} pts.",
            f"(b) Rostered players with no gsis_id: before {len(no_gsis_before)}"
            + (f" [{'; '.join(no_gsis_before)}]" if no_gsis_before else "")
            + f"; after {len(no_gsis_after)}"
            + (f" [{'; '.join(no_gsis_after)}]" if no_gsis_after else "")
            + ".",
            f"(c) Unmapped top-{TOP_SCORERS} {season} scorers: before "
            f"{len(top_b)}{' ' + str(top_b) if top_b else ''}; after "
            f"{len(top_a)}{' ' + str(top_a) if top_a else ''}.",
        ]
        if not reverse.empty:
            lines.append("Still unmapped after the fallback:")
            lines += [
                f"  {row.gsis_id} {row.player_name} ({row.position}, "
                f"{row.nfl_team}): {row.active_player_weeks} active weeks, "
                f"{row.fantasy_points:.1f} pts"
                for row in reverse.itertuples()
            ]

    (out_dir / "summary.txt").write_text("\n".join(lines) + "\n")
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse arguments, run the report, print the summary."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", type=int, default=DEFAULT_SEASON)
    parser.add_argument(
        "--league",
        dest="leagues",
        action="append",
        choices=sorted(LEAGUES),
        help="League slug; repeatable. Defaults to every preset league.",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    lines = build_report(args.season, args.leagues or list(LEAGUES), args.out_dir)
    print("\n".join(lines))
    print(f"\nWrote CSVs and summary.txt to {args.out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Live, in-season team power rankings for the 2026 draft-report leagues.

Ad hoc analysis script (not a package module / not on the AGENTS.md ticket
board) that blends three already-computed or already-shippable signals into
one power score per team, for the three leagues ``scripts/draft_report_2026.py``
already covers (NWC FFL, New Wave, Zipline):

1. **Preseason roster/draft value** -- each team's ``overall_z`` column from
   ``scripts/output/draft2026/<prefix>_2026_draft_report_team_grades.csv``
   (FFA-084/085/086's value-scale draft grade, already a z-score).
2. **Week 1 performance** -- that team's actual week-1 fantasy score from
   live Sleeper matchups, z-scored within its own league.
3. **Rest-of-season outlook** -- each team's *starting lineup* projected
   points for the rest of the season, built by reusing
   ``waiver_rankings.build_free_agent_ros_projections`` (FFA-092) against a
   pool of the team's own *rostered* players instead of free agents (the
   function only needs a FREE_AGENT_POOL_COLUMNS-shaped frame; nothing in it
   assumes free-agent status). Uses ``player_analysis.build_robust_id_crosswalk``
   (DynastyProcess-backed, FFA-074) rather than the plain Sleeper-catalog
   crosswalk -- the plain one badly under-covers rostered players, not just
   free agents. Then greedily fills the team's starting
   slots (``lineup_efficiency.START_SLOT_ELIGIBILITY``) by descending
   projected rest-of-season points. Starters only, not the whole bench, so
   a deep-but-unstartable roster doesn't inflate this component. Z-scored
   within-league.

Blend weights, per the user's explicit choice (2026-09-17): 50% draft value,
20% week-1 performance, 30% ROS outlook -- "one week of results is noisy,
preseason roster value and forward outlook should dominate."

This intentionally does NOT use ``analytics.power_rankings.build_power_rankings``
(FFA-056): that model is win_pct/all-play/consistency over a full season's
matchup history, which is meaningless after one week and answers a
different question ("who has been the best team so far") than what was
asked here ("who is the strongest team right now, given roster talent and
outlook").
"""

from __future__ import annotations

import statistics
import sys as _sys
from pathlib import Path
from pathlib import Path as _Path

import pandas as pd

from fantasy_analyzer.league.snapshot import load_league_snapshot
from fantasy_analyzer.players.free_agents import FREE_AGENT_POOL_COLUMNS
from fantasy_analyzer.players.lineup_efficiency import START_SLOT_ELIGIBILITY
from fantasy_analyzer.players.nflverse_provider import NflverseWeeklyStatsProvider
from fantasy_analyzer.players.ros_backtest import build_scored_player_weeks
from fantasy_analyzer.players.ros_projection import DEFAULT_N0, ShrinkageParameters
from fantasy_analyzer.players.waiver_rankings import build_free_agent_ros_projections
from fantasy_analyzer.sleeper.cache import get_players_cached
from fantasy_analyzer.sleeper.client import SleeperClient

_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from player_analysis import build_robust_id_crosswalk  # noqa: E402

SEASON = 2026
CUTOFF_WEEK = 1
NFL_SEASON_WEEKS = range(1, 19)
OUTPUT_DIR = Path("scripts/output/draft2026")

LEAGUES = {
    "nwc": {
        "league_id": "1389350137481932800",
        "out_prefix": "NWC",
    },
    "new-wave": {
        "league_id": "1389754945892274176",
        "out_prefix": "NewWave",
    },
    "zipline": {
        "league_id": "1389707229824815104",
        "out_prefix": "Zipline",
    },
}

WEIGHT_DRAFT_VALUE = 0.5
WEIGHT_WEEK1 = 0.2
WEIGHT_ROS_OUTLOOK = 0.3


def _fetch_weekly_frames(provider, season: int, weeks) -> pd.DataFrame:
    frames = [provider.weekly_stats(season, week) for week in weeks]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _rostered_pool(raw_rosters: list[dict], catalog: dict, crosswalk: pd.DataFrame):
    """Build a FREE_AGENT_POOL_COLUMNS-shaped pool of every rostered player.

    Mirrors ``free_agents.build_free_agent_pool``'s row shape exactly, but
    over the *rostered* population (tagged with ``roster_id``) instead of
    the unrostered one -- see the module docstring.
    """
    gsis_by_sleeper_id = {}
    if crosswalk is not None and not crosswalk.empty:
        gsis_by_sleeper_id = dict(
            zip(crosswalk["sleeper_player_id"], crosswalk["gsis_id"])
        )

    rows = []
    roster_id_by_player_id: dict[str, int] = {}
    for roster in raw_rosters:
        roster_id = roster.get("roster_id")
        for player_id in roster.get("players") or []:
            player = catalog.get(player_id)
            if not isinstance(player, dict):
                continue
            gsis_id = gsis_by_sleeper_id.get(player_id)
            rows.append(
                {
                    "player_id": player_id,
                    "full_name": player.get("full_name"),
                    "position": player.get("position"),
                    "team": player.get("team"),
                    "status": player.get("status"),
                    "gsis_id": gsis_id,
                    "has_crosswalk": gsis_id is not None,
                    "player_owned_avg": None,
                }
            )
            roster_id_by_player_id[player_id] = roster_id

    pool = pd.DataFrame(rows, columns=FREE_AGENT_POOL_COLUMNS)
    pool["has_crosswalk"] = pool["has_crosswalk"].astype(bool)
    return pool, roster_id_by_player_id


def _greedy_starting_total(
    team_projections: pd.DataFrame, roster_positions: list[str]
) -> float:
    """Greedily fill starting slots by descending projected ROS points.

    Processes the most position-restrictive slots first (dedicated
    QB/RB/WR/TE/K/DEF before FLEX-style slots), then fills each slot with
    the best remaining eligible, not-yet-used player. Not an exhaustive
    optimum (see ``lineup_efficiency._optimal_lineup`` for that, over
    *realized* weekly points) but a reasonable, transparent approximation
    for a forward-looking outlook number.
    """
    remaining = team_projections.dropna(subset=["projected_ros_points"]).copy()
    remaining = remaining.sort_values("projected_ros_points", ascending=False)
    available = list(remaining.itertuples(index=False))

    start_slots = [slot for slot in roster_positions if slot in START_SLOT_ELIGIBILITY]
    start_slots.sort(key=lambda slot: len(START_SLOT_ELIGIBILITY[slot]))

    used_index: set[int] = set()
    total = 0.0
    for slot in start_slots:
        eligible_positions = START_SLOT_ELIGIBILITY[slot]
        best_i = None
        best_points = None
        for i, row in enumerate(available):
            if i in used_index:
                continue
            if row.position not in eligible_positions:
                continue
            if best_points is None or row.projected_ros_points > best_points:
                best_points = row.projected_ros_points
                best_i = i
        if best_i is not None:
            used_index.add(best_i)
            total += best_points
    return total


def _zscore(values: dict[int, float]) -> dict[int, float]:
    nums = list(values.values())
    if len(nums) < 2 or statistics.pstdev(nums) == 0:
        return {k: 0.0 for k in values}
    mean = statistics.mean(nums)
    stdev = statistics.pstdev(nums)
    return {k: (v - mean) / stdev for k, v in values.items()}


def run_league(slug: str, config: dict) -> pd.DataFrame:
    league_id = config["league_id"]
    client = SleeperClient()

    snapshot = load_league_snapshot(client, league_id)
    teams_df = snapshot.teams_df[["roster_id", "display_name"]].copy()

    # --- Signal 1: preseason draft/roster value (already computed) ---
    grades_path = OUTPUT_DIR / f"{config['out_prefix']}_2026_draft_report_team_grades.csv"
    grades_df = pd.read_csv(grades_path)[["roster_id", "team_name", "overall_z"]]

    # --- Signal 2: week 1 actual performance ---
    week1_raw = client.get_matchups(league_id, CUTOFF_WEEK)
    week1_points = {m["roster_id"]: m.get("points") or 0.0 for m in week1_raw}
    week1_z = _zscore(week1_points)

    # --- Signal 3: rest-of-season outlook (starters only) ---
    raw_rosters = client.get_rosters(league_id)
    catalog = get_players_cached(client)
    crosswalk = build_robust_id_crosswalk(catalog)
    provider = NflverseWeeklyStatsProvider(id_crosswalk=crosswalk)

    pool, roster_id_by_player_id = _rostered_pool(raw_rosters, catalog, crosswalk)

    current_season_raw = _fetch_weekly_frames(provider, SEASON, NFL_SEASON_WEEKS)
    prior_season_raw = _fetch_weekly_frames(provider, SEASON - 1, NFL_SEASON_WEEKS)
    scored_weeks = build_scored_player_weeks(
        [current_season_raw, prior_season_raw],
        snapshot.scoring_settings,
        player_id_column="gsis_id",
    )

    parameters = ShrinkageParameters(n0_by_position={}, default_n0=DEFAULT_N0)
    projections = build_free_agent_ros_projections(
        pool, scored_weeks, SEASON, CUTOFF_WEEK, parameters
    )
    projections["roster_id"] = projections["player_id"].map(roster_id_by_player_id)

    ros_outlook: dict[int, float] = {}
    for roster_id, group in projections.groupby("roster_id"):
        ros_outlook[roster_id] = _greedy_starting_total(
            group, snapshot.roster_positions
        )
    ros_outlook_z = _zscore(ros_outlook)

    # --- Blend ---
    rows = []
    for row in teams_df.itertuples(index=False):
        roster_id = row.roster_id
        rows.append(
            {
                "roster_id": roster_id,
                "team": row.display_name,
                "draft_value_z": None,
                "week1_points": week1_points.get(roster_id),
                "week1_z": week1_z.get(roster_id, 0.0),
                "ros_outlook_starters": ros_outlook.get(roster_id, 0.0),
                "ros_outlook_z": ros_outlook_z.get(roster_id, 0.0),
            }
        )
    result = pd.DataFrame(rows)
    result = result.merge(
        grades_df.rename(columns={"overall_z": "draft_value_z_grade"}),
        on="roster_id",
        how="left",
    )
    result["draft_value_z"] = result["draft_value_z_grade"]
    result = result.drop(columns=["draft_value_z_grade"])
    result["team"] = result["team_name"].fillna(result["team"])
    result = result.drop(columns=["team_name"])

    result["power_score"] = (
        WEIGHT_DRAFT_VALUE * result["draft_value_z"].fillna(0.0)
        + WEIGHT_WEEK1 * result["week1_z"]
        + WEIGHT_ROS_OUTLOOK * result["ros_outlook_z"]
    )
    result = result.sort_values("power_score", ascending=False).reset_index(drop=True)
    result.insert(0, "power_rank", range(1, len(result) + 1))
    return result


def main() -> None:
    for slug, config in LEAGUES.items():
        print(f"\n=== {config['out_prefix']} ({slug}) -- live power rankings after week {CUTOFF_WEEK}, {SEASON} ===")
        result = run_league(slug, config)
        cols = [
            "power_rank",
            "team",
            "power_score",
            "draft_value_z",
            "week1_points",
            "week1_z",
            "ros_outlook_starters",
            "ros_outlook_z",
        ]
        print(result[cols].to_string(index=False, float_format=lambda x: f"{x:.2f}"))


if __name__ == "__main__":
    main()

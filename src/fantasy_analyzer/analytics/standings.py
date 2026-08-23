"""Build base league standings from a normalized ``LeagueSnapshot``.

This module computes one row of season-to-date standings per team, joining
``rosters_df`` (Sleeper's cumulative per-roster record and points) with
``teams_df`` (roster-to-owner/display labels) on the immutable ``roster_id``.

Metric definitions
-------------------

- **wins**, **losses**, **ties** -- passed through unchanged from
  ``rosters_df`` (Sleeper's own cumulative roster-settings counters). This
  function does not recompute or validate these against matchup-level data.
- **win percentage** (``win_pct``) -- ``(wins + 0.5 * ties) / (wins + losses
  + ties)``. A team that has played zero games (``wins + losses + ties ==
  0``) gets ``win_pct = 0.0`` rather than a division-by-zero error or
  ``NaN`` -- this is the explicit missing-value/edge-case rule for this
  metric.
- **points for** (``points_for``) -- passed through unchanged from
  ``rosters_df["fpts"]`` (Sleeper's cumulative points scored, already
  combined from ``fpts``/``fpts_decimal`` upstream in
  :func:`fantasy_analyzer.league.snapshot._combine_points_setting`).
- **points against** (``points_against``) -- passed through unchanged from
  ``rosters_df["fpts_against"]`` (same combination treatment as
  ``points_for``).
- **point differential** (``point_diff``) -- ``points_for - points_against``.

Ranking rule
------------

Standings are sorted by descending ``win_pct``, then descending
``points_for`` as the tiebreaker (i.e. among teams with identical win
percentage, the team with more cumulative points scored ranks higher). This
mirrors Sleeper's own default standings tiebreak (record, then points for).

The ``rank`` column uses **standard competition ranking** ("1224" ranking):
teams tied on both ``win_pct`` and ``points_for`` receive the same rank, and
the next distinct rank skips the number of tied teams (e.g. two teams tied
for 1st both get ``rank = 1``, and the next team gets ``rank = 3``, not
``rank = 2``).

Regular season vs. playoffs
----------------------------

``build_standings`` operates entirely on Sleeper's roster-level cumulative
``wins``/``losses``/``ties``/``fpts``/``fpts_against`` fields. Sleeper does
not split these cumulative roster counters by season phase -- they are a
running season-to-date total that mixes regular-season and playoff games
indistinguishably at the roster-settings level. Consequently this function
makes **no** regular-season-vs-playoff distinction and cannot be made to;
phase-specific standings/records require per-week, per-matchup data and are
deferred to the matchup-level normalization work in Epic 4/5 (FFA-030
onward), which has the week-level granularity needed to filter by phase.
"""

from __future__ import annotations

import pandas as pd

#: Column order for the DataFrame returned by :func:`build_standings`.
STANDINGS_COLUMNS = [
    "roster_id",
    "owner_id",
    "display_name",
    "team_name",
    "wins",
    "losses",
    "ties",
    "win_pct",
    "points_for",
    "points_against",
    "point_diff",
    "rank",
]


def _win_pct(wins: float, losses: float, ties: float) -> float:
    """Compute win percentage, treating a winless/lossless/tieless team as 0.0.

    ``(wins + 0.5 * ties) / (wins + losses + ties)``. A team that has played
    zero games returns ``0.0`` rather than raising a division-by-zero error.
    """
    games = (wins or 0) + (losses or 0) + (ties or 0)
    if games == 0:
        return 0.0
    return ((wins or 0) + 0.5 * (ties or 0)) / games


def build_standings(rosters_df: pd.DataFrame, teams_df: pd.DataFrame) -> pd.DataFrame:
    """Build one row of season-to-date standings per team.

    Joins ``rosters_df`` (Sleeper's cumulative per-roster wins/losses/ties/
    points) to ``teams_df`` (roster-to-owner/display-name labels) on
    ``roster_id``, then computes ``win_pct``, ``point_diff``, and a
    competition-style ``rank``. See the module docstring for the exact
    metric definitions, ranking rule, and regular-season-vs-playoff caveat.

    Args:
        rosters_df: A ``LeagueSnapshot.rosters_df``-shaped DataFrame with at
            least ``["roster_id", "wins", "losses", "ties", "fpts",
            "fpts_against"]``.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame with at
            least ``["roster_id", "owner_id", "display_name",
            "team_name"]``.

    Returns:
        A DataFrame with columns ``["roster_id", "owner_id",
        "display_name", "team_name", "wins", "losses", "ties", "win_pct",
        "points_for", "points_against", "point_diff", "rank"]``, one row
        per roster, sorted by descending ``win_pct`` then descending
        ``points_for``. ``rank`` is 1-indexed standard competition ranking
        (ties share a rank; the next rank skips accordingly).

        If either input is empty, an empty DataFrame with the expected
        columns is returned.
    """
    if rosters_df.empty or teams_df.empty:
        return pd.DataFrame(columns=STANDINGS_COLUMNS)

    merged = rosters_df.merge(
        teams_df[["roster_id", "owner_id", "display_name", "team_name"]],
        on="roster_id",
        how="left",
        suffixes=("", "_team"),
    )

    merged["win_pct"] = merged.apply(
        lambda row: _win_pct(row["wins"], row["losses"], row["ties"]), axis=1
    )
    merged["points_for"] = merged["fpts"]
    merged["points_against"] = merged["fpts_against"]
    merged["point_diff"] = merged["points_for"] - merged["points_against"]

    merged = merged.sort_values(
        by=["win_pct", "points_for"], ascending=[False, False]
    ).reset_index(drop=True)

    # Standard competition ("1224") ranking: ties share a rank, and the next
    # distinct rank skips the number of tied teams.
    rank_keys = merged[["win_pct", "points_for"]].apply(tuple, axis=1)
    ranks = []
    current_rank = 0
    previous_key = None
    for position, key in enumerate(rank_keys, start=1):
        if key != previous_key:
            current_rank = position
            previous_key = key
        ranks.append(current_rank)
    merged["rank"] = ranks

    return merged[STANDINGS_COLUMNS]

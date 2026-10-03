"""Season-to-date team comparison for a head-to-head matchup preview (FFA-115).

Pure composition of existing analytics -- no new metric is defined here where
an existing one fits, and nothing touches the network. The three builders
produce the pieces of the dashboard's matchup ``Comparison`` object
(``docs/matchup_tab.md``): per-team season stats, this season's head-to-head
between the two teams, and a per-position production comparison.

Scope rule shared by every builder: **regular season only**, weeks
``<= through_week``. A matchup counts as a *played game* only if it has an
opponent and both sides' points are present -- the same rule
:func:`~fantasy_analyzer.analytics.standings.build_standings_through_week`
applies. Byes and weeks with missing points are not games, for either side.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from fantasy_analyzer.analytics.all_play import build_all_play_standings
from fantasy_analyzer.analytics.consistency import build_consistency_metrics
from fantasy_analyzer.analytics.head_to_head import build_head_to_head_records
from fantasy_analyzer.analytics.power_rankings import build_power_rankings
from fantasy_analyzer.analytics.standings import build_standings_through_week
from fantasy_analyzer.analytics.weekly_scores import build_weekly_scoring_ranks

#: Column order of :func:`build_matchup_team_stats`.
MATCHUP_TEAM_STATS_COLUMNS = [
    "roster_id",
    "wins",
    "losses",
    "ties",
    "rank",
    "points_for",
    "points_against",
    "ppg",
    "last3_ppg",
    "high",
    "low",
    "stdev_points",
    "all_play_wins",
    "all_play_losses",
    "all_play_ties",
    "power_rank",
    "power_score",
]

#: Positions listed first, in this order, by :func:`build_position_comparison`.
_POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF"]

_LAST_N_WEEKS = 3


def _regular_season_through(df: pd.DataFrame, through_week: int) -> pd.DataFrame:
    """Regular-season rows with ``week <= through_week`` (byes/incomplete kept)."""
    if df.empty:
        return df
    return df[
        (df["week"] <= through_week) & ~df["is_playoff"].fillna(False).astype(bool)
    ]


def _played(df: pd.DataFrame, through_week: int) -> pd.DataFrame:
    """Regular-season ``<= through_week`` rows that are real, scored games."""
    scoped = _regular_season_through(df, through_week)
    if scoped.empty:
        return scoped
    return scoped[
        scoped["roster_2_id"].notna()
        & scoped["points_1"].notna()
        & scoped["points_2"].notna()
    ]


def _nan_if_none(value: Any) -> float:
    return float("nan") if value is None or pd.isna(value) else float(value)


def build_matchup_team_stats(
    season_matchup_df: pd.DataFrame, teams_df: pd.DataFrame, through_week: int
) -> pd.DataFrame:
    """Build one season-to-date stat row per roster in ``teams_df``.

    Regular season only, weeks ``<= through_week``. Only *played games* count
    (see the module docstring): byes and weeks with missing points are not
    games.

    Columns (:data:`MATCHUP_TEAM_STATS_COLUMNS`):

    - ``wins``/``losses``/``ties``, ``rank``, ``points_for``,
      ``points_against``: from
      :func:`~fantasy_analyzer.analytics.standings.build_standings_through_week`
      (its standard-competition ``rank``; ties are not re-ranked here).
    - ``ppg``: ``points_for`` divided by games played; ``NaN`` with no games.
    - ``last3_ppg``: mean of the roster's last up-to-3 played weeks.
    - ``high`` / ``low``: the extreme single-week scores over played games.
    - ``stdev_points``: from
      :func:`~fantasy_analyzer.analytics.consistency.build_consistency_metrics`
      (population standard deviation; ``NaN`` under its 2-week minimum).
    - ``all_play_wins``/``all_play_losses``/``all_play_ties``: from
      :func:`~fantasy_analyzer.analytics.all_play.build_all_play_standings`
      over the played games; ``0`` for a roster with none.
    - ``power_rank`` / ``power_score``: from
      :func:`~fantasy_analyzer.analytics.power_rankings.build_power_rankings`
      over the regular-season, ``week <= through_week`` frame (the same input
      the dashboard's week payload uses); ``NaN`` for a roster with no decided
      game.

    An undefined value is ``NaN``, never dropped. ``through_week = 0`` (or any
    week before a game is played) returns every roster with a zero record and
    ``NaN`` for the rate/extreme/power columns rather than raising. Rows keep
    ``teams_df`` order; an empty ``teams_df`` yields an empty frame.
    """
    if teams_df.empty:
        return pd.DataFrame(columns=MATCHUP_TEAM_STATS_COLUMNS)

    standings = build_standings_through_week(
        season_matchup_df, teams_df, through_week
    ).set_index("roster_id")

    played = _played(season_matchup_df, through_week)
    weekly = build_weekly_scoring_ranks(played, teams_df)
    consistency = build_consistency_metrics(weekly)
    stdev_by_roster = (
        consistency.set_index("roster_id")["stdev_points"].to_dict()
        if not consistency.empty
        else {}
    )
    all_play = build_all_play_standings(weekly)
    all_play_by_roster = (
        all_play.set_index("roster_id").to_dict("index") if not all_play.empty else {}
    )
    power = build_power_rankings(
        _regular_season_through(season_matchup_df, through_week), teams_df
    )
    power_by_roster = (
        power.set_index("roster_id").to_dict("index") if not power.empty else {}
    )

    scores_by_roster: dict[int, list[float]] = {}
    if not weekly.empty:
        for row in weekly.sort_values(["week", "roster_id"]).itertuples(index=False):
            scores_by_roster.setdefault(int(row.roster_id), []).append(
                float(row.points)
            )

    rows = []
    for roster_id in teams_df["roster_id"]:
        roster_id = int(roster_id)
        standing = standings.loc[roster_id]
        scores = scores_by_roster.get(roster_id, [])
        play = all_play_by_roster.get(roster_id, {})
        pwr = power_by_roster.get(roster_id, {})
        last = scores[-_LAST_N_WEEKS:]
        rows.append(
            {
                "roster_id": roster_id,
                "wins": int(standing["wins"]),
                "losses": int(standing["losses"]),
                "ties": int(standing["ties"]),
                "rank": int(standing["rank"]),
                "points_for": float(standing["points_for"]),
                "points_against": float(standing["points_against"]),
                "ppg": float(standing["points_for"]) / len(scores)
                if scores
                else math.nan,
                "last3_ppg": sum(last) / len(last) if last else math.nan,
                "high": max(scores) if scores else math.nan,
                "low": min(scores) if scores else math.nan,
                "stdev_points": _nan_if_none(stdev_by_roster.get(roster_id)),
                "all_play_wins": int(play.get("all_play_wins", 0)),
                "all_play_losses": int(play.get("all_play_losses", 0)),
                "all_play_ties": int(play.get("all_play_ties", 0)),
                "power_rank": _nan_if_none(pwr.get("power_rank")),
                "power_score": _nan_if_none(pwr.get("power_score")),
            }
        )
    return pd.DataFrame(rows, columns=MATCHUP_TEAM_STATS_COLUMNS)


def build_season_head_to_head(
    season_matchup_df: pd.DataFrame,
    roster_id: int,
    opponent_roster_id: int,
    through_week: int,
) -> dict:
    """This season's meetings between two rosters, from ``roster_id``'s side.

    Regular season only, weeks ``<= through_week``, played games only. The
    ``wins``/``losses``/``ties`` totals come from
    :func:`~fantasy_analyzer.analytics.head_to_head.build_head_to_head_records`
    over that scope; ``games`` lists each meeting by ascending week.

    Returns:
        ``{"meetings", "wins", "losses", "ties", "games": [{"week", "points",
        "opponent_points"}]}``. Zero meetings gives zero counts and an empty
        ``games`` list. A pair that met twice is two entries.
    """
    played = _played(season_matchup_df, through_week)
    games: list[dict] = []
    if not played.empty:
        for row in played.sort_values("week", kind="stable").itertuples(index=False):
            pair = (int(row.roster_1_id), int(row.roster_2_id))
            if pair == (roster_id, opponent_roster_id):
                own, against = row.points_1, row.points_2
            elif pair == (opponent_roster_id, roster_id):
                own, against = row.points_2, row.points_1
            else:
                continue
            games.append(
                {"week": int(row.week), "points": float(own),
                 "opponent_points": float(against)}
            )

    records = build_head_to_head_records(played, pd.DataFrame())
    match = records[
        (records["roster_id"] == roster_id)
        & (records["opponent_roster_id"] == opponent_roster_id)
    ]
    if match.empty:
        wins = losses = ties = 0
    else:
        record = match.iloc[0]
        wins, losses, ties = (
            int(record["wins"]), int(record["losses"]), int(record["ties"])
        )
    return {
        "meetings": len(games),
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "games": games,
    }


def build_position_comparison(
    position_strength_df: pd.DataFrame, team_label: str, opponent_label: str
) -> list[dict]:
    """Compare two teams' started production by position.

    Reads
    :func:`~fantasy_analyzer.players.position_strength.build_position_strength_metrics`
    output: ``points_per_game`` and ``positional_rank`` (standard competition
    rank by total points among all teams at that position) for the rows whose
    ``fantasy_team`` equals each label.

    Returns:
        ``[{"position", "me_ppg", "me_rank", "opponent_ppg",
        "opponent_rank"}]`` over the union of positions either team has, QB,
        RB, WR, TE, K, DEF first (when present) then any others
        alphabetically. A side with no row at a position has ``None`` for
        ppg and rank. Empty input gives ``[]``.
    """
    if position_strength_df.empty:
        return []

    def side(label: str) -> dict:
        subset = position_strength_df[position_strength_df["fantasy_team"] == label]
        return {
            row.position: (float(row.points_per_game), int(row.positional_rank))
            for row in subset.itertuples(index=False)
        }

    mine, theirs = side(team_label), side(opponent_label)
    present = set(mine) | set(theirs)
    ordered = [p for p in _POSITION_ORDER if p in present] + sorted(
        present - set(_POSITION_ORDER)
    )
    result = []
    for position in ordered:
        me_ppg, me_rank = mine.get(position, (None, None))
        opp_ppg, opp_rank = theirs.get(position, (None, None))
        result.append(
            {
                "position": position,
                "me_ppg": me_ppg,
                "me_rank": me_rank,
                "opponent_ppg": opp_ppg,
                "opponent_rank": opp_rank,
            }
        )
    return result

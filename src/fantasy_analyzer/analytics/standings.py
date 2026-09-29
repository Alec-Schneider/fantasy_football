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

Scoring summary (FFA-021)
--------------------------

:func:`build_scoring_summary` extends the same season-cumulative
``rosters_df``/``teams_df`` inputs with per-game scoring rate metrics.

- **games played** -- ``wins + losses + ties`` (not a returned column, but
  the shared denominator for the per-game metrics below). Same
  cumulative-counter caveat as ``build_standings``: it is season-to-date and
  does not distinguish regular season from playoffs.
- **points per game** (``points_per_game``) -- ``points_for / games_played``.
  A team with zero games played gets ``0.0`` rather than a
  division-by-zero error or ``NaN`` -- the same explicit missing-value rule
  used for ``win_pct`` in ``build_standings``.
- **points against per game** (``points_against_per_game``) -- same pattern,
  using ``points_against``; also ``0.0`` at zero games played.
- **average margin** (``avg_margin``) -- ``point_diff / games_played``; also
  ``0.0`` at zero games played.
- **scoring rank** (``scoring_rank``) -- rank of teams by ``points_for``
  descending, using the same standard competition ("1224") ranking
  convention as ``build_standings.rank`` (documented above): tied
  ``points_for`` values share a rank, and the next distinct rank skips the
  number of tied teams.

``high_score`` / ``low_score`` -- **not implemented, by design.** The ticket
(FFA-021) calls for a team's single highest and lowest weekly scores.
Sleeper's roster-level ``settings`` only exposes season-cumulative
``fpts``/``fpts_against`` totals (see ``league/snapshot.py``), not a
per-week score history, so there is no way to derive a single game's high
or low from the data available to this module. Computing this requires
per-week matchup data, which does not exist in this codebase yet (Epic 4 /
FFA-030 onward). Rather than approximate or fabricate these values from the
cumulative totals, ``build_scoring_summary`` omits ``high_score`` and
``low_score`` entirely and this gap is called out explicitly. Revisit once
FFA-033's season matchup DataFrame exists.

Scoring summary does not distinguish regular season from playoffs, for the
same reason as ``build_standings`` above -- Sleeper's roster counters are
season-cumulative.

As-of-week standings (FFA-102)
-------------------------------

:func:`build_standings_through_week` answers the question ``build_standings``
structurally cannot: *what did the standings look like after week N?* It
takes the week-level
:data:`~fantasy_analyzer.matchups.season_matchups.SEASON_MATCHUP_COLUMNS`
frame instead of ``rosters_df``, so every counter is re-derived from
matchup results rather than read off Sleeper's running totals. It returns
the same :data:`STANDINGS_COLUMNS` shape, uses the same win-percentage
definition and the same ``win_pct`` -> ``points_for`` competition-ranking
rule, and is therefore a drop-in for any consumer of ``build_standings``.

- **wins/losses/ties** -- counted from ``winner``/``loser``/``is_tie``,
  which :mod:`~fantasy_analyzer.matchups.season_matchups` carries through as
  raw ``roster_id`` values (not owner labels).
- **points_for** / **points_against** -- summed from ``points_1``/
  ``points_2``, read from whichever side of the pairing the roster sits on.

Regular season vs. playoffs -- **explicit**, unlike the two functions above.
``include_playoffs`` defaults to ``False``, so the returned standings
describe regular-season play only, matching the conventional meaning of
"standings after week N". Pass ``include_playoffs=True`` to count playoff
results too.

Incomplete matchups -- a bye, or a week whose scores Sleeper has not
populated -- contribute **nothing**: no win, no loss, and no points on
either side. A row is counted only when it has an opponent
(``roster_2_id``) and both point totals. This keeps ``points_for`` and
``points_against`` symmetric across the league (every counted game
contributes to both), which in turn keeps ``point_diff`` meaningful; the
alternative, crediting a bye team's points with no opposing total, would
inflate that team's differential by a full game. A team whose every game so
far is incomplete appears with an all-zero record rather than being dropped.
"""

from __future__ import annotations

from typing import Any, Sequence

import pandas as pd

#: Per-roster counters :func:`build_standings_through_week` accumulates.
_RECORD_FIELDS = ["wins", "losses", "ties", "points_for", "points_against"]

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

#: Column order for the DataFrame returned by :func:`build_scoring_summary`.
SCORING_SUMMARY_COLUMNS = [
    "roster_id",
    "owner_id",
    "display_name",
    "team_name",
    "points_per_game",
    "points_against_per_game",
    "scoring_rank",
    "avg_margin",
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

    merged["rank"] = _competition_ranks(
        merged[["win_pct", "points_for"]].apply(tuple, axis=1)
    )

    return merged[STANDINGS_COLUMNS]


def _competition_ranks(keys: Sequence[Any]) -> list[int]:
    """Assign standard competition ("1224") ranks to already-sorted ``keys``.

    Equal adjacent keys share a rank, and the next distinct rank skips the
    number of tied entries -- two teams tied for 1st both get ``1`` and the
    next gets ``3``. ``keys`` must already be in ranking order; this helper
    does not sort.
    """
    ranks: list[int] = []
    current_rank = 0
    previous_key = None
    for position, key in enumerate(keys, start=1):
        if key != previous_key:
            current_rank = position
            previous_key = key
        ranks.append(current_rank)
    return ranks


def build_standings_through_week(
    season_matchup_df: pd.DataFrame,
    teams_df: pd.DataFrame,
    week: int,
    *,
    include_playoffs: bool = False,
) -> pd.DataFrame:
    """Build standings as they stood after ``week``, from matchup results.

    Re-derives every counter from the week-level season matchup frame rather
    than reading Sleeper's season-cumulative roster totals, which is what
    makes an "after week N" view possible at all --
    :func:`build_standings` can only ever report the present. See the module
    docstring's "As-of-week standings" section for the metric definitions,
    the explicit regular-season-vs-playoff rule, and how incomplete matchups
    and byes are handled.

    Args:
        season_matchup_df: A
            :data:`~fantasy_analyzer.matchups.season_matchups.SEASON_MATCHUP_COLUMNS`-shaped
            DataFrame, as returned by
            :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame with at
            least ``["roster_id", "owner_id", "display_name",
            "team_name"]``. Defines the league's full set of rosters, so a
            team that has not yet played still gets a row.
        week: The last week to count. Every matchup with ``week <= week`` is
            included; later weeks are ignored.
        include_playoffs: If ``False`` (the default), count regular-season
            matchups only. If ``True``, count playoff matchups as well.

    Returns:
        A :data:`STANDINGS_COLUMNS`-shaped DataFrame, one row per roster in
        ``teams_df``, sorted by descending ``win_pct`` then descending
        ``points_for``, with 1-indexed standard competition ``rank``.

        An empty DataFrame with the expected columns if ``teams_df`` is
        empty. If no matchup qualifies (``week`` precedes the season, or
        every result is incomplete), every team is returned at an all-zero
        record -- the league before a ball was snapped, not an error.
    """
    if teams_df.empty:
        return pd.DataFrame(columns=STANDINGS_COLUMNS)

    records: dict[Any, dict[str, float]] = {
        roster_id: {
            "wins": 0.0,
            "losses": 0.0,
            "ties": 0.0,
            "points_for": 0.0,
            "points_against": 0.0,
        }
        for roster_id in teams_df["roster_id"]
    }

    if not season_matchup_df.empty:
        played = season_matchup_df[season_matchup_df["week"] <= week]
        if not include_playoffs:
            played = played[~played["is_playoff"].fillna(False).astype(bool)]
        # Byes and unplayed/partial weeks carry no opponent or no scores;
        # they contribute to neither record nor points. See the module
        # docstring's "Incomplete matchups" rule.
        played = played[
            played["roster_2_id"].notna()
            & played["points_1"].notna()
            & played["points_2"].notna()
        ]

        for row in played.itertuples(index=False):
            for roster_id, own, against in (
                (row.roster_1_id, row.points_1, row.points_2),
                (row.roster_2_id, row.points_2, row.points_1),
            ):
                record = records.setdefault(
                    roster_id,
                    {
                        "wins": 0.0,
                        "losses": 0.0,
                        "ties": 0.0,
                        "points_for": 0.0,
                        "points_against": 0.0,
                    },
                )
                record["points_for"] += float(own)
                record["points_against"] += float(against)
                if row.is_tie:
                    record["ties"] += 1
                elif row.winner == roster_id:
                    record["wins"] += 1
                elif row.loser == roster_id:
                    record["losses"] += 1

    rows = [
        {"roster_id": roster_id, **record} for roster_id, record in records.items()
    ]
    standings = pd.DataFrame(rows, columns=["roster_id", *_RECORD_FIELDS])

    standings = standings.merge(
        teams_df[["roster_id", "owner_id", "display_name", "team_name"]],
        on="roster_id",
        how="left",
    )

    standings["win_pct"] = standings.apply(
        lambda row: _win_pct(row["wins"], row["losses"], row["ties"]), axis=1
    )
    standings["point_diff"] = standings["points_for"] - standings["points_against"]

    standings = standings.sort_values(
        by=["win_pct", "points_for"], ascending=[False, False]
    ).reset_index(drop=True)
    standings["rank"] = _competition_ranks(
        standings[["win_pct", "points_for"]].apply(tuple, axis=1)
    )

    return standings[STANDINGS_COLUMNS]


def _games_played(wins: float, losses: float, ties: float) -> float:
    """Return the shared per-game denominator: ``wins + losses + ties``."""
    return (wins or 0) + (losses or 0) + (ties or 0)


def _per_game(total: float, games_played: float) -> float:
    """Divide ``total`` by ``games_played``, returning ``0.0`` at zero games.

    Shared missing-value rule for ``points_per_game``,
    ``points_against_per_game``, and ``avg_margin`` -- see the module
    docstring's "Scoring summary" section.
    """
    if games_played == 0:
        return 0.0
    return total / games_played


def build_scoring_summary(
    rosters_df: pd.DataFrame, teams_df: pd.DataFrame
) -> pd.DataFrame:
    """Build one row of season-to-date scoring-rate metrics per team.

    Joins ``rosters_df`` (Sleeper's cumulative per-roster points and
    win/loss/tie counters) to ``teams_df`` (roster-to-owner/display-name
    labels) on ``roster_id``, then computes ``points_per_game``,
    ``points_against_per_game``, ``avg_margin``, and ``scoring_rank``. See
    the module docstring's "Scoring summary (FFA-021)" section for exact
    metric definitions, the zero-games edge case, the ranking rule, and why
    ``high_score``/``low_score`` are not included.

    Args:
        rosters_df: A ``LeagueSnapshot.rosters_df``-shaped DataFrame with at
            least ``["roster_id", "wins", "losses", "ties", "fpts",
            "fpts_against"]``.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame with at
            least ``["roster_id", "owner_id", "display_name",
            "team_name"]``.

    Returns:
        A DataFrame with columns ``["roster_id", "owner_id",
        "display_name", "team_name", "points_per_game",
        "points_against_per_game", "scoring_rank", "avg_margin"]``, one row
        per roster, sorted by descending ``points_per_game``.
        ``scoring_rank`` is 1-indexed standard competition ranking based on
        cumulative ``points_for`` (ties share a rank; the next rank skips
        accordingly).

        If either input is empty, an empty DataFrame with the expected
        columns is returned.
    """
    if rosters_df.empty or teams_df.empty:
        return pd.DataFrame(columns=SCORING_SUMMARY_COLUMNS)

    merged = rosters_df.merge(
        teams_df[["roster_id", "owner_id", "display_name", "team_name"]],
        on="roster_id",
        how="left",
        suffixes=("", "_team"),
    )

    merged["points_for"] = merged["fpts"]
    merged["points_against"] = merged["fpts_against"]
    merged["_games_played"] = merged.apply(
        lambda row: _games_played(row["wins"], row["losses"], row["ties"]), axis=1
    )
    merged["points_per_game"] = merged.apply(
        lambda row: _per_game(row["points_for"], row["_games_played"]), axis=1
    )
    merged["points_against_per_game"] = merged.apply(
        lambda row: _per_game(row["points_against"], row["_games_played"]), axis=1
    )
    merged["avg_margin"] = merged.apply(
        lambda row: _per_game(
            row["points_for"] - row["points_against"], row["_games_played"]
        ),
        axis=1,
    )

    merged = merged.sort_values(by=["points_per_game"], ascending=[False]).reset_index(
        drop=True
    )

    # scoring_rank is based on cumulative points_for, not points_per_game --
    # same standard competition ("1224") ranking convention as
    # build_standings.rank.
    rank_source = rosters_df[["roster_id", "fpts"]].rename(
        columns={"fpts": "points_for"}
    )
    rank_source = rank_source.sort_values(
        by=["points_for"], ascending=[False]
    ).reset_index(drop=True)

    ranks_by_roster: dict = {}
    current_rank = 0
    previous_key = None
    for position, row in enumerate(rank_source.itertuples(index=False), start=1):
        key = row.points_for
        if key != previous_key:
            current_rank = position
            previous_key = key
        ranks_by_roster[row.roster_id] = current_rank

    merged["scoring_rank"] = merged["roster_id"].map(ranks_by_roster)

    return merged[SCORING_SUMMARY_COLUMNS]

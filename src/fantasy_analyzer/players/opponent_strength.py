"""Opponent and schedule context for a player projection (FFA-099).

The first opponent-aware layer in this codebase.
:mod:`fantasy_analyzer.players.ros_projection` is explicit that it performs
**no opponent adjustment** -- it blends a player's own rate with his own
prior and stops. That is the right scope for a projection, but it leaves a
waiver board unable to answer the two questions a manager actually asks in
week 2: *who does he play this week*, and *does his rest-of-season schedule
help or hurt*.

This module answers both without touching the projection. Everything here
produces **context columns beside** ``projected_ppg``, never a replacement
for it, so the measured accuracy in ``docs/ros-projection-accuracy.md``
still describes the number the board ranks on.

The three inputs
--------------------------------------------------------------------------

1. **The NFL schedule** (``nflverse_schedule_cache.get_games_cached``, the
   cumulative ``games.csv``). This carries every *future* week, which is
   the whole point: nflverse's weekly player stats carry an
   ``opponent_team`` column, but only for weeks already played. A week-2
   opponent cannot come from the stats frame.
2. **Realized player-weeks** (``build_scored_player_weeks``), which now
   carry :data:`~fantasy_analyzer.players.ros_backtest.CARRIED_CONTEXT_COLUMNS`
   so points can be attributed to the defense that allowed them.
3. **The betting market**, carried on the schedule as ``spread_line`` and
   ``total_line``. See "Implied team total" below.

Defense vs. position, and why it is shrunk
--------------------------------------------------------------------------

:func:`build_defense_vs_position` asks: how many fantasy points per game
has this defense allowed to this position, relative to what the average
defense allowed? The raw ratio is

.. code-block:: text

    raw_multiplier = points_allowed_per_game / league_mean_points_allowed

computed per ``(defense, position)`` over the weeks played so far, where
"points allowed" is scored **with the league's own scoring settings** --
a PPR league and a standard league genuinely have different defense-vs-WR
rankings, and using a generic points column would quietly ignore that.

Raw defense-vs-position is close to useless early in a season, and being
early in a season is exactly when a waiver board is most consulted. After
one week, a defense that happened to face a team's backup quarterback
looks elite; after two, one long touchdown separates "toughest" from
"average". So the multiplier is shrunk toward 1.0 (no adjustment) by the
same empirical-Bayes form the projection itself uses:

.. code-block:: text

    multiplier = (n * raw_multiplier + k * 1.0) / (n + k)

``n`` is the number of games the defense has played, ``k`` is
:data:`DEFAULT_DVP_SHRINKAGE_GAMES`. At the default ``k = 6``, a week-2
defense carries ``2 / 8 = 25%`` of its raw signal and the adjustment is
deliberately timid -- a defense that allowed twice the league average
moves a projection by about 25%, not 100%. By week 10 it carries 62%.
This is a considered choice, not a hedge: an unshrunk week-2 multiplier
would swamp the projection it is supposed to inform, and the fitted
shrinkage work in ``docs/ros-projection-accuracy.md`` is the precedent for
preferring a blended estimate over a raw early-season rate.

``k`` is **not fitted**. Unlike ``ros_projection``'s ``n0``, no backtest in
this codebase measures defense-vs-position accuracy, so 6 is a documented
prior, not a measured optimum. :func:`build_defense_vs_position` takes it
as an argument so a future ticket can fit it the way FFA-089/090 fit
``n0``; until then, every adjusted number this module produces should be
read as directional. That is why :func:`add_matchup_context` writes
``matchup_adjusted_ppg`` as a *separate column* and never overwrites
``projected_ppg``.

Implied team total
--------------------------------------------------------------------------

``spread_line`` and ``total_line`` give a team's implied points:

.. code-block:: text

    implied_team_total = total_line / 2 - spread_line / 2   (for the favorite's
                                                             opponent, sign per
                                                             nflverse's convention)

nflverse states ``spread_line`` from the **home team's** perspective (a
positive value means the home team is favored by that many points), so the
home side's implied total is ``total_line / 2 + spread_line / 2`` and the
away side's is ``total_line / 2 - spread_line / 2``.

This is the single strongest weekly signal available here, and also the
most perishable: nflverse populates lines only for the next week or two.
Measured on the 2026 schedule at week 2, **48 of 272** regular-season games
carried a line -- weeks 1 through 3. So implied totals inform the
*this-week* view and are simply ``NaN`` for the rest of the season, which
is the honest representation rather than a stale or extrapolated number.
No column here blends the market into the projection; ``ros_projection``
still owns that, and it has no market input.

What this module does not do
--------------------------------------------------------------------------

- **No home/road adjustment beyond reporting ``is_home``.** The effect is
  real but small relative to the noise in a two-week defense sample.
- **No defense-vs-position for K or DEF.** Both are computed if the data
  is there, but kicker scoring is close to unmodellable at this sample
  size and the reader should ignore those rows.
- **No injury or depth-chart signal**, so a defense-vs-position figure
  built over weeks when a team's starting corner was healthy is applied
  unchanged to a week when he is not.
- **No strength-of-schedule beyond the mean multiplier.** A player whose
  hardest games cluster in the fantasy playoffs and one whose cluster in
  October get the same ``remaining_schedule_multiplier``.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

#: Games of evidence at which a defense's raw defense-vs-position ratio and
#: the no-adjustment null (1.0) carry equal weight. See the module
#: docstring's "Defense vs. position, and why it is shrunk" section --
#: notably that this value is a documented prior, not a fitted one.
DEFAULT_DVP_SHRINKAGE_GAMES = 6.0

#: Team abbreviations that differ between Sleeper's player catalog and
#: nflverse's schedule/stats. Measured against the full 2026 vocabularies,
#: this is the complete set of disagreements: Sleeper says ``LAR`` where
#: nflverse says ``LA``, and Sleeper still carries the historical ``OAK``
#: for a handful of catalog entries.
SLEEPER_TO_NFLVERSE_TEAM = {"LAR": "LA", "OAK": "LV"}

#: Column order for :func:`normalize_schedule`'s output.
TEAM_WEEK_SCHEDULE_COLUMNS = [
    "season",
    "week",
    "team",
    "opponent",
    "is_home",
    "implied_team_total",
    "total_line",
    "spread_line",
]

#: Column order for :func:`build_defense_vs_position`'s output.
DEFENSE_VS_POSITION_COLUMNS = [
    "defense",
    "position",
    "games",
    "points_allowed_per_game",
    "league_mean_points_allowed",
    "raw_multiplier",
    "dvp_multiplier",
]

#: Columns :func:`add_matchup_context` appends to a ranking frame.
MATCHUP_CONTEXT_COLUMNS = [
    "nfl_team",
    "week_opponent",
    "week_is_home",
    "week_implied_team_total",
    "week_dvp_multiplier",
    "matchup_adjusted_ppg",
    "bye_week",
    "remaining_schedule_multiplier",
    "remaining_games_scheduled",
    "schedule_adjusted_ros_points",
]


def normalize_team(team: Optional[str]) -> Optional[str]:
    """Map a Sleeper team abbreviation onto nflverse's vocabulary.

    Args:
        team: A team abbreviation from any source, or ``None``.

    Returns:
        The nflverse spelling (see :data:`SLEEPER_TO_NFLVERSE_TEAM`), or the
        input unchanged when the two sources already agree. ``None`` and
        the empty string pass through as ``None``, so an unsigned free
        agent does not acquire a phantom team.
    """
    if team is None or (isinstance(team, float) and pd.isna(team)) or team == "":
        return None
    return SLEEPER_TO_NFLVERSE_TEAM.get(team, team)


def normalize_schedule(games: pd.DataFrame, season: int) -> pd.DataFrame:
    """Turn nflverse's one-row-per-game table into two team-week rows.

    Regular-season games only (``game_type == "REG"``), matching
    :func:`~fantasy_analyzer.players.ros_backtest.build_scored_player_weeks`'s
    own regular-season filter so the two frames join cleanly.

    See the module docstring's "Implied team total" section for the
    ``spread_line`` sign convention and why most weeks have none.

    Args:
        games: nflverse's cumulative games table, as returned by
            :func:`~fantasy_analyzer.players.nflverse_schedule_cache.get_games_cached`.
        season: The season to extract.

    Returns:
        A DataFrame with :data:`TEAM_WEEK_SCHEDULE_COLUMNS`, two rows per
        game (one per team). Empty (same columns) if ``games`` is empty or
        has no regular-season rows for ``season``. A team's bye week
        simply has no row -- see :func:`bye_weeks`.
    """
    if games.empty:
        return pd.DataFrame(
            {column: pd.Series(dtype=object) for column in TEAM_WEEK_SCHEDULE_COLUMNS}
        )

    season_games = games[games["season"] == season]
    if "game_type" in season_games.columns:
        season_games = season_games[season_games["game_type"] == "REG"]
    if season_games.empty:
        return pd.DataFrame(
            {column: pd.Series(dtype=object) for column in TEAM_WEEK_SCHEDULE_COLUMNS}
        )

    total = pd.to_numeric(season_games.get("total_line"), errors="coerce")
    spread = pd.to_numeric(season_games.get("spread_line"), errors="coerce")

    home = pd.DataFrame(
        {
            "season": season_games["season"],
            "week": season_games["week"],
            "team": season_games["home_team"],
            "opponent": season_games["away_team"],
            "is_home": True,
            # spread_line is stated from the home team's perspective.
            "implied_team_total": total / 2.0 + spread / 2.0,
            "total_line": total,
            "spread_line": spread,
        }
    )
    away = pd.DataFrame(
        {
            "season": season_games["season"],
            "week": season_games["week"],
            "team": season_games["away_team"],
            "opponent": season_games["home_team"],
            "is_home": False,
            "implied_team_total": total / 2.0 - spread / 2.0,
            "total_line": total,
            "spread_line": -spread,
        }
    )

    schedule = pd.concat([home, away], ignore_index=True)
    schedule["week"] = pd.to_numeric(schedule["week"], errors="coerce").astype("int64")
    schedule["is_home"] = schedule["is_home"].astype(bool)
    return schedule.sort_values(["week", "team"], kind="stable").reset_index(drop=True)[
        TEAM_WEEK_SCHEDULE_COLUMNS
    ]


def bye_weeks(schedule: pd.DataFrame, season_end_week: int) -> dict[str, Optional[int]]:
    """Each team's bye week, derived from the weeks it has no game.

    Args:
        schedule: As returned by :func:`normalize_schedule`.
        season_end_week: Last week to consider. A team with no game after
            this is not on a bye, it is simply outside the window.

    Returns:
        ``team -> bye week``, or ``team -> None`` for a team with no
        missing week inside the window (or more than one, which would mean
        the schedule is incomplete rather than that the team has two byes).
        Empty if ``schedule`` is empty.
    """
    if schedule.empty:
        return {}

    weeks = set(range(1, season_end_week + 1))
    byes: dict[str, Optional[int]] = {}
    for team, played in schedule[schedule["week"] <= season_end_week].groupby("team")[
        "week"
    ]:
        missing = sorted(weeks - set(played.tolist()))
        byes[team] = int(missing[0]) if len(missing) == 1 else None
    return byes


def completed_nfl_weeks(schedule: pd.DataFrame, season: int) -> list[int]:
    """NFL weeks of ``season`` in which every scheduled game has a final score.

    A week is complete iff it has at least one regular-season game and
    every one of its games carries both ``home_score`` and ``away_score``.
    This is the exact signal a fantasy week needs (FFA-108): fantasy
    points alone cannot tell a finished week from one still waiting on
    Monday night, because by Monday every fantasy team already has *some*
    points. nflverse fills a game's scores once it is final, so a week
    with 15 of 16 games scored is not complete.

    Regular season only (``game_type == "REG"``), matching
    :func:`normalize_schedule`. A game that is never played (cancelled)
    keeps its week incomplete forever -- the conservative failure: the
    week shows as unfinished rather than final with a missing result.

    Args:
        schedule: nflverse's one-row-per-game table, as returned by
            :func:`~fantasy_analyzer.players.nflverse_schedule_cache.get_games_cached`
            -- the ``games`` input to :func:`normalize_schedule`, not its
            output, which carries no scores.
        season: The season to inspect.

    Returns:
        The complete weeks, ascending. Empty if ``schedule`` is empty, has
        no score columns, or has no regular-season rows for ``season``.
    """
    required = {"season", "week", "home_score", "away_score"}
    if schedule.empty or not required <= set(schedule.columns):
        return []

    games = schedule[schedule["season"] == season]
    if "game_type" in games.columns:
        games = games[games["game_type"] == "REG"]
    if games.empty:
        return []

    home = pd.to_numeric(games["home_score"], errors="coerce")
    away = pd.to_numeric(games["away_score"], errors="coerce")
    scored = (home.notna() & away.notna()).groupby(games["week"]).all()
    return sorted(int(week) for week, done in scored.items() if done)


def build_defense_vs_position(
    scored_weeks: pd.DataFrame,
    season: int,
    through_week: int,
    *,
    shrinkage_games: float = DEFAULT_DVP_SHRINKAGE_GAMES,
    positions: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Fantasy points each defense allows per position, shrunk toward 1.0.

    See the module docstring's "Defense vs. position, and why it is shrunk"
    section for the full definition, the shrinkage form, and the explicit
    warning that ``shrinkage_games`` is an unfitted prior.

    Worked example (hand-checkable). Two defenses, one position, two weeks
    each, ``shrinkage_games = 6``:

    - ``D1`` allowed 20 and 40 points to WRs -> 30.0 per game.
    - ``D2`` allowed 10 and 10 -> 10.0 per game.
    - League mean allowed per game = ``(30 + 10) / 2 = 20.0``.
    - ``D1``'s raw multiplier = ``30 / 20 = 1.5``; shrunk =
      ``(2 * 1.5 + 6 * 1.0) / 8 = 1.125``.
    - ``D2``'s raw = ``0.5``; shrunk = ``(2 * 0.5 + 6 * 1.0) / 8 = 0.875``.

    Args:
        scored_weeks: League-scored player-weeks carrying
            :data:`~fantasy_analyzer.players.ros_backtest.CARRIED_CONTEXT_COLUMNS`
            (specifically ``opponent_team``). Rows without an opponent --
            every future week, and any provider that does not supply it --
            are ignored.
        season: The season to measure.
        through_week: Last completed week to include.
        shrinkage_games: ``k`` in the blend toward 1.0. ``0`` disables
            shrinkage and returns the raw ratio.
        positions: Restrict to these positions. Defaults to every position
            present.

    Returns:
        A DataFrame with :data:`DEFENSE_VS_POSITION_COLUMNS`, one row per
        ``(defense, position)`` with at least one attributed game. Empty
        (same columns) if no row can be attributed to a defense -- an
        expected outcome before week 1, not an error.

    Raises:
        ValueError: If ``shrinkage_games`` is negative.
    """
    if shrinkage_games < 0:
        raise ValueError(f"shrinkage_games must be >= 0; got {shrinkage_games}.")

    empty = pd.DataFrame(
        {column: pd.Series(dtype="float64") for column in DEFENSE_VS_POSITION_COLUMNS}
    )
    if scored_weeks.empty or "opponent_team" not in scored_weeks.columns:
        return empty

    weeks = scored_weeks[
        (scored_weeks["season"] == season)
        & (scored_weeks["week"] >= 1)
        & (scored_weeks["week"] <= through_week)
        & scored_weeks["opponent_team"].notna()
        & scored_weeks["position"].notna()
    ]
    if positions is not None:
        weeks = weeks[weeks["position"].isin(positions)]
    if weeks.empty:
        return empty

    # Points allowed by a defense in a week = the sum of what every player
    # at that position scored against it. Summed first, then averaged over
    # the defense's games, so a position group's whole output counts (a
    # committee backfield allows the same points as a bellcow).
    per_game = (
        weeks.groupby(["opponent_team", "position", "week"], sort=False)[
            "fantasy_points"
        ]
        .sum()
        .reset_index()
    )
    summary = (
        per_game.groupby(["opponent_team", "position"], sort=False)["fantasy_points"]
        .agg(["size", "mean"])
        .reset_index()
        .rename(
            columns={
                "opponent_team": "defense",
                "size": "games",
                "mean": "points_allowed_per_game",
            }
        )
    )

    league_mean = summary.groupby("position")["points_allowed_per_game"].transform(
        "mean"
    )
    summary["league_mean_points_allowed"] = league_mean
    summary["raw_multiplier"] = summary["points_allowed_per_game"] / league_mean
    # A position whose league mean is 0.0 leaves the ratio undefined; treat
    # it as "no information", which is exactly a multiplier of 1.0.
    summary["raw_multiplier"] = summary["raw_multiplier"].replace(
        [float("inf"), float("-inf")], float("nan")
    )

    games = summary["games"].astype(float)
    summary["dvp_multiplier"] = (
        games * summary["raw_multiplier"].fillna(1.0) + shrinkage_games * 1.0
    ) / (games + shrinkage_games)

    summary["games"] = summary["games"].astype("int64")
    return summary.sort_values(
        ["position", "dvp_multiplier"], kind="stable"
    ).reset_index(drop=True)[DEFENSE_VS_POSITION_COLUMNS]


def add_matchup_context(
    rankings: pd.DataFrame,
    schedule: pd.DataFrame,
    defense_vs_position: pd.DataFrame,
    *,
    week: int,
    season_end_week: int,
    team_column: str = "team",
    ppg_column: str = "projected_ppg",
) -> pd.DataFrame:
    """Attach this-week and rest-of-season schedule context to a ranking.

    Adds :data:`MATCHUP_CONTEXT_COLUMNS`. ``rankings``' own columns are
    left untouched -- in particular ``projected_ppg`` is never overwritten;
    the adjusted figure is a separate ``matchup_adjusted_ppg``, for the
    reason given in the module docstring's "Defense vs. position" section.

    ``remaining_games_scheduled`` is the count of weeks in
    ``(week, season_end_week]`` in which the player's team actually has a
    game. This is the first bye-aware games count in the pipeline:
    :func:`~fantasy_analyzer.players.waiver_rankings.build_free_agent_ros_projections`'s
    ``remaining_games`` is a schedule-blind constant for every player, and
    that module's docstring flags the resulting overstatement for a player
    with a bye ahead. ``schedule_adjusted_ros_points`` corrects it, and
    also applies the rest-of-season multiplier.

    Args:
        rankings: Any frame carrying a team column and a per-game
            projection -- notably
            :data:`~fantasy_analyzer.players.waiver_rankings.WAIVER_WIRE_RANKING_COLUMNS`.
        schedule: As returned by :func:`normalize_schedule`.
        defense_vs_position: As returned by
            :func:`build_defense_vs_position`. May be empty, in which case
            every multiplier is ``1.0`` and the adjusted columns equal the
            unadjusted ones.
        week: The cutoff week. Context is built for ``week + 1`` (the week
            about to be played) and for ``(week, season_end_week]``.
        season_end_week: Last regular-season week counted.
        team_column: Column in ``rankings`` holding the player's NFL team
            (Sleeper spelling; normalized via :func:`normalize_team`).
        ppg_column: Column in ``rankings`` holding the per-game projection
            to adjust.

    Returns:
        ``rankings`` with :data:`MATCHUP_CONTEXT_COLUMNS` appended. A
        player with no team (unsigned), whose team is on a bye in
        ``week + 1``, or who has no projection, gets ``NaN``/``None`` in
        the affected columns rather than a fabricated matchup.
    """
    result = rankings.copy()
    for column in MATCHUP_CONTEXT_COLUMNS:
        result[column] = None

    if result.empty:
        return result

    # Object dtype explicitly: an unsigned player's team must stay ``None``
    # rather than being coerced to ``NaN``, matching the label-column
    # convention in ``waiver_rankings.py``'s "Column dtypes" section.
    result["nfl_team"] = pd.Series(
        [normalize_team(value) for value in result[team_column]],
        index=result.index,
        dtype=object,
    )

    if schedule.empty:
        return result

    target_week = week + 1
    this_week = schedule[schedule["week"] == target_week].set_index("team")
    remaining = schedule[
        (schedule["week"] > week) & (schedule["week"] <= season_end_week)
    ]

    multiplier_lookup: dict[tuple[str, str], float] = {}
    if not defense_vs_position.empty:
        multiplier_lookup = {
            (str(row.defense), str(row.position)): float(row.dvp_multiplier)
            for row in defense_vs_position.itertuples(index=False)
        }

    byes = bye_weeks(schedule, season_end_week)
    games_left = remaining.groupby("team")["week"].size().to_dict()
    # Membership is judged against the *whole* schedule, not against the
    # target week or the remaining window: a team on a bye in week + 1
    # with nothing left to play is still a known team whose bye week we
    # can report, not an unrecognized abbreviation.
    known_teams = set(schedule["team"])

    # Per (team, position) mean multiplier over the remaining schedule --
    # computed once per team, then read per row, since a 12,000-row pool
    # would otherwise re-scan the schedule for every player.
    remaining_by_team: dict[str, list[str]] = (
        remaining.groupby("team")["opponent"].apply(list).to_dict()
    )

    week_opponent: list[Optional[str]] = []
    week_is_home: list[Optional[bool]] = []
    week_total: list[float] = []
    week_multiplier: list[float] = []
    adjusted_ppg: list[float] = []
    bye: list[Optional[int]] = []
    remaining_multiplier: list[float] = []
    remaining_count: list[float] = []
    adjusted_points: list[float] = []

    nan = float("nan")
    for team, position, ppg in zip(
        result["nfl_team"], result["position"], result[ppg_column]
    ):
        position = (
            str(position) if position is not None and pd.notna(position) else None
        )
        ppg_value = float(ppg) if ppg is not None and pd.notna(ppg) else nan

        if team is None or team not in known_teams:
            week_opponent.append(None)
            week_is_home.append(None)
            week_total.append(nan)
            week_multiplier.append(nan)
            adjusted_ppg.append(nan)
            bye.append(None)
            remaining_multiplier.append(nan)
            remaining_count.append(nan)
            adjusted_points.append(nan)
            continue

        if team in this_week.index:
            row = this_week.loc[team]
            opponent = str(row["opponent"])
            week_opponent.append(opponent)
            week_is_home.append(bool(row["is_home"]))
            week_total.append(float(row["implied_team_total"]))
            multiplier = (
                multiplier_lookup.get((opponent, position), 1.0)
                if position is not None
                else 1.0
            )
            week_multiplier.append(multiplier)
            adjusted_ppg.append(ppg_value * multiplier)
        else:
            # No game in the target week: a bye, not a missing opponent.
            week_opponent.append(None)
            week_is_home.append(None)
            week_total.append(nan)
            week_multiplier.append(nan)
            adjusted_ppg.append(nan)

        bye.append(byes.get(team))

        opponents = remaining_by_team.get(team, [])
        if opponents and position is not None:
            multipliers = [
                multiplier_lookup.get((opponent, position), 1.0)
                for opponent in opponents
            ]
            mean_multiplier = sum(multipliers) / len(multipliers)
        else:
            mean_multiplier = 1.0 if opponents else nan
        remaining_multiplier.append(mean_multiplier)

        count = float(games_left.get(team, 0))
        remaining_count.append(count)
        # An undefined multiplier (nothing left to play) is *reported* as
        # NaN but must not poison the point total: with zero games left
        # the rest-of-season points are 0.0, not unknown.
        effective = 1.0 if pd.isna(mean_multiplier) else mean_multiplier
        adjusted_points.append(ppg_value * effective * count)

    result["week_opponent"] = pd.Series(week_opponent, index=result.index, dtype=object)
    result["week_is_home"] = pd.Series(week_is_home, index=result.index, dtype=object)
    result["week_implied_team_total"] = week_total
    result["week_dvp_multiplier"] = week_multiplier
    result["matchup_adjusted_ppg"] = adjusted_ppg
    result["bye_week"] = pd.Series(bye, index=result.index, dtype=object)
    result["remaining_schedule_multiplier"] = remaining_multiplier
    result["remaining_games_scheduled"] = remaining_count
    result["schedule_adjusted_ros_points"] = adjusted_points

    for column in (
        "week_implied_team_total",
        "week_dvp_multiplier",
        "matchup_adjusted_ppg",
        "remaining_schedule_multiplier",
        "remaining_games_scheduled",
        "schedule_adjusted_ros_points",
    ):
        result[column] = pd.to_numeric(result[column], errors="coerce").astype(
            "float64"
        )

    return result

"""Aggregate nflverse's per-player defensive/ST stats to a team-defense row (FFA-074).

A Sleeper ``DEF`` roster slot represents a whole team's defense/special
teams unit, not an individual player -- Sleeper's own roster data
identifies it by team code (e.g. ``"SEA"``) rather than a per-player ID
(confirmed against this project's real league rosters: a roster's
``players`` list contains entries like ``"NE"``/``"LAR"`` alongside normal
numeric Sleeper player IDs). Neither ``nflverse_client.py``'s per-player
stats table nor ``nflverse_provider.py``'s normalization produces a row
like that -- see ``nflverse_provider.py``'s module docstring, "Additional
stat columns" section. This module builds one: it aggregates the *raw*
per-player defensive/special-teams stat columns (already present in
nflverse's current release, just not passed through by
``nflverse_provider.normalize_player_stats``, which is scoped to
individual rostered *players*) up to one row per team per week, and joins
in points allowed from ``points_allowed.py`` (FFA-073).

Scope of this ticket: raw aggregation only, not final Sleeper scoring
--------------------------------------------------------------------------

This module produces *descriptive* raw counting stats -- "how many sacks
did this team's defense record this week" -- summed from whichever
individual players recorded them. It deliberately does **not** attempt to
map these onto Sleeper's ``sack``/``int``/``fum_rec``/``ff``/``def_st_ff``/
``st_ff``/``def_st_fum_rec``/``st_fum_rec``/``def_td``/``def_st_td``/
``st_td`` scoring keys yet. Several of those keys look like near-duplicates
of each other (e.g. ``def_st_ff`` and ``st_ff`` both appear, at the same
weight, in this project's real league scoring settings), and guessing
which raw column(s) each one actually corresponds to risks silently wrong
DEF scores -- exactly what AGENTS.md's Data Scientist role requires a
written, verified definition before committing to. That mapping (plus
tiered ``pts_allow_*`` bucket support in ``scoring.py``, which needs new
rule-shape support this module does not add) is deferred to a follow-up
ticket, to be verified against Sleeper's own already-computed DEF points
(available per-roster in real matchup data) before being trusted.

Row universe: one row per team that had *any* player-week row that week
----------------------------------------------------------------------------

A team on a bye has no player rows in nflverse's data for that week at
all, so it produces no team-defense row here -- "no data yet" rather than
a zero-stat row, mirroring ``PlayerStatsProvider``'s documented convention
for a player who did not play.

Team codes: aliased to Sleeper's convention, not left as nflverse-native
------------------------------------------------------------------------------

nflverse and Sleeper mostly share team codes, but not always -- verified
against this project's real league rosters, nflverse's ``"LA"`` (Rams) is
Sleeper's ``"LAR"``. :data:`TEAM_CODE_ALIASES` documents every known
mismatch; this module's output uses Sleeper's codes (so a future join
against Sleeper roster data works directly), while the points-allowed join
happens *before* aliasing, since ``points_allowed.py`` is nflverse-native
(see that module's docstring).

Sleeper-scoreable team-week stat line (FFA-112)
--------------------------------------------------------------------------

:func:`build_team_defense_stats` above stays a descriptive per-week sum.
:func:`build_team_defense_weeks` is the scoring-grade successor: one row
per team-game for a whole season, with every quantity
:func:`fantasy_analyzer.players.scoring.calculate_team_defense_points`
needs, each derived the way Sleeper's own ``DEF`` points turned out to be
computed. Every derivation below was checked two ways: against nflverse's
play-by-play for 2025 (which classifies each play, so special-teams and
scrimmage events can be told apart), and against Sleeper's own ``DEF``
points for three real leagues. See ``docs/kicker-defense.md`` for the
evidence table.

- **Player-less rows are dropped.** Each week of nflverse's weekly table
  carries one row with no ``player_id``, holding that week's
  *unattributed* stats (penalty safeties above all) under an arbitrary
  team -- in 2025 week 3 it credited Arizona's safety to Miami. Summing
  it would hand a safety to the wrong defense.
- **Unattributed safeties are recovered from the score.** A team's final
  score is reconstructed from its players' touchdowns, kicks, two-point
  conversions and safeties. For 2015-2026 the reconstruction is exact for
  every team-game except those short by exactly 2, and in every one of
  those weeks the count of 2-short teams equals the player-less row's
  safety count. ``unattributed_safeties`` is therefore
  ``score_residual / 2`` when that residual is a positive even number.
- **Sacks** come from the *opponent's* ``sacks_suffered``, not the sum of
  ``def_sacks``: team sacks with no credited defender (9 team-games in
  2025) appear only there. It matched play-by-play in 544 of 544 2025
  team-games; ``def_sacks`` in 535.
- **Special-teams fumble recoveries** (Sleeper's ``def_st_fum_rec``,
  worth less than ``fum_rec``) are the opponent's *return* fumbles lost:
  ``fumbles_lost_total`` less the three scrimmage fumble columns, on
  rows of players who returned a punt or kickoff that week, capped at the
  team's own ``fumble_recovery_opp``. The rest of ``fumble_recovery_opp``
  is ``fumble_recoveries``.
- **Defensive touchdowns** are ``def_tds`` (interception returns) **plus**
  fumble-return touchdowns, which nflverse files under
  ``fumble_recovery_tds`` instead. Only a row whose recovery was of the
  *opponent's* fumble (``fumble_recovery_opp``) counts; an offensive
  player falling on his own fumble in the end zone scored an offensive
  touchdown.
- **``def_points_allowed``** is the opponent's score minus 6 per
  defensive touchdown and minus 2 per safety the opponent scored --
  Sleeper's definition, not the raw score (which is kept as
  ``points_allowed``). The point after a defensive touchdown, and
  special-teams return touchdowns, stay in.
- **Forced fumbles** include special-teams ones. The weekly table cannot
  separate them, and every league checked weights ``ff`` and
  ``def_st_ff`` equally, so the total is exact for them;
  ``st_forced_fumbles`` is emitted as zero so a league that weights the
  two differently gets the documented approximation rather than a crash.

Team codes: historical franchise codes in nflverse's *schedule*
(``OAK``/``SD``/``STL``) are folded into the franchise's current code
(:data:`FRANCHISE_CODE_ALIASES`) before joining, because nflverse's
*player stats* already use current codes for every season. Output codes
follow Sleeper (:data:`TEAM_CODE_ALIASES`). Regular season only. A team
on a bye, or a game without a final score, has no row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd

from fantasy_analyzer.players.nflverse_cache import (
    DEFAULT_CACHE_DIR as DEFAULT_STATS_CACHE_DIR,
)
from fantasy_analyzer.players.nflverse_cache import get_player_stats_cached
from fantasy_analyzer.players.nflverse_client import NflverseClient
from fantasy_analyzer.players.points_allowed import NflverseScheduleProvider
from fantasy_analyzer.players.provider import PLAYER_WEEK_IDENTITY_COLUMNS

#: nflverse team code -> Sleeper team code, for every known mismatch between
#: the two. Verified against this project's real 2025 league rosters (see
#: the module docstring); not necessarily exhaustive for every historical
#: franchise relocation/renaming nflverse's data spans (e.g. ``"OAK"``/
#: ``"SD"``/``"STL"``), since only currently-active teams have been checked.
TEAM_CODE_ALIASES: dict[str, str] = {
    "LA": "LAR",
}

#: Historical nflverse franchise code -> that franchise's current nflverse
#: code. nflverse's *schedule* keeps the code a team used that season
#: (``OAK`` through 2019, ``SD`` in 2016, ``STL`` through 2015), while its
#: *player stats* use the current code for every season -- measured on the
#: cached 2016-2019 files, where every mismatch between the two
#: vocabularies was one of these three.
FRANCHISE_CODE_ALIASES: dict[str, str] = {
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LA",
}

#: Column order of :func:`build_team_defense_weeks`'s output.
TEAM_DEFENSE_WEEK_COLUMNS = [
    "season",
    "week",
    "team",
    "opponent",
    "is_home",
    "points_scored",
    "points_allowed",
    "def_points_allowed",
    "sacks",
    "interceptions",
    "fumble_recoveries",
    "st_fumble_recoveries",
    "forced_fumbles",
    "st_forced_fumbles",
    "def_tds",
    "st_tds",
    "safeties",
    "blocked_kicks",
    "unattributed_safeties",
    "score_residual",
]

_TEAM_WEEK_SOURCE_COLUMNS = [
    "def_interceptions",
    "fumble_recovery_opp",
    "def_fumbles_forced",
    "def_tds",
    "special_teams_tds",
    "def_safeties",
    "sacks_suffered",
    "_def_fumble_return_tds",
    "_return_fumbles_lost",
    "_blocked_kicks",
    "_reconstructed_points",
]

#: Raw nflverse per-player defensive/special-teams columns summed by
#: ``(season, week, team)`` to build one team-defense row. See the module
#: docstring for why these are not yet mapped onto specific Sleeper scoring
#: keys. Each is attributed to whichever player's ``team`` column recorded
#: it that week -- e.g. ``special_teams_tds``/``fumble_recovery_tds`` may be
#: recorded on an offensive player (a WR who returned a kick), and summing
#: by team (not by position) attributes it to that player's team correctly
#: either way.
TEAM_DEFENSE_RAW_STAT_COLUMNS = [
    "def_sacks",
    "def_interceptions",
    "def_fumbles_forced",
    "def_tds",
    "def_safeties",
    "def_punt_blocks",
    "def_pat_blocks",
    "def_fg_blocks",
    "fumble_recovery_opp",
    "fumble_recovery_tds",
    "special_teams_tds",
]


def build_team_defense_stats(
    raw_stats: pd.DataFrame,
    points_allowed: pd.DataFrame,
    season: int,
    week: int,
) -> pd.DataFrame:
    """Aggregate one team-defense row per team from raw per-player nflverse stats.

    Args:
        raw_stats: nflverse's raw, unfiltered per-season player-stats table,
            as returned by ``NflverseClient.download_player_stats(season)``
            (or a cached copy) -- the *raw* table, not
            ``nflverse_provider.normalize_player_stats``'s output, since
            the latter drops the defensive columns this function needs.
        points_allowed: A DataFrame shaped like
            :func:`fantasy_analyzer.players.points_allowed.normalize_points_allowed`'s
            output (``season``/``week``/``team``/``points_allowed``,
            nflverse-native team codes).
        season: The NFL season to filter to.
        week: The NFL week number to filter to.

    Returns:
        A DataFrame whose columns begin with
        :data:`~fantasy_analyzer.players.provider.PLAYER_WEEK_IDENTITY_COLUMNS`
        (``sleeper_player_id``/``nfl_team`` hold the team code, aliased to
        Sleeper's convention per :data:`TEAM_CODE_ALIASES`; ``gsis_id`` and
        ``player_name`` are always ``None`` -- a team has neither),
        followed by :data:`TEAM_DEFENSE_RAW_STAT_COLUMNS` and
        ``points_allowed``. One row per team with at least one player-week
        row in ``raw_stats`` for ``season``/``week``; ``points_allowed`` is
        ``NaN`` for a team with no matching row in ``points_allowed`` (e.g.
        the game hasn't been played/published yet). Empty (same columns,
        zero rows) if no row in ``raw_stats`` matches ``season``/``week``.
    """
    if "season" in raw_stats.columns and "week" in raw_stats.columns:
        matched = raw_stats[
            (raw_stats["season"] == season) & (raw_stats["week"] == week)
        ]
    else:
        matched = raw_stats.iloc[0:0]

    if "team" in matched.columns:
        matched = matched[matched["team"].notna()]
    else:
        matched = matched.iloc[0:0]

    present_stat_columns = [
        column for column in TEAM_DEFENSE_RAW_STAT_COLUMNS if column in matched.columns
    ]

    if matched.empty:
        aggregated = pd.DataFrame(
            {column: [] for column in present_stat_columns},
            index=pd.Index([], name="team"),
        )
    else:
        aggregated = matched.groupby("team")[present_stat_columns].sum()

    result = aggregated.reset_index().rename(columns={"team": "raw_team"})
    result["season"] = season
    result["week"] = week

    if points_allowed.empty:
        points_allowed_this_week = pd.DataFrame(columns=["team", "points_allowed"])
    else:
        points_allowed_this_week = points_allowed[
            (points_allowed["season"] == season) & (points_allowed["week"] == week)
        ][["team", "points_allowed"]]

    result = result.merge(
        points_allowed_this_week, left_on="raw_team", right_on="team", how="left"
    )

    result["sleeper_player_id"] = result["raw_team"].map(
        lambda team: TEAM_CODE_ALIASES.get(team, team)
    )
    result["nfl_team"] = result["sleeper_player_id"]
    result["gsis_id"] = None
    result["player_name"] = None
    result["position"] = "DEF"

    ordered_columns = (
        PLAYER_WEEK_IDENTITY_COLUMNS + present_stat_columns + ["points_allowed"]
    )
    return result[ordered_columns].reset_index(drop=True)


class NflverseTeamDefenseProvider:
    """A :class:`PlayerStatsProvider` for team ``DEF`` rows, backed by nflverse.

    Satisfies ``PlayerStatsProvider`` structurally -- no inheritance -- by
    implementing ``weekly_stats(season, week) -> pd.DataFrame``, exactly
    like
    :class:`~fantasy_analyzer.players.nflverse_provider.NflverseWeeklyStatsProvider`,
    but returns one row per *team* rather than one row per rostered player.
    See :func:`build_team_defense_stats` for the aggregation this wraps
    with disk/in-memory caching, mirroring
    ``NflverseWeeklyStatsProvider``'s per-season caching pattern.
    """

    def __init__(
        self,
        stats_client: Optional[NflverseClient] = None,
        schedule_provider: Optional[NflverseScheduleProvider] = None,
        cache_dir: Union[str, Path] = DEFAULT_STATS_CACHE_DIR,
        force_refresh: bool = False,
    ) -> None:
        self._stats_client = stats_client or NflverseClient()
        self._schedule_provider = schedule_provider or NflverseScheduleProvider(
            cache_dir=cache_dir, force_refresh=force_refresh
        )
        self._cache_dir = cache_dir
        self._force_refresh = force_refresh
        self._raw_stats_by_season: dict[int, pd.DataFrame] = {}

    def weekly_stats(self, season: int, week: int) -> pd.DataFrame:
        """Return one team-defense row per team for ``season``/``week``.

        See :func:`build_team_defense_stats` for the full return-shape
        contract.
        """
        if season not in self._raw_stats_by_season:
            self._raw_stats_by_season[season] = get_player_stats_cached(
                self._stats_client,
                season,
                self._cache_dir,
                force_refresh=self._force_refresh,
            )

        points_allowed = self._schedule_provider.points_allowed(season, week)
        # NflverseScheduleProvider.points_allowed already filters to
        # season/week and drops those columns -- add season/week back so
        # build_team_defense_stats's own (season, week) filter still works
        # regardless of caller.
        points_allowed = points_allowed.assign(season=season, week=week)

        return build_team_defense_stats(
            self._raw_stats_by_season[season], points_allowed, season, week
        )


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    """``frame[column]`` as floats with ``NaN`` -> 0; zeros if absent."""
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0).astype(float)


def _team_game_schedule(games: pd.DataFrame, season: int) -> pd.DataFrame:
    """Two rows per scored regular-season game: team, opponent, both scores."""
    required = {"season", "week", "home_team", "away_team", "home_score", "away_score"}
    if games.empty or not required.issubset(games.columns):
        return pd.DataFrame(
            columns=["week", "team", "opponent", "is_home", "score", "opp_score"]
        )
    played = games[
        (games["season"] == season)
        & games["home_score"].notna()
        & games["away_score"].notna()
    ]
    if "game_type" in played.columns:
        played = played[played["game_type"] == "REG"]
    home = pd.DataFrame(
        {
            "week": played["week"],
            "team": played["home_team"],
            "opponent": played["away_team"],
            "is_home": True,
            "score": played["home_score"],
            "opp_score": played["away_score"],
        }
    )
    away = pd.DataFrame(
        {
            "week": played["week"],
            "team": played["away_team"],
            "opponent": played["home_team"],
            "is_home": False,
            "score": played["away_score"],
            "opp_score": played["home_score"],
        }
    )
    schedule = pd.concat([home, away], ignore_index=True)
    for column in ("team", "opponent"):
        schedule[column] = schedule[column].replace(FRANCHISE_CODE_ALIASES)
    schedule["week"] = schedule["week"].astype(int)
    return schedule


#: nflverse ``position_group`` values of defensive players. A fumble-return
#: touchdown counts as a *defensive* touchdown only when one of these
#: scored it: measured on 2025 play-by-play, that rule agrees on every
#: team-game (544/544), while counting any player's opponent-fumble
#: touchdown misfiles an offensive player who recovers his own team's
#: turnover-return fumble in the end zone.
DEFENSIVE_POSITION_GROUPS = frozenset({"DL", "LB", "DB"})


def _per_team_sources(stats: pd.DataFrame) -> pd.DataFrame:
    """Sum the per-player inputs of :func:`build_team_defense_weeks` by team-week.

    Args:
        stats: Regular-season, player-identified raw nflverse rows.

    Returns:
        A frame indexed by ``(week, team)`` (franchise-aliased nflverse
        codes) with :data:`_TEAM_WEEK_SOURCE_COLUMNS`.
    """
    if stats.empty:
        return pd.DataFrame(
            columns=_TEAM_WEEK_SOURCE_COLUMNS,
            index=pd.MultiIndex.from_arrays([[], []], names=["week", "team"]),
        )
    fumble_recovery_tds = _numeric(stats, "fumble_recovery_tds")
    if "position_group" in stats.columns:
        is_defender = stats["position_group"].isin(DEFENSIVE_POSITION_GROUPS)
    else:
        is_defender = pd.Series(True, index=stats.index)
    returned = (
        _numeric(stats, "punt_returns") + _numeric(stats, "kickoff_returns")
    ) > 0
    non_scrimmage_lost = (
        _numeric(stats, "fumbles_lost_total")
        - _numeric(stats, "sack_fumbles_lost")
        - _numeric(stats, "rushing_fumbles_lost")
        - _numeric(stats, "receiving_fumbles_lost")
    ).clip(lower=0.0)
    derived = pd.DataFrame(
        {
            "week": pd.to_numeric(stats["week"]).astype(int),
            "team": stats["team"].replace(FRANCHISE_CODE_ALIASES),
            "def_interceptions": _numeric(stats, "def_interceptions"),
            "fumble_recovery_opp": _numeric(stats, "fumble_recovery_opp"),
            "def_fumbles_forced": _numeric(stats, "def_fumbles_forced"),
            "def_tds": _numeric(stats, "def_tds"),
            "special_teams_tds": _numeric(stats, "special_teams_tds"),
            "def_safeties": _numeric(stats, "def_safeties"),
            "sacks_suffered": _numeric(stats, "sacks_suffered"),
            "_def_fumble_return_tds": np.minimum(
                fumble_recovery_tds, _numeric(stats, "fumble_recovery_opp")
            ).where(is_defender, 0.0),
            "_return_fumbles_lost": non_scrimmage_lost.where(returned, 0.0),
            "_blocked_kicks": _numeric(stats, "def_punt_blocks")
            + _numeric(stats, "def_fg_blocks")
            + _numeric(stats, "def_pat_blocks"),
            "_reconstructed_points": 6.0
            * (
                _numeric(stats, "rushing_tds")
                + _numeric(stats, "receiving_tds")
                + _numeric(stats, "def_tds")
                + fumble_recovery_tds
                + _numeric(stats, "special_teams_tds")
            )
            + 3.0 * _numeric(stats, "fg_made")
            + _numeric(stats, "pat_made")
            + 2.0
            * (
                _numeric(stats, "rushing_2pt_conversions")
                + _numeric(stats, "receiving_2pt_conversions")
                + _numeric(stats, "def_safeties")
                + _numeric(stats, "def_2pt_made")
            ),
        }
    )
    return derived.groupby(["week", "team"])[_TEAM_WEEK_SOURCE_COLUMNS].sum()


def build_team_defense_weeks(
    raw_stats: pd.DataFrame, games: pd.DataFrame, season: int
) -> pd.DataFrame:
    """One Sleeper-scoreable team-defense stat line per team-game of a season.

    See the module docstring's "Sleeper-scoreable team-week stat line"
    section for how each column is derived and the evidence behind it.
    Score it with
    :func:`fantasy_analyzer.players.scoring.calculate_team_defense_points`.

    Args:
        raw_stats: nflverse's raw per-player weekly table covering
            ``season`` (other seasons are ignored), e.g. the cached
            ``player_stats_<season>.csv``. Rows whose ``season_type`` is
            not ``"REG"`` and rows with no ``player_id`` are dropped.
        games: nflverse's cumulative games table (``games.csv``).
        season: The season to build.

    Returns:
        A DataFrame with :data:`TEAM_DEFENSE_WEEK_COLUMNS`, one row per team
        per regular-season game with a final score, team codes in Sleeper's
        convention. Stat columns are floats; a team with no player rows
        for a played game gets zeros. Empty (same columns) when nothing
        matches.
    """
    schedule = _team_game_schedule(games, season)
    if schedule.empty:
        return pd.DataFrame(columns=TEAM_DEFENSE_WEEK_COLUMNS)

    stats = raw_stats
    if "season" in stats.columns:
        stats = stats[stats["season"] == season]
    if "season_type" in stats.columns:
        stats = stats[stats["season_type"] == "REG"]
    if "player_id" in stats.columns:
        stats = stats[stats["player_id"].notna()]
    if not {"team", "week"}.issubset(stats.columns):
        stats = pd.DataFrame(columns=["team", "week"])
    stats = stats[stats["team"].notna()]
    per_team = _per_team_sources(stats)

    own = schedule.merge(
        per_team, left_on=["week", "team"], right_index=True, how="left"
    )
    own[_TEAM_WEEK_SOURCE_COLUMNS] = own[_TEAM_WEEK_SOURCE_COLUMNS].fillna(0.0)
    own["score_residual"] = own["score"].astype(float) - own["_reconstructed_points"]
    residual = own["score_residual"]
    own["unattributed_safeties"] = np.where(
        (residual > 0) & (residual % 2 == 0), residual / 2.0, 0.0
    )

    # The same team-game seen from the other sideline: what the *opponent*
    # did determines this defense's sacks, return-fumble recoveries and
    # Sleeper points allowed.
    opponent_view = pd.DataFrame(
        {
            "week": own["week"],
            "opponent": own["team"],
            "opp_sacks_suffered": own["sacks_suffered"],
            "opp_def_tds": own["def_tds"] + own["_def_fumble_return_tds"],
            "opp_safeties": own["def_safeties"] + own["unattributed_safeties"],
            "opp_return_fumbles_lost": own["_return_fumbles_lost"],
        }
    )
    merged = own.merge(opponent_view, on=["week", "opponent"], how="left")
    opp_columns = list(opponent_view.columns[2:])
    merged[opp_columns] = merged[opp_columns].fillna(0.0)

    st_recoveries = np.minimum(
        merged["opp_return_fumbles_lost"], merged["fumble_recovery_opp"]
    )
    result = pd.DataFrame(
        {
            "season": season,
            "week": merged["week"].astype(int),
            "team": merged["team"].map(lambda team: TEAM_CODE_ALIASES.get(team, team)),
            "opponent": merged["opponent"].map(
                lambda team: TEAM_CODE_ALIASES.get(team, team)
            ),
            "is_home": merged["is_home"].astype(bool),
            "points_scored": merged["score"].astype(float),
            "points_allowed": merged["opp_score"].astype(float),
            "def_points_allowed": merged["opp_score"].astype(float)
            - 6.0 * merged["opp_def_tds"]
            - 2.0 * merged["opp_safeties"],
            "sacks": merged["opp_sacks_suffered"],
            "interceptions": merged["def_interceptions"],
            "fumble_recoveries": merged["fumble_recovery_opp"] - st_recoveries,
            "st_fumble_recoveries": st_recoveries,
            "forced_fumbles": merged["def_fumbles_forced"],
            "st_forced_fumbles": 0.0,
            "def_tds": merged["def_tds"] + merged["_def_fumble_return_tds"],
            "st_tds": merged["special_teams_tds"],
            "safeties": merged["def_safeties"] + merged["unattributed_safeties"],
            "blocked_kicks": merged["_blocked_kicks"],
            "unattributed_safeties": merged["unattributed_safeties"],
            "score_residual": merged["score_residual"],
        }
    )
    return (
        result[TEAM_DEFENSE_WEEK_COLUMNS]
        .sort_values(["week", "team"], kind="stable")
        .reset_index(drop=True)
    )

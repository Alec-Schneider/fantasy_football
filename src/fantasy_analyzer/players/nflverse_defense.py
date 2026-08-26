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
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

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

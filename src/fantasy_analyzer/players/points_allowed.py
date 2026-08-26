"""Derive per-team points allowed from nflverse's game-schedule/score data.

Points allowed is the one input a Sleeper league's ``pts_allow_*`` team-
defense scoring categories need that neither the player-week stats provider
nor the Sleeper API itself supplies (see ``nflverse_provider.py``'s module
docstring, "Additional stat columns" section). It is fundamentally a
per-*game* fact -- "how many points did this team's opponent score" -- not
a per-player one, so it cannot be derived from
``nflverse_client.download_player_stats``'s per-player table no matter how
it's aggregated. This module derives it instead from
``nflverse_schedule_client.py``'s per-game score data.

Regular season only
--------------------

nflverse's ``games`` table's ``game_type`` column distinguishes regular-
season games (``"REG"``) from the NFL's own postseason (``"WC"``, ``"DIV"``,
``"CON"``, ``"SB"``). A fantasy league's season -- regular season *and*
fantasy playoffs alike -- is played entirely within NFL weeks 1-18, i.e.
entirely within ``"REG"`` games; the NFL's actual postseason games are
future/irrelevant weeks from a fantasy scoring perspective and are always
excluded here, not just for playoff-boundary reasons but because they
would otherwise collide on the same ``(season, week)`` key as fantasy's own
late-season weeks (NFL postseason "week" numbers restart from 1 within
each round). See ``nflverse_provider.py``'s module docstring and
``league/season.py`` for the analogous regular-season framing used
elsewhere in this codebase.

One row per team per game
---------------------------

Each game involves two teams, each with its own points-allowed value (the
*other* team's score), so :func:`normalize_points_allowed` turns each game
row into two output rows: the home team's points allowed is the away
team's score, and vice versa.

Team codes are nflverse-native, not yet Sleeper-aligned
----------------------------------------------------------

Like ``nflverse_provider.py``'s ``nfl_team`` column, the ``team`` column
this module produces uses nflverse's own team codes (e.g. ``"LA"`` for the
Rams) verbatim -- no crosswalk to Sleeper's codes (e.g. ``"LAR"``) is
applied here. That alignment is a concern for whichever module joins this
output against Sleeper roster data (team-defense aggregation), not this
one, mirroring how ``nflverse_provider.py`` leaves ``sleeper_player_id``
unpopulated by default rather than baking a crosswalk into the raw
normalization step.

Missing/incomplete data
-------------------------

A game with no final score yet (in progress, or not yet played) is
excluded entirely -- "no data yet" for that team/week, not a ``NaN``
points-allowed row -- the same convention
``NflverseClient.download_player_stats`` uses for an unpublished season.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import pandas as pd

from fantasy_analyzer.players.nflverse_schedule_cache import (
    DEFAULT_CACHE_DIR,
    get_games_cached,
)
from fantasy_analyzer.players.nflverse_schedule_client import NflverseScheduleClient

#: Columns of the DataFrame :func:`normalize_points_allowed` (and
#: :class:`NflverseScheduleProvider`) return, in this order.
POINTS_ALLOWED_COLUMNS = ["season", "week", "team", "points_allowed"]


def normalize_points_allowed(games: pd.DataFrame) -> pd.DataFrame:
    """Derive one row per team per regular-season game from nflverse's raw games table.

    Args:
        games: nflverse's raw, unfiltered games table, as returned by
            ``NflverseScheduleClient.download_games()`` (or a cached copy).
            Expected to carry (at least) ``season``, ``week``, ``game_type``,
            ``home_team``, ``home_score``, ``away_team``, ``away_score``.

    Returns:
        A DataFrame with :data:`POINTS_ALLOWED_COLUMNS`
        (``season``/``week``/``team``/``points_allowed``), two rows per
        regular-season game with a final score (see the module docstring
        for why non-``"REG"`` games and games with no final score yet are
        excluded). Empty (same columns, zero rows) if ``games`` is empty or
        carries none of the expected columns.
    """
    required_columns = {
        "season",
        "week",
        "game_type",
        "home_team",
        "home_score",
        "away_team",
        "away_score",
    }
    if not required_columns.issubset(games.columns):
        return pd.DataFrame(columns=POINTS_ALLOWED_COLUMNS)

    regular_season = games[
        (games["game_type"] == "REG")
        & games["home_score"].notna()
        & games["away_score"].notna()
    ]

    home_allowed = pd.DataFrame(
        {
            "season": regular_season["season"],
            "week": regular_season["week"],
            "team": regular_season["home_team"],
            "points_allowed": regular_season["away_score"],
        }
    )
    away_allowed = pd.DataFrame(
        {
            "season": regular_season["season"],
            "week": regular_season["week"],
            "team": regular_season["away_team"],
            "points_allowed": regular_season["home_score"],
        }
    )

    result = pd.concat([home_allowed, away_allowed], ignore_index=True)
    return result[POINTS_ALLOWED_COLUMNS]


class NflverseScheduleProvider:
    """Looks up per-team points allowed for a season/week, backed by nflverse.

    The full cumulative games table (see ``nflverse_schedule_client.py``'s
    docstring for why it's one download covering every season) is
    downloaded/loaded from cache at most once per provider instance, on the
    first :meth:`points_allowed` call, and reused in memory for every
    subsequent call regardless of which season/week is requested.
    """

    def __init__(
        self,
        client: NflverseScheduleClient | None = None,
        cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
        force_refresh: bool = False,
    ) -> None:
        self._client = client or NflverseScheduleClient()
        self._cache_dir = cache_dir
        self._force_refresh = force_refresh
        self._points_allowed: pd.DataFrame | None = None

    def points_allowed(self, season: int, week: int) -> pd.DataFrame:
        """Return points-allowed rows for every team that played in ``season``/``week``.

        Returns:
            A DataFrame with columns ``team``/``points_allowed`` (the
            ``season``/``week`` columns from :data:`POINTS_ALLOWED_COLUMNS`
            are dropped since every row already matches the requested
            values). Empty if no regular-season game with a final score
            matches ``season``/``week``.
        """
        if self._points_allowed is None:
            games = get_games_cached(
                self._client, self._cache_dir, force_refresh=self._force_refresh
            )
            self._points_allowed = normalize_points_allowed(games)

        matched = self._points_allowed[
            (self._points_allowed["season"] == season)
            & (self._points_allowed["week"] == week)
        ]
        return matched[["team", "points_allowed"]].reset_index(drop=True)

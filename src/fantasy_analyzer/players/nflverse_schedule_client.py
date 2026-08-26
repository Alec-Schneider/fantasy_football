"""Thin HTTP client for downloading nflverse's published game-schedule/score data.

This module exists for one reason: team defense fantasy scoring (a Sleeper
``DEF`` roster slot) depends on *points allowed*, and nflverse's per-player
weekly stats table (``nflverse_client.py``) has no such column -- it is a
per-*player* fact table, and points allowed is a per-*game* fact. This
client downloads nflverse's ``schedules`` release, which does carry final
game scores, so a caller can derive points allowed by joining a team to its
opponent's score for that week (see ``points_allowed.py``, not implemented
in this module).

Unlike ``NflverseClient.download_player_stats`` (one release asset per
season, see that module's docstring for why), nflverse's ``schedules``
release publishes a single **cumulative** ``games.csv`` asset covering
every season nflverse has schedule data for (1999-present as of this
module's writing), plain CSV (not gzip-compressed, unlike
``stats_player_week_<season>.csv.gz``). This mirrors the *original*,
pre-migration shape ``nflverse_client.py``'s docstring describes for the
old retired ``player_stats.csv.gz`` asset -- one download covers every
season, so this client takes no ``season`` argument.
"""

from __future__ import annotations

import io

import pandas as pd
import requests


class NflverseScheduleClient:
    """A thin, reusable client around nflverse-data's public schedules asset."""

    #: The single cumulative game-schedule/score CSV, covering every season
    #: nflverse publishes schedule data for. See the module docstring for
    #: why this is one file rather than one per season.
    GAMES_URL = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        "schedules/games.csv"
    )

    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self.session = requests.Session()

    def download_games(self) -> pd.DataFrame:
        """Download nflverse's full game-schedule/score table.

        Returns every season/week/game nflverse has published as of the
        request, with nflverse's own raw column names (``season``, ``week``,
        ``game_type``, ``home_team``, ``home_score``, ``away_team``,
        ``away_score``, plus a large number of other game-metadata columns
        this client does not filter or rename) -- see ``points_allowed.py``
        for the normalization step that derives points allowed from this
        raw shape. This is a multi-megabyte download covering every
        historical season; callers should prefer a disk-caching layer
        (mirroring ``nflverse_cache.py``'s pattern) rather than calling this
        repeatedly.

        Returns:
            An empty ``DataFrame`` (no columns) if nflverse's release asset
            is unreachable via a 404 -- treated as "no data available", not
            an error, matching ``NflverseClient.download_player_stats``'s
            convention. Any other non-2xx response still raises.

        Raises:
            requests.exceptions.RequestException: On any connection,
                timeout, or non-2xx/non-404 HTTP response, exactly as
                raised by ``requests`` -- mirrors
                ``NflverseClient.download_player_stats``'s error handling.
        """
        response = self.session.get(self.GAMES_URL, timeout=self.timeout)
        if response.status_code == 404:
            return pd.DataFrame()
        response.raise_for_status()
        return pd.read_csv(io.BytesIO(response.content))

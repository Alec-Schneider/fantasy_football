"""Thin HTTP client for downloading nflverse's published snap-count data (FFA-110).

nflverse's weekly player-stats table (``nflverse_client.py``) records what a
player *did* with the ball -- targets, carries, yards -- but not how often
he was on the field. A receiver who ran forty routes and drew no targets
has no row there at all. Snap counts are the missing denominator: they are
the one published, per-player-week signal of *role* rather than
*production*.

nflverse republishes Pro Football Reference's snap counts as release assets
on the ``nflverse-data`` repository, under the ``snap_counts`` release tag
(https://github.com/nflverse/nflverse-data/releases/tag/snap_counts), one
plain (uncompressed) CSV per season named ``snap_counts_<season>.csv`` --
including the current in-progress season, updated on nflverse's own
schedule.

Verified against the live release on 2026-09-29:

- Seasons 2013 onward carry data. ``snap_counts_2012.csv`` exists but is a
  header-only file (zero rows); 2011 and earlier return HTTP 404.
- The table covers **every** position that took a snap, offense, defense and
  special teams, and both regular season (``game_type`` ``REG``) and
  postseason (``WC``/``DIV``/``CON``/``SB``) games.
- The player key is ``pfr_player_id`` (Pro Football Reference, e.g.
  ``"AltxJo01"``), **not** a GSIS id. Mapping it onto the rest of this
  codebase's GSIS-keyed tables is ``usage.normalize_snap_counts``'s job,
  not this client's.

Mirrors ``nflverse_client.py``'s shape: one release asset per season, raw
columns returned unfiltered and unrenamed.
"""

from __future__ import annotations

import io

import pandas as pd
import requests


class SnapCountsClient:
    """A thin, reusable client around nflverse-data's public snap-count assets."""

    #: Template for one season's snap-count CSV under the ``snap_counts``
    #: release tag. Plain CSV, unlike ``stats_player_week_<season>.csv.gz``.
    SNAP_COUNTS_URL_TEMPLATE = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        "snap_counts/snap_counts_{season}.csv"
    )

    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self.session = requests.Session()

    def download_snap_counts(self, season: int) -> pd.DataFrame:
        """Download nflverse's per-player-game snap counts for one season.

        Returns every game nflverse has published for ``season`` as of the
        request, with nflverse's own raw column names (``game_id``,
        ``season``, ``game_type``, ``week``, ``player``, ``pfr_player_id``,
        ``position``, ``team``, ``opponent``, ``offense_snaps``,
        ``offense_pct``, ``defense_snaps``, ``defense_pct``, ``st_snaps``,
        ``st_pct``, ...) -- no filtering or renaming is applied here. Callers
        should prefer the disk-caching layer in ``snap_counts_cache``.

        Args:
            season: The NFL season to download, e.g. ``2026``.

        Returns:
            An empty ``DataFrame`` (no columns) if nflverse has not published
            a release asset for ``season`` (an HTTP 404) -- treated as "no
            data for this season", not an error, matching
            ``NflverseClient.download_player_stats``. A published but
            header-only asset (2012) returns an empty frame *with* columns.

        Raises:
            requests.exceptions.RequestException: On any connection,
                timeout, or non-2xx/non-404 HTTP response, exactly as raised
                by ``requests`` -- mirrors
                ``NflverseClient.download_player_stats``'s error handling.
        """
        url = self.SNAP_COUNTS_URL_TEMPLATE.format(season=season)
        response = self.session.get(url, timeout=self.timeout)
        if response.status_code == 404:
            return pd.DataFrame()
        response.raise_for_status()
        return pd.read_csv(io.BytesIO(response.content), low_memory=False)

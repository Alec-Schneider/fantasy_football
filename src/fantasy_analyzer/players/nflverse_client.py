"""Thin HTTP client for downloading nflverse's published player-stats data.

This module is responsible for raw nflverse asset download only; it does not
filter by week or rename columns -- see ``nflverse_provider`` for that. This
mirrors ``sleeper/client.py``'s split between raw HTTP communication and
normalization.

nflverse publishes weekly player statistics as release assets on the
``nflverse-data`` GitHub repository. **As of this ticket**, that is the
``stats_player`` release tag
(https://github.com/nflverse/nflverse-data/releases/tag/stats_player), one
gzip-compressed CSV per season named ``stats_player_week_<season>.csv.gz``
-- including the current in-progress season, updated on nflverse's own
schedule.

This is a migration from this module's original design, which downloaded a
single cumulative ``player_stats.csv.gz`` asset (all seasons in one file)
from the older ``player_stats`` release tag. nflverse retired that tag
without further updates after the 2024 season -- its assets are frozen and
will never carry a 2025-or-later season -- and replaced it with the
per-season ``stats_player`` scheme this module now uses. Consequently
``download_player_stats`` takes an explicit ``season`` (one release asset
per call) rather than returning every season at once; see
``nflverse_cache``/``nflverse_provider`` for how callers now cache and
request one season at a time. This keeps the dependency footprint to
``requests`` + ``pandas`` (no ``pyarrow``), matching the rest of this
project's stack.
"""

from __future__ import annotations

import io

import pandas as pd
import requests


class NflverseClient:
    """A thin, reusable client around nflverse-data's public player-stats asset."""

    #: Template for one season's weekly player-stats CSV under the
    #: ``stats_player`` release tag. See the module docstring for why this
    #: replaced the old cumulative ``player_stats`` release.
    STATS_PLAYER_WEEK_URL_TEMPLATE = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        "stats_player/stats_player_week_{season}.csv.gz"
    )

    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self.session = requests.Session()

    def download_player_stats(self, season: int) -> pd.DataFrame:
        """Download nflverse's weekly player-stats table for one season.

        Returns every week nflverse has published for ``season`` as of the
        request, with nflverse's own raw column names (e.g. ``player_id``,
        ``recent_team``) -- no filtering or renaming is applied here. This
        is a moderately large (multi-megabyte) per-season download; callers
        should prefer the disk-caching layer in ``nflverse_cache`` rather
        than calling this repeatedly for the same season.

        Args:
            season: The NFL season to download, e.g. ``2025``.

        Returns:
            An empty ``DataFrame`` (no columns) if nflverse has not
            published a release asset for ``season`` yet (an HTTP 404) --
            treated as "no data for this season", not an error, matching
            ``PlayerStatsProvider``'s documented discretion to leave
            unpublished season/week combinations as empty rather than
            raising. Any other non-2xx response still raises.

        Raises:
            requests.exceptions.RequestException: On any connection,
                timeout, or non-2xx/non-404 HTTP response, exactly as
                raised by ``requests`` -- this client does not wrap
                nflverse errors in custom exception types the way
                ``SleeperClient`` does for Sleeper, since nflverse is
                accessed as a plain static file download rather than a
                JSON API with its own error shape.
        """
        url = self.STATS_PLAYER_WEEK_URL_TEMPLATE.format(season=season)
        response = self.session.get(url, timeout=self.timeout)
        if response.status_code == 404:
            return pd.DataFrame()
        response.raise_for_status()
        return pd.read_csv(io.BytesIO(response.content), compression="gzip")

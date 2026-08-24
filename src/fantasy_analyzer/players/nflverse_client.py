"""Thin HTTP client for downloading nflverse's published player-stats data.

This module is responsible for raw nflverse asset download only; it does not
filter by season/week or rename columns -- see ``nflverse_provider`` for
that. This mirrors ``sleeper/client.py``'s split between raw HTTP
communication and normalization.

nflverse publishes weekly player statistics as release assets on the
``nflverse-data`` GitHub repository, under the ``player_stats`` release tag
(https://github.com/nflverse/nflverse-data/releases/tag/player_stats). Two
asset shapes exist there:

- ``player_stats_<season>.csv`` -- one file per *completed* season.
- ``player_stats.csv`` / ``player_stats.csv.gz`` -- a single cumulative file
  covering every season nflverse has published, including the current
  in-progress season.

As of this ticket, the per-season assets stop at the most recently completed
season; the current/most-recent season's data is only available in the
cumulative file. Since ``weekly_stats`` must be able to serve *any*
requested season, this client always downloads the cumulative
``player_stats.csv.gz`` asset (gzip-compressed CSV, ~7MB vs. ~33MB
uncompressed) rather than trying to pick a per-season asset -- see
``nflverse_provider`` for how that single download is filtered down to one
season/week per call. This keeps the dependency footprint to ``requests`` +
``pandas`` (no ``pyarrow``), matching the rest of this project's stack.
"""

from __future__ import annotations

import io

import pandas as pd
import requests


class NflverseClient:
    """A thin, reusable client around nflverse-data's public player-stats asset."""

    #: The cumulative, all-seasons weekly player-stats CSV. See the module
    #: docstring for why this asset is used instead of a per-season file.
    PLAYER_STATS_URL = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        "player_stats/player_stats.csv.gz"
    )

    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self.session = requests.Session()

    def download_player_stats(self) -> pd.DataFrame:
        """Download nflverse's full cumulative weekly player-stats table.

        Returns every season/week nflverse has published as of the request,
        with nflverse's own raw column names (e.g. ``player_id``,
        ``recent_team``) -- no filtering or renaming is applied here. This
        is a single, moderately large (multi-megabyte) download; callers
        should prefer the disk-caching layer in ``nflverse_cache`` rather
        than calling this repeatedly.

        Raises:
            requests.exceptions.RequestException: On any connection,
                timeout, or non-2xx HTTP response, exactly as raised by
                ``requests`` -- this client does not wrap nflverse errors in
                custom exception types the way ``SleeperClient`` does for
                Sleeper, since nflverse is accessed as a plain static file
                download rather than a JSON API with its own error shape.
        """
        response = self.session.get(self.PLAYER_STATS_URL, timeout=self.timeout)
        response.raise_for_status()
        return pd.read_csv(io.BytesIO(response.content), compression="gzip")

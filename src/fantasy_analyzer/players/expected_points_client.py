"""Thin HTTP client for ffopportunity's weekly expected-points data (FFA-110).

nflverse's weekly player stats (``nflverse_client.py``) measure *volume*
-- targets, carries -- but say nothing about the *quality* of each
opportunity. A target at the one-yard line and a target on third-and-long
from the own twenty are both "1 target". Expected fantasy points (xFP)
price each opportunity by its situation (field position, down, distance,
air yards, ...), so a player's xFP is the fantasy output an average player
would have produced from exactly his opportunities.

`ffopportunity <https://github.com/ffverse/ffopportunity>`_ is ffverse's
(the nflverse family's fantasy-football arm) published expected-points
model, fit on nflverse play-by-play. It publishes one plain CSV per season
under the ``latest-data`` release tag, named ``ep_weekly_<season>.csv``, for
every season from 2006 onward, including the current in-progress season.

Verified against the live release on 2026-09-29 (see ``usage.py``'s module
docstring for the full write-up):

- ``player_id`` **is a GSIS id** (e.g. ``"00-0037744"``): every non-null
  2026 value matches ``^00-\\d{7}$``, and every one joins to a row of
  nflverse's own ``stats_player_week_2026`` table on
  ``(season, week, player_id)`` -- 954/954, with targets, carries and pass
  attempts equal on 100% of joined rows.
- Rows with a null ``player_id`` exist: one per team-game, carrying only
  unattributed targets (passes with no charted receiver). They belong to no
  player.
- There is no ``season_type`` column; postseason games appear as weeks
  19-22 alongside the regular season.
- The ``*_fantasy_points`` / ``*_fantasy_points_exp`` columns assume
  **full-PPR** scoring -- see ``usage.py``.

Mirrors ``nflverse_client.py``'s shape: one release asset per season, raw
columns returned unfiltered and unrenamed. This is a distinct project from
nflverse-data itself, so it carries its own availability risk, the same as
``id_crosswalk_client.py``'s DynastyProcess source.
"""

from __future__ import annotations

import io

import pandas as pd
import requests


class ExpectedPointsClient:
    """A thin, reusable client around ffopportunity's public weekly EP assets."""

    #: Template for one season's weekly expected-points CSV under
    #: ffopportunity's ``latest-data`` release tag.
    EP_WEEKLY_URL_TEMPLATE = (
        "https://github.com/ffverse/ffopportunity/releases/download/"
        "latest-data/ep_weekly_{season}.csv"
    )

    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self.session = requests.Session()

    def download_expected_points(self, season: int) -> pd.DataFrame:
        """Download ffopportunity's weekly expected-points table for one season.

        Returns every week ffopportunity has published for ``season`` as of
        the request (159 columns as of 2026: identity, actual and expected
        per-stat columns, ``*_diff`` columns, and ``*_team`` totals), with
        ffopportunity's own raw column names -- no filtering or renaming is
        applied here. Callers should prefer the disk-caching layer in
        ``expected_points_cache``.

        Args:
            season: The NFL season to download, e.g. ``2026``.

        Returns:
            An empty ``DataFrame`` (no columns) if ffopportunity has not
            published a release asset for ``season`` (an HTTP 404) --
            treated as "no data for this season", not an error, matching
            ``NflverseClient.download_player_stats``.

        Raises:
            requests.exceptions.RequestException: On any connection,
                timeout, or non-2xx/non-404 HTTP response, exactly as raised
                by ``requests``.
        """
        url = self.EP_WEEKLY_URL_TEMPLATE.format(season=season)
        response = self.session.get(url, timeout=self.timeout)
        if response.status_code == 404:
            return pd.DataFrame()
        response.raise_for_status()
        return pd.read_csv(io.BytesIO(response.content), low_memory=False)

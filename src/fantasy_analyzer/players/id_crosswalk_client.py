"""Thin HTTP client for downloading DynastyProcess's player-ID crosswalk.

This module exists to close a coverage gap in FFA-062's original crosswalk
(``crosswalk.py``): Sleeper's own player catalog carries a ``gsis_id`` field
on only a minority of players -- as of this ticket, roughly 32% of Sleeper's
~12,000-player catalog, and a similar fraction of any given week's actual
statistical participants, including some players with real, prolific 2025
production (verified directly against the live catalog while diagnosing this
gap: Justin Jefferson's Sleeper catalog entry has ``gsis_id: None``, despite
Sleeper otherwise carrying his identity correctly). A ``build_id_crosswalk``
run from Sleeper's catalog alone therefore silently drops most of the league
-- and non-uniformly, since which players happen to have a populated
``gsis_id`` is not correlated with how good they are. Downstream, this
starves :mod:`~fantasy_analyzer.players.player_value`'s replacement-level
computation of most of its intended comparison pool, understating the
baseline and distorting VORP for every player who *did* resolve.

`DynastyProcess <https://github.com/dynastyprocess/data>`_ publishes and
maintains ``db_playerids.csv``, a community-maintained ID crosswalk across
dynasty-fantasy platforms (MFL, Sleeper, ESPN, Yahoo, ...) and providers
(nflverse's own ``gsis_id``, PFR, Sportradar, ...), refreshed regularly. As
of this ticket it carries a populated ``sleeper_id`` for essentially every
row (verified directly: 12,484 of 12,484 rows) -- including Justin
Jefferson, correctly cross-referenced to both his real ``sleeper_id`` and
``gsis_id``. Using it as a *second, explicit* ID-to-ID source (never a
name/position/team fuzzy match -- see ``crosswalk.py``'s
:func:`~fantasy_analyzer.players.crosswalk.build_id_crosswalk_from_player_ids`
for the normalizer built on top of this client) keeps faith with AGENTS.md's
"prefer immutable IDs" principle while actually covering the player pool.

This is a new, second-party network dependency alongside nflverse's own
GitHub-hosted release assets (``nflverse_client.py``,
``nflverse_schedule_client.py``) -- DynastyProcess is a distinct,
community-maintained project, not an official nflverse release, so it
carries its own (smaller, single-maintainer) availability/continuity risk.
Every caller of this client has a documented fallback to the original
Sleeper-catalog-only crosswalk (see ``crosswalk.py``), so this module's
unavailability degrades coverage rather than breaking the pipeline.

Mirrors ``nflverse_schedule_client.py``'s shape exactly: a single cumulative,
uncompressed CSV asset (not one file per season -- an ID crosswalk has no
season axis), so this client takes no arguments beyond construction options.
"""

from __future__ import annotations

import io

import pandas as pd
import requests


class PlayerIdCrosswalkClient:
    """A thin, reusable client around DynastyProcess's public ID-crosswalk asset."""

    #: The single cumulative player-ID crosswalk CSV. See the module
    #: docstring for why this file (not nflverse's own ``players`` release,
    #: which was checked first and does not carry a ``sleeper_id`` column).
    PLAYER_IDS_URL = (
        "https://raw.githubusercontent.com/dynastyprocess/data/master/"
        "files/db_playerids.csv"
    )

    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self.session = requests.Session()

    def download_player_ids(self) -> pd.DataFrame:
        """Download DynastyProcess's full player-ID crosswalk table.

        Returns DynastyProcess's own raw column names (``sleeper_id``,
        ``gsis_id``, ``name``, ``position``, ``team``, plus a large number of
        other platform-ID columns this client does not filter or rename) --
        see
        :func:`~fantasy_analyzer.players.crosswalk.build_id_crosswalk_from_player_ids`
        for the normalization step that maps this into this codebase's
        :data:`~fantasy_analyzer.players.crosswalk.CROSSWALK_COLUMNS` shape.
        This is a multi-megabyte download covering every player the source
        tracks; callers should prefer a disk-caching layer (mirroring
        ``nflverse_schedule_cache.py``'s pattern) rather than calling this
        repeatedly.

        Returns:
            An empty ``DataFrame`` (no columns) if the asset is unreachable
            via a 404 -- treated as "no data available", not an error,
            matching ``NflverseScheduleClient.download_games``'s convention.
            Any other non-2xx response still raises.

        Raises:
            requests.exceptions.RequestException: On any connection,
                timeout, or non-2xx/non-404 HTTP response, exactly as raised
                by ``requests`` -- mirrors
                ``NflverseScheduleClient.download_games``'s error handling.
        """
        response = self.session.get(self.PLAYER_IDS_URL, timeout=self.timeout)
        if response.status_code == 404:
            return pd.DataFrame()
        response.raise_for_status()
        return pd.read_csv(io.BytesIO(response.content), low_memory=False)

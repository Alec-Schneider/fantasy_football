"""Local caching for nflverse's cumulative weekly player-stats table.

``NflverseClient.download_player_stats()`` downloads a multi-megabyte,
all-seasons CSV. This module provides a thin disk-caching layer around that
call, mirroring ``sleeper/cache.py``'s split between raw client and cache:

- The cache is a single CSV file containing the raw (unfiltered, unrenamed)
  response from ``NflverseClient.download_player_stats()``.
- Callers choose the cache file path; there is no implicit global cache
  location baked into library logic. A reasonable default path is exposed
  as :data:`DEFAULT_CACHE_PATH`, pointing at ``.cache/nflverse/player_stats.csv``
  relative to the current working directory.
- This module intentionally does not implement a time-to-live/staleness
  check, for the same reason ``sleeper/cache.py`` does not: nflverse
  publishes updates on its own schedule (roughly weekly during the season),
  and callers who want fresher data call :func:`refresh_player_stats_cache`
  explicitly. The one difference from the Sleeper player catalog is that
  nflverse's cumulative file *does* change more often in-season (a new
  week's rows are appended); this module still leaves that staleness
  decision to the caller rather than guessing a TTL.

Granularity: one cache file for the entire cumulative table (all seasons,
all weeks), not one file per season or per week. nflverse itself only
publishes the current/in-progress season as part of this single cumulative
asset (see ``nflverse_client``'s module docstring), so a per-season cache
would still require downloading the same multi-season file to populate any
single season's slice. Filtering down to one ``(season, week)`` is left to
``nflverse_provider.normalize_player_stats``, which operates on whatever
this cache returns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pandas as pd

from fantasy_analyzer.players.nflverse_client import NflverseClient

DEFAULT_CACHE_PATH = Path(".cache/nflverse/player_stats.csv")


def load_player_stats_cache(
    path: Union[str, Path] = DEFAULT_CACHE_PATH,
) -> Optional[pd.DataFrame]:
    """Load a previously cached nflverse player-stats table from disk.

    Returns ``None`` if no cache file exists at ``path`` yet, so callers can
    decide whether to fall back to :func:`refresh_player_stats_cache`. Does
    not make any network calls.
    """
    cache_path = Path(path)

    if not cache_path.exists():
        return None

    return pd.read_csv(cache_path, low_memory=False)


def refresh_player_stats_cache(
    client: NflverseClient, path: Union[str, Path] = DEFAULT_CACHE_PATH
) -> pd.DataFrame:
    """Download the nflverse player-stats table and (over)write it to the cache.

    Always hits the network via ``client.download_player_stats()``, then
    persists the result to ``path`` as CSV, creating parent directories as
    needed. Any existing cache file at ``path`` is overwritten.
    """
    stats = client.download_player_stats()

    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    stats.to_csv(cache_path, index=False)

    return stats


def get_player_stats_cached(
    client: NflverseClient,
    path: Union[str, Path] = DEFAULT_CACHE_PATH,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get nflverse's player-stats table, preferring a local cache when present.

    Loads from ``path`` if a cache file already exists and ``force_refresh``
    is ``False``. Otherwise downloads and caches a fresh copy via
    :func:`refresh_player_stats_cache`.
    """
    if not force_refresh:
        cached = load_player_stats_cache(path)
        if cached is not None:
            return cached

    return refresh_player_stats_cache(client, path)

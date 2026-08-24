"""Local caching for nflverse's per-season weekly player-stats tables.

``NflverseClient.download_player_stats(season)`` downloads a multi-megabyte
CSV for one season. This module provides a thin disk-caching layer around
that call, mirroring ``sleeper/cache.py``'s split between raw client and
cache:

- The cache is one CSV file per season, containing the raw (unfiltered,
  unrenamed) response from ``NflverseClient.download_player_stats``.
- Callers choose the cache *directory*; there is no implicit global cache
  location baked into library logic. A reasonable default is exposed as
  :data:`DEFAULT_CACHE_DIR`, pointing at ``.cache/nflverse`` relative to the
  current working directory. Each season's file lives at
  ``<cache_dir>/player_stats_<season>.csv``.
- This module intentionally does not implement a time-to-live/staleness
  check, for the same reason ``sleeper/cache.py`` does not: nflverse
  publishes updates on its own schedule (roughly weekly during the season),
  and callers who want fresher data call :func:`refresh_player_stats_cache`
  explicitly.

Granularity: one cache file per season, not one cumulative file for every
season nflverse has published. This follows directly from
``NflverseClient``'s own per-season release asset (see that module's
docstring for the ``player_stats`` -> ``stats_player`` migration this
mirrors) -- there is no longer a single upstream file that would make a
cumulative cache possible. Filtering a season's file down to one week is
left to ``nflverse_provider.normalize_player_stats``, which operates on
whatever this cache returns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pandas as pd

from fantasy_analyzer.players.nflverse_client import NflverseClient

DEFAULT_CACHE_DIR = Path(".cache/nflverse")


def _season_cache_path(season: int, cache_dir: Union[str, Path]) -> Path:
    """Return the cache file path for one season under ``cache_dir``."""
    return Path(cache_dir) / f"player_stats_{season}.csv"


def load_player_stats_cache(
    season: int, cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR
) -> Optional[pd.DataFrame]:
    """Load a previously cached nflverse player-stats table for one season.

    Returns ``None`` if no cache file exists for ``season`` yet, so callers
    can decide whether to fall back to :func:`refresh_player_stats_cache`.
    Does not make any network calls.
    """
    cache_path = _season_cache_path(season, cache_dir)

    if not cache_path.exists():
        return None

    return pd.read_csv(cache_path, low_memory=False)


def refresh_player_stats_cache(
    client: NflverseClient,
    season: int,
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """Download one season's nflverse player-stats table and (over)write its cache.

    Always hits the network via ``client.download_player_stats(season)``,
    then persists the result to ``<cache_dir>/player_stats_<season>.csv``,
    creating parent directories as needed. Any existing cache file for
    ``season`` is overwritten -- including with an empty file if nflverse
    has no release asset for ``season`` yet (see
    ``NflverseClient.download_player_stats``'s "no data yet" behavior).
    """
    stats = client.download_player_stats(season)

    cache_path = _season_cache_path(season, cache_dir)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    stats.to_csv(cache_path, index=False)

    return stats


def get_player_stats_cached(
    client: NflverseClient,
    season: int,
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get one season's nflverse player-stats table, preferring a local cache.

    Loads from ``<cache_dir>/player_stats_<season>.csv`` if that cache file
    already exists and ``force_refresh`` is ``False``. Otherwise downloads
    and caches a fresh copy via :func:`refresh_player_stats_cache`.
    """
    if not force_refresh:
        cached = load_player_stats_cache(season, cache_dir)
        if cached is not None:
            return cached

    return refresh_player_stats_cache(client, season, cache_dir)

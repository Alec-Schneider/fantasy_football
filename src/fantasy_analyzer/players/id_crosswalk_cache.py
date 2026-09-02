"""Local caching for DynastyProcess's cumulative player-ID crosswalk table.

Mirrors ``nflverse_schedule_cache.py``'s split between raw client and disk
cache, for the same reason: DynastyProcess's crosswalk is a single
cumulative asset covering every player it tracks, not one asset per season,
so this cache is a single file (``<cache_dir>/db_playerids.csv``) rather
than one file per season. As with the nflverse caches, there is no
time-to-live/staleness check -- callers who want a fresh download call
:func:`refresh_player_ids_cache` explicitly.

Cached under a separate directory (:data:`DEFAULT_CACHE_DIR`,
``.cache/id_crosswalk``) rather than ``.cache/nflverse`` -- this asset comes
from a distinct third-party source (see ``id_crosswalk_client.py``'s module
docstring), and keeping its cache directory separate makes that provenance
visible on disk rather than implying it is an nflverse release asset.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pandas as pd

from fantasy_analyzer.players.id_crosswalk_client import PlayerIdCrosswalkClient

DEFAULT_CACHE_DIR = Path(".cache/id_crosswalk")


def _player_ids_cache_path(cache_dir: Union[str, Path]) -> Path:
    """Return the single cache file path for the cumulative ID crosswalk."""
    return Path(cache_dir) / "db_playerids.csv"


def load_player_ids_cache(
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
) -> Optional[pd.DataFrame]:
    """Load a previously cached DynastyProcess player-ID crosswalk table.

    Returns ``None`` if no cache file exists yet, so callers can decide
    whether to fall back to :func:`refresh_player_ids_cache`. Does not make
    any network calls.
    """
    cache_path = _player_ids_cache_path(cache_dir)

    if not cache_path.exists():
        return None

    return pd.read_csv(cache_path, low_memory=False)


def refresh_player_ids_cache(
    client: PlayerIdCrosswalkClient,
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """Download DynastyProcess's ID crosswalk and (over)write its cache.

    Always hits the network via ``client.download_player_ids()``, then
    persists the result to ``<cache_dir>/db_playerids.csv``, creating parent
    directories as needed. Any existing cache file is overwritten.
    """
    player_ids = client.download_player_ids()

    cache_path = _player_ids_cache_path(cache_dir)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    player_ids.to_csv(cache_path, index=False)

    return player_ids


def get_player_ids_cached(
    client: PlayerIdCrosswalkClient,
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get DynastyProcess's ID crosswalk table, preferring a local cache.

    Loads from ``<cache_dir>/db_playerids.csv`` if that cache file already
    exists and ``force_refresh`` is ``False``. Otherwise downloads and
    caches a fresh copy via :func:`refresh_player_ids_cache`.
    """
    if not force_refresh:
        cached = load_player_ids_cache(cache_dir)
        if cached is not None:
            return cached

    return refresh_player_ids_cache(client, cache_dir)

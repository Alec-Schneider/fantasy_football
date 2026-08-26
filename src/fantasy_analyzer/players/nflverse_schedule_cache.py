"""Local caching for nflverse's cumulative game-schedule/score table.

Mirrors ``nflverse_cache.py``'s split between raw client and disk cache, with
one difference that follows directly from ``nflverse_schedule_client.py``'s
docstring: nflverse's ``schedules`` release is a single cumulative asset
covering every season, not one asset per season, so this cache is a single
file (``<cache_dir>/games.csv``) rather than one file per season. As with
``nflverse_cache.py``, there is no time-to-live/staleness check -- callers
who want a fresh download call :func:`refresh_games_cache` explicitly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pandas as pd

from fantasy_analyzer.players.nflverse_schedule_client import NflverseScheduleClient

DEFAULT_CACHE_DIR = Path(".cache/nflverse")


def _games_cache_path(cache_dir: Union[str, Path]) -> Path:
    """Return the single cache file path for the cumulative games table."""
    return Path(cache_dir) / "games.csv"


def load_games_cache(
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
) -> Optional[pd.DataFrame]:
    """Load a previously cached nflverse games table.

    Returns ``None`` if no cache file exists yet, so callers can decide
    whether to fall back to :func:`refresh_games_cache`. Does not make any
    network calls.
    """
    cache_path = _games_cache_path(cache_dir)

    if not cache_path.exists():
        return None

    return pd.read_csv(cache_path, low_memory=False)


def refresh_games_cache(
    client: NflverseScheduleClient,
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """Download nflverse's games table and (over)write its cache.

    Always hits the network via ``client.download_games()``, then persists
    the result to ``<cache_dir>/games.csv``, creating parent directories as
    needed. Any existing cache file is overwritten.
    """
    games = client.download_games()

    cache_path = _games_cache_path(cache_dir)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    games.to_csv(cache_path, index=False)

    return games


def get_games_cached(
    client: NflverseScheduleClient,
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get nflverse's games table, preferring a local cache.

    Loads from ``<cache_dir>/games.csv`` if that cache file already exists
    and ``force_refresh`` is ``False``. Otherwise downloads and caches a
    fresh copy via :func:`refresh_games_cache`.
    """
    if not force_refresh:
        cached = load_games_cache(cache_dir)
        if cached is not None:
            return cached

    return refresh_games_cache(client, cache_dir)

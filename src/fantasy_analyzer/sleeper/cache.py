"""Local caching for the Sleeper NFL player catalog.

``SleeperClient.get_players()`` downloads Sleeper's entire NFL player
database, which is a large (5MB+) JSON blob. This module provides a thin
disk-caching layer around that call so normal analysis does not need to
repeatedly re-download the catalog.

The cache is a single JSON file containing the raw response from
``SleeperClient.get_players()``. Callers choose the cache file path; there is
no implicit global cache location baked into library logic. A reasonable
default path is exposed as :data:`DEFAULT_CACHE_PATH`, pointing at
``.cache/sleeper/players.json`` relative to the current working directory.

This module intentionally does not implement a time-to-live/staleness check.
The Sleeper player catalog changes slowly (roster moves, new players), and
callers who want fresh data can call :func:`refresh_player_cache` explicitly.
Adding an automatic TTL is left as a future enhancement if it proves useful.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Union

from fantasy_analyzer.sleeper.client import SleeperClient

DEFAULT_CACHE_PATH = Path(".cache/sleeper/players.json")


def load_player_cache(path: Union[str, Path] = DEFAULT_CACHE_PATH) -> Optional[dict]:
    """Load a previously cached Sleeper player catalog from disk.

    Returns ``None`` if no cache file exists at ``path`` yet, so callers can
    decide whether to fall back to :func:`refresh_player_cache`. Does not
    make any network calls.
    """
    cache_path = Path(path)

    if not cache_path.exists():
        return None

    return json.loads(cache_path.read_text())


def refresh_player_cache(
    client: SleeperClient, path: Union[str, Path] = DEFAULT_CACHE_PATH
) -> dict:
    """Download the Sleeper player catalog and (over)write it to the cache.

    Always hits the network via ``client.get_players()``, then persists the
    result to ``path`` as JSON, creating parent directories as needed. Any
    existing cache file at ``path`` is overwritten.
    """
    players = client.get_players()

    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(players))

    return players


def get_players_cached(
    client: SleeperClient,
    path: Union[str, Path] = DEFAULT_CACHE_PATH,
    force_refresh: bool = False,
) -> dict:
    """Get the Sleeper player catalog, preferring a local cache when present.

    Loads from ``path`` if a cache file already exists and ``force_refresh``
    is ``False``. Otherwise downloads and caches a fresh copy via
    :func:`refresh_player_cache`.
    """
    if not force_refresh:
        cached = load_player_cache(path)
        if cached is not None:
            return cached

    return refresh_player_cache(client, path)

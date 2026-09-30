"""Local caching for ffopportunity's per-season weekly expected points (FFA-110).

Mirrors ``nflverse_cache.py`` exactly: one CSV per season holding the raw
(unfiltered, unrenamed) response from
``ExpectedPointsClient.download_expected_points``, a caller-chosen cache
directory with :data:`DEFAULT_CACHE_DIR` as a reasonable default, and no
time-to-live/staleness check -- callers who want the current week call
:func:`refresh_expected_points_cache` explicitly.

Cached under its own directory, ``.cache/ffopportunity``, rather than
``.cache/nflverse``, for the same provenance reason ``id_crosswalk_cache.py``
gives: ffopportunity is a separate ffverse project, not an nflverse-data
release asset. Each season lives at ``<cache_dir>/ep_weekly_<season>.csv``.

As in ``snap_counts_cache.py``, a season cached from an HTTP 404 reads back
as an empty ``DataFrame`` rather than raising pandas' ``EmptyDataError``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pandas as pd

from fantasy_analyzer.players.expected_points_client import ExpectedPointsClient

DEFAULT_CACHE_DIR = Path(".cache/ffopportunity")


def _season_cache_path(season: int, cache_dir: Union[str, Path]) -> Path:
    """Return the cache file path for one season under ``cache_dir``."""
    return Path(cache_dir) / f"ep_weekly_{season}.csv"


def load_expected_points_cache(
    season: int, cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR
) -> Optional[pd.DataFrame]:
    """Load a previously cached ffopportunity weekly table for one season.

    Returns ``None`` if no cache file exists for ``season`` yet, and an empty
    ``DataFrame`` if the cached file records an unpublished season. Does not
    make any network calls.
    """
    cache_path = _season_cache_path(season, cache_dir)

    if not cache_path.exists():
        return None

    try:
        return pd.read_csv(cache_path, low_memory=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def refresh_expected_points_cache(
    client: ExpectedPointsClient,
    season: int,
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """Download one season's expected-points table and (over)write its cache.

    Always hits the network via ``client.download_expected_points(season)``,
    then persists the result to ``<cache_dir>/ep_weekly_<season>.csv``,
    creating parent directories as needed. Any existing cache file for
    ``season`` is overwritten.
    """
    expected = client.download_expected_points(season)

    cache_path = _season_cache_path(season, cache_dir)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    expected.to_csv(cache_path, index=False)

    return expected


def get_expected_points_cached(
    client: ExpectedPointsClient,
    season: int,
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get one season's expected-points table, preferring a local cache.

    Loads from ``<cache_dir>/ep_weekly_<season>.csv`` if that cache file
    already exists and ``force_refresh`` is ``False``. Otherwise downloads
    and caches a fresh copy via :func:`refresh_expected_points_cache`.
    """
    if not force_refresh:
        cached = load_expected_points_cache(season, cache_dir)
        if cached is not None:
            return cached

    return refresh_expected_points_cache(client, season, cache_dir)

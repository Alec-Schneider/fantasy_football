"""Local caching for nflverse's per-season snap-count tables (FFA-110).

Mirrors ``nflverse_cache.py`` exactly: one CSV per season holding the raw
(unfiltered, unrenamed) response from
``SnapCountsClient.download_snap_counts``, a caller-chosen cache directory
with :data:`DEFAULT_CACHE_DIR` as a reasonable default, and no
time-to-live/staleness check -- the current season changes weekly, so
callers who want fresher data call :func:`refresh_snap_counts_cache`
explicitly (``scripts/fetch_usage_seasons.py --refresh-season`` does this).

Cached alongside the player-stats files in ``.cache/nflverse``, because this
*is* an nflverse-data release asset: ``<cache_dir>/snap_counts_<season>.csv``.

One deliberate difference from ``nflverse_cache.py``: a season nflverse has
not published (HTTP 404) is cached as an empty file, and reading that file
back returns an empty ``DataFrame`` rather than raising pandas'
``EmptyDataError``. "Not published" is therefore remembered on disk and
distinguishable from "never fetched" (``None``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pandas as pd

from fantasy_analyzer.players.snap_counts_client import SnapCountsClient

DEFAULT_CACHE_DIR = Path(".cache/nflverse")


def _season_cache_path(season: int, cache_dir: Union[str, Path]) -> Path:
    """Return the cache file path for one season under ``cache_dir``."""
    return Path(cache_dir) / f"snap_counts_{season}.csv"


def load_snap_counts_cache(
    season: int, cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR
) -> Optional[pd.DataFrame]:
    """Load a previously cached nflverse snap-count table for one season.

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


def refresh_snap_counts_cache(
    client: SnapCountsClient,
    season: int,
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """Download one season's snap counts and (over)write its cache.

    Always hits the network via ``client.download_snap_counts(season)``,
    then persists the result to ``<cache_dir>/snap_counts_<season>.csv``,
    creating parent directories as needed. Any existing cache file for
    ``season`` is overwritten.
    """
    snaps = client.download_snap_counts(season)

    cache_path = _season_cache_path(season, cache_dir)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    snaps.to_csv(cache_path, index=False)

    return snaps


def get_snap_counts_cached(
    client: SnapCountsClient,
    season: int,
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get one season's snap-count table, preferring a local cache.

    Loads from ``<cache_dir>/snap_counts_<season>.csv`` if that cache file
    already exists and ``force_refresh`` is ``False``. Otherwise downloads
    and caches a fresh copy via :func:`refresh_snap_counts_cache`.
    """
    if not force_refresh:
        cached = load_snap_counts_cache(season, cache_dir)
        if cached is not None:
            return cached

    return refresh_snap_counts_cache(client, season, cache_dir)

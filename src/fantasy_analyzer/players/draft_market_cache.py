"""Local caching and fetch-and-normalize glue for FFA-075's draft-market data.

Mirrors ``id_crosswalk_cache.py``'s split between raw client and disk cache
for each of the two new sources ``draft_market_client.py`` introduces, plus
one addition neither ``id_crosswalk_cache.py`` nor ``nflverse_cache.py``
needs: this module also owns the "fetch every source, then hand it to the
pure normalizer" orchestration (:func:`get_draft_market_cached` /
:func:`get_draft_market_player_pool_cached`), so that ``draft_market.py``
itself never imports ``requests`` or performs any I/O -- see that module's
docstring for why keeping it 100% pure matters for testability.

Two cache shapes, because the two sources have different axes
------------------------------------------------------------------

- **FFC's ADP** varies by season, league size, and scoring format (its own
  request parameters) -- there is no single "the" ADP table the way there
  is a single cumulative ID crosswalk. This cache is therefore one file per
  ``(scoring, teams, season)`` combination, following
  ``nflverse_cache.py``'s per-season-file precedent generalized to this
  source's extra axes.
- **DynastyProcess's FantasyPros ECR export** (``db_fpecr_latest.csv``) is,
  like ``db_playerids.csv``, a single cumulative "latest" asset with no
  season/league-size axis of its own (a fresh scrape happens on
  DynastyProcess's own schedule, not per season) -- this cache is a single
  file, exactly mirroring ``id_crosswalk_cache.py``.

As with every existing cache module in this codebase, there is no
time-to-live/staleness check; callers who want a fresh download pass
``force_refresh=True`` or call the corresponding ``refresh_*`` function
directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pandas as pd

from fantasy_analyzer.players.draft_market import (
    build_draft_market,
    build_draft_market_player_pool,
)
from fantasy_analyzer.players.draft_market_client import (
    FantasyProsEcrClient,
    FfcAdpClient,
)
from fantasy_analyzer.players.id_crosswalk_cache import (
    DEFAULT_CACHE_DIR as ID_CROSSWALK_DEFAULT_CACHE_DIR,
)
from fantasy_analyzer.players.id_crosswalk_cache import get_player_ids_cached
from fantasy_analyzer.players.id_crosswalk_client import PlayerIdCrosswalkClient

DEFAULT_CACHE_DIR = Path(".cache/draft_market")


def _ffc_adp_cache_path(
    season: int, teams: int, scoring: str, cache_dir: Union[str, Path]
) -> Path:
    """Return the cache file path for one FFC ADP request under ``cache_dir``."""
    return Path(cache_dir) / "ffc" / f"adp_{scoring}_{teams}_{season}.csv"


def load_ffc_adp_cache(
    season: int,
    teams: int = 12,
    scoring: str = "half-ppr",
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
) -> Optional[pd.DataFrame]:
    """Load a previously cached FFC ADP table for one (scoring, teams, season).

    Returns ``None`` if no cache file exists yet, so callers can decide
    whether to fall back to :func:`refresh_ffc_adp_cache`. Does not make
    any network calls.
    """
    cache_path = _ffc_adp_cache_path(season, teams, scoring, cache_dir)

    if not cache_path.exists():
        return None

    return pd.read_csv(cache_path, low_memory=False)


def refresh_ffc_adp_cache(
    client: FfcAdpClient,
    season: int,
    teams: int = 12,
    scoring: str = "half-ppr",
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """Download one FFC ADP table and (over)write its cache.

    Always hits the network via ``client.download_adp(...)``, then
    persists the result to
    ``<cache_dir>/ffc/adp_<scoring>_<teams>_<season>.csv``, creating parent
    directories as needed. Any existing cache file for this combination is
    overwritten -- including with an empty file if FFC has no data for it
    (see ``FfcAdpClient.download_adp``'s "no data yet" behavior).
    """
    adp = client.download_adp(season, teams=teams, scoring=scoring)

    cache_path = _ffc_adp_cache_path(season, teams, scoring, cache_dir)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    adp.to_csv(cache_path, index=False)

    return adp


def get_ffc_adp_cached(
    client: FfcAdpClient,
    season: int,
    teams: int = 12,
    scoring: str = "half-ppr",
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get one FFC ADP table, preferring a local cache.

    Loads from ``<cache_dir>/ffc/adp_<scoring>_<teams>_<season>.csv`` if
    that cache file already exists and ``force_refresh`` is ``False``.
    Otherwise downloads and caches a fresh copy via
    :func:`refresh_ffc_adp_cache`.
    """
    if not force_refresh:
        cached = load_ffc_adp_cache(season, teams, scoring, cache_dir)
        if cached is not None:
            return cached

    return refresh_ffc_adp_cache(client, season, teams, scoring, cache_dir)


def _fpecr_cache_path(cache_dir: Union[str, Path]) -> Path:
    """Return the single cache file path for the cumulative FP-ECR export."""
    return Path(cache_dir) / "fantasypros" / "db_fpecr_latest.csv"


def load_fpecr_cache(
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
) -> Optional[pd.DataFrame]:
    """Load a previously cached FantasyPros ECR export.

    Returns ``None`` if no cache file exists yet, so callers can decide
    whether to fall back to :func:`refresh_fpecr_cache`. Does not make any
    network calls.
    """
    cache_path = _fpecr_cache_path(cache_dir)

    if not cache_path.exists():
        return None

    return pd.read_csv(cache_path, low_memory=False)


def refresh_fpecr_cache(
    client: FantasyProsEcrClient,
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """Download DynastyProcess's FantasyPros ECR export and (over)write its cache.

    Always hits the network via ``client.download_ecr()``, then persists
    the result to ``<cache_dir>/fantasypros/db_fpecr_latest.csv``, creating
    parent directories as needed. Any existing cache file is overwritten.
    """
    fpecr = client.download_ecr()

    cache_path = _fpecr_cache_path(cache_dir)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    fpecr.to_csv(cache_path, index=False)

    return fpecr


def get_fpecr_cached(
    client: FantasyProsEcrClient,
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get DynastyProcess's FantasyPros ECR export, preferring a local cache.

    Loads from ``<cache_dir>/fantasypros/db_fpecr_latest.csv`` if that
    cache file already exists and ``force_refresh`` is ``False``. Otherwise
    downloads and caches a fresh copy via :func:`refresh_fpecr_cache`.
    """
    if not force_refresh:
        cached = load_fpecr_cache(cache_dir)
        if cached is not None:
            return cached

    return refresh_fpecr_cache(client, cache_dir)


def get_draft_market_cached(
    season: int,
    teams: int = 12,
    scoring: str = "half-ppr",
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
    id_crosswalk_cache_dir: Union[str, Path] = ID_CROSSWALK_DEFAULT_CACHE_DIR,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Fetch (from cache or network) and normalize both draft-market sources.

    This is the one call a caller who just wants
    :data:`~fantasy_analyzer.players.draft_market.DRAFT_MARKET_COLUMNS`-shaped
    data needs: it fetches FFC's ADP, DynastyProcess's FantasyPros ECR
    export, and DynastyProcess's ID crosswalk (each preferring its own
    disk cache, reusing
    :func:`~fantasy_analyzer.players.id_crosswalk_cache.get_player_ids_cached`
    directly rather than re-downloading that asset -- see this module's
    docstring), then hands all three to
    :func:`~fantasy_analyzer.players.draft_market.build_draft_market`.

    Args:
        season: The draft season to fetch, e.g. ``2026``.
        teams: League size for FFC's ADP request. Defaults to ``12``.
        scoring: FFC's scoring-format path segment. Defaults to
            ``"half-ppr"``.
        cache_dir: Directory for this module's own caches (FFC ADP and the
            FantasyPros ECR export). Defaults to :data:`DEFAULT_CACHE_DIR`.
        id_crosswalk_cache_dir: Directory for the shared DynastyProcess ID
            crosswalk cache. Defaults to
            :data:`~fantasy_analyzer.players.id_crosswalk_cache.DEFAULT_CACHE_DIR`,
            so this call reuses whatever cache any other part of this
            codebase has already populated instead of downloading a second
            copy.
        force_refresh: If ``True``, re-downloads all three sources instead
            of using any existing cache.

    Returns:
        A :data:`~fantasy_analyzer.players.draft_market.DRAFT_MARKET_COLUMNS`-shaped
        DataFrame; see :func:`~fantasy_analyzer.players.draft_market.build_draft_market`
        for its empty-input behavior.
    """
    ffc_players = get_ffc_adp_cached(
        FfcAdpClient(), season, teams=teams, scoring=scoring,
        cache_dir=cache_dir, force_refresh=force_refresh,
    )
    fpecr_raw = get_fpecr_cached(
        FantasyProsEcrClient(), cache_dir=cache_dir, force_refresh=force_refresh
    )
    player_ids = get_player_ids_cached(
        PlayerIdCrosswalkClient(),
        cache_dir=id_crosswalk_cache_dir,
        force_refresh=force_refresh,
    )
    return build_draft_market(ffc_players, fpecr_raw, player_ids, season)


def get_draft_market_player_pool_cached(
    season: int,
    teams: int = 12,
    scoring: str = "half-ppr",
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
    id_crosswalk_cache_dir: Union[str, Path] = ID_CROSSWALK_DEFAULT_CACHE_DIR,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Fetch and normalize both sources, then pivot to the wide player pool.

    Convenience wrapper combining :func:`get_draft_market_cached` with
    :func:`~fantasy_analyzer.players.draft_market.build_draft_market_player_pool`.
    See both for the full argument and return contract.

    Returns:
        A
        :data:`~fantasy_analyzer.players.draft_market.DRAFT_MARKET_POOL_COLUMNS`-shaped
        DataFrame, one row per resolved ``sleeper_player_id``.
    """
    fpecr_raw = get_fpecr_cached(
        FantasyProsEcrClient(), cache_dir=cache_dir, force_refresh=force_refresh
    )
    player_ids = get_player_ids_cached(
        PlayerIdCrosswalkClient(),
        cache_dir=id_crosswalk_cache_dir,
        force_refresh=force_refresh,
    )
    ffc_players = get_ffc_adp_cached(
        FfcAdpClient(), season, teams=teams, scoring=scoring,
        cache_dir=cache_dir, force_refresh=force_refresh,
    )
    draft_market = build_draft_market(ffc_players, fpecr_raw, player_ids, season)
    return build_draft_market_player_pool(draft_market, fpecr_raw, player_ids)

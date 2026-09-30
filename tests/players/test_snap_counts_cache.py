"""Tests for the local nflverse snap-count cache (FFA-110).

No live network: HTTP calls are mocked with requests_mock. Mirrors
``test_nflverse_schedule_cache.py``, plus the one behavior this cache adds:
a season cached from a 404 reads back as an empty frame instead of raising.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests_mock as requests_mock_lib

from fantasy_analyzer.players.snap_counts_cache import (
    get_snap_counts_cached,
    load_snap_counts_cache,
    refresh_snap_counts_cache,
)
from fantasy_analyzer.players.snap_counts_client import SnapCountsClient

SNAP_FIXTURE = (
    Path(__file__).resolve().parent.parent / "fixtures" / "nflverse" / "snap_counts.csv"
)


def _mock_url(m: requests_mock_lib.Mocker, season: int = 2025, **kwargs) -> None:
    m.get(SnapCountsClient.SNAP_COUNTS_URL_TEMPLATE.format(season=season), **kwargs)


def test_load_returns_none_when_never_fetched(tmp_path: Path) -> None:
    assert load_snap_counts_cache(2025, tmp_path) is None


def test_refresh_writes_one_file_per_season(tmp_path: Path) -> None:
    cache_dir = tmp_path / "nflverse"
    with requests_mock_lib.Mocker() as m:
        _mock_url(m, content=SNAP_FIXTURE.read_bytes())
        result = refresh_snap_counts_cache(SnapCountsClient(), 2025, cache_dir)

    on_disk = pd.read_csv(cache_dir / "snap_counts_2025.csv")
    assert len(on_disk) == len(result) == 19


def test_get_cached_reads_disk_without_network(tmp_path: Path) -> None:
    (tmp_path / "snap_counts_2025.csv").write_bytes(SNAP_FIXTURE.read_bytes())

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, status_code=500)
        result = get_snap_counts_cached(SnapCountsClient(), 2025, tmp_path)

        assert not m.called

    assert len(result) == 19


def test_get_cached_downloads_when_missing(tmp_path: Path) -> None:
    with requests_mock_lib.Mocker() as m:
        _mock_url(m, content=SNAP_FIXTURE.read_bytes())
        result = get_snap_counts_cached(SnapCountsClient(), 2025, tmp_path)

    assert len(result) == 19
    assert (tmp_path / "snap_counts_2025.csv").exists()


def test_force_refresh_replaces_an_existing_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "snap_counts_2026.csv"
    cache_path.write_text("season,week\n2026,1\n")

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, season=2026, content=SNAP_FIXTURE.read_bytes())
        result = get_snap_counts_cached(
            SnapCountsClient(), 2026, tmp_path, force_refresh=True
        )

        assert m.called

    assert len(result) == len(pd.read_csv(cache_path)) == 19


def test_unpublished_season_round_trips_as_empty_not_an_error(tmp_path: Path) -> None:
    with requests_mock_lib.Mocker() as m:
        _mock_url(m, season=2011, status_code=404)
        refresh_snap_counts_cache(SnapCountsClient(), 2011, tmp_path)

    cached = load_snap_counts_cache(2011, tmp_path)
    assert cached is not None
    assert cached.empty

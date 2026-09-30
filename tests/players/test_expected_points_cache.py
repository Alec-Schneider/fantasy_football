"""Tests for the local ffopportunity expected-points cache (FFA-110).

No live network: HTTP calls are mocked with requests_mock. Mirrors
``test_snap_counts_cache.py``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests_mock as requests_mock_lib

from fantasy_analyzer.players.expected_points_cache import (
    DEFAULT_CACHE_DIR,
    get_expected_points_cached,
    load_expected_points_cache,
    refresh_expected_points_cache,
)
from fantasy_analyzer.players.expected_points_client import ExpectedPointsClient

EP_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "ffopportunity"
    / "ep_weekly.csv"
)


def _mock_url(m: requests_mock_lib.Mocker, season: int = 2025, **kwargs) -> None:
    m.get(ExpectedPointsClient.EP_WEEKLY_URL_TEMPLATE.format(season=season), **kwargs)


def test_default_cache_dir_is_separate_from_nflverse() -> None:
    assert DEFAULT_CACHE_DIR == Path(".cache/ffopportunity")


def test_load_returns_none_when_never_fetched(tmp_path: Path) -> None:
    assert load_expected_points_cache(2025, tmp_path) is None


def test_refresh_writes_one_file_per_season(tmp_path: Path) -> None:
    cache_dir = tmp_path / "ffopportunity"
    with requests_mock_lib.Mocker() as m:
        _mock_url(m, content=EP_FIXTURE.read_bytes())
        result = refresh_expected_points_cache(ExpectedPointsClient(), 2025, cache_dir)

    on_disk = pd.read_csv(cache_dir / "ep_weekly_2025.csv")
    assert len(on_disk) == len(result) == 12


def test_get_cached_reads_disk_without_network(tmp_path: Path) -> None:
    (tmp_path / "ep_weekly_2025.csv").write_bytes(EP_FIXTURE.read_bytes())

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, status_code=500)
        result = get_expected_points_cached(ExpectedPointsClient(), 2025, tmp_path)

        assert not m.called

    assert len(result) == 12


def test_force_refresh_replaces_an_existing_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "ep_weekly_2026.csv"
    cache_path.write_text("season,week\n2026,1\n")

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, season=2026, content=EP_FIXTURE.read_bytes())
        result = get_expected_points_cached(
            ExpectedPointsClient(), 2026, tmp_path, force_refresh=True
        )

        assert m.called

    assert len(result) == len(pd.read_csv(cache_path)) == 12


def test_unpublished_season_round_trips_as_empty_not_an_error(tmp_path: Path) -> None:
    with requests_mock_lib.Mocker() as m:
        _mock_url(m, season=2005, status_code=404)
        refresh_expected_points_cache(ExpectedPointsClient(), 2005, tmp_path)

    cached = load_expected_points_cache(2005, tmp_path)
    assert cached is not None
    assert cached.empty

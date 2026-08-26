"""Tests for the local nflverse games/schedule cache (FFA-073).

These tests never touch the live nflverse-data release -- all HTTP calls are
mocked with requests_mock against a sanitized fixture CSV. Mirrors
``test_nflverse_cache.py``'s structure for the sibling player-stats cache.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests_mock as requests_mock_lib

from fantasy_analyzer.players.nflverse_schedule_cache import (
    get_games_cached,
    load_games_cache,
    refresh_games_cache,
)
from fantasy_analyzer.players.nflverse_schedule_client import NflverseScheduleClient


def _mock_url(m: requests_mock_lib.Mocker, **kwargs) -> None:
    m.get(NflverseScheduleClient.GAMES_URL, **kwargs)


def test_load_games_cache_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_games_cache(tmp_path) is None


def test_refresh_games_cache_writes_table_to_disk(
    tmp_path: Path, nflverse_games_fixture_path: Path
) -> None:
    cache_dir = tmp_path / "nflverse"
    client = NflverseScheduleClient()

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, content=nflverse_games_fixture_path.read_bytes())
        result = refresh_games_cache(client, cache_dir)

    cache_path = cache_dir / "games.csv"
    assert cache_path.exists()
    on_disk = pd.read_csv(cache_path)
    assert len(on_disk) == len(result) == 6


def test_load_games_cache_reads_existing_cache_without_network(
    tmp_path: Path, nflverse_games_fixture_path: Path
) -> None:
    cache_path = tmp_path / "games.csv"
    cache_path.write_bytes(nflverse_games_fixture_path.read_bytes())

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, status_code=500)
        result = load_games_cache(tmp_path)

        assert not m.called

    assert len(result) == 6


def test_get_games_cached_loads_from_cache_without_network(
    tmp_path: Path, nflverse_games_fixture_path: Path
) -> None:
    cache_path = tmp_path / "games.csv"
    cache_path.write_bytes(nflverse_games_fixture_path.read_bytes())
    client = NflverseScheduleClient()

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, status_code=500)
        result = get_games_cached(client, tmp_path)

        assert not m.called

    assert len(result) == 6


def test_get_games_cached_refreshes_when_no_cache_present(
    tmp_path: Path, nflverse_games_fixture_path: Path
) -> None:
    client = NflverseScheduleClient()

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, content=nflverse_games_fixture_path.read_bytes())
        result = get_games_cached(client, tmp_path)

    assert len(result) == 6
    assert (tmp_path / "games.csv").exists()


def test_get_games_cached_force_refresh_ignores_existing_cache(
    tmp_path: Path, nflverse_games_fixture_path: Path
) -> None:
    cache_path = tmp_path / "games.csv"
    cache_path.write_text("season,week\n1999,1\n")
    client = NflverseScheduleClient()

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, content=nflverse_games_fixture_path.read_bytes())
        result = get_games_cached(client, tmp_path, force_refresh=True)

        assert m.called

    assert len(result) == 6
    on_disk = pd.read_csv(cache_path)
    assert len(on_disk) == 6

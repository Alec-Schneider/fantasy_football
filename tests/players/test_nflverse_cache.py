"""Tests for the local nflverse player-stats cache (FFA-061).

These tests never touch the live nflverse-data release -- all HTTP calls are
mocked with requests_mock against a sanitized fixture CSV. Cache files are
always written under pytest's ``tmp_path`` fixture, never into the real repo
tree. Mirrors ``tests/sleeper/test_cache.py``'s structure for the sibling
Sleeper player-catalog cache.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd
import requests_mock as requests_mock_lib

from fantasy_analyzer.players.nflverse_cache import (
    get_player_stats_cached,
    load_player_stats_cache,
    refresh_player_stats_cache,
)
from fantasy_analyzer.players.nflverse_client import NflverseClient


def _gzipped_fixture(path: Path) -> bytes:
    return gzip.compress(path.read_bytes())


def test_load_player_stats_cache_returns_none_when_missing(tmp_path: Path) -> None:
    cache_path = tmp_path / "player_stats.csv"

    assert load_player_stats_cache(cache_path) is None


def test_refresh_player_stats_cache_writes_table_to_disk(
    tmp_path: Path, nflverse_fixture_path: Path
) -> None:
    cache_path = tmp_path / "nflverse" / "player_stats.csv"
    client = NflverseClient()

    with requests_mock_lib.Mocker() as m:
        m.get(
            NflverseClient.PLAYER_STATS_URL,
            content=_gzipped_fixture(nflverse_fixture_path),
        )
        result = refresh_player_stats_cache(client, cache_path)

    assert cache_path.exists()
    on_disk = pd.read_csv(cache_path)
    assert len(on_disk) == len(result) == 4


def test_load_player_stats_cache_reads_existing_cache_without_network(
    tmp_path: Path, nflverse_fixture_path: Path
) -> None:
    cache_path = tmp_path / "player_stats.csv"
    cache_path.write_bytes(nflverse_fixture_path.read_bytes())

    with requests_mock_lib.Mocker() as m:
        m.get(NflverseClient.PLAYER_STATS_URL, status_code=500)
        result = load_player_stats_cache(cache_path)

        assert not m.called

    assert len(result) == 4


def test_get_player_stats_cached_loads_from_cache_without_network(
    tmp_path: Path, nflverse_fixture_path: Path
) -> None:
    cache_path = tmp_path / "player_stats.csv"
    cache_path.write_bytes(nflverse_fixture_path.read_bytes())
    client = NflverseClient()

    with requests_mock_lib.Mocker() as m:
        m.get(NflverseClient.PLAYER_STATS_URL, status_code=500)
        result = get_player_stats_cached(client, cache_path)

        assert not m.called

    assert len(result) == 4


def test_get_player_stats_cached_refreshes_when_no_cache_present(
    tmp_path: Path, nflverse_fixture_path: Path
) -> None:
    cache_path = tmp_path / "player_stats.csv"
    client = NflverseClient()

    with requests_mock_lib.Mocker() as m:
        m.get(
            NflverseClient.PLAYER_STATS_URL,
            content=_gzipped_fixture(nflverse_fixture_path),
        )
        result = get_player_stats_cached(client, cache_path)

    assert len(result) == 4
    assert cache_path.exists()


def test_get_player_stats_cached_force_refresh_ignores_existing_cache(
    tmp_path: Path, nflverse_fixture_path: Path
) -> None:
    cache_path = tmp_path / "player_stats.csv"
    cache_path.write_text("player_id,season,week\n00-9999,1999,1\n")
    client = NflverseClient()

    with requests_mock_lib.Mocker() as m:
        m.get(
            NflverseClient.PLAYER_STATS_URL,
            content=_gzipped_fixture(nflverse_fixture_path),
        )
        result = get_player_stats_cached(client, cache_path, force_refresh=True)

        assert m.called

    assert len(result) == 4
    on_disk = pd.read_csv(cache_path)
    assert len(on_disk) == 4

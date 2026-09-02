"""Tests for the local DynastyProcess player-ID crosswalk cache.

These tests never touch the live DynastyProcess asset -- all HTTP calls are
mocked with requests_mock against a sanitized fixture CSV. Mirrors
``test_nflverse_schedule_cache.py``'s structure for the sibling cumulative
CSV cache.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests_mock as requests_mock_lib

from fantasy_analyzer.players.id_crosswalk_cache import (
    get_player_ids_cached,
    load_player_ids_cache,
    refresh_player_ids_cache,
)
from fantasy_analyzer.players.id_crosswalk_client import PlayerIdCrosswalkClient


def _mock_url(m: requests_mock_lib.Mocker, **kwargs) -> None:
    m.get(PlayerIdCrosswalkClient.PLAYER_IDS_URL, **kwargs)


def test_load_player_ids_cache_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_player_ids_cache(tmp_path) is None


def test_refresh_player_ids_cache_writes_table_to_disk(
    tmp_path: Path, id_crosswalk_fixture_path: Path
) -> None:
    cache_dir = tmp_path / "id_crosswalk"
    client = PlayerIdCrosswalkClient()

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, content=id_crosswalk_fixture_path.read_bytes())
        result = refresh_player_ids_cache(client, cache_dir)

    cache_path = cache_dir / "db_playerids.csv"
    assert cache_path.exists()
    on_disk = pd.read_csv(cache_path)
    assert len(on_disk) == len(result) == 7


def test_load_player_ids_cache_reads_existing_cache_without_network(
    tmp_path: Path, id_crosswalk_fixture_path: Path
) -> None:
    cache_path = tmp_path / "db_playerids.csv"
    cache_path.write_bytes(id_crosswalk_fixture_path.read_bytes())

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, status_code=500)
        result = load_player_ids_cache(tmp_path)

        assert not m.called

    assert len(result) == 7


def test_get_player_ids_cached_loads_from_cache_without_network(
    tmp_path: Path, id_crosswalk_fixture_path: Path
) -> None:
    cache_path = tmp_path / "db_playerids.csv"
    cache_path.write_bytes(id_crosswalk_fixture_path.read_bytes())
    client = PlayerIdCrosswalkClient()

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, status_code=500)
        result = get_player_ids_cached(client, tmp_path)

        assert not m.called

    assert len(result) == 7


def test_get_player_ids_cached_refreshes_when_no_cache_present(
    tmp_path: Path, id_crosswalk_fixture_path: Path
) -> None:
    client = PlayerIdCrosswalkClient()

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, content=id_crosswalk_fixture_path.read_bytes())
        result = get_player_ids_cached(client, tmp_path)

    assert len(result) == 7
    assert (tmp_path / "db_playerids.csv").exists()


def test_get_player_ids_cached_force_refresh_ignores_existing_cache(
    tmp_path: Path, id_crosswalk_fixture_path: Path
) -> None:
    cache_path = tmp_path / "db_playerids.csv"
    cache_path.write_text("sleeper_id,gsis_id,name,position,team\n1,00-9999,X,QB,ZZZ\n")
    client = PlayerIdCrosswalkClient()

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, content=id_crosswalk_fixture_path.read_bytes())
        result = get_player_ids_cached(client, tmp_path, force_refresh=True)

        assert m.called

    assert len(result) == 7
    on_disk = pd.read_csv(cache_path)
    assert len(on_disk) == 7

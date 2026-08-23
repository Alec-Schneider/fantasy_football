"""Tests for the local Sleeper player catalog cache.

These tests never touch the live Sleeper API -- all HTTP calls are mocked
with requests_mock against sanitized fixture responses. Cache files are
always written under pytest's ``tmp_path`` fixture, never into the real
repo tree.
"""

import json
from pathlib import Path

import requests_mock as requests_mock_lib

from fantasy_analyzer.sleeper import SleeperClient
from fantasy_analyzer.sleeper.cache import (
    get_players_cached,
    load_player_cache,
    refresh_player_cache,
)


def test_load_player_cache_returns_none_when_missing(tmp_path: Path) -> None:
    cache_path = tmp_path / "players.json"

    assert load_player_cache(cache_path) is None


def test_refresh_player_cache_writes_catalog_to_disk(
    tmp_path: Path, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("players.json")
    cache_path = tmp_path / "sleeper" / "players.json"
    client = SleeperClient()

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/players/nfl", json=fixture)
        result = refresh_player_cache(client, cache_path)

    assert result == fixture
    assert cache_path.exists()
    assert json.loads(cache_path.read_text()) == fixture


def test_load_player_cache_reads_existing_cache_without_network(
    tmp_path: Path, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("players.json")
    cache_path = tmp_path / "players.json"
    cache_path.write_text(json.dumps(fixture))

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/players/nfl", json={})
        result = load_player_cache(cache_path)

        assert not m.called

    assert result == fixture


def test_get_players_cached_loads_from_cache_without_network(
    tmp_path: Path, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("players.json")
    cache_path = tmp_path / "players.json"
    cache_path.write_text(json.dumps(fixture))
    client = SleeperClient()

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/players/nfl", json={})
        result = get_players_cached(client, cache_path)

        assert not m.called

    assert result == fixture


def test_get_players_cached_refreshes_when_no_cache_present(
    tmp_path: Path, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("players.json")
    cache_path = tmp_path / "players.json"
    client = SleeperClient()

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/players/nfl", json=fixture)
        result = get_players_cached(client, cache_path)

    assert result == fixture
    assert cache_path.exists()


def test_refresh_player_cache_overwrites_stale_data(tmp_path: Path) -> None:
    cache_path = tmp_path / "players.json"
    stale = {"1000": {"player_id": "1000", "full_name": "Stale Player"}}
    cache_path.write_text(json.dumps(stale))

    fresh = {"1000": {"player_id": "1000", "full_name": "Fresh Player"}}
    client = SleeperClient()

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/players/nfl", json=fresh)
        result = refresh_player_cache(client, cache_path)

    assert result == fresh
    assert json.loads(cache_path.read_text()) == fresh
    assert result != stale


def test_get_players_cached_force_refresh_ignores_existing_cache(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "players.json"
    stale = {"1000": {"player_id": "1000", "full_name": "Stale Player"}}
    cache_path.write_text(json.dumps(stale))

    fresh = {"1000": {"player_id": "1000", "full_name": "Fresh Player"}}
    client = SleeperClient()

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/players/nfl", json=fresh)
        result = get_players_cached(client, cache_path, force_refresh=True)

        assert m.called

    assert result == fresh

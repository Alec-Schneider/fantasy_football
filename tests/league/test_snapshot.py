"""Tests for the LeagueSnapshot composition service.

These tests operate on already-fetched raw Sleeper dicts -- no HTTP calls
are made or mocked, per AGENTS.md's separation of data access from
normalization -- except for the single integration-style test of
:func:`load_league_snapshot`, which exercises the thin fetching wrapper via
``requests_mock``.
"""

import pandas as pd
import requests_mock as requests_mock_lib

from fantasy_analyzer.league import (
    LeagueSettings,
    LeagueSnapshot,
    build_league_snapshot,
)
from fantasy_analyzer.league.snapshot import load_league_snapshot
from fantasy_analyzer.sleeper import SleeperClient


def test_build_league_snapshot_from_fixtures(load_sleeper_fixture) -> None:
    raw_league = load_sleeper_fixture("league.json")
    raw_users = load_sleeper_fixture("users.json")
    raw_rosters = load_sleeper_fixture("rosters.json")
    player_catalog = load_sleeper_fixture("players.json")

    snapshot = build_league_snapshot(raw_league, raw_users, raw_rosters, player_catalog)

    assert isinstance(snapshot, LeagueSnapshot)
    assert isinstance(snapshot.league, LeagueSettings)
    assert snapshot.league.league_id == "111111111111111111"


def test_build_league_snapshot_teams_df_matches_team_mapping(
    load_sleeper_fixture,
) -> None:
    raw_league = load_sleeper_fixture("league.json")
    raw_users = load_sleeper_fixture("users.json")
    raw_rosters = load_sleeper_fixture("rosters.json")
    player_catalog = load_sleeper_fixture("players.json")

    snapshot = build_league_snapshot(raw_league, raw_users, raw_rosters, player_catalog)

    assert list(snapshot.teams_df.columns) == [
        "roster_id",
        "owner_id",
        "display_name",
        "team_name",
    ]
    assert len(snapshot.teams_df) == len(raw_rosters)

    row = snapshot.teams_df.loc[snapshot.teams_df["roster_id"] == 1].iloc[0]
    assert row["display_name"] == "Test User"
    assert row["team_name"] == "The Testers"


def test_build_league_snapshot_users_df(load_sleeper_fixture) -> None:
    raw_league = load_sleeper_fixture("league.json")
    raw_users = load_sleeper_fixture("users.json")
    raw_rosters = load_sleeper_fixture("rosters.json")
    player_catalog = load_sleeper_fixture("players.json")

    snapshot = build_league_snapshot(raw_league, raw_users, raw_rosters, player_catalog)

    assert list(snapshot.users_df.columns) == ["user_id", "display_name", "team_name"]
    assert len(snapshot.users_df) == len(raw_users)

    row = snapshot.users_df.loc[
        snapshot.users_df["user_id"] == "223456789012345678"
    ].iloc[0]
    assert row["display_name"] == "Other User"
    # metadata.team_name absent -> falls back to display_name.
    assert row["team_name"] == "Other User"


def test_build_league_snapshot_rosters_df(load_sleeper_fixture) -> None:
    raw_league = load_sleeper_fixture("league.json")
    raw_users = load_sleeper_fixture("users.json")
    raw_rosters = load_sleeper_fixture("rosters.json")
    player_catalog = load_sleeper_fixture("players.json")

    snapshot = build_league_snapshot(raw_league, raw_users, raw_rosters, player_catalog)

    assert list(snapshot.rosters_df.columns) == [
        "roster_id",
        "owner_id",
        "wins",
        "losses",
        "ties",
        "fpts",
        "players",
        "starters",
    ]
    assert len(snapshot.rosters_df) == len(raw_rosters)

    row = snapshot.rosters_df.loc[snapshot.rosters_df["roster_id"] == 1].iloc[0]
    assert row["wins"] == 5
    assert row["losses"] == 3
    assert row["ties"] == 0
    assert row["players"] == ["1000", "1001"]
    assert row["starters"] == ["1000"]


def test_build_league_snapshot_players_df_deduplicates_across_rosters(
    load_sleeper_fixture,
) -> None:
    raw_league = load_sleeper_fixture("league.json")
    raw_users = load_sleeper_fixture("users.json")
    raw_rosters = load_sleeper_fixture("rosters.json")
    player_catalog = load_sleeper_fixture("players.json")

    snapshot = build_league_snapshot(raw_league, raw_users, raw_rosters, player_catalog)

    # Fixture rosters reference "1000", "1001" (roster 1) and "1002" (roster 2).
    assert list(snapshot.players_df.columns) == [
        "player_id",
        "full_name",
        "position",
        "team",
    ]
    assert list(snapshot.players_df["player_id"]) == ["1000", "1001", "1002"]

    known = snapshot.players_df.loc[snapshot.players_df["player_id"] == "1000"].iloc[0]
    assert known["full_name"] == "Test Player One"
    assert known["position"] == "QB"

    # 1001 is referenced by a roster but absent from the fixture catalog.
    unknown = snapshot.players_df.loc[snapshot.players_df["player_id"] == "1001"].iloc[
        0
    ]
    assert pd.isna(unknown["full_name"])


def test_build_league_snapshot_scoring_settings_and_roster_positions_passthrough(
    load_sleeper_fixture,
) -> None:
    raw_league = load_sleeper_fixture("league.json")
    raw_users = load_sleeper_fixture("users.json")
    raw_rosters = load_sleeper_fixture("rosters.json")
    player_catalog = load_sleeper_fixture("players.json")

    snapshot = build_league_snapshot(raw_league, raw_users, raw_rosters, player_catalog)

    assert snapshot.scoring_settings == snapshot.league.scoring_settings
    assert snapshot.scoring_settings["pass_td"] == 4
    assert snapshot.roster_positions == snapshot.league.roster_positions
    assert "FLEX" in snapshot.roster_positions


def test_build_league_snapshot_handles_roster_with_no_owner() -> None:
    """A roster with no owner_id must not crash snapshot construction."""
    raw_league = {"league_id": "1", "season": "2025"}
    raw_users = [{"user_id": "u1", "display_name": "Alice", "metadata": {}}]
    raw_rosters = [{"roster_id": 1, "owner_id": None, "players": [], "settings": {}}]
    player_catalog: dict = {}

    snapshot = build_league_snapshot(raw_league, raw_users, raw_rosters, player_catalog)

    row = snapshot.teams_df.iloc[0]
    assert row["owner_id"] is None
    assert row["display_name"] is None

    roster_row = snapshot.rosters_df.iloc[0]
    assert roster_row["owner_id"] is None
    assert roster_row["wins"] is None
    assert roster_row["players"] == []

    assert snapshot.players_df.empty


def test_build_league_snapshot_handles_sparse_league_settings() -> None:
    """A minimal/sparse raw league dict must not crash snapshot construction."""
    raw_league = {"league_id": "1"}
    raw_users: list = []
    raw_rosters: list = []
    player_catalog: dict = {}

    snapshot = build_league_snapshot(raw_league, raw_users, raw_rosters, player_catalog)

    assert snapshot.league.league_id == "1"
    assert snapshot.scoring_settings == {}
    assert snapshot.roster_positions == []
    assert snapshot.teams_df.empty
    assert snapshot.users_df.empty
    assert snapshot.rosters_df.empty
    assert snapshot.players_df.empty


def test_build_league_snapshot_deduplicates_player_id_shared_across_rosters() -> None:
    """A player ID referenced by multiple rosters appears once in players_df."""
    raw_league = {"league_id": "1"}
    raw_users: list = []
    raw_rosters = [
        {"roster_id": 1, "owner_id": None, "players": ["1000", "1002"], "settings": {}},
        {"roster_id": 2, "owner_id": None, "players": ["1002", "1003"], "settings": {}},
    ]
    player_catalog = {
        "1000": {
            "player_id": "1000",
            "full_name": "Player A",
            "position": "QB",
            "team": "SEA",
        },
        "1002": {
            "player_id": "1002",
            "full_name": "Player B",
            "position": "RB",
            "team": "KC",
        },
    }

    snapshot = build_league_snapshot(raw_league, raw_users, raw_rosters, player_catalog)

    assert list(snapshot.players_df["player_id"]) == ["1000", "1002", "1003"]


def test_load_league_snapshot_fetches_and_builds_from_client(
    tmp_path, load_sleeper_fixture
) -> None:
    """Thin integration-style test of the fetching convenience wrapper."""
    raw_league = load_sleeper_fixture("league.json")
    raw_users = load_sleeper_fixture("users.json")
    raw_rosters = load_sleeper_fixture("rosters.json")
    player_catalog = load_sleeper_fixture("players.json")

    league_id = raw_league["league_id"]
    client = SleeperClient()
    cache_path = tmp_path / "players.json"

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/{league_id}", json=raw_league)
        m.get(f"{SleeperClient.BASE_URL}/league/{league_id}/users", json=raw_users)
        m.get(f"{SleeperClient.BASE_URL}/league/{league_id}/rosters", json=raw_rosters)
        m.get(f"{SleeperClient.BASE_URL}/players/nfl", json=player_catalog)

        snapshot = load_league_snapshot(client, league_id, player_cache_path=cache_path)

    assert isinstance(snapshot, LeagueSnapshot)
    assert snapshot.league.league_id == league_id
    assert len(snapshot.teams_df) == len(raw_rosters)
    assert cache_path.exists()

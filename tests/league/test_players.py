"""Tests for player metadata resolution.

These tests operate on already-fetched raw Sleeper dicts -- no HTTP calls
are made or mocked here, per AGENTS.md's separation of data access from
normalization.
"""

import pandas as pd

from fantasy_analyzer.league import resolve_player, resolve_roster_players

PLAYER_CATALOG = {
    "4984": {
        "player_id": "4984",
        "full_name": "Josh Allen",
        "position": "QB",
        "team": "BUF",
    },
    "9001": {
        "player_id": "9001",
        "first_name": "Ja'Marr",
        "last_name": "Chase",
        "position": "WR",
        "team": "CIN",
    },
    "9002": {
        "player_id": "9002",
        "full_name": "Free Agent Guy",
        "position": "RB",
        "team": None,
    },
}


def test_resolve_player_returns_metadata_for_known_player() -> None:
    resolved = resolve_player("4984", PLAYER_CATALOG)

    assert resolved == {
        "player_id": "4984",
        "full_name": "Josh Allen",
        "position": "QB",
        "team": "BUF",
    }


def test_resolve_player_falls_back_to_first_and_last_name() -> None:
    """Some catalog entries lack full_name and only have first/last name."""
    resolved = resolve_player("9001", PLAYER_CATALOG)

    assert resolved["full_name"] == "Ja'Marr Chase"
    assert resolved["position"] == "WR"
    assert resolved["team"] == "CIN"


def test_resolve_player_handles_free_agent_with_no_team() -> None:
    resolved = resolve_player("9002", PLAYER_CATALOG)

    assert resolved["team"] is None
    assert resolved["full_name"] == "Free Agent Guy"


def test_resolve_player_unknown_id_does_not_crash() -> None:
    """Team-abbreviation defense IDs and retired players may be absent."""
    resolved = resolve_player("BUF", PLAYER_CATALOG)

    assert resolved == {
        "player_id": "BUF",
        "full_name": None,
        "position": None,
        "team": None,
    }


def test_resolve_player_retired_player_missing_from_stale_cache() -> None:
    resolved = resolve_player("99999999", PLAYER_CATALOG)

    assert resolved["player_id"] == "99999999"
    assert resolved["full_name"] is None
    assert resolved["position"] is None
    assert resolved["team"] is None


def test_resolve_roster_players_returns_one_row_per_id() -> None:
    player_ids = ["4984", "9001", "BUF"]

    resolved = resolve_roster_players(player_ids, PLAYER_CATALOG)

    assert list(resolved.columns) == ["player_id", "full_name", "position", "team"]
    assert len(resolved) == 3

    row = resolved.loc[resolved["player_id"] == "4984"].iloc[0]
    assert row["full_name"] == "Josh Allen"
    assert row["position"] == "QB"
    assert row["team"] == "BUF"

    unresolved = resolved.loc[resolved["player_id"] == "BUF"].iloc[0]
    assert pd.isna(unresolved["full_name"])
    assert pd.isna(unresolved["position"])
    assert pd.isna(unresolved["team"])


def test_resolve_roster_players_preserves_order_and_duplicates() -> None:
    player_ids = ["9002", "4984", "9002"]

    resolved = resolve_roster_players(player_ids, PLAYER_CATALOG)

    assert list(resolved["player_id"]) == ["9002", "4984", "9002"]


def test_resolve_roster_players_empty_input_produces_empty_frame() -> None:
    resolved = resolve_roster_players([], PLAYER_CATALOG)

    assert resolved.empty
    assert list(resolved.columns) == ["player_id", "full_name", "position", "team"]


def test_resolve_roster_players_from_fixture_catalog_and_roster(
    load_sleeper_fixture,
) -> None:
    """Resolve a real roster's players list against the fixture catalog."""
    player_catalog = load_sleeper_fixture("players.json")
    rosters = load_sleeper_fixture("rosters.json")
    roster = next(r for r in rosters if r["roster_id"] == 1)

    resolved = resolve_roster_players(roster["players"], player_catalog)

    assert list(resolved["player_id"]) == ["1000", "1001"]

    known = resolved.loc[resolved["player_id"] == "1000"].iloc[0]
    assert known["full_name"] == "Test Player One"
    assert known["position"] == "QB"
    assert known["team"] == "SEA"

    # 1001 is referenced by the roster but absent from the fixture catalog.
    unknown = resolved.loc[resolved["player_id"] == "1001"].iloc[0]
    assert pd.isna(unknown["full_name"])
    assert pd.isna(unknown["position"])
    assert pd.isna(unknown["team"])

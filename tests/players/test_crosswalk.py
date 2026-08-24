"""Tests for the Sleeper<->nflverse ID crosswalk (FFA-062).

Operates entirely on in-memory dicts and the sanitized Sleeper player-catalog
fixture -- no HTTP calls are made or mocked here, per AGENTS.md's separation
of data access from normalization.
"""

from __future__ import annotations

import pandas as pd

from fantasy_analyzer.players import (
    CROSSWALK_COLUMNS,
    build_id_crosswalk,
    gsis_to_sleeper_lookup,
    sleeper_to_gsis_lookup,
)

PLAYER_CATALOG = {
    "4984": {
        "player_id": "4984",
        "full_name": "Josh Allen",
        "position": "QB",
        "team": "BUF",
        "gsis_id": "00-0034857",
    },
    "9001": {
        "player_id": "9001",
        "full_name": "Ja'Marr Chase",
        "position": "WR",
        "team": "CIN",
        "gsis_id": None,
    },
    "9002": {
        "player_id": "9002",
        "full_name": "Practice Squad Guy",
        "position": "RB",
        "team": "KC",
        # No gsis_id key at all -- mirrors the real API's shape for some
        # players.
    },
}


def test_build_id_crosswalk_pairs_a_normal_player() -> None:
    crosswalk = build_id_crosswalk(PLAYER_CATALOG)

    assert list(crosswalk.columns) == CROSSWALK_COLUMNS
    row = crosswalk.loc[crosswalk["sleeper_player_id"] == "4984"].iloc[0]
    assert row["gsis_id"] == "00-0034857"
    assert row["full_name"] == "Josh Allen"
    assert row["position"] == "QB"
    assert row["team"] == "BUF"


def test_build_id_crosswalk_excludes_null_gsis_id() -> None:
    """A player with gsis_id: null contributes no crosswalk row."""
    crosswalk = build_id_crosswalk(PLAYER_CATALOG)

    assert "9001" not in set(crosswalk["sleeper_player_id"])


def test_build_id_crosswalk_excludes_missing_gsis_id_key() -> None:
    """A player missing the gsis_id key entirely contributes no crosswalk row."""
    crosswalk = build_id_crosswalk(PLAYER_CATALOG)

    assert "9002" not in set(crosswalk["sleeper_player_id"])


def test_build_id_crosswalk_only_includes_players_with_a_usable_gsis_id() -> None:
    crosswalk = build_id_crosswalk(PLAYER_CATALOG)

    assert len(crosswalk) == 1
    assert list(crosswalk["sleeper_player_id"]) == ["4984"]


def test_build_id_crosswalk_empty_catalog_returns_empty_frame() -> None:
    crosswalk = build_id_crosswalk({})

    assert crosswalk.empty
    assert list(crosswalk.columns) == CROSSWALK_COLUMNS


def test_build_id_crosswalk_resolves_gsis_id_collision_last_wins() -> None:
    """Two Sleeper ids sharing a gsis_id: the later catalog entry wins."""
    catalog = {
        "1111": {
            "player_id": "1111",
            "full_name": "Stale Duplicate",
            "position": "WR",
            "team": "NYJ",
            "gsis_id": "00-0099999",
        },
        "2222": {
            "player_id": "2222",
            "full_name": "Current Player",
            "position": "WR",
            "team": "NYJ",
            "gsis_id": "00-0099999",
        },
    }

    crosswalk = build_id_crosswalk(catalog)

    assert len(crosswalk) == 1
    assert crosswalk.iloc[0]["sleeper_player_id"] == "2222"
    assert crosswalk.iloc[0]["full_name"] == "Current Player"


def test_gsis_to_sleeper_lookup_builds_a_reverse_dict() -> None:
    crosswalk = build_id_crosswalk(PLAYER_CATALOG)

    lookup = gsis_to_sleeper_lookup(crosswalk)

    assert lookup == {"00-0034857": "4984"}


def test_gsis_to_sleeper_lookup_empty_crosswalk_returns_empty_dict() -> None:
    empty = pd.DataFrame(columns=CROSSWALK_COLUMNS)

    assert gsis_to_sleeper_lookup(empty) == {}


def test_sleeper_to_gsis_lookup_builds_a_forward_dict() -> None:
    crosswalk = build_id_crosswalk(PLAYER_CATALOG)

    lookup = sleeper_to_gsis_lookup(crosswalk)

    assert lookup == {"4984": "00-0034857"}


def test_sleeper_to_gsis_lookup_empty_crosswalk_returns_empty_dict() -> None:
    empty = pd.DataFrame(columns=CROSSWALK_COLUMNS)

    assert sleeper_to_gsis_lookup(empty) == {}


def test_build_id_crosswalk_from_fixture_catalog(load_sleeper_fixture) -> None:
    """The sanitized fixture carries a mix of populated/null/missing gsis_id."""
    player_catalog = load_sleeper_fixture("players.json")

    crosswalk = build_id_crosswalk(player_catalog)

    # "1000" has a populated gsis_id; "1002" has gsis_id: null; "1003" has
    # no gsis_id key at all -- only "1000" should produce a row.
    assert list(crosswalk["sleeper_player_id"]) == ["1000"]
    assert crosswalk.iloc[0]["gsis_id"] == "00-0034857"

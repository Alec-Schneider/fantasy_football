"""Tests for the Sleeper<->nflverse ID crosswalk (FFA-062).

Operates entirely on in-memory dicts and the sanitized Sleeper player-catalog
fixture -- no HTTP calls are made or mocked here, per AGENTS.md's separation
of data access from normalization.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.players import (
    CROSSWALK_COLUMNS,
    build_id_crosswalk,
    build_id_crosswalk_from_player_ids,
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


# -------------------------
# build_id_crosswalk_from_player_ids (DynastyProcess source)
# -------------------------


def test_build_id_crosswalk_from_player_ids_pairs_a_normal_player(
    id_crosswalk_fixture_path,
) -> None:
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    assert list(crosswalk.columns) == CROSSWALK_COLUMNS
    row = crosswalk.loc[crosswalk["sleeper_player_id"] == "4984"].iloc[0]
    assert row["gsis_id"] == "00-0034857"
    assert row["full_name"] == "Josh Allen"
    assert row["position"] == "QB"
    assert row["team"] == "BUF"


def test_build_id_crosswalk_from_player_ids_sleeper_id_has_no_float_suffix(
    id_crosswalk_fixture_path,
) -> None:
    """The source stores sleeper_id numerically -- must render "4984", not "4984.0"."""
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    assert "4984" in set(crosswalk["sleeper_player_id"])
    assert "4984.0" not in set(crosswalk["sleeper_player_id"])


def test_build_id_crosswalk_from_player_ids_excludes_missing_sleeper_id(
    id_crosswalk_fixture_path,
) -> None:
    """A row with no sleeper_id (blank in the fixture) contributes no row."""
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    assert "No Sleeper Match" not in set(crosswalk["full_name"])


def test_build_id_crosswalk_from_player_ids_excludes_missing_gsis_id(
    id_crosswalk_fixture_path,
) -> None:
    """A row with no gsis_id (blank in the fixture) contributes no row."""
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    assert "No Gsis Match" not in set(crosswalk["full_name"])


def test_build_id_crosswalk_from_player_ids_resolves_gsis_id_collision_last_wins(
    id_crosswalk_fixture_path,
) -> None:
    """Two rows sharing a gsis_id ("00-0055555"): the later row wins."""
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    matches = crosswalk[crosswalk["gsis_id"] == "00-0055555"]
    assert len(matches) == 1
    assert matches.iloc[0]["full_name"] == "Current Player"
    assert "Stale Duplicate" not in set(crosswalk["full_name"])


def test_build_id_crosswalk_from_player_ids_resolves_sleeper_id_collision_last_wins(
    id_crosswalk_fixture_path,
) -> None:
    """Two rows sharing a sleeper_id ("6000"): the later row wins."""
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    matches = crosswalk[crosswalk["sleeper_player_id"] == "6000"]
    assert len(matches) == 1
    assert matches.iloc[0]["full_name"] == "New Mapping"
    assert "Old Mapping" not in set(crosswalk["full_name"])


def test_build_id_crosswalk_from_player_ids_only_includes_usable_rows(
    id_crosswalk_fixture_path,
) -> None:
    """7 source rows: 1 dropped (no sleeper_id), 1 dropped (no gsis_id), 2
    collision pairs collapse to 1 each -> 3 rows survive."""
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    assert len(crosswalk) == 3


def test_build_id_crosswalk_from_player_ids_empty_frame_returns_empty() -> None:
    crosswalk = build_id_crosswalk_from_player_ids(pd.DataFrame())

    assert crosswalk.empty
    assert list(crosswalk.columns) == CROSSWALK_COLUMNS


def test_build_id_crosswalk_from_player_ids_missing_column_raises() -> None:
    wrong_shape = pd.DataFrame({"sleeper_id": [1], "gsis_id": ["00-0000001"]})

    with pytest.raises(ValueError, match="name"):
        build_id_crosswalk_from_player_ids(wrong_shape)


def test_build_id_crosswalk_from_player_ids_ignores_unrelated_columns(
    id_crosswalk_fixture_path,
) -> None:
    """mfl_id is present in the fixture but not part of CROSSWALK_COLUMNS."""
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    assert "mfl_id" not in crosswalk.columns

"""Tests for current-state free-agent pool resolution (FFA-091).

All tests operate on hand-built roster/catalog dicts and small in-memory
DataFrames -- no HTTP calls -- so every inclusion/exclusion can be verified
by hand against the module docstring's toy example. No test depends on
``tests/fixtures/sleeper/rosters.json`` / ``players.json`` beyond a light
sanity check, since those fixtures were not built with ``status``/``taxi``
in mind.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.players import (
    DEFAULT_EXCLUDED_STATUSES,
    FREE_AGENT_POOL_COLUMNS,
    build_fantasypros_ownership_lookup,
    build_free_agent_pool,
    resolve_startable_positions,
    rostered_player_ids,
)
from fantasy_analyzer.players.crosswalk import CROSSWALK_COLUMNS

ROSTER_POSITIONS = [
    "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN", "BN", "IR",
]


# -------------------------
# resolve_startable_positions
# -------------------------


def test_resolve_startable_positions_toy_example():
    positions = resolve_startable_positions(ROSTER_POSITIONS)
    assert positions == {"QB", "RB", "WR", "TE", "K", "DEF"}


def test_resolve_startable_positions_ignores_bench_and_unknown_slots():
    assert resolve_startable_positions(["BN", "IR", "TAXI", "not_a_slot"]) == set()


def test_resolve_startable_positions_empty_input():
    assert resolve_startable_positions([]) == set()


def test_resolve_startable_positions_flex_adds_no_new_position_if_already_present():
    # A pure sanity check that FLEX doesn't do anything exotic: RB/WR/TE
    # already present from dedicated slots, FLEX just reinforces them.
    positions = resolve_startable_positions(["RB", "WR", "TE", "FLEX"])
    assert positions == {"RB", "WR", "TE"}


# -------------------------
# rostered_player_ids
# -------------------------


def test_rostered_player_ids_unions_players_starters_reserve_taxi():
    raw_rosters = [
        {
            "roster_id": 1,
            "players": ["1", "2"],
            "starters": ["1"],
            "reserve": ["2"],
        },
        {
            "roster_id": 2,
            "players": ["3"],
            "starters": ["3"],
            "reserve": [],
            "taxi": ["4"],
        },
    ]
    assert rostered_player_ids(raw_rosters) == {"1", "2", "3", "4"}


def test_rostered_player_ids_empty_rosters():
    assert rostered_player_ids([]) == set()
    assert rostered_player_ids([{"roster_id": 1}]) == set()


# -------------------------
# build_free_agent_pool -- the module docstring's toy example
# -------------------------


@pytest.fixture
def toy_catalog() -> dict:
    return {
        "1": {
            "player_id": "1",
            "full_name": "Rostered Starter",
            "position": "QB",
            "team": "SEA",
        },
        "2": {"player_id": "2", "full_name": "IR Guy", "position": "QB", "team": "KC"},
        "3": {
            "player_id": "3",
            "full_name": "Free Agent QB",
            "position": "QB",
            "team": "CIN",
        },
        "4": {
            "player_id": "4",
            "full_name": "Retired QB",
            "position": "QB",
            "team": None,
            "status": "Retired",
        },
        "5": {
            "player_id": "5",
            "full_name": "Free Agent RB",
            "position": "RB",
            "team": "DAL",
        },
    }


@pytest.fixture
def toy_rosters() -> list[dict]:
    return [
        {"roster_id": 1, "players": ["1"], "starters": ["1"], "reserve": []},
        {"roster_id": 2, "players": ["2"], "starters": [], "reserve": ["2"]},
    ]


def test_toy_example_free_agent_pool_matches_docstring(toy_catalog, toy_rosters):
    # Only QB is startable -- RB is not in roster_positions at all.
    pool = build_free_agent_pool(
        toy_rosters, toy_catalog, roster_positions=["QB", "BN"]
    )

    assert list(pool.columns) == FREE_AGENT_POOL_COLUMNS
    assert set(pool["player_id"]) == {"3"}
    row = pool.iloc[0]
    assert row["full_name"] == "Free Agent QB"
    assert row["position"] == "QB"
    assert bool(row["has_crosswalk"]) is False
    assert pd.isna(row["player_owned_avg"])


def test_ir_and_taxi_players_are_not_free_agents():
    catalog = {
        "1": {"player_id": "1", "position": "RB", "full_name": "IR Player"},
        "2": {"player_id": "2", "position": "RB", "full_name": "Taxi Player"},
        "3": {"player_id": "3", "position": "RB", "full_name": "True Free Agent"},
    }
    raw_rosters = [
        {"roster_id": 1, "players": ["1"], "starters": [], "reserve": ["1"]},
        {"roster_id": 2, "players": ["2"], "starters": [], "taxi": ["2"]},
    ]
    pool = build_free_agent_pool(raw_rosters, catalog, roster_positions=["RB", "BN"])
    assert set(pool["player_id"]) == {"3"}


def test_inactive_and_retired_excluded_case_insensitively():
    catalog = {
        "1": {"player_id": "1", "position": "WR", "status": "inactive"},
        "2": {"player_id": "2", "position": "WR", "status": "RETIRED"},
        "3": {"player_id": "3", "position": "WR", "status": "Active"},
        "4": {"player_id": "4", "position": "WR"},  # missing status -> included
    }
    pool = build_free_agent_pool([], catalog, roster_positions=["WR", "BN"])
    assert set(pool["player_id"]) == {"3", "4"}


def test_default_excluded_statuses_constant():
    assert DEFAULT_EXCLUDED_STATUSES == frozenset({"inactive", "retired"})


def test_position_not_started_by_league_is_excluded():
    catalog = {
        "1": {"player_id": "1", "position": "LS", "full_name": "Long Snapper"},
        "2": {"player_id": "2", "position": "QB", "full_name": "Startable QB"},
    }
    pool = build_free_agent_pool([], catalog, roster_positions=["QB", "BN"])
    assert set(pool["player_id"]) == {"2"}


def test_no_startable_positions_returns_empty_pool():
    catalog = {"1": {"player_id": "1", "position": "QB"}}
    pool = build_free_agent_pool([], catalog, roster_positions=["BN", "IR"])
    assert pool.empty
    assert list(pool.columns) == FREE_AGENT_POOL_COLUMNS


def test_empty_catalog_returns_empty_pool():
    pool = build_free_agent_pool([], {}, roster_positions=["QB"])
    assert pool.empty
    assert list(pool.columns) == FREE_AGENT_POOL_COLUMNS


def test_missing_crosswalk_entry_kept_not_dropped():
    catalog = {
        "1": {"player_id": "1", "position": "WR", "full_name": "Has Crosswalk"},
        "2": {"player_id": "2", "position": "WR", "full_name": "No Crosswalk"},
    }
    crosswalk = pd.DataFrame(
        [
            {
                "sleeper_player_id": "1",
                "gsis_id": "00-1111111",
                "full_name": "Has Crosswalk",
                "position": "WR",
                "team": "SF",
            }
        ],
        columns=CROSSWALK_COLUMNS,
    )
    pool = build_free_agent_pool(
        [], catalog, roster_positions=["WR", "BN"], crosswalk=crosswalk
    )
    assert set(pool["player_id"]) == {"1", "2"}

    with_crosswalk = pool.set_index("player_id").loc["1"]
    without_crosswalk = pool.set_index("player_id").loc["2"]
    assert bool(with_crosswalk["has_crosswalk"]) is True
    assert with_crosswalk["gsis_id"] == "00-1111111"
    assert bool(without_crosswalk["has_crosswalk"]) is False
    assert pd.isna(without_crosswalk["gsis_id"])


def test_ownership_lookup_populates_player_owned_avg_when_given():
    catalog = {"1": {"player_id": "1", "position": "WR", "full_name": "Owned Guy"}}
    pool = build_free_agent_pool(
        [], catalog, roster_positions=["WR", "BN"], ownership_lookup={"1": 12.5}
    )
    assert pool.iloc[0]["player_owned_avg"] == 12.5


def test_ownership_lookup_missing_entry_is_nan():
    catalog = {"1": {"player_id": "1", "position": "WR", "full_name": "Unlisted"}}
    pool = build_free_agent_pool(
        [], catalog, roster_positions=["WR", "BN"], ownership_lookup={"999": 50.0}
    )
    assert pd.isna(pool.iloc[0]["player_owned_avg"])


def test_defense_player_ids_use_team_abbreviations():
    catalog = {"SF": {"player_id": "SF", "position": "DEF", "full_name": "49ers"}}
    pool = build_free_agent_pool([], catalog, roster_positions=["DEF", "BN"])
    assert set(pool["player_id"]) == {"SF"}


def test_real_sleeper_and_rosters_fixtures_produce_no_error(load_sleeper_fixture):
    """Light integration sanity check against this repo's shared fixtures."""
    catalog = load_sleeper_fixture("players.json")
    raw_rosters = load_sleeper_fixture("rosters.json")
    pool = build_free_agent_pool(
        raw_rosters, catalog, roster_positions=["QB", "RB", "WR", "BN"]
    )
    # "1000" (QB) and "1002" (RB) are rostered; "1003" (WR) is not on any
    # roster in the fixture and WR is startable, so it must appear.
    assert "1003" in set(pool["player_id"])
    assert "1000" not in set(pool["player_id"])
    assert "1002" not in set(pool["player_id"])


# -------------------------
# build_fantasypros_ownership_lookup
# -------------------------


@pytest.fixture
def fpecr_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "page_type": "redraft-overall",
                "id": 1001,
                "player": "A",
                "player_owned_avg": 90.0,
            },
            {
                "page_type": "redraft-overall",
                "id": 1002,
                "player": "B",
                "player_owned_avg": 4.0,
            },
            {
                "page_type": "redraft-overall",
                "id": 9999,
                "player": "No Match",
                "player_owned_avg": 50.0,
            },
            {
                "page_type": "redraft-overall",
                "id": None,
                "player": "No FP Id (DST)",
                "player_owned_avg": 80.0,
            },
            {
                "page_type": "redraft-qb",
                "id": 1001,
                "player": "A",
                "player_owned_avg": 1.0,
            },
        ]
    )


@pytest.fixture
def player_ids_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"fantasypros_id": 1001.0, "sleeper_id": 100.0},
            {"fantasypros_id": 1002.0, "sleeper_id": 200.0},
            {"fantasypros_id": None, "sleeper_id": 300.0},
        ]
    )


def test_build_fantasypros_ownership_lookup_toy_example(fpecr_df, player_ids_df):
    lookup = build_fantasypros_ownership_lookup(fpecr_df, player_ids_df)
    assert lookup == {"100": 90.0, "200": 4.0}


def test_build_fantasypros_ownership_lookup_empty_inputs():
    empty = pd.DataFrame()
    assert build_fantasypros_ownership_lookup(empty, empty) == {}


def test_build_fantasypros_ownership_lookup_missing_columns():
    assert build_fantasypros_ownership_lookup(
        pd.DataFrame({"page_type": ["redraft-overall"]}), pd.DataFrame({"x": [1]})
    ) == {}

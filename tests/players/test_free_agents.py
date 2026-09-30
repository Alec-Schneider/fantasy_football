"""Tests for current-state free-agent pool resolution (FFA-091, FFA-103, FFA-109).

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
from fantasy_analyzer.players.free_agents import (
    PLAYER_UNIVERSE_COLUMNS,
    build_player_universe,
    catalog_display_name,
    has_nfl_team,
    roster_id_by_player,
)

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
        # FFA-103: Sleeper's shape for an unsigned NFL free agent.
        "6": {
            "player_id": "6",
            "full_name": "Unsigned QB",
            "position": "QB",
            "team": None,
            "status": "Active",
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


# FFA-103: the catalogs below originally carried no ``team`` key, which the
# pre-FFA-103 pool silently accepted. Each now names an NFL team so the test
# still isolates the rule it is about rather than tripping the team guard,
# which has its own tests further down.


def test_ir_and_taxi_players_are_not_free_agents():
    catalog = {
        "1": {
            "player_id": "1",
            "position": "RB",
            "full_name": "IR Player",
            "team": "SF",
        },
        "2": {
            "player_id": "2",
            "position": "RB",
            "full_name": "Taxi Player",
            "team": "SF",
        },
        "3": {
            "player_id": "3",
            "position": "RB",
            "full_name": "True Free Agent",
            "team": "SF",
        },
    }
    raw_rosters = [
        {"roster_id": 1, "players": ["1"], "starters": [], "reserve": ["1"]},
        {"roster_id": 2, "players": ["2"], "starters": [], "taxi": ["2"]},
    ]
    pool = build_free_agent_pool(raw_rosters, catalog, roster_positions=["RB", "BN"])
    assert set(pool["player_id"]) == {"3"}


def test_inactive_and_retired_excluded_case_insensitively():
    catalog = {
        "1": {"player_id": "1", "position": "WR", "status": "inactive", "team": "SF"},
        "2": {"player_id": "2", "position": "WR", "status": "RETIRED", "team": "SF"},
        "3": {"player_id": "3", "position": "WR", "status": "Active", "team": "SF"},
        # missing status -> included
        "4": {"player_id": "4", "position": "WR", "team": "SF"},
    }
    pool = build_free_agent_pool([], catalog, roster_positions=["WR", "BN"])
    assert set(pool["player_id"]) == {"3", "4"}


def test_default_excluded_statuses_constant():
    assert DEFAULT_EXCLUDED_STATUSES == frozenset({"inactive", "retired"})


def test_position_not_started_by_league_is_excluded():
    catalog = {
        "1": {
            "player_id": "1",
            "position": "LS",
            "full_name": "Long Snapper",
            "team": "SF",
        },
        "2": {
            "player_id": "2",
            "position": "QB",
            "full_name": "Startable QB",
            "team": "SF",
        },
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
        "1": {
            "player_id": "1",
            "position": "WR",
            "full_name": "Has Crosswalk",
            "team": "SF",
        },
        "2": {
            "player_id": "2",
            "position": "WR",
            "full_name": "No Crosswalk",
            "team": "SF",
        },
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
    catalog = {
        "1": {
            "player_id": "1",
            "position": "WR",
            "full_name": "Owned Guy",
            "team": "SF",
        }
    }
    pool = build_free_agent_pool(
        [], catalog, roster_positions=["WR", "BN"], ownership_lookup={"1": 12.5}
    )
    assert pool.iloc[0]["player_owned_avg"] == 12.5


def test_ownership_lookup_missing_entry_is_nan():
    catalog = {
        "1": {"player_id": "1", "position": "WR", "full_name": "Unlisted", "team": "SF"}
    }
    pool = build_free_agent_pool(
        [], catalog, roster_positions=["WR", "BN"], ownership_lookup={"999": 50.0}
    )
    assert pd.isna(pool.iloc[0]["player_owned_avg"])


def test_defense_player_ids_use_team_abbreviations():
    # No ``team`` key: a DEF entry falls back to its team-code player_id for
    # the FFA-103 guard, so it survives either way.
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


# -------------------------
# FFA-103 -- teamless players are not free agents
# -------------------------


def test_toy_example_teamless_active_qb_excluded(toy_catalog, toy_rosters):
    pool = build_free_agent_pool(
        toy_rosters, toy_catalog, roster_positions=["QB", "BN"]
    )
    assert "6" not in set(pool["player_id"])


@pytest.mark.parametrize(
    "team_entry", [{"team": None}, {"team": ""}, {"team": "  "}, {}]
)
def test_teamless_free_agent_excluded_by_default(team_entry):
    catalog = {
        "1": {"player_id": "1", "position": "WR", "status": "Active", **team_entry},
        "2": {"player_id": "2", "position": "WR", "status": "Active", "team": "SEA"},
    }
    pool = build_free_agent_pool([], catalog, roster_positions=["WR", "BN"])
    assert set(pool["player_id"]) == {"2"}


def test_require_nfl_team_false_restores_teamless_players(toy_catalog, toy_rosters):
    pool = build_free_agent_pool(
        toy_rosters, toy_catalog, roster_positions=["QB", "BN"], require_nfl_team=False
    )
    # "4" is still excluded by status; only the team guard is lifted.
    assert set(pool["player_id"]) == {"3", "6"}


def test_defense_with_team_code_survives_the_guard():
    catalog = {
        "SEA": {
            "player_id": "SEA",
            "position": "DEF",
            "team": "SEA",
            "first_name": "Seattle",
            "last_name": "Seahawks",
        },
        "KC": {"player_id": "KC", "position": "DEF", "team": None},
    }
    pool = build_free_agent_pool([], catalog, roster_positions=["DEF", "BN"])
    assert set(pool["player_id"]) == {"SEA", "KC"}
    # The fallback is for the guard only; the row keeps the catalog's team.
    assert pd.isna(pool.set_index("player_id").loc["KC", "team"])


def test_has_nfl_team():
    assert has_nfl_team("1", {"position": "QB", "team": "SEA"}) is True
    assert has_nfl_team("1", {"position": "QB", "team": None}) is False
    assert has_nfl_team("1", {"position": "QB", "team": ""}) is False
    assert has_nfl_team("1", {"position": "QB"}) is False
    assert has_nfl_team("SF", {"position": "DEF"}) is True
    assert has_nfl_team("", {"position": "DEF"}) is False


# -------------------------
# roster_id_by_player / catalog_display_name
# -------------------------


def test_roster_id_by_player_covers_every_key_and_skips_empty_slot():
    raw_rosters = [
        {
            "roster_id": 1,
            "players": ["1", "2"],
            "starters": ["1", "0"],
            "reserve": ["2"],
        },
        {"roster_id": 2, "players": ["3"], "starters": ["0"], "taxi": ["4"]},
    ]
    assert roster_id_by_player(raw_rosters) == {"1": 1, "2": 1, "3": 2, "4": 2}


def test_roster_id_by_player_first_roster_wins_on_duplicate():
    raw_rosters = [
        {"roster_id": 7, "players": ["1"]},
        {"roster_id": 3, "players": ["1"]},
    ]
    assert roster_id_by_player(raw_rosters) == {"1": 7}


def test_catalog_display_name_falls_back_to_first_and_last():
    assert catalog_display_name({"full_name": "Josh Allen"}) == "Josh Allen"
    assert (
        catalog_display_name({"first_name": "Houston", "last_name": "Texans"})
        == "Houston Texans"
    )
    assert catalog_display_name({}) is None


# -------------------------
# build_player_universe (FFA-109)
# -------------------------


def test_universe_toy_example_matches_docstring(toy_catalog, toy_rosters):
    universe = build_player_universe(
        toy_rosters, toy_catalog, roster_positions=["QB", "BN"]
    )

    assert list(universe.columns) == PLAYER_UNIVERSE_COLUMNS
    assert list(universe["player_id"]) == ["1", "2", "3"]
    by_id = universe.set_index("player_id")
    assert by_id.loc["1", "is_rostered"] and by_id.loc["1", "roster_id"] == 1
    assert by_id.loc["2", "is_rostered"] and by_id.loc["2", "roster_id"] == 2
    assert not by_id.loc["3", "is_rostered"] and pd.isna(by_id.loc["3", "roster_id"])
    assert universe["is_rostered"].dtype == bool
    assert str(universe["roster_id"].dtype) == "Int64"


def test_universe_keeps_rostered_players_regardless_of_status_team_or_position():
    # The measured A.J. Brown / Tyreek Hill cases: rostered, but Sleeper
    # marks one Inactive (NFL IR) and the other has no NFL team.
    catalog = {
        "1": {
            "player_id": "1",
            "full_name": "IR Star",
            "position": "WR",
            "team": "PHI",
            "status": "Inactive",
        },
        "2": {
            "player_id": "2",
            "full_name": "Released Vet",
            "position": "WR",
            "team": None,
            "status": "Active",
        },
        "3": {"player_id": "3", "full_name": "Punter", "position": "P", "team": "SF"},
    }
    raw_rosters = [
        {"roster_id": 4, "players": ["1", "2", "3"], "reserve": ["1"]},
    ]
    universe = build_player_universe(raw_rosters, catalog, roster_positions=["WR"])

    assert set(universe["player_id"]) == {"1", "2", "3"}
    assert universe["is_rostered"].all()
    assert set(universe["roster_id"]) == {4}
    # build_free_agent_pool([], ...) -- the old population -- drops two of them.
    old_population = build_free_agent_pool([], catalog, roster_positions=["WR"])
    assert set(old_population["player_id"]) == set()


def test_universe_free_agent_rows_match_build_free_agent_pool(toy_catalog, toy_rosters):
    universe = build_player_universe(
        toy_rosters, toy_catalog, roster_positions=["QB", "RB", "BN"]
    )
    pool = build_free_agent_pool(
        toy_rosters, toy_catalog, roster_positions=["QB", "RB", "BN"]
    )
    free_agents = universe[~universe["is_rostered"]][FREE_AGENT_POOL_COLUMNS]
    pd.testing.assert_frame_equal(
        free_agents.reset_index(drop=True), pool.reset_index(drop=True)
    )


def test_universe_covers_kickers_and_defenses_the_league_starts():
    catalog = {
        "10": {
            "player_id": "10",
            "full_name": "Free K",
            "position": "K",
            "team": "DAL",
        },
        "HOU": {
            "player_id": "HOU",
            "position": "DEF",
            "team": "HOU",
            "first_name": "Houston",
            "last_name": "Texans",
        },
        "NE": {
            "player_id": "NE",
            "position": "DEF",
            "team": "NE",
            "first_name": "New England",
            "last_name": "Patriots",
        },
    }
    raw_rosters = [{"roster_id": 1, "players": ["NE"], "starters": ["NE"]}]

    universe = build_player_universe(raw_rosters, catalog, ROSTER_POSITIONS)
    by_id = universe.set_index("player_id")
    assert set(universe["player_id"]) == {"10", "HOU", "NE"}
    assert by_id.loc["HOU", "full_name"] == "Houston Texans"
    assert by_id.loc["NE", "is_rostered"] and by_id.loc["NE", "roster_id"] == 1

    # A league with no K or DEF slot has no K or DEF free agents -- but a
    # rostered defense is still accounted for.
    no_k_def = build_player_universe(raw_rosters, catalog, ["QB", "BN"])
    assert set(no_k_def["player_id"]) == {"NE"}


def test_universe_rostered_id_missing_from_catalog_gets_a_row():
    crosswalk = pd.DataFrame(
        [
            {
                "sleeper_player_id": "900",
                "gsis_id": "00-0000900",
                "full_name": "Brand New Rookie",
                "position": "RB",
                "team": "DET",
            }
        ],
        columns=CROSSWALK_COLUMNS,
    )
    raw_rosters = [
        {"roster_id": 5, "players": ["900", "901", "JAX"], "starters": ["0"]}
    ]

    universe = build_player_universe(
        raw_rosters, {}, ROSTER_POSITIONS, crosswalk=crosswalk
    )
    by_id = universe.set_index("player_id")

    # Sorted order; the "0" empty-slot placeholder never becomes a row.
    assert list(universe["player_id"]) == ["900", "901", "JAX"]
    assert by_id.loc["900", "full_name"] == "Brand New Rookie"
    assert by_id.loc["900", "gsis_id"] == "00-0000900"
    assert bool(by_id.loc["900", "has_crosswalk"]) is True
    assert pd.isna(by_id.loc["901", "position"])
    assert bool(by_id.loc["901", "has_crosswalk"]) is False
    assert by_id.loc["JAX", "position"] == "DEF"
    assert by_id.loc["JAX", "team"] == "JAX"
    assert universe["is_rostered"].all()
    assert set(universe["roster_id"]) == {5}


def test_universe_fills_crosswalk_and_ownership_for_rostered_players():
    catalog = {
        "1": {"player_id": "1", "full_name": "A", "position": "QB", "team": "SEA"}
    }
    crosswalk = pd.DataFrame(
        [
            {
                "sleeper_player_id": "1",
                "gsis_id": "00-1",
                "full_name": "A",
                "position": "QB",
                "team": "SEA",
            }
        ],
        columns=CROSSWALK_COLUMNS,
    )
    universe = build_player_universe(
        [{"roster_id": 1, "players": ["1"]}],
        catalog,
        ["QB"],
        crosswalk=crosswalk,
        ownership_lookup={"1": 99.0},
    )
    row = universe.iloc[0]
    assert row["gsis_id"] == "00-1"
    assert bool(row["has_crosswalk"]) is True
    assert row["player_owned_avg"] == 99.0


def test_universe_empty_inputs_return_shaped_frame():
    universe = build_player_universe([], {}, ["QB"])
    assert universe.empty
    assert list(universe.columns) == PLAYER_UNIVERSE_COLUMNS
    assert universe["is_rostered"].dtype == bool
    assert str(universe["roster_id"].dtype) == "Int64"

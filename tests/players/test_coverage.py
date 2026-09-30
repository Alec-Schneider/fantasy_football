"""Tests for the forward and reverse player-coverage audits (FFA-109).

Hand-built catalog/roster dicts and tiny raw-shape nflverse frames only -- no
HTTP -- so every ``coverage_reason`` and every summed point can be checked by
hand against the module docstring.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.players.coverage import (
    COVERAGE_REASONS,
    EXCLUDED_REASONS,
    FORWARD_AUDIT_COLUMNS,
    REVERSE_AUDIT_COLUMNS,
    build_forward_coverage_audit,
    build_reverse_coverage_audit,
)
from fantasy_analyzer.players.crosswalk import CROSSWALK_COLUMNS

SEASON = 2026


def _stat_row(gsis_id, name, position, team, season, week, **stats):
    """One raw-shape nflverse player-week row."""
    row = {
        "player_id": gsis_id,
        "player_name": "abbrev",
        "player_display_name": name,
        "position": position,
        "team": team,
        "season": season,
        "week": week,
        "season_type": "REG",
    }
    row.update(stats)
    return row


def _crosswalk(pairs: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            [sleeper_id, gsis_id, None, None, None]
            for sleeper_id, gsis_id in pairs.items()
        ],
        columns=CROSSWALK_COLUMNS,
    )


# -------------------------
# Forward audit -- the module docstring's toy example
# -------------------------


@pytest.fixture
def toy_catalog() -> dict:
    return {
        "1": {"player_id": "1", "full_name": "Ok QB", "position": "QB", "team": "SEA"},
        "2": {
            "player_id": "2",
            "full_name": "IR QB",
            "position": "QB",
            "team": "KC",
            "status": "Inactive",
            "injury_status": "IR",
        },
        "3": {
            "player_id": "3",
            "full_name": "Unsigned QB",
            "position": "QB",
            "team": None,
            "status": "Active",
        },
        "4": {
            "player_id": "4",
            "full_name": "Prior QB",
            "position": "QB",
            "team": "CIN",
        },
        "SEA": {
            "player_id": "SEA",
            "position": "DEF",
            "team": "SEA",
            "first_name": "Seattle",
            "last_name": "Seahawks",
        },
    }


@pytest.fixture
def toy_rosters() -> list[dict]:
    return [
        {"roster_id": 1, "players": ["1"], "starters": ["1"]},
        {"roster_id": 2, "players": ["2"], "reserve": ["2"]},
    ]


@pytest.fixture
def toy_stats() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _stat_row("G1", "Ok QB", "QB", "SEA", SEASON, 1, attempts=30),
            _stat_row("G4", "Prior QB", "QB", "CIN", SEASON - 1, 5, attempts=20),
        ]
    )


def _toy_audit(toy_catalog, toy_rosters, toy_stats, roster_positions=("QB", "BN")):
    return build_forward_coverage_audit(
        toy_catalog,
        toy_rosters,
        list(roster_positions),
        _crosswalk({"1": "G1", "4": "G4"}),
        toy_stats,
        SEASON,
    )


def test_forward_toy_example_matches_docstring(toy_catalog, toy_rosters, toy_stats):
    audit = _toy_audit(toy_catalog, toy_rosters, toy_stats)

    assert list(audit.columns) == FORWARD_AUDIT_COLUMNS
    reasons = dict(zip(audit["sleeper_player_id"], audit["coverage_reason"]))
    assert reasons == {
        "1": "ok",
        "2": "no_crosswalk",
        "3": "no_nfl_team",
        "4": "crosswalk_but_no_stats_yet",
        "SEA": "team_unit",
    }


def test_forward_in_universe_and_roster_columns(toy_catalog, toy_rosters, toy_stats):
    audit = _toy_audit(toy_catalog, toy_rosters, toy_stats).set_index(
        "sleeper_player_id"
    )

    assert audit.loc["1", "is_rostered"] and audit.loc["1", "roster_id"] == 1
    assert audit.loc["2", "is_rostered"] and audit.loc["2", "roster_id"] == 2
    assert audit.loc["2", "status"] == "Inactive"
    assert audit.loc["2", "injury_status"] == "IR"
    assert not audit.loc["3", "in_universe"]
    assert audit.loc["4", "in_universe"]
    # The league starts no DEF, so the defense is out of the universe but
    # still a team unit, not a failure.
    assert not audit.loc["SEA", "in_universe"]
    assert audit.loc["SEA", "full_name"] == "Seattle Seahawks"
    assert str(audit["roster_id"].dtype) == "Int64"


def test_forward_stats_columns(toy_catalog, toy_rosters, toy_stats):
    audit = _toy_audit(toy_catalog, toy_rosters, toy_stats).set_index(
        "sleeper_player_id"
    )

    assert audit.loc["1", "gsis_id"] == "G1"
    assert audit.loc["1", "has_current_season_stats"]
    assert audit.loc["1", "current_season_games"] == 1
    assert not audit.loc["4", "has_current_season_stats"]
    assert audit.loc["4", "has_prior_season_stats"]
    assert audit.loc["4", "prior_season_games"] == 1
    assert pd.isna(audit.loc["2", "gsis_id"])
    assert audit["current_season_games"].dtype == "int64"


def test_forward_every_reason_is_declared_and_exclusions_are_out_of_universe(
    toy_catalog, toy_rosters, toy_stats
):
    audit = _toy_audit(toy_catalog, toy_rosters, toy_stats)

    assert set(audit["coverage_reason"]) <= set(COVERAGE_REASONS)
    excluded = audit[audit["coverage_reason"].isin(EXCLUDED_REASONS)]
    assert not excluded["in_universe"].any()


def test_forward_free_agent_exclusion_reasons_in_precedence_order():
    catalog = {
        # RB in a QB-only league, retired and teamless: position wins.
        "1": {"player_id": "1", "position": "RB", "status": "Retired", "team": None},
        # Retired and teamless QB: status wins over team.
        "2": {"player_id": "2", "position": "QB", "status": "Retired", "team": None},
        "3": {"player_id": "3", "position": "QB", "status": "Active", "team": None},
    }
    audit = build_forward_coverage_audit(
        catalog, [], ["QB"], _crosswalk({}), pd.DataFrame(), SEASON
    )

    assert list(audit["coverage_reason"]) == [
        "position_not_started",
        "excluded_status",
        "no_nfl_team",
    ]


def test_forward_rostered_player_never_gets_an_exclusion_reason():
    catalog = {
        "1": {"player_id": "1", "position": "WR", "status": "Inactive", "team": None},
    }
    audit = build_forward_coverage_audit(
        catalog,
        [{"roster_id": 3, "players": ["1"]}],
        ["QB"],
        _crosswalk({"1": "G1"}),
        pd.DataFrame(),
        SEASON,
    )

    row = audit.iloc[0]
    assert row["in_universe"]
    assert row["coverage_reason"] == "crosswalk_no_stats_any_season"


def test_forward_includes_rostered_ids_outside_audit_positions_and_catalog():
    catalog = {"1": {"player_id": "1", "position": "P", "team": "SF"}}
    audit = build_forward_coverage_audit(
        catalog,
        [{"roster_id": 1, "players": ["1", "999"]}],
        ["QB"],
        _crosswalk({}),
        pd.DataFrame(),
        SEASON,
    )

    reasons = dict(zip(audit["sleeper_player_id"], audit["coverage_reason"]))
    assert reasons == {"1": "no_crosswalk", "999": "not_in_catalog"}
    assert audit["in_universe"].all()


def test_forward_counts_distinct_regular_season_weeks_only():
    catalog = {"1": {"player_id": "1", "position": "WR", "team": "SF"}}
    stats = pd.DataFrame(
        [
            _stat_row("G1", "A", "WR", "SF", SEASON, 1, targets=1),
            _stat_row("G1", "A", "WR", "SF", SEASON, 1, targets=1),  # duplicate
            _stat_row("G1", "A", "WR", "SF", SEASON, 2, targets=1),
            {
                **_stat_row("G1", "A", "WR", "SF", SEASON, 19, targets=1),
                "season_type": "POST",
            },
        ]
    )
    audit = build_forward_coverage_audit(
        catalog, [], ["WR"], _crosswalk({"1": "G1"}), stats, SEASON
    )

    assert audit.iloc[0]["current_season_games"] == 2


def test_forward_missing_stats_frame_is_not_an_error():
    catalog = {"1": {"player_id": "1", "position": "WR", "team": "SF"}}
    audit = build_forward_coverage_audit(
        catalog, [], ["WR"], _crosswalk({"1": "G1"}), None, SEASON
    )

    assert audit.iloc[0]["coverage_reason"] == "crosswalk_no_stats_any_season"


# -------------------------
# Reverse audit
# -------------------------

#: Hand-checkable scoring: 0.04/pass yd, 1/rec, 0.1/rec yd, 1/PAT, 3/30-39 FG.
SCORING = {"pass_yd": 0.04, "rec": 1.0, "rec_yd": 0.1, "xpm": 1.0, "fgm_30_39": 3.0}


@pytest.fixture
def reverse_stats() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # Mapped QB: 250 * 0.04 = 10.0 points.
            _stat_row(
                "G1",
                "Mapped QB",
                "QB",
                "SEA",
                SEASON,
                1,
                attempts=30,
                passing_yards=250,
            ),
            # Unmapped WR: week 1 = 4 + 5.0 = 9.0; week 2 inactive (0 points).
            _stat_row(
                "G5",
                "Orphan WR",
                "WR",
                "BUF",
                SEASON,
                1,
                targets=5,
                receptions=4,
                receiving_yards=50,
            ),
            _stat_row("G5", "Orphan WR", "WR", "BUF", SEASON, 2, targets=0),
            # Same player: prior season and a playoff row are both ignored.
            _stat_row("G5", "Orphan WR", "WR", "BUF", SEASON - 1, 3, receptions=9),
            {
                **_stat_row("G5", "Orphan WR", "WR", "BUF", SEASON, 19, receptions=9),
                "season_type": "POST",
            },
            # Unmapped TE tied with the WR on 9.0 points.
            _stat_row(
                "G8",
                "Orphan TE",
                "TE",
                "MIA",
                SEASON,
                1,
                targets=3,
                receptions=4,
                receiving_yards=50,
            ),
            # Unmapped K: 2 PAT + one 30-39 FG = 5.0 points, 3 kick attempts.
            _stat_row(
                "G6", "Orphan K", "K", "GB", SEASON, 1, pat_made=2, fg_made_30_39=1
            ),
            # Unmapped linebacker: not a fantasy position, never listed.
            _stat_row("G7", "Some LB", "LB", "GB", SEASON, 1),
            # nflverse's team placeholder row: no gsis id, no position.
            _stat_row(None, None, None, "GB", SEASON, 1),
        ]
    )


def test_reverse_toy_example(reverse_stats):
    audit = build_reverse_coverage_audit(
        reverse_stats, _crosswalk({"1": "G1"}), SEASON, SCORING
    )

    assert list(audit.columns) == REVERSE_AUDIT_COLUMNS
    assert list(audit["gsis_id"]) == ["G5", "G8", "G6"]
    by_gsis = audit.set_index("gsis_id")
    assert by_gsis.loc["G5", "fantasy_points"] == pytest.approx(9.0)
    assert by_gsis.loc["G5", "player_weeks"] == 2
    assert by_gsis.loc["G5", "active_player_weeks"] == 1
    assert by_gsis.loc["G5", "targets"] == 5
    assert by_gsis.loc["G6", "fantasy_points"] == pytest.approx(5.0)
    assert by_gsis.loc["G6", "kick_attempts"] == 3
    assert by_gsis.loc["G6", "position"] == "K"


def test_reverse_points_rank_is_over_all_players_and_ties_share_rank(reverse_stats):
    audit = build_reverse_coverage_audit(
        reverse_stats, _crosswalk({"1": "G1"}), SEASON, SCORING
    ).set_index("gsis_id")

    # The mapped QB (10.0) is rank 1 even though he is not listed.
    assert audit.loc["G5", "points_rank"] == 2
    assert audit.loc["G8", "points_rank"] == 2
    assert audit.loc["G6", "points_rank"] == 4


def test_reverse_everything_mapped_returns_empty(reverse_stats):
    crosswalk = _crosswalk({"1": "G1", "5": "G5", "6": "G6", "8": "G8"})

    audit = build_reverse_coverage_audit(reverse_stats, crosswalk, SEASON, SCORING)

    assert audit.empty
    assert list(audit.columns) == REVERSE_AUDIT_COLUMNS


def test_reverse_empty_or_missing_stats():
    assert build_reverse_coverage_audit(
        pd.DataFrame(), _crosswalk({}), SEASON, SCORING
    ).empty
    assert build_reverse_coverage_audit(None, _crosswalk({}), SEASON, SCORING).empty


def test_reverse_accepts_provider_normalized_shape():
    normalized = pd.DataFrame(
        [
            {
                "season": SEASON,
                "week": 1,
                "sleeper_player_id": None,
                "gsis_id": "G5",
                "player_name": "Orphan WR",
                "position": "WR",
                "nfl_team": "BUF",
                "targets": 5,
                "receptions": 4,
                "receiving_yards": float("nan"),
            }
        ]
    )

    audit = build_reverse_coverage_audit(normalized, _crosswalk({}), SEASON, SCORING)

    # A NaN stat contributes zero, per scoring.py's missing-value convention.
    assert audit.iloc[0]["fantasy_points"] == pytest.approx(4.0)
    assert audit.iloc[0]["player_name"] == "Orphan WR"

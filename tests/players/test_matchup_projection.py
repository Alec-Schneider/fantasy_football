"""Tests for one-side matchup projection (FFA-113). No network."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from fantasy_analyzer.players.matchup_projection import (
    MATCHUP_SLOT_COLUMNS,
    build_matchup_side,
    build_position_edges,
)
from fantasy_analyzer.players.opponent_strength import nfl_game_states

ROSTER = ["QB", "RB", "WR", "FLEX", "DEF", "BN", "BN", "IR"]

# Week 4: Thursday CLE-PIT (final), Sunday 1 pm BAL-TEN and DAL-NYG.
GAMES = pd.DataFrame(
    [
        {"season": 2026, "game_type": "REG", "week": 4, "home_team": "CLE",
         "away_team": "PIT", "gameday": "2026-10-01", "gametime": "20:15",
         "home_score": 27.0, "away_score": 24.0},
        {"season": 2026, "game_type": "REG", "week": 4, "home_team": "BAL",
         "away_team": "TEN", "gameday": "2026-10-04", "gametime": "13:00",
         "home_score": float("nan"), "away_score": float("nan")},
        {"season": 2026, "game_type": "REG", "week": 4, "home_team": "DAL",
         "away_team": "NYG", "gameday": "2026-10-04", "gametime": "13:00",
         "home_score": float("nan"), "away_score": float("nan")},
    ]
)

PROJECTIONS = pd.DataFrame(
    [
        {"player_id": "q1", "full_name": "Quinn", "position": "QB", "team": "BAL",
         "projected_ppg": 20.0, "ppg_to_date": 19.0},
        {"player_id": "r1", "full_name": "Rex", "position": "RB", "team": "PIT",
         "projected_ppg": 12.0},
        {"player_id": "w1", "full_name": "Wes", "position": "WR", "team": "TEN",
         "projected_ppg": 10.0},
        {"player_id": "f1", "full_name": "Flex", "position": "RB", "team": "DAL",
         "projected_ppg": 8.0},
        {"player_id": "b1", "full_name": "Ben", "position": "WR", "team": "DAL",
         "projected_ppg": 6.0},
        {"player_id": "b2", "full_name": "Bo", "position": "WR", "team": "NYG",
         "projected_ppg": 9.0},
        {"player_id": "ir1", "full_name": "Ira", "position": "RB", "team": "BAL",
         "projected_ppg": 30.0},
    ]
)

CATALOG = {
    "q1": {"injury_status": None},
    "ir1": {"injury_status": "IR"},
    "PIT": {"position": "DEF", "team": "PIT", "first_name": "Pittsburgh",
            "last_name": "Steelers"},
    "n1": {"first_name": "No", "last_name": "Row", "position": "WR", "team": "TEN"},
}


PRE = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
# Before Thursday night nothing has a score yet.
PRE_GAMES = GAMES.assign(home_score=float("nan"), away_score=float("nan"))


def _states(now: datetime) -> dict:
    return nfl_game_states(PRE_GAMES if now == PRE else GAMES, 2026, 4, now)


SATURDAY = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


def _side(starters, projections=PROJECTIONS, catalog=CATALOG, live=None,
          now=SATURDAY, **kwargs):
    return build_matchup_side(
        starters, ["q1", "r1", "w1", "f1", "b1", "b2", "ir1"], ROSTER,
        projections, catalog, live or {}, _states(now), 4, **kwargs,
    )


def test_pre_kickoff_side_sums_projections() -> None:
    # 20 + 12 + 10 + 8 + (DEF "PIT": no projection row -> 0) = 50, 4 pending.
    side = _side(["q1", "r1", "w1", "f1", "PIT"], now=PRE)
    assert list(side.starters.columns) == MATCHUP_SLOT_COLUMNS
    assert side.projected_total == 50.0
    assert side.live_points_total == 0.0
    assert side.players_remaining == 4
    assert side.starters["actual_points"].isna().all()
    assert [a["reason"] for a in side.alerts] == ["No projection"]
    qb = side.starters.iloc[0]
    assert qb["nfl_opponent"] == "TEN" and qb["is_home"] == True  # noqa: E712
    assert qb["kickoff"] == "2026-10-04T13:00:00-04:00"
    assert qb["ppg_to_date"] == 19.0 and pd.isna(side.starters.iloc[1]["ppg_to_date"])


def test_mid_week_side_mixes_final_in_progress_and_scheduled() -> None:
    # Sunday 13:30 ET: PIT (RB r1) final with 15.5 live; BAL-TEN in progress
    # (QB q1 live 7.0, WR w1 live 3.0); DAL-NYG also in progress -> f1 live 0.
    # Make DAL scheduled instead by moving "now" to just after BAL-TEN only.
    games = GAMES.copy()
    games.loc[2, ["gameday", "gametime"]] = ["2026-10-04", "16:25"]
    states = nfl_game_states(
        games, 2026, 4, datetime(2026, 10, 4, 18, 0, tzinfo=timezone.utc)
    )
    side = build_matchup_side(
        ["q1", "r1", "w1", "f1", "PIT"], ["q1", "r1", "w1", "f1"], ROSTER,
        PROJECTIONS, CATALOG, {"r1": 15.5, "q1": 7.0, "w1": 3.0, "PIT": 9.0},
        states, 4,
    )
    # expected: q1 7.0 + r1 15.5 + w1 3.0 + f1 8.0 (pending) + PIT 9.0 = 42.5
    assert side.projected_total == 42.5
    assert side.live_points_total == 34.5
    assert side.players_remaining == 1
    assert list(side.starters["game_state"]) == [
        "in_progress", "final", "in_progress", "scheduled", "final",
    ]
    assert side.alerts == []  # kicked-off starters raise nothing


def test_empty_slot_and_trailing_missing_slot() -> None:
    side = _side(["q1", "0", "w1"], now=PRE)
    # slots: QB RB WR FLEX DEF -> RB "0", FLEX/DEF missing.
    assert side.projected_total == 30.0
    assert [(a["slot"], a["reason"]) for a in side.alerts] == [
        ("RB", "Empty slot"), ("FLEX", "Empty slot"), ("DEF", "Empty slot"),
    ]
    empty = side.starters.iloc[1]
    assert empty["player_id"] is None and empty["game_state"] is None
    assert empty["expected_points"] == 0.0 and not empty["pending"]


def test_out_starter_is_zero_and_alerted() -> None:
    catalog = {**CATALOG, "w1": {"injury_status": "Out", "injury_body_part": "Knee"}}
    side = _side(["q1", "r1", "w1", "f1", "PIT"], catalog=catalog, now=PRE)
    wr = side.starters.iloc[2]
    assert wr["expected_points"] == 0.0 and not wr["available"]
    assert wr["unavailable_reason"] == "Out" and wr["injury_body_part"] == "Knee"
    assert not wr["pending"]
    assert ("WR", "Out") in [(a["slot"], a["reason"]) for a in side.alerts]
    assert side.players_remaining == 3  # q1, r1, f1 (PIT DEF has no projection)


def test_questionable_starter_is_pending_and_flagged() -> None:
    catalog = {**CATALOG, "q1": {"injury_status": "Questionable"}}
    side = _side(["q1", "r1", "w1", "f1", "PIT"], catalog=catalog, now=PRE)
    assert side.starters.iloc[0]["pending"]
    assert ("QB", "Questionable") in [(a["slot"], a["reason"]) for a in side.alerts]


def test_bye_starter_from_game_states() -> None:
    # KC has no game in the schedule -> bye.
    projections = pd.concat(
        [PROJECTIONS, pd.DataFrame([{"player_id": "k1", "full_name": "Kel",
                                     "position": "WR", "team": "KC",
                                     "projected_ppg": 14.0}])],
        ignore_index=True,
    )
    side = _side(["q1", "r1", "k1", "f1", "PIT"], projections=projections, now=PRE)
    row = side.starters.iloc[2]
    assert row["game_state"] == "bye" and row["unavailable_reason"] == "Bye"
    assert row["expected_points"] == 0.0
    assert ("WR", "Bye") in [(a["slot"], a["reason"]) for a in side.alerts]


def test_empty_game_states_falls_back_to_byes_mapping() -> None:
    side = build_matchup_side(
        ["q1", "r1", "w1", "f1", "PIT"], [], ROSTER, PROJECTIONS, CATALOG, {},
        {}, 4, byes={"TEN": 4},
    )
    assert side.starters["game_state"].isna().all()
    wr = side.starters.iloc[2]
    assert wr["unavailable_reason"] == "Bye" and wr["expected_points"] == 0.0
    assert side.starters.iloc[0]["expected_points"] == 20.0


def test_starter_without_projection_row_is_labelled_from_catalog() -> None:
    side = _side(["q1", "r1", "n1", "f1", "PIT"], now=PRE)
    row = side.starters.iloc[2]
    assert row["full_name"] == "No Row" and row["position"] == "WR"
    assert row["team"] == "TEN" and row["projection_missing"]
    assert row["expected_points"] == 0.0 and not row["pending"]
    assert ("WR", "No projection") in [(a["slot"], a["reason"]) for a in side.alerts]


def test_defense_id_is_labelled_and_uses_its_team() -> None:
    projections = pd.concat(
        [PROJECTIONS, pd.DataFrame([{"player_id": "PIT", "position": "DEF",
                                     "team": "PIT", "full_name": "Steelers",
                                     "projected_ppg": 7.0}])],
        ignore_index=True,
    )
    side = _side(["q1", "r1", "w1", "f1", "PIT"], projections=projections, now=PRE)
    assert side.starters.iloc[4]["expected_points"] == 7.0
    # Without a projection row the catalog supplies the label and the team.
    bare = _side(["q1", "r1", "w1", "f1", "PIT"], now=PRE).starters.iloc[4]
    assert bare["full_name"] == "Pittsburgh Steelers"
    assert bare["position"] == "DEF" and bare["nfl_opponent"] == "CLE"


def test_bench_has_reserve_slot_and_projection_sort() -> None:
    side = _side(["q1", "r1", "w1", "f1", "PIT"], now=PRE, reserve=["ir1"])
    assert list(side.bench["player_id"]) == ["ir1", "b2", "b1"]
    assert list(side.bench["slot"]) == ["IR", "BN", "BN"]
    ir = side.bench.iloc[0]
    assert ir["unavailable_reason"] == "IR" and ir["expected_points"] == 0.0
    assert side.projected_total == 50.0  # bench is never summed


def test_position_edges_ties_and_one_sided_groups() -> None:
    def starters(rows):
        return pd.DataFrame(rows, columns=["slot", "expected_points"])

    mine = starters([("QB", 18.0), ("RB", 10.0), ("RB", 5.0), ("WR", 7.0)])
    theirs = starters([("QB", 21.0), ("RB", 15.0), ("WR", 7.0), ("K", 8.0)])
    edges = build_position_edges(mine, theirs)
    assert list(edges["group"]) == ["QB", "RB", "WR", "K"]
    assert list(edges["me"]) == [18.0, 15.0, 7.0, 0.0]
    assert list(edges["opponent"]) == [21.0, 15.0, 7.0, 8.0]
    assert list(edges["edge"]) == [-3.0, 0.0, 0.0, -8.0]

"""Tests for ``scripts/build_dashboard.py``'s pure helpers (FFA-107, FFA-108).

``scripts/`` is not a package, so -- like ``tests/test_draft_report_script.py``
-- this file puts it on ``sys.path`` before importing the script. Only the
helpers that take plain frames and dicts are tested here; ``build_bundle``
itself talks to Sleeper and nflverse and is exercised by a real build, not
by unit tests.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_dashboard  # noqa: E402

from fantasy_analyzer.players.opponent_strength import (  # noqa: E402
    completed_nfl_weeks,
)

# --------------------------------------------------------------------------
# _completed_weeks (FFA-108)
# --------------------------------------------------------------------------


def _pairing(week, points_1, points_2, roster_2_id=2):
    return {
        "week": week,
        "roster_1_id": 1,
        "roster_2_id": roster_2_id,
        "points_1": points_1,
        "points_2": points_2,
    }


def _nfl_week(week, games, scored):
    return [
        {
            "season": 2026,
            "game_type": "REG",
            "week": week,
            "home_team": f"H{index}",
            "away_team": f"A{index}",
            "home_score": 21.0 if index < scored else None,
            "away_score": 14.0 if index < scored else None,
        }
        for index in range(games)
    ]


def test_week_waiting_on_monday_night_is_not_complete() -> None:
    """The 2026-09-21 failure, end to end.

    Every fantasy pairing in week 2 has non-zero points on both sides --
    the old test passed it -- but only 15 of 16 NFL games are final.
    """
    matchups = pd.DataFrame(
        [_pairing(1, 101.2, 99.8), _pairing(2, 88.4, 92.1), _pairing(3, 0.0, 0.0)]
    )
    games = pd.DataFrame(
        _nfl_week(1, 16, 16) + _nfl_week(2, 16, 15) + _nfl_week(3, 16, 0)
    )
    assert build_dashboard._completed_weeks(
        matchups, completed_nfl_weeks(games, 2026)
    ) == [1]


def test_week_complete_once_both_conditions_hold() -> None:
    matchups = pd.DataFrame([_pairing(1, 101.2, 99.8), _pairing(2, 88.4, 92.1)])
    assert build_dashboard._completed_weeks(matchups, [1, 2]) == [1, 2]


def test_nfl_complete_but_a_pairing_still_at_zero_is_not_complete() -> None:
    matchups = pd.DataFrame([_pairing(1, 101.2, 0.0)])
    assert build_dashboard._completed_weeks(matchups, [1]) == []


def test_byes_only_week_and_empty_inputs() -> None:
    """A week with no contested pairing, or no NFL signal, is never complete."""
    matchups = pd.DataFrame([_pairing(1, 101.2, None, roster_2_id=None)])
    assert build_dashboard._completed_weeks(matchups, [1]) == []
    assert build_dashboard._completed_weeks(pd.DataFrame(), [1]) == []
    assert (
        build_dashboard._completed_weeks(pd.DataFrame([_pairing(1, 90, 80)]), []) == []
    )


# --------------------------------------------------------------------------
# unprojectable_positions
# --------------------------------------------------------------------------


def test_unprojectable_positions_follow_the_projection_frame() -> None:
    none = pd.DataFrame(
        {"position": ["QB", "K"], "projected_ppg": [20.0, float("nan")]}
    )
    assert build_dashboard.unprojectable_positions(none) == {"K", "DEF", "DST"}

    kicker = pd.DataFrame({"position": ["QB", "K"], "projected_ppg": [20.0, 8.0]})
    assert build_dashboard.unprojectable_positions(kicker) == {"DEF", "DST"}

    # Either spelling of a team defense brings the DEF slot back.
    dst = pd.DataFrame({"position": ["DST"], "projected_ppg": [7.0]})
    assert build_dashboard.unprojectable_positions(dst) == {"K"}

    assert (
        build_dashboard.unprojectable_positions(pd.DataFrame())
        == build_dashboard.UNPROJECTABLE_POSITIONS
    )


# --------------------------------------------------------------------------
# _build_lineup (FFA-107)
# --------------------------------------------------------------------------

# Seven roster spots: K is a real spot, but no kicker is projected, so its
# slot is stripped from the solve.
ROSTER_POSITIONS = ["QB", "RB", "WR", "FLEX", "K", "BN", "BN"]


def _projection(player_id, position, ppg, team="KC"):
    return {
        "player_id": player_id,
        "full_name": f"P{player_id}",
        "position": position,
        "team": team,
        "projected_ppg": ppg,
        "games_to_date": 3.0,
        "ppg_to_date": ppg,
        "confidence_tier": "medium",
    }


PROJECTIONS = pd.DataFrame(
    [
        _projection("q1", "QB", 20.0),
        _projection("r1", "RB", 15.0),  # Out this week
        _projection("r2", "RB", 10.0),
        _projection("w1", "WR", 12.0, team="SEA"),  # SEA on bye in week 4
        _projection("w2", "WR", 8.0),
        _projection("b1", "WR", 3.0),
        _projection("ir1", "RB", 18.0),  # IR, in a reserve slot
        _projection("k1", "K", float("nan")),
    ]
)

# Seven held players fill seven spots; ir1 sits in reserve, outside them.
MY_ROSTER = {
    "players": ["q1", "r1", "r2", "w1", "w2", "b1", "k1", "ir1"],
    "starters": ["q1", "r1", "w1", "r2", "k1"],
    "reserve": ["ir1"],
}

CATALOG = {
    "r1": {"injury_status": "Out", "injury_body_part": "Ankle"},
    "ir1": {"injury_status": "IR", "injury_body_part": "Knee"},
}

BYES = {"SEA": 4, "KC": 10}

BOARD = pd.DataFrame(
    [
        {
            **_projection("f1", "WR", 14.0, team="DAL"),
            "board_rank": 1,
            "injury_status": None,
            "bye_week": None,
        },
        {
            **_projection("f2", "RB", 30.0, team="DAL"),
            "board_rank": 2,
            "injury_status": "IR",
            "bye_week": None,
        },
    ]
)


def _lineup(board=BOARD, projections=PROJECTIONS):
    return build_dashboard._build_lineup(
        ROSTER_POSITIONS, MY_ROSTER, projections, board, CATALOG, BYES, 4, 6
    )


def test_lineup_never_starts_out_or_bye_players() -> None:
    """Week 4: r1 is Out, w1 on bye, ir1 on IR.

    Available: q1, r2, w2, b1 -> QB q1, RB r2, WR w2, FLEX b1 = 41.0.
    """
    lineup = _lineup()
    starters = [row["player_id"] for row in lineup["recommended_starters"]]
    assert starters == ["q1", "r2", "w2", "b1"]  # slot order
    assert [row["slot"] for row in lineup["recommended_starters"]] == [
        "QB",
        "RB",
        "WR",
        "FLEX",
    ]
    assert lineup["projected_points"] == pytest.approx(41.0)

    unavailable = {row["player_id"]: row for row in lineup["unavailable"]}
    assert set(unavailable) == {"r1", "w1", "ir1"}
    assert unavailable["r1"]["unavailable_reason"] == "Out"
    assert unavailable["w1"]["unavailable_reason"] == "Bye"
    assert unavailable["ir1"]["in_reserve"] is True
    assert unavailable["r1"]["in_reserve"] is False


def test_lineup_strips_unprojected_kicker_slot() -> None:
    lineup = _lineup()
    assert lineup["excluded_positions"] == ["DEF", "DST", "K"]
    assert "K" not in lineup["projected_slots"]
    assert [entry["slot"] for entry in lineup["slot_order"]] == [
        "QB",
        "RB",
        "WR",
        "FLEX",
    ]


def test_lineup_starts_a_kicker_once_one_is_projected() -> None:
    projections = PROJECTIONS.copy()
    projections.loc[projections["player_id"] == "k1", "projected_ppg"] = 8.0
    lineup = _lineup(projections=projections)
    assert "K" in lineup["projected_slots"]
    assert lineup["slot_order"][-1] == {"slot": "K", "player_id": "k1"}
    assert lineup["projected_points"] == pytest.approx(49.0)


def test_moves_are_scored_over_the_rest_of_the_season() -> None:
    """Weeks 4-6; hand-computed in the module docstring's terms.

    Baseline: 41 / 57 / 57. The cheapest drop is b1 (worth 3.0 in week 4
    only) -- not r1 or w1, who are worth 0.0 in week 4 alone but 14.0 and
    8.0 over the horizon, and never ir1, who is in a reserve slot. Adding
    f1 (WR 14.0): 52 / 61 / 61 either way, +19.0 total.
    f2 is on IR, a long-term status, so he is not shortlisted at all.
    """
    lineup = _lineup()
    assert lineup["open_roster_spots"] == 0
    assert lineup["horizon"] == {"from_week": 4, "through_week": 6}

    moves = {row["player_id"]: row for row in lineup["add_drop"]}
    assert set(moves) == {"f1"}
    move = moves["f1"]
    assert move["best_drop_player_id"] == "b1"
    assert move["best_drop_marginal_value"] == pytest.approx(1.0)
    assert move["net_lineup_gain_total"] == pytest.approx(19.0)
    assert move["net_lineup_gain"] == pytest.approx(19.0 / 3)
    assert move["net_gain_this_week"] == pytest.approx(11.0)
    assert move["weeks_evaluated"] == 3
    # Board context rides along for the page.
    assert move["board_rank"] == 1


def test_lineup_with_no_projected_roster_or_empty_board() -> None:
    empty = build_dashboard._build_lineup(
        ROSTER_POSITIONS,
        {"players": ["nobody"]},
        PROJECTIONS,
        BOARD,
        CATALOG,
        BYES,
        4,
        6,
    )
    assert empty["recommended_starters"] == []
    assert empty["projected_points"] is None
    assert empty["open_roster_spots"] == 6

    no_board = _lineup(board=pd.DataFrame())
    assert no_board["add_drop"] == []
    assert len(no_board["recommended_starters"]) == 4


def test_unprojected_kicker_fills_his_slot_and_is_never_the_drop() -> None:
    """Some kicker is projected, so the K slot stays -- but not k1.

    The solve leaves K empty; the page fills it with k1 (display only, no
    points) rather than telling the manager to bench his only kicker, and
    the move search never offers k1 as the drop.
    """
    projections = pd.concat(
        [PROJECTIONS, pd.DataFrame([_projection("k9", "K", 9.0)])],
        ignore_index=True,
    )
    lineup = _lineup(projections=projections)
    assert lineup["slot_order"][-1] == {"slot": "K", "player_id": "k1"}
    kicker = lineup["recommended_starters"][-1]
    assert kicker["player_id"] == "k1"
    assert kicker["projection_missing"] is True
    assert lineup["projected_points"] == pytest.approx(41.0)
    assert all(row["best_drop_player_id"] != "k1" for row in lineup["add_drop"])


# --------------------------------------------------------------------------
# Phase 2: the player universe, K/DEF projections, full-universe valuation
# --------------------------------------------------------------------------


def _skill(player_id, position, ppg, **extra):
    return {
        "player_id": player_id,
        "full_name": f"P{player_id}",
        "position": position,
        "team": "KC",
        "remaining_games": 10.0,
        "projected_ppg": ppg,
        "projected_ros_points": ppg * 10.0 if ppg == ppg else float("nan"),
        **extra,
    }


def _kdef(player_id, position, ppg, week_points, team="KC"):
    return _skill(
        player_id,
        position,
        ppg,
        team=team,
        week_projected_points=week_points,
        week_opponent="LV",
        week_is_home=True,
        bye_week=9,
    )


def test_board_and_universe_projections_share_the_usage_model(monkeypatch) -> None:
    """FFA-111: the board and the lineup's projection get the same three inputs.

    Both package calls are stubbed to record their keyword arguments. q3 --
    no games and no prior season, FFA-104's population -- stays on the
    board: no display filter sits on top of the ranking any more.
    """
    calls: dict = {}

    def fake_board(pool, *args, **kwargs):
        calls["board"] = kwargs
        calls["pool"] = list(pool["player_id"])
        return pd.DataFrame(
            [
                _skill(
                    "q3",
                    "QB",
                    15.0,
                    waiver_rank=1,
                    points_above_replacement=-30.0,
                    prior_season_games=0.0,
                    games_to_date=0.0,
                )
            ]
        )

    def fake_projections(population, *args, **kwargs):
        calls["universe"] = kwargs
        calls["population"] = list(population["player_id"])
        return pd.DataFrame(
            [
                _skill("q1", "QB", 20.0),
                _skill("q2", "QB", 18.0),
                _skill("q3", "QB", 15.0),
            ]
        )

    monkeypatch.setattr(build_dashboard, "build_waiver_wire_rankings", fake_board)
    monkeypatch.setattr(
        build_dashboard, "build_free_agent_ros_projections", fake_projections
    )

    universe = pd.DataFrame(
        {
            "player_id": ["q1", "q2", "q3"],
            "full_name": ["Pq1", "Pq2", "Pq3"],
            "position": ["QB", "QB", "QB"],
            "team": ["KC", "KC", "KC"],
            "status": ["Active", "Active", "Active"],
            "gsis_id": ["g1", "g2", "g3"],
            "has_crosswalk": [True, True, True],
            "player_owned_avg": [None, None, None],
            "is_rostered": [True, True, False],
            "roster_id": pd.array([1, 2, None], dtype="Int64"),
        }
    )
    snapshot = SimpleNamespace(
        roster_positions=["QB", "BN"],
        league=SimpleNamespace(total_rosters=2),
        scoring_settings={"pass_td": 4.0},
    )
    usage_parameters = object()
    usage = pd.DataFrame({"season": [2026], "week": [3], "gsis_id": ["g3"]})

    board, valued = build_dashboard._build_waiver_board(
        snapshot,
        universe,
        pd.DataFrame(),
        {},
        pd.DataFrame(),
        2026,
        3,
        build_dashboard.ShrinkageParameters(n0_by_position={}, default_n0=2.0),
        pd.DataFrame(),
        usage_parameters=usage_parameters,
        usage=usage,
    )

    for call in ("board", "universe"):
        assert calls[call]["usage_parameters"] is usage_parameters
        assert calls[call]["scoring_settings"] is snapshot.scoring_settings
        assert calls[call]["usage"] is usage
    assert calls["pool"] == ["q3"]
    assert calls["population"] == ["q1", "q2", "q3"]
    assert list(board["player_id"]) == ["q3"]
    # The universe projection is what the lineup reads: q1/q2 are rostered.
    assert sorted(valued["player_id"]) == ["q1", "q2", "q3"]
    assert list(valued.loc[valued["is_rostered"], "player_id"]) == ["q1", "q2"]


UNIVERSE = pd.DataFrame(
    {
        "player_id": ["q1", "q2", "q3", "k1", "k2", "k3", "k4", "SEA", "DAL"],
        "position": ["QB", "QB", "QB", "K", "K", "K", "K", "DEF", "DEF"],
        "is_rostered": [True, True, False, True, True, False, False, False, False],
        "roster_id": pd.array(
            [1, 2, None, 1, 2, None, None, None, None], dtype="Int64"
        ),
    }
)


def test_projection_universe_takes_kdef_only_from_its_own_model() -> None:
    skill = pd.DataFrame(
        [
            _skill("q1", "QB", 20.0),
            _skill("q2", "QB", 18.0),
            _skill("q3", "QB", 15.0),
            # The skill model's kicker row must be discarded.
            _skill("k1", "K", 99.0),
        ]
    )
    kdef = pd.DataFrame(
        [
            _kdef("k1", "K", 9.0, 9.5),
            _kdef("k2", "K", 8.0, 7.0),
            _kdef("k3", "K", 8.0, 8.4),
            _kdef("SEA", "DEF", 6.0, 6.6, team="SEA"),
            # Not in the universe (e.g. an Inactive kicker): dropped.
            _kdef("k9", "K", 12.0, 12.0),
        ]
    )
    combined = build_dashboard._projection_universe(skill, kdef, UNIVERSE)
    by_id = combined.set_index("player_id")

    assert sorted(by_id.index) == ["SEA", "k1", "k2", "k3", "q1", "q2", "q3"]
    # k4 and DAL are in the universe but had no K/DEF row here: no row.
    assert by_id.loc["k1", "projected_ppg"] == 9.0
    assert by_id.loc["k1", "projection_source"] == "kicker_defense"
    assert by_id.loc["q1", "projection_source"] == "skill"
    # The lineup column: this week's number for K/DEF, the rate otherwise.
    assert by_id.loc["k2", build_dashboard.LINEUP_PPG_COLUMN] == 7.0
    assert by_id.loc["q1", build_dashboard.LINEUP_PPG_COLUMN] == 20.0
    assert bool(by_id.loc["k1", "is_rostered"]) is True
    assert bool(by_id.loc["k3", "is_rostered"]) is False
    assert by_id.loc["k1", "roster_id"] == 1


def _valued():
    skill = pd.DataFrame(
        [_skill("q1", "QB", 20.0), _skill("q2", "QB", 18.0), _skill("q3", "QB", 15.0)]
    )
    kdef = pd.DataFrame(
        [
            _kdef("k1", "K", 9.0, 9.5),
            _kdef("k2", "K", 8.0, 7.0),
            _kdef("k3", "K", 8.0, 8.4),
            _kdef("k4", "K", float("nan"), float("nan")),
            _kdef("SEA", "DEF", 6.0, 6.6, team="SEA"),
            _kdef("DAL", "DEF", 5.0, 5.5, team="DAL"),
        ]
    )
    combined = build_dashboard._projection_universe(skill, kdef, UNIVERSE)
    return build_dashboard._value_players(combined, 2026, ["QB", "K", "DEF", "BN"], 2)


def test_value_players_worked_example() -> None:
    """Two teams, one QB, K and DEF slot: replacement is each position's 2nd best.

    QB replacement 18.0: q1 +2.0/g -> +20.0 over 10 games, q2 0.0, q3
    -30.0. K replacement 8.0: k1 +10.0, k2 and k3 tie at 0.0. DEF
    replacement 5.0: SEA +10.0, DAL 0.0. k4 has no projection, so no VORP
    and no rank. Overall competition ranks: q1 1; k1 and SEA tied at 2;
    q2/k2/k3/DAL tied at 4; q3 8.
    """
    valued = _valued().set_index("player_id")
    assert valued.loc["q1", "replacement_ppg"] == pytest.approx(18.0)
    assert valued.loc["k1", "replacement_ppg"] == pytest.approx(8.0)
    assert valued.loc["SEA", "replacement_ppg"] == pytest.approx(5.0)
    assert valued.loc["q1", "points_above_replacement"] == pytest.approx(20.0)
    assert valued.loc["q3", "points_above_replacement"] == pytest.approx(-30.0)
    assert valued.loc["k1", "points_above_replacement"] == pytest.approx(10.0)
    assert valued.loc["SEA", "points_above_replacement"] == pytest.approx(10.0)

    ranks = valued["overall_rank"].to_dict()
    assert ranks["q1"] == 1
    assert ranks["k1"] == ranks["SEA"] == 2
    assert ranks["q2"] == ranks["k2"] == ranks["k3"] == ranks["DAL"] == 4
    assert ranks["q3"] == 8
    assert valued.loc["k2", "position_rank"] == valued.loc["k3", "position_rank"] == 2
    assert pd.isna(valued.loc["k4", "points_above_replacement"])
    assert pd.isna(valued.loc["k4", "overall_rank"])


def test_merge_kdef_board_interleaves_free_agent_kickers_by_vorp() -> None:
    """Only free-agent K/DEF join; rostered k1/k2 never do.

    SEA (+10.0) tops the +5.0 receiver; k3 and DAL tie at 0.0 and split
    on projection (8.0 over 5.0); the unprojected k4 sorts last. k3's
    matchup_adjusted_ppg is the K/DEF model's this-week number.
    """
    board = pd.DataFrame(
        [
            {**_skill("w1", "WR", 12.0), "points_above_replacement": 5.0},
            {**_skill("w2", "WR", 9.0), "points_above_replacement": -1.0},
        ]
    )
    merged = build_dashboard._merge_kdef_board(board, _valued())
    assert list(merged["player_id"]) == ["SEA", "w1", "k3", "DAL", "w2", "k4"]
    assert list(merged["board_rank"]) == [1, 2, 3, 4, 5, 6]
    k3 = merged.set_index("player_id").loc["k3"]
    assert k3["matchup_adjusted_ppg"] == pytest.approx(8.4)


def test_board_rows_keep_the_best_kdef_beyond_the_cut() -> None:
    board = pd.DataFrame(
        {
            "board_rank": [1, 2, 3, 4, 5, 6],
            "player_id": ["w1", "w2", "k1", "w3", "k2", "d1"],
            "position": ["WR", "WR", "K", "WR", "K", "DEF"],
        }
    )
    rows = build_dashboard._board_rows(board, top=2, per_kdef=1)
    assert list(rows["player_id"]) == ["w1", "w2", "k1", "d1"]


def test_valuation_table_adds_owner_injury_and_bye() -> None:
    teams = pd.DataFrame(
        {
            "roster_id": [1, 2],
            "display_name": ["alice", "bob"],
            "team_name": ["Team A", None],
        }
    )
    catalog = {"q1": {"injury_status": "Questionable", "injury_body_part": "Knee"}}
    table = build_dashboard._valuation_table(
        _valued(), catalog, {"KC": 10, "SEA": 8}, teams
    )
    assert list(table.columns) == [
        c for c in build_dashboard.VALUATION_COLUMNS if c in table.columns
    ]
    # By overall_rank, ties by position then id; the unranked k4 is last.
    assert list(table["player_id"][:3]) == ["q1", "SEA", "k1"]
    assert table.iloc[-1]["player_id"] == "k4"

    by_id = table.set_index("player_id")
    assert by_id.loc["q1", "owner"] == "alice"
    assert by_id.loc["q1", "owner_team_name"] == "Team A"
    assert by_id.loc["k2", "owner"] == "bob"
    assert pd.isna(by_id.loc["k2", "owner_team_name"])
    assert pd.isna(by_id.loc["q3", "owner"])
    assert by_id.loc["q1", "injury_status"] == "Questionable"
    assert by_id.loc["q1", "bye_week"] == 10
    assert by_id.loc["SEA", "bye_week"] == 8


def test_rank_moves_merges_and_renumbers() -> None:
    frame = lambda rows: pd.DataFrame(  # noqa: E731
        [
            {
                "player_id": pid,
                "net_lineup_gain": net,
                "starting_ppg_gain": gain,
                "projected_ppg": ppg,
                "add_drop_rank": 1,
            }
            for pid, net, gain, ppg in rows
        ]
    )
    skill = frame([("w1", 1.0, 2.0, 9.0), ("w2", 0.0, 0.0, 8.0)])
    kicker = frame([("k1", 1.0, 3.0, 8.0)])
    moves = build_dashboard._rank_moves([skill, kicker])
    # w1 and k1 tie on net gain; k1's larger starting gain wins.
    assert list(moves["player_id"]) == ["k1", "w1", "w2"]
    assert list(moves["add_drop_rank"]) == [1, 2, 3]
    assert build_dashboard._rank_moves([]).empty


def test_lineup_uses_this_weeks_kicker_number_and_swaps_kickers() -> None:
    """kA has the better rate, kB the better week: kB starts this week.

    The kicker move is a like-for-like swap: adding free agent kF drops a
    rostered kicker, never the bench receiver.
    """
    projections = pd.concat(
        [
            PROJECTIONS[PROJECTIONS["player_id"] != "k1"],
            pd.DataFrame(
                [
                    {**_projection("kA", "K", 9.0), "lineup_ppg": 6.0},
                    {**_projection("kB", "K", 8.0), "lineup_ppg": 8.5},
                ]
            ),
        ],
        ignore_index=True,
    )
    roster = {**MY_ROSTER, "players": ["q1", "r1", "r2", "w1", "w2", "kA", "kB"]}
    board = pd.DataFrame(
        [
            {
                **_projection("kF", "K", 12.0, team="DAL"),
                "board_rank": 1,
                "injury_status": None,
                "bye_week": None,
            }
        ]
    )
    lineup = build_dashboard._build_lineup(
        ROSTER_POSITIONS, roster, projections, board, CATALOG, BYES, 4, 6
    )
    assert lineup["slot_order"][-1] == {"slot": "K", "player_id": "kB"}
    kicker = lineup["recommended_starters"][-1]
    assert kicker["lineup_ppg"] == pytest.approx(8.5)

    move = lineup["add_drop"][0]
    assert move["player_id"] == "kF"
    assert move["best_drop_player_id"] in {"kA", "kB"}


def test_replacement_levels_come_from_the_valuation() -> None:
    levels = build_dashboard._replacement_levels(_valued())
    assert levels == {"QB": 18.0, "K": 8.0, "DEF": 5.0}
    assert build_dashboard._replacement_levels(pd.DataFrame()) == {}


def test_moves_stream_for_holes_when_replacement_levels_exist() -> None:
    """b1 (3.0) starts in week 4 only because r1 is Out and w1 is on bye.

    Without a fill he is worth his 3.0 that week (the FLEX would otherwise
    be empty). With replacement levels on the projections (RB 5.0, WR 5.0,
    QB 15.0) a 5.0 streamer beats him, so he is worth exactly 0.0 -- still
    the cheapest drop -- and the bundle records which values were used.
    """
    levels = {"QB": 15.0, "RB": 5.0, "WR": 5.0}
    projections = PROJECTIONS.assign(
        replacement_ppg=PROJECTIONS["position"].map(levels)
    )
    lineup = _lineup(projections=projections)
    assert lineup["streaming_values"] == levels
    move = {row["player_id"]: row for row in lineup["add_drop"]}["f1"]
    assert move["best_drop_player_id"] == "b1"
    assert move["best_drop_marginal_value"] == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Game locks: a Thursday night game has been played
# --------------------------------------------------------------------------

# r2 (Sleeper FLEX starter) and b1 (bench) play for PIT, whose game is over.
LOCKED_PROJECTIONS = PROJECTIONS.assign(
    team=PROJECTIONS["team"].where(~PROJECTIONS["player_id"].isin(["r2", "b1"]), "PIT")
)
LIVE_POINTS = {"r2": 7.5, "b1": 20.0, "q1": 0.0}


def _locked_lineup(board=BOARD, projections=LOCKED_PROJECTIONS, roster=MY_ROSTER):
    return build_dashboard._build_lineup(
        ROSTER_POSITIONS,
        roster,
        projections,
        board,
        CATALOG,
        BYES,
        4,
        6,
        locked_teams=frozenset({"PIT"}),
        live_points=LIVE_POINTS,
    )


def test_locked_starter_keeps_his_slot_and_banks_his_points() -> None:
    """Unlocked, r2 would move to RB and b1 would take the FLEX (41.0).

    Locked, r2 stays at FLEX with his actual 7.5 and b1 cannot come in, so
    with r1 Out the RB slot has nobody: QB q1 20 + WR w2 8 + FLEX 7.5.
    """
    lineup = _locked_lineup()
    assert lineup["slot_order"] == [
        {"slot": "QB", "player_id": "q1"},
        {"slot": "RB", "player_id": None},
        {"slot": "WR", "player_id": "w2"},
        {"slot": "FLEX", "player_id": "r2"},
    ]
    assert lineup["locked_points"] == pytest.approx(7.5)
    assert lineup["projected_points"] == pytest.approx(35.5)
    assert lineup["locked_teams"] == ["PIT"]

    starters = {row["player_id"]: row for row in lineup["recommended_starters"]}
    assert starters["r2"]["locked"] is True
    assert starters["r2"]["actual_points"] == pytest.approx(7.5)
    assert starters["q1"]["locked"] is False

    unavailable = {row["player_id"]: row for row in lineup["unavailable"]}
    assert unavailable["b1"]["unavailable_reason"] == "Locked"
    assert unavailable["b1"]["actual_points"] == pytest.approx(20.0)
    assert "b1" not in {row["player_id"] for row in lineup["bench"]}


def test_no_locks_matches_the_unlocked_lineup() -> None:
    """An empty ``locked_teams`` is the old behavior exactly."""
    plain = _lineup(projections=LOCKED_PROJECTIONS)
    assert plain["slot_order"][3] == {"slot": "FLEX", "player_id": "b1"}
    assert plain["projected_points"] == pytest.approx(41.0)
    assert plain["locked_points"] is None


def test_locked_players_are_never_added_or_dropped() -> None:
    """f3 (PIT) has played and cannot be added; r2 and b1 cannot be dropped."""
    board = pd.concat(
        [
            BOARD,
            pd.DataFrame(
                [
                    {
                        **_projection("f3", "WR", 16.0, team="PIT"),
                        "board_rank": 3,
                        "injury_status": None,
                        "bye_week": None,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    moves = {row["player_id"]: row for row in _locked_lineup(board=board)["add_drop"]}
    assert set(moves) == {"f1"}
    assert moves["f1"]["best_drop_player_id"] not in {"r2", "b1"}


def test_kicker_swap_waits_while_the_rostered_kicker_is_locked() -> None:
    """Every rostered kicker has played: no K move until the lock clears."""
    projections = pd.concat(
        [
            LOCKED_PROJECTIONS[LOCKED_PROJECTIONS["player_id"] != "k1"],
            pd.DataFrame(
                [{**_projection("kA", "K", 9.0, team="PIT"), "lineup_ppg": 6.0}]
            ),
        ],
        ignore_index=True,
    )
    roster = {
        **MY_ROSTER,
        "players": ["q1", "r1", "r2", "w1", "w2", "b1", "kA", "ir1"],
        "starters": ["q1", "r1", "w1", "r2", "kA"],
    }
    board = pd.DataFrame(
        [
            {
                **_projection("kF", "K", 12.0, team="DAL"),
                "board_rank": 1,
                "injury_status": None,
                "bye_week": None,
            }
        ]
    )
    lineup = _locked_lineup(board=board, projections=projections, roster=roster)
    assert lineup["add_drop"] == []
    assert lineup["slot_order"][-1] == {"slot": "K", "player_id": "kA"}

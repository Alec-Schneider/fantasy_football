"""Tests for roster-fit add/drop analysis (FFA-100).

Every lineup below is small enough to solve by hand; the toy roster
mirrors the module docstring's worked example.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.players.roster_fit import (
    ADD_DROP_COLUMNS,
    DROP_CANDIDATE_COLUMNS,
    assign_lineup_slots,
    build_add_drop_candidates,
    build_drop_candidates,
    build_roster_projection_frame,
    open_roster_spots,
    optimal_lineup,
    slot_fill_values,
    starting_slots,
)

SLOTS = ["QB", "RB", "FLEX", "BN", "BN"]


def _player(player_id, position, ppg, name=None, team="SF"):
    return {
        "player_id": player_id,
        "full_name": name or f"P{player_id}",
        "position": position,
        "team": team,
        "projected_ppg": ppg,
    }


# The module docstring's worked example: QB1 20, RB1 12, RB2 9, WR1 11.
# QB slot -> QB1, RB slot -> RB1, FLEX -> WR1 (11 beats RB2's 9). Total 43.
ROSTER = pd.DataFrame(
    [
        _player("q1", "QB", 20.0),
        _player("r1", "RB", 12.0),
        _player("r2", "RB", 9.0),
        _player("w1", "WR", 11.0),
    ]
)


# --------------------------------------------------------------------------
# starting_slots / optimal_lineup
# --------------------------------------------------------------------------


def test_starting_slots_filters_bench_labels() -> None:
    assert starting_slots(SLOTS) == ["QB", "RB", "FLEX"]
    assert starting_slots(["BN", "IR", "TAXI", "MYSTERY"]) == []
    assert starting_slots([]) == []


def test_optimal_lineup_worked_example() -> None:
    solution = optimal_lineup(ROSTER, SLOTS)
    assert solution.points_per_game == pytest.approx(43.0)
    assert solution.starters == frozenset({"q1", "r1", "w1"})


def test_optimal_lineup_prefers_the_better_flex() -> None:
    """Raising RB2 above WR1 flips the FLEX choice."""
    roster = ROSTER.copy()
    roster.loc[roster["player_id"] == "r2", "projected_ppg"] = 15.0
    solution = optimal_lineup(roster, SLOTS)
    assert solution.points_per_game == pytest.approx(47.0)
    assert solution.starters == frozenset({"q1", "r1", "r2"})


def test_optimal_lineup_ignores_unstartable_and_unprojected_players() -> None:
    roster = pd.concat(
        [
            ROSTER,
            pd.DataFrame(
                [
                    _player("x1", "LB", 99.0),  # no slot accepts LB
                    _player("w2", "WR", float("nan")),  # no projection
                ]
            ),
        ],
        ignore_index=True,
    )
    solution = optimal_lineup(roster, SLOTS)
    assert solution.points_per_game == pytest.approx(43.0)
    assert "x1" not in solution.starters
    assert "w2" not in solution.starters


def test_optimal_lineup_with_fewer_players_than_slots() -> None:
    """An unfillable slot is left empty rather than scored as zero-or-error."""
    solution = optimal_lineup(pd.DataFrame([_player("q1", "QB", 20.0)]), SLOTS)
    assert solution.points_per_game == pytest.approx(20.0)
    assert solution.starters == frozenset({"q1"})


def test_optimal_lineup_empty_inputs() -> None:
    assert optimal_lineup(ROSTER.iloc[0:0], SLOTS).points_per_game == 0.0
    assert optimal_lineup(ROSTER, ["BN", "BN"]).starters == frozenset()


def test_optimal_lineup_superflex_can_take_a_second_quarterback() -> None:
    roster = pd.concat(
        [ROSTER, pd.DataFrame([_player("q2", "QB", 18.0)])], ignore_index=True
    )
    single = optimal_lineup(roster, ["QB", "RB", "FLEX"])
    superflex = optimal_lineup(roster, ["QB", "RB", "SUPER_FLEX"])
    # FLEX cannot take a QB; SUPER_FLEX can, and 18.0 beats WR1's 11.0.
    assert single.points_per_game == pytest.approx(43.0)
    assert superflex.points_per_game == pytest.approx(50.0)
    assert "q2" in superflex.starters


# --------------------------------------------------------------------------
# build_drop_candidates
# --------------------------------------------------------------------------


def test_drop_candidates_marginal_value_is_the_lineup_cost() -> None:
    """RB2 is the only non-starter, so dropping him costs nothing.

    Dropping RB1 (12.0) promotes RB2 (9.0) into the RB slot, costing 3.0.
    Dropping WR1 (11.0) promotes RB2 into the FLEX, costing 2.0. Dropping
    QB1 costs his whole 20.0, since nobody else is a QB.
    """
    result = build_drop_candidates(ROSTER, SLOTS).set_index("player_id")

    assert list(result.reset_index().columns) == DROP_CANDIDATE_COLUMNS
    assert result.loc["r2", "marginal_value"] == pytest.approx(0.0)
    assert result.loc["w1", "marginal_value"] == pytest.approx(2.0)
    assert result.loc["r1", "marginal_value"] == pytest.approx(3.0)
    assert result.loc["q1", "marginal_value"] == pytest.approx(20.0)

    assert bool(result.loc["r2", "is_starter"]) is False
    assert bool(result.loc["q1", "is_starter"]) is True


def test_drop_candidates_are_ranked_cheapest_first() -> None:
    result = build_drop_candidates(ROSTER, SLOTS)
    assert result.iloc[0]["player_id"] == "r2"
    assert result.iloc[0]["drop_rank"] == 1
    assert result.iloc[-1]["player_id"] == "q1"
    assert list(result["drop_rank"]) == [1, 2, 3, 4]


def test_drop_candidates_zero_marginal_value_is_not_worst_projection() -> None:
    """A backup QB is free to drop even with a strong projection.

    QB2 at 18.0 is the second-highest projection on the roster, but in a
    one-QB league removing him leaves the best lineup untouched -- while
    RB2 at 9.0 now has nonzero value. Ranking on projection alone would
    get this backwards; ranking on marginal value gets it right.
    """
    roster = pd.concat(
        [ROSTER, pd.DataFrame([_player("q2", "QB", 18.0)])], ignore_index=True
    )
    result = build_drop_candidates(roster, SLOTS).set_index("player_id")
    assert result.loc["q2", "marginal_value"] == pytest.approx(0.0)
    assert result.loc["q2", "projected_ppg"] == pytest.approx(18.0)


def test_drop_candidates_empty_roster() -> None:
    result = build_drop_candidates(ROSTER.iloc[0:0], SLOTS)
    assert result.empty
    assert list(result.columns) == DROP_CANDIDATE_COLUMNS


# --------------------------------------------------------------------------
# build_add_drop_candidates
# --------------------------------------------------------------------------


CANDIDATES = pd.DataFrame(
    [
        _player("f1", "WR", 14.0, name="Strong WR"),
        _player("f2", "WR", 6.0, name="Weak WR"),
        _player("f3", "TE", 10.5, name="Decent TE"),
    ]
)


def test_add_drop_gain_and_displacement() -> None:
    """A 14.0 WR takes the FLEX from WR1 (11.0): a gain of 3.0.

    The cheapest drop is RB2 (marginal value 0.0), and RB2 is not in the
    lineup, so the net gain equals the starting gain.
    """
    result = build_add_drop_candidates(ROSTER, CANDIDATES, SLOTS).set_index("player_id")

    assert list(result.reset_index().columns) == ADD_DROP_COLUMNS
    assert result.loc["f1", "starting_ppg_gain"] == pytest.approx(3.0)
    assert bool(result.loc["f1", "starts_immediately"]) is True
    assert result.loc["f1", "displaces_player_id"] == "w1"
    assert result.loc["f1", "displaces_name"] == "Pw1"
    assert result.loc["f1", "best_drop_player_id"] == "r2"
    assert result.loc["f1", "best_drop_marginal_value"] == pytest.approx(0.0)
    assert result.loc["f1", "net_lineup_gain"] == pytest.approx(3.0)


def test_add_drop_candidate_who_does_not_crack_the_lineup() -> None:
    """A 6.0 WR is worse than every startable option: zero gain, no displacement."""
    result = build_add_drop_candidates(ROSTER, CANDIDATES, SLOTS).set_index("player_id")
    assert result.loc["f2", "starting_ppg_gain"] == pytest.approx(0.0)
    assert bool(result.loc["f2", "starts_immediately"]) is False
    assert result.loc["f2", "displaces_player_id"] is None
    assert result.loc["f2", "net_lineup_gain"] == pytest.approx(0.0)


def test_add_drop_ranks_by_net_gain() -> None:
    result = build_add_drop_candidates(ROSTER, CANDIDATES, SLOTS)
    assert result.iloc[0]["player_id"] == "f1"
    assert result.iloc[0]["add_drop_rank"] == 1
    assert list(result["add_drop_rank"]) == [1, 2, 3]
    # f3 (TE 10.5) does not beat WR1's 11.0 for the FLEX -> no gain.
    ranked = result.set_index("player_id")
    assert ranked.loc["f3", "starting_ppg_gain"] == pytest.approx(0.0)


def test_net_gain_is_below_starting_gain_when_the_drop_is_a_starter() -> None:
    """With no spare bench player, the add must cost a starter.

    Roster of exactly three players filling three slots: every drop has a
    real cost. Adding a 14.0 WR gains 3.0 on its own, but the cheapest
    drop is WR1 at 2.0, so the executable transaction nets 3.0 - 2.0 = 1.0.
    """
    tight = pd.DataFrame(
        [
            _player("q1", "QB", 20.0),
            _player("r1", "RB", 12.0),
            _player("w1", "WR", 11.0),
        ]
    )
    result = build_add_drop_candidates(
        tight, CANDIDATES[CANDIDATES["player_id"] == "f1"], SLOTS
    ).iloc[0]

    assert result["starting_ppg_gain"] == pytest.approx(3.0)
    assert result["best_drop_player_id"] == "w1"
    assert result["best_drop_marginal_value"] == pytest.approx(11.0)
    assert result["net_lineup_gain"] == pytest.approx(3.0)


def test_max_candidates_truncates_by_projection() -> None:
    result = build_add_drop_candidates(ROSTER, CANDIDATES, SLOTS, max_candidates=2)
    assert len(result) == 2
    # The two best projections are kept: 14.0 and 10.5.
    assert set(result["player_id"]) == {"f1", "f3"}


def test_add_drop_skips_candidates_with_no_projection() -> None:
    candidates = pd.concat(
        [CANDIDATES, pd.DataFrame([_player("f4", "WR", float("nan"))])],
        ignore_index=True,
    )
    result = build_add_drop_candidates(ROSTER, candidates, SLOTS)
    assert "f4" not in set(result["player_id"])


def test_add_drop_empty_inputs() -> None:
    assert build_add_drop_candidates(ROSTER.iloc[0:0], CANDIDATES, SLOTS).empty
    assert build_add_drop_candidates(ROSTER, CANDIDATES.iloc[0:0], SLOTS).empty
    empty = build_add_drop_candidates(ROSTER, CANDIDATES.iloc[0:0], SLOTS)
    assert list(empty.columns) == ADD_DROP_COLUMNS


# --------------------------------------------------------------------------
# build_roster_projection_frame
# --------------------------------------------------------------------------


def test_build_roster_projection_frame_selects_by_id() -> None:
    projections = pd.concat([ROSTER, CANDIDATES], ignore_index=True)
    selected = build_roster_projection_frame(["q1", "w1", "missing"], projections)
    assert set(selected["player_id"]) == {"q1", "w1"}


def test_build_roster_projection_frame_empty() -> None:
    assert build_roster_projection_frame([], ROSTER).empty
    assert build_roster_projection_frame(["q1"], ROSTER.iloc[0:0]).empty


def test_add_drop_ties_break_toward_the_better_projection() -> None:
    """A board mostly ties at 0.00; order that block by projection, not id.

    None of these three cracks the lineup, so all three net 0.00. The
    ordering must then be 14.0 / 10.5 / 6.0 by projection -- not the
    player_id order f1 / f2 / f3, which would bury the near-miss.
    """
    deep = pd.DataFrame(
        [
            _player("q1", "QB", 40.0),
            _player("r1", "RB", 30.0),
            _player("w1", "WR", 25.0),
            # A spare, so the cheapest drop costs nothing and every net
            # gain is exactly 0.0 rather than negative.
            _player("r2", "RB", 1.0),
        ]
    )
    result = build_add_drop_candidates(deep, CANDIDATES, SLOTS)
    assert list(result["net_lineup_gain"].round(6)) == [0.0, 0.0, 0.0]
    assert list(result["player_id"]) == ["f1", "f3", "f2"]
    assert list(result["projected_ppg"]) == [14.0, 10.5, 6.0]


# --------------------------------------------------------------------------
# FFA-107: availability, the rest-of-season horizon, reserve slots, K/DEF
# --------------------------------------------------------------------------


def _hurt(player_id, position, ppg, status=None, bye=None, name=None):
    row = _player(player_id, position, ppg, name=name)
    row["injury_status"] = status
    row["bye_week"] = bye
    return row


# The module docstring's horizon example: week 4 through 6. RB1 is Out
# (misses week 4 only), WR1 has a week-5 bye.
#   Week 4: QB1 + RB2 + WR1 = 40.0
#   Week 5: QB1 + RB1 + RB2 = 41.0
#   Week 6: QB1 + RB1 + WR1 = 43.0          ROS = 124.0
HORIZON_ROSTER = pd.DataFrame(
    [
        _hurt("q1", "QB", 20.0),
        _hurt("r1", "RB", 12.0, status="Out"),
        _hurt("w1", "WR", 11.0, bye=5),
        _hurt("r2", "RB", 9.0),
    ]
)
HORIZON = {"week": 4, "season_end_week": 6}


def test_optimal_lineup_never_starts_an_unavailable_player() -> None:
    """RB1 at 12.0 would start; marked unavailable, RB2 takes his slot."""
    roster = ROSTER.assign(available=[True, False, True, True])
    solution = optimal_lineup(roster, SLOTS)
    assert "r1" not in solution.starters
    assert solution.starters == frozenset({"q1", "r2", "w1"})
    assert solution.points_per_game == pytest.approx(40.0)


def test_optimal_lineup_reads_missing_availability_as_available() -> None:
    roster = ROSTER.assign(available=[True, None, float("nan"), True])
    assert optimal_lineup(roster, SLOTS).points_per_game == pytest.approx(43.0)


def test_drop_marginal_value_over_the_horizon_worked_example() -> None:
    """Hand-computed in the module docstring.

    Without WR1: 29 / 41 / 41 = 111 -> 13.0. Without RB1: 40 / 29 / 40 =
    109 -> 15.0. Without RB2: 31 / 32 / 43 = 106 -> 18.0. Without QB1:
    20 / 21 / 23 = 64 -> 60.0. Means divide by the 3 weeks evaluated.
    """
    result = build_drop_candidates(HORIZON_ROSTER, SLOTS, **HORIZON)
    assert list(result.columns) == DROP_CANDIDATE_COLUMNS
    assert list(result["player_id"]) == ["w1", "r1", "r2", "q1"]
    assert list(result["marginal_value_total"]) == pytest.approx(
        [13.0, 15.0, 18.0, 60.0]
    )
    assert list(result["marginal_value"]) == pytest.approx([13.0 / 3, 5.0, 6.0, 20.0])
    assert set(result["weeks_evaluated"]) == {3}
    # is_starter describes the first horizon week, when RB1 is out.
    starters = dict(zip(result["player_id"], result["is_starter"]))
    assert starters == {"q1": True, "r1": False, "w1": True, "r2": True}


def test_out_player_is_not_free_to_drop_over_the_horizon() -> None:
    """The FFA-107 failure: a coming-week-only solve calls RB1 free.

    RB1 cannot play week 4, so over that week alone removing him costs
    nothing (0.0, cheapest drop). Over weeks 4-6 he is worth 5.0 a week
    and is not the cheapest drop.
    """
    this_week = build_drop_candidates(HORIZON_ROSTER, SLOTS, week=4)
    assert this_week.iloc[0]["player_id"] == "r1"
    assert this_week.iloc[0]["marginal_value"] == pytest.approx(0.0)

    horizon = build_drop_candidates(HORIZON_ROSTER, SLOTS, **HORIZON)
    assert horizon.iloc[0]["player_id"] != "r1"
    ranked = horizon.set_index("player_id")
    assert ranked.loc["r1", "marginal_value"] == pytest.approx(5.0)


def test_no_week_keeps_the_ffa100_numbers_even_with_status_columns() -> None:
    """Without ``week``, injury_status/bye_week are ignored, as before."""
    result = build_drop_candidates(HORIZON_ROSTER, SLOTS).set_index("player_id")
    assert result.loc["r2", "marginal_value"] == pytest.approx(0.0)
    assert result.loc["w1", "marginal_value"] == pytest.approx(2.0)
    assert result.loc["r1", "marginal_value"] == pytest.approx(3.0)
    assert result.loc["q1", "marginal_value"] == pytest.approx(20.0)
    assert set(result["weeks_evaluated"]) == {1}


def test_horizon_collapses_to_the_coming_week_past_season_end() -> None:
    """A fantasy-playoff week after the regular season is a one-week horizon."""
    result = build_drop_candidates(HORIZON_ROSTER, SLOTS, week=15, season_end_week=14)
    assert set(result["weeks_evaluated"]) == {1}


def test_available_column_applies_to_the_first_horizon_week_only() -> None:
    """``available=False`` on RB1 matches status Out: out week 4 only."""
    roster = HORIZON_ROSTER.assign(
        injury_status=[None, None, None, None],
        available=[True, False, True, True],
    )
    result = build_drop_candidates(roster, SLOTS, **HORIZON).set_index("player_id")
    assert result.loc["r1", "marginal_value_total"] == pytest.approx(15.0)


def test_drop_ties_break_toward_lower_projection_then_player_id() -> None:
    """Three bench players, each worth exactly 0.0 over the horizon.

    Nobody is injured or on bye, so no bench player ever starts. The tie
    at 0.0 is broken by projection (1.0 before 2.0), then by player_id
    (b2 before b3 at the same 2.0).
    """
    roster = pd.DataFrame(
        [
            _hurt("q1", "QB", 20.0),
            _hurt("r1", "RB", 12.0),
            _hurt("w1", "WR", 11.0),
            _hurt("b3", "QB", 2.0),
            _hurt("b2", "QB", 2.0),
            _hurt("b1", "QB", 1.0),
        ]
    )
    result = build_drop_candidates(roster, SLOTS, **HORIZON)
    assert list(result["player_id"][:3]) == ["b1", "b2", "b3"]
    assert list(result["marginal_value"][:3]) == [0.0, 0.0, 0.0]


def test_add_drop_over_the_horizon_worked_example() -> None:
    """A healthy 14.0 WR against the horizon roster.

    With him (no drop): 43 / 46 / 46 = 135, +11.0 total, 11/3 a week. The
    cheapest drop is WR1 (13.0 total); without WR1 and with the new WR the
    lineup is still 43 / 46 / 46, so the net gain is the same 11.0 total,
    +3.0 in week 4.
    """
    candidates = pd.DataFrame([_hurt("f1", "WR", 14.0)])
    result = build_add_drop_candidates(
        HORIZON_ROSTER, candidates, SLOTS, **HORIZON
    ).iloc[0]

    assert result["starting_ppg_gain"] == pytest.approx(11.0 / 3)
    assert bool(result["starts_immediately"]) is True
    assert result["displaces_player_id"] == "w1"
    assert result["best_drop_player_id"] == "w1"
    assert result["best_drop_marginal_value"] == pytest.approx(13.0 / 3)
    assert result["net_lineup_gain"] == pytest.approx(11.0 / 3)
    assert result["net_lineup_gain_total"] == pytest.approx(11.0)
    assert result["net_gain_this_week"] == pytest.approx(3.0)
    assert result["weeks_evaluated"] == 3


def test_add_drop_out_candidate_pays_for_the_week_he_misses() -> None:
    """The same 14.0 WR, but Out for week 4.

    Swapped for WR1, week 4 is QB1 + RB2 alone (29.0, an 11.0 loss),
    weeks 5-6 gain 5.0 and 3.0: net -3.0 total. He first starts in week
    5, where he pushes RB2 out of the FLEX.
    """
    candidates = pd.DataFrame([_hurt("f2", "WR", 14.0, status="Out")])
    result = build_add_drop_candidates(
        HORIZON_ROSTER, candidates, SLOTS, **HORIZON
    ).iloc[0]

    assert bool(result["starts_immediately"]) is False
    assert result["displaces_player_id"] == "r2"
    assert result["net_gain_this_week"] == pytest.approx(-11.0)
    assert result["net_lineup_gain_total"] == pytest.approx(-3.0)
    assert result["net_lineup_gain"] == pytest.approx(-1.0)


def test_reserve_players_are_never_the_drop() -> None:
    """An IR-slot player out for the whole horizon is worth 0.0 -- and stays.

    Status IR keeps him out for weeks 4-7, the whole 4-6 horizon, so his
    marginal value is 0.0 and he would rank as the cheapest drop. In a
    Sleeper reserve slot he frees no bench spot, so he is not a candidate.
    """
    roster = pd.concat(
        [HORIZON_ROSTER, pd.DataFrame([_hurt("ir1", "RB", 15.0, status="IR")])],
        ignore_index=True,
    )
    unflagged = build_drop_candidates(roster, SLOTS, **HORIZON)
    assert unflagged.set_index("player_id").loc["ir1", "marginal_value"] == 0.0

    drops = build_drop_candidates(roster, SLOTS, reserve_player_ids=["ir1"], **HORIZON)
    assert "ir1" not in set(drops["player_id"])

    candidates = pd.DataFrame([_hurt("f1", "WR", 14.0)])
    add_drop = build_add_drop_candidates(
        roster, candidates, SLOTS, reserve_player_ids=["ir1"], **HORIZON
    ).iloc[0]
    assert add_drop["best_drop_player_id"] != "ir1"


def test_reserve_players_still_count_once_they_return() -> None:
    """A reserve RB back by week 5 lowers the value of the RB who covers him.

    With a 1-week absence, RB ir1 (15.0) starts weeks 5-6 over RB2.
    RB2's marginal value falls from 18.0 total to what week 4 alone needs.
    """
    roster = pd.concat(
        [HORIZON_ROSTER, pd.DataFrame([_hurt("ir1", "RB", 15.0, status="IR")])],
        ignore_index=True,
    )
    short_ir = {"IR": 1, "Out": 1}
    result = build_drop_candidates(
        roster, SLOTS, reserve_player_ids=["ir1"], weeks_out=short_ir, **HORIZON
    ).set_index("player_id")
    # Week 4: ir1 and r1 both out; without RB2 the lineup loses 9.0.
    # Weeks 5-6: ir1 and r1 fill RB and FLEX; RB2 is surplus.
    assert result.loc["r2", "marginal_value_total"] == pytest.approx(9.0)


def test_open_roster_spot_means_no_drop() -> None:
    candidates = pd.DataFrame([_hurt("f1", "WR", 14.0)])
    result = build_add_drop_candidates(
        HORIZON_ROSTER, candidates, SLOTS, open_roster_spots=1, **HORIZON
    ).iloc[0]
    assert result["best_drop_player_id"] is None
    assert result["best_drop_name"] is None
    assert pd.isna(result["best_drop_marginal_value"])
    assert result["net_lineup_gain"] == pytest.approx(result["starting_ppg_gain"])


def test_candidate_already_on_the_roster_is_ignored() -> None:
    candidates = pd.concat(
        [CANDIDATES, pd.DataFrame([_player("w1", "WR", 11.0)])], ignore_index=True
    )
    result = build_add_drop_candidates(ROSTER, candidates, SLOTS)
    assert "w1" not in set(result["player_id"])


def test_open_roster_spots_counts_reserve_outside_capacity() -> None:
    """The docstring example: 16 slots, 17 players, 1 in reserve -> full."""
    positions = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"] + ["BN"] * 7
    players = [str(index) for index in range(17)]
    full = {"players": players, "reserve": ["16"], "taxi": None}
    assert open_roster_spots(full, positions) == 0

    short = {"players": players[:15], "reserve": ["14"], "taxi": []}
    assert open_roster_spots(short, positions) == 2
    assert open_roster_spots({"players": None}, positions) == 16
    # An over-full roster (mid-transaction) is 0, not negative.
    assert open_roster_spots({"players": players + ["x"]}, positions) == 0


# The three leagues' shape: K and DEF slots, a DEF identified by team code.
KDEF_SLOTS = ["QB", "RB", "FLEX", "K", "DEF", "BN", "BN"]


def test_optimal_lineup_starts_kicker_and_team_defense() -> None:
    roster = pd.concat(
        [
            ROSTER,
            pd.DataFrame(
                [
                    _player("4037", "K", 8.5),
                    _player("SEA", "DEF", 7.0, name="Seattle Seahawks"),
                    _player("DAL", "DEF", 5.0),
                ]
            ),
        ],
        ignore_index=True,
    )
    solution = optimal_lineup(roster, KDEF_SLOTS)
    assert starting_slots(KDEF_SLOTS) == ["QB", "RB", "FLEX", "K", "DEF"]
    assert solution.starters == frozenset({"q1", "r1", "w1", "4037", "SEA"})
    assert solution.points_per_game == pytest.approx(43.0 + 8.5 + 7.0)


def test_dst_spelling_is_read_as_def() -> None:
    roster = pd.DataFrame([_player("SEA", "DST", 7.0), _player("NE", "D/ST", 6.0)])
    solution = optimal_lineup(roster, ["DEF"])
    assert solution.starters == frozenset({"SEA"})


def test_team_defense_bye_over_the_horizon() -> None:
    """SEA (7.0) is on bye in week 5; DAL (5.0) covers it and has value."""
    roster = pd.DataFrame(
        [
            _hurt("SEA", "DEF", 7.0, bye=5),
            _hurt("DAL", "DEF", 5.0),
        ]
    )
    result = build_drop_candidates(roster, ["DEF", "BN"], **HORIZON).set_index(
        "player_id"
    )
    assert result.loc["DAL", "marginal_value_total"] == pytest.approx(5.0)
    assert result.loc["SEA", "marginal_value_total"] == pytest.approx(4.0)


def test_assign_lineup_slots_fills_dedicated_slots_first() -> None:
    """Two RBs and a WR for RB, FLEX: the better RB takes the RB slot."""
    roster = ROSTER.copy()
    roster.loc[roster["player_id"] == "r2", "projected_ppg"] = 15.0
    solution = optimal_lineup(roster, SLOTS)
    placed = assign_lineup_slots(roster, solution.starters, SLOTS)
    assert placed == [("QB", "q1"), ("RB", "r2"), ("FLEX", "r1")]


def test_assign_lineup_slots_backtracks_past_a_greedy_dead_end() -> None:
    """Greedy would put the 20.0 WR in REC_FLEX and strand the TE."""
    roster = pd.DataFrame(
        [_player("w1", "WR", 20.0), _player("t1", "TE", 10.0), _player("r1", "RB", 8.0)]
    )
    slots = ["REC_FLEX", "WRRB_FLEX"]
    solution = optimal_lineup(roster, slots)
    assert solution.starters == frozenset({"w1", "t1"})
    assert assign_lineup_slots(roster, solution.starters, slots) == [
        ("REC_FLEX", "t1"),
        ("WRRB_FLEX", "w1"),
    ]


def test_assign_lineup_slots_leaves_unfillable_slots_empty() -> None:
    roster = pd.DataFrame([_player("q1", "QB", 20.0)])
    placed = assign_lineup_slots(roster, {"q1"}, KDEF_SLOTS)
    assert placed == [
        ("QB", "q1"),
        ("RB", None),
        ("FLEX", None),
        ("K", None),
        ("DEF", None),
    ]


def test_unprojected_player_is_never_the_drop() -> None:
    """A missing projection is an unknown value, not a zero one.

    The solve cannot start an unprojected kicker, so his computed marginal
    value would be 0.0 and he would be the cheapest drop. He is reported
    with NaN, ranked last, and the best drop falls to RB2 (0.0, a real
    zero: he never starts over RB1 or WR1).
    """
    roster = pd.concat(
        [ROSTER, pd.DataFrame([_player("k1", "K", float("nan"))])],
        ignore_index=True,
    )
    drops = build_drop_candidates(roster, KDEF_SLOTS)
    assert drops.iloc[-1]["player_id"] == "k1"
    assert pd.isna(drops.iloc[-1]["marginal_value"])
    assert drops.iloc[0]["player_id"] == "r2"

    result = build_add_drop_candidates(
        roster, CANDIDATES[CANDIDATES["player_id"] == "f1"], KDEF_SLOTS
    ).iloc[0]
    assert result["best_drop_player_id"] == "r2"


def test_same_position_drop_swaps_like_for_like() -> None:
    """A kicker upgrade is a swap, not a second kicker.

    Slots QB, K, BN; weeks 4-6; K1 (7.0) has a week-5 bye; the bench RB is
    worth nothing. Adding K3 (8.0, bye week 6):

    - Roster-wide drop (the RB, 0.0): both kickers stay. Week 4 K3 over K1
      +1.0; week 5 K3 covers K1's bye +8.0; week 6 K1 covers K3's bye
      +0.0. Net +9.0 -- mostly "bye coverage" worth a whole kicker.
    - Same-position drop (K1): K3 replaces him. +1.0 / +8.0 / -7.0 (week
      6 now has no kicker) = +2.0, the upgrade a manager would actually
      make.
    - A healthy K2 (8.0, no bye) as a swap: +1.0 / +8.0 / +1.0 = +10.0.
    """
    roster = pd.DataFrame(
        [
            _hurt("q1", "QB", 20.0),
            _hurt("k1", "K", 7.0, bye=5),
            _hurt("r9", "RB", 1.0),
        ]
    )
    slots = ["QB", "K", "BN"]
    healthy = pd.DataFrame([_hurt("k2", "K", 8.0)])
    with_bye = pd.DataFrame([_hurt("k3", "K", 8.0, bye=6)])

    wide = build_add_drop_candidates(roster, with_bye, slots, **HORIZON).iloc[0]
    assert wide["best_drop_player_id"] == "r9"
    assert wide["net_lineup_gain_total"] == pytest.approx(1.0 + 8.0 + 0.0)

    swap = build_add_drop_candidates(
        roster, with_bye, slots, same_position_drop=True, **HORIZON
    ).iloc[0]
    assert swap["best_drop_player_id"] == "k1"
    # K1's own value: 7 + 0 + 7 = 14 over the horizon.
    assert swap["best_drop_marginal_value"] == pytest.approx(14.0 / 3)
    assert swap["net_lineup_gain_total"] == pytest.approx(1.0 + 8.0 - 7.0)

    plain = build_add_drop_candidates(
        roster, healthy, slots, same_position_drop=True, **HORIZON
    ).iloc[0]
    assert plain["best_drop_player_id"] == "k1"
    assert plain["net_lineup_gain_total"] == pytest.approx(10.0)


def test_same_position_drop_falls_back_without_a_rostered_match() -> None:
    """No rostered TE: the TE candidate takes the roster-wide best drop."""
    result = build_add_drop_candidates(
        ROSTER,
        CANDIDATES[CANDIDATES["player_id"] == "f3"],
        SLOTS,
        same_position_drop=True,
    ).iloc[0]
    assert result["best_drop_player_id"] == "r2"


# --------------------------------------------------------------------------
# Streaming-level fill (empty_slot_values)
# --------------------------------------------------------------------------

# QB1 20.0; RB1 12.0 on bye in week 5; RB2 9.0 is the backup who covers it.
BYE_ROSTER = pd.DataFrame(
    [
        _hurt("q1", "QB", 20.0),
        _hurt("r1", "RB", 12.0, bye=5),
        _hurt("r2", "RB", 9.0),
    ]
)
BYE_SLOTS = ["QB", "RB", "BN", "BN"]
STREAMERS = {"QB": 10.0, "RB": 6.0, "WR": 5.0, "TE": 4.0}


def test_backup_is_worth_only_his_margin_over_a_streamer() -> None:
    """The bye week is RB2's only start: week 5, QB1 + RB2 = 29.0.

    Without him and without a fill the RB slot is empty (20.0), so he is
    worth his full 9.0. With a replacement-level RB streamable at 6.0 the
    slot scores 26.0 without him, so he is worth 9.0 - 6.0 = 3.0.
    """
    plain = build_drop_candidates(BYE_ROSTER, BYE_SLOTS, **HORIZON).set_index(
        "player_id"
    )
    filled = build_drop_candidates(
        BYE_ROSTER, BYE_SLOTS, empty_slot_values=STREAMERS, **HORIZON
    ).set_index("player_id")

    assert plain.loc["r2", "marginal_value_total"] == pytest.approx(9.0)
    assert filled.loc["r2", "marginal_value_total"] == pytest.approx(9.0 - 6.0)
    # Without RB1, RB2 (above the streamer) starts in weeks 4 and 6, so RB1
    # is worth 12 - 9 in each; QB1 is worth 20 - 10 every week.
    assert filled.loc["r1", "marginal_value_total"] == pytest.approx(3.0 + 3.0)
    assert filled.loc["q1", "marginal_value_total"] == pytest.approx(30.0)


def test_backup_below_replacement_is_worth_nothing() -> None:
    """A 5.0 backup never beats the 6.0 streamer, even in the bye week."""
    roster = BYE_ROSTER.copy()
    roster.loc[roster["player_id"] == "r2", "projected_ppg"] = 5.0
    plain = build_drop_candidates(roster, BYE_SLOTS, **HORIZON).set_index("player_id")
    filled = build_drop_candidates(
        roster, BYE_SLOTS, empty_slot_values=STREAMERS, **HORIZON
    ).set_index("player_id")
    assert plain.loc["r2", "marginal_value_total"] == pytest.approx(5.0)
    assert filled.loc["r2", "marginal_value_total"] == pytest.approx(0.0)
    # The streamer is not a player: RB2 is not a starter in week 5 either.
    assert bool(filled.loc["r2", "is_starter"]) is False


def test_add_drop_with_streaming_fill() -> None:
    """A 10.0 RB replaces RB2 as the bye cover: +1.0, in week 5 only.

    The cheapest drop is RB2 (3.0 total with the fill, i.e. 1.0 a week).
    """
    candidates = pd.DataFrame([_hurt("f1", "RB", 10.0)])
    result = build_add_drop_candidates(
        BYE_ROSTER, candidates, BYE_SLOTS, empty_slot_values=STREAMERS, **HORIZON
    ).iloc[0]
    assert result["best_drop_player_id"] == "r2"
    assert result["best_drop_marginal_value"] == pytest.approx(1.0)
    assert result["net_lineup_gain_total"] == pytest.approx(1.0)
    assert result["net_gain_this_week"] == pytest.approx(0.0)


def test_no_fill_reproduces_the_current_output() -> None:
    """``None`` is the default path; an all-zero fill agrees with it too."""
    candidates = pd.DataFrame([_hurt("f1", "WR", 14.0), _hurt("f2", "RB", 3.0)])
    default_drops = build_drop_candidates(HORIZON_ROSTER, SLOTS, **HORIZON)
    default_moves = build_add_drop_candidates(
        HORIZON_ROSTER, candidates, SLOTS, **HORIZON
    )
    pd.testing.assert_frame_equal(
        build_drop_candidates(HORIZON_ROSTER, SLOTS, empty_slot_values=None, **HORIZON),
        default_drops,
    )
    pd.testing.assert_frame_equal(
        build_add_drop_candidates(
            HORIZON_ROSTER, candidates, SLOTS, empty_slot_values=None, **HORIZON
        ),
        default_moves,
    )
    # The worked example's numbers, unchanged.
    assert list(default_drops["marginal_value_total"]) == pytest.approx(
        [13.0, 15.0, 18.0, 60.0]
    )

    zeros = {position: 0.0 for position in ("QB", "RB", "WR", "TE")}
    pd.testing.assert_frame_equal(
        build_drop_candidates(
            HORIZON_ROSTER, SLOTS, empty_slot_values=zeros, **HORIZON
        ),
        default_drops,
    )


def test_slot_fill_values_take_the_cheapest_eligible_position() -> None:
    slots = ["QB", "RB", "FLEX", "SUPER_FLEX", "K", "DEF"]
    values = slot_fill_values(slots, {**STREAMERS, "K": -1.0})
    # FLEX = min(RB 6, WR 5, TE 4); SUPER_FLEX adds QB 10 but still takes
    # the minimum; a negative value clamps to 0.0; DEF has no value.
    assert values == [10.0, 6.0, 4.0, 4.0, 0.0, 0.0]

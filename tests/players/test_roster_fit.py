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
    build_add_drop_candidates,
    build_drop_candidates,
    build_roster_projection_frame,
    optimal_lineup,
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

"""Tests for per-team draft grades and talking points (FFA-079, FFA-080).

All tests operate on small hand-built ``scored_picks_df`` frames shaped like
``SCORED_DRAFT_PICK_COLUMNS`` (FFA-078's output contract) -- no HTTP calls,
no live Sleeper/nflverse access, and no dependency on
``score_draft_picks()`` itself; every column this module reads is set
directly so each test's arithmetic is fully controlled. Z-scores are
verified with ``statistics.fmean``/``pstdev`` computed directly in this
file (not imported from the module under test), matching
``test_draft_board.py``'s convention for a hand-checkable toy example.
"""

from __future__ import annotations

from statistics import fmean, pstdev

import pandas as pd
import pytest

from fantasy_analyzer.players.draft_grade import SCORED_DRAFT_PICK_COLUMNS
from fantasy_analyzer.players.draft_report import (
    DRAFT_TALKING_POINT_COLUMNS,
    TEAM_DRAFT_GRADE_COLUMNS,
    DraftGradeWeights,
    build_draft_talking_points,
    build_team_draft_grades,
)


def _pick(
    roster_id: int,
    team_name: str,
    sleeper_player_id: str,
    *,
    pick_no: int = 1,
    round_no: int = 1,
    position: str = "RB",
    expected_pick_source: str = "adp_pool_rank",
    excluded_reason: str | None = None,
    vor: float | None = None,
    pick_value: float | None = None,
    is_keeper: bool | None = None,
    expected_pick: float | None = None,
) -> dict:
    row = {column: None for column in SCORED_DRAFT_PICK_COLUMNS}
    row.update(
        {
            "season": 2026,
            "league_id": "league1",
            "draft_id": "draft1",
            "round": round_no,
            "pick_no": pick_no,
            "draft_slot": pick_no,
            "roster_id": roster_id,
            "owner_id": f"owner{roster_id}",
            "team_name": team_name,
            "sleeper_player_id": sleeper_player_id,
            "player_name": sleeper_player_id,
            "position": position,
            "nfl_team": "AAA",
            "is_keeper": is_keeper,
            "expected_pick": expected_pick if expected_pick is not None else pick_value,
            "expected_pick_source": expected_pick_source,
            "pick_value": pick_value,
            "vor": vor,
            "tier": None,
            "draft_score": None,
            "position_rank": None,
            "excluded_reason": excluded_reason,
        }
    )
    return row


def _get_grade(df: pd.DataFrame, roster_id: int) -> pd.Series:
    match = df[df["roster_id"] == roster_id]
    assert len(match) == 1
    return match.iloc[0]


# =======================================================================
# FFA-079: build_team_draft_grades
# =======================================================================

# ---------------------------------------------------------------------
# Toy example: 4 teams, hand-verified z-scores, overall_z, grade, rank
# ---------------------------------------------------------------------

# total_vor = [40, 20, 10, -10] for teams 1..4 (roster_id order); mean 15,
# population variance = mean((x-15)^2) = (625+25+25+625)/4 = 325,
# stdev = sqrt(325) ~= 18.0278 -> z ~= [1.3868, 0.2774, -0.2774, -1.3868].
_TOTAL_VOR = {1: 40.0, 2: 20.0, 3: 10.0, 4: -10.0}
# avg_pick_value analogue, chosen independently: [5, -5, 15, -15].
_AVG_PICK_VALUE = {1: 5.0, 2: -5.0, 3: 15.0, 4: -15.0}


def _toy_four_team_picks() -> pd.DataFrame:
    rows = []
    for roster_id in (1, 2, 3, 4):
        rows.append(
            _pick(
                roster_id,
                f"Team {roster_id}",
                f"p{roster_id}",
                pick_no=10,
                position="RB",
                vor=_TOTAL_VOR[roster_id],
                pick_value=_AVG_PICK_VALUE[roster_id],
            )
        )
    return pd.DataFrame(rows)


def test_toy_example_hand_verified_zscores_grade_and_rank() -> None:
    weights = DraftGradeWeights(vor=0.5, value=0.5)
    grades = build_team_draft_grades(_toy_four_team_picks(), weights=weights)

    total_vor_values = list(_TOTAL_VOR.values())
    vor_mean, vor_sd = fmean(total_vor_values), pstdev(total_vor_values)
    apv_values = list(_AVG_PICK_VALUE.values())
    apv_mean, apv_sd = fmean(apv_values), pstdev(apv_values)

    expected_overall_z = {}
    for roster_id in (1, 2, 3, 4):
        z_vor = (_TOTAL_VOR[roster_id] - vor_mean) / vor_sd
        z_apv = (_AVG_PICK_VALUE[roster_id] - apv_mean) / apv_sd
        expected_overall_z[roster_id] = 0.5 * z_vor + 0.5 * z_apv

        row = _get_grade(grades, roster_id)
        assert row["total_vor"] == pytest.approx(_TOTAL_VOR[roster_id])
        assert row["avg_pick_value"] == pytest.approx(_AVG_PICK_VALUE[roster_id])
        assert row["total_vor_z"] == pytest.approx(z_vor)
        assert row["avg_pick_value_z"] == pytest.approx(z_apv)
        assert row["overall_z"] == pytest.approx(expected_overall_z[roster_id])

    # Grade letters from the fixed thresholds, hand-computed from the
    # z-scores above:
    #   team1: 0.5*1.386750 + 0.5*0.447214 = 0.916982 -> in [0.5, 1.0) -> B+
    #   team2: 0.5*0.277350 + 0.5*(-0.447214) = -0.084932 -> in [-0.5, 0.0) -> C+
    #   team3: 0.5*(-0.277350) + 0.5*1.341641 = 0.532145 -> in [0.5, 1.0) -> B+
    #   team4: 0.5*(-1.386750) + 0.5*(-1.341641) = -1.364196 -> in [-1.5, -1.0) -> D
    assert expected_overall_z[1] == pytest.approx(0.9169820430315153, abs=1e-6)
    assert expected_overall_z[2] == pytest.approx(-0.08493174869367168, abs=1e-6)
    assert expected_overall_z[3] == pytest.approx(0.5321453441936297, abs=1e-6)
    assert expected_overall_z[4] == pytest.approx(-1.3641956385314733, abs=1e-6)
    assert _get_grade(grades, 1)["grade_letter"] == "B+"
    assert _get_grade(grades, 2)["grade_letter"] == "C+"
    assert _get_grade(grades, 3)["grade_letter"] == "B+"
    assert _get_grade(grades, 4)["grade_letter"] == "D"

    # draft_rank: standard competition rank on overall_z descending.
    ranked_ids = sorted((1, 2, 3, 4), key=lambda rid: -expected_overall_z[rid])
    for expected_rank, roster_id in enumerate(ranked_ids, start=1):
        assert _get_grade(grades, roster_id)["draft_rank"] == pytest.approx(
            float(expected_rank)
        )

    # best_pick / worst_pick reflect the team's single pick.
    row1 = _get_grade(grades, 1)
    assert row1["best_pick_player"] == "p1"
    assert row1["best_pick_value"] == pytest.approx(5.0)
    assert row1["worst_pick_player"] == "p1"
    assert row1["worst_pick_value"] == pytest.approx(5.0)


def test_grade_letter_threshold_boundaries_hand_checked() -> None:
    """Independently confirms the threshold table against the toy example's
    team 2, whose overall_z sits between -0.5 and 0.0 (a boundary case,
    since it is close to the C+/B split at 0.0)."""
    total_vor_values = list(_TOTAL_VOR.values())
    vor_mean, vor_sd = fmean(total_vor_values), pstdev(total_vor_values)
    apv_values = list(_AVG_PICK_VALUE.values())
    apv_mean, apv_sd = fmean(apv_values), pstdev(apv_values)
    z_vor_2 = (_TOTAL_VOR[2] - vor_mean) / vor_sd
    z_apv_2 = (_AVG_PICK_VALUE[2] - apv_mean) / apv_sd
    overall_z_2 = 0.5 * z_vor_2 + 0.5 * z_apv_2
    assert -0.5 <= overall_z_2 < 0.0

    grades = build_team_draft_grades(_toy_four_team_picks())
    assert _get_grade(grades, 2)["grade_letter"] == "C+"


# ---------------------------------------------------------------------
# Ties in overall_z: share a rank, next rank skips
# ---------------------------------------------------------------------


def test_tied_overall_z_share_rank_and_next_rank_skips() -> None:
    picks = pd.DataFrame(
        [
            _pick(1, "Team A", "pa", pick_no=10, vor=20.0, pick_value=5.0),
            _pick(2, "Team B", "pb", pick_no=10, vor=20.0, pick_value=5.0),  # tied w/ A
            _pick(3, "Team C", "pc", pick_no=10, vor=-20.0, pick_value=-5.0),
        ]
    )
    grades = build_team_draft_grades(picks)
    a = _get_grade(grades, 1)
    b = _get_grade(grades, 2)
    c = _get_grade(grades, 3)
    assert a["overall_z"] == pytest.approx(b["overall_z"])
    assert a["draft_rank"] == b["draft_rank"] == 1.0
    assert c["draft_rank"] == 3.0  # rank 2 skipped, not reused


# ---------------------------------------------------------------------
# All-unscored team
# ---------------------------------------------------------------------


def test_all_unscored_team_is_nan_and_does_not_corrupt_other_teams() -> None:
    picks_with_unscored = pd.DataFrame(
        [
            _pick(1, "Team A", "pa", pick_no=10, vor=40.0, pick_value=5.0),
            _pick(2, "Team B", "pb", pick_no=10, vor=20.0, pick_value=-5.0),
            _pick(
                3,
                "Team C",
                "pc",
                pick_no=10,
                expected_pick_source="unscored",
                vor=None,
                pick_value=None,
            ),
        ]
    )
    grades = build_team_draft_grades(picks_with_unscored)

    unscored_row = _get_grade(grades, 3)
    assert pd.isna(unscored_row["total_vor"])
    assert pd.isna(unscored_row["avg_pick_value"])
    assert pd.isna(unscored_row["overall_z"])
    assert unscored_row["grade_letter"] is None
    assert pd.isna(unscored_row["draft_rank"])
    assert unscored_row["unscored_pick_count"] == 1

    # Compare against the same two real teams scored alone: the unscored
    # team's presence must not shift teams A/B's z-scores at all (it is
    # excluded from the population, not zero-filled).
    picks_without_unscored = pd.DataFrame(
        [
            _pick(1, "Team A", "pa", pick_no=10, vor=40.0, pick_value=5.0),
            _pick(2, "Team B", "pb", pick_no=10, vor=20.0, pick_value=-5.0),
        ]
    )
    grades_without = build_team_draft_grades(picks_without_unscored)
    for roster_id in (1, 2):
        with_row = _get_grade(grades, roster_id)
        without_row = _get_grade(grades_without, roster_id)
        assert with_row["total_vor_z"] == pytest.approx(without_row["total_vor_z"])
        assert with_row["avg_pick_value_z"] == pytest.approx(
            without_row["avg_pick_value_z"]
        )
        assert with_row["overall_z"] == pytest.approx(without_row["overall_z"])


# ---------------------------------------------------------------------
# Single-team edge case
# ---------------------------------------------------------------------


def test_single_team_has_no_defined_zscore_or_grade() -> None:
    picks = pd.DataFrame(
        [_pick(1, "Team A", "pa", pick_no=10, vor=40.0, pick_value=5.0)]
    )
    grades = build_team_draft_grades(picks)
    assert len(grades) == 1
    row = _get_grade(grades, 1)
    # Only one usable value in the total_vor population -> z undefined.
    assert pd.isna(row["total_vor_z"])
    assert pd.isna(row["avg_pick_value_z"])
    assert pd.isna(row["overall_z"])
    assert row["grade_letter"] is None
    assert pd.isna(row["draft_rank"])
    # total_vor/avg_pick_value themselves are still real numbers.
    assert row["total_vor"] == pytest.approx(40.0)
    assert row["avg_pick_value"] == pytest.approx(5.0)


# ---------------------------------------------------------------------
# All-keeper team
# ---------------------------------------------------------------------


def test_all_keeper_team_is_nan_like_all_unscored() -> None:
    picks = pd.DataFrame(
        [
            _pick(1, "Team A", "pa", pick_no=10, vor=40.0, pick_value=5.0),
            _pick(2, "Team B", "pb", pick_no=10, vor=20.0, pick_value=-5.0),
            _pick(
                3,
                "Team C",
                "kp1",
                pick_no=1,
                excluded_reason="keeper",
                vor=None,
                pick_value=None,
            ),
            _pick(
                3,
                "Team C",
                "kp2",
                pick_no=2,
                excluded_reason="keeper",
                vor=None,
                pick_value=None,
            ),
        ]
    )
    grades = build_team_draft_grades(picks)
    row = _get_grade(grades, 3)
    assert pd.isna(row["total_vor"])
    assert pd.isna(row["avg_pick_value"])
    assert pd.isna(row["overall_z"])
    assert row["grade_letter"] is None
    assert pd.isna(row["draft_rank"])
    assert row["keeper_pick_count"] == 2
    assert row["unscored_pick_count"] == 0


# ---------------------------------------------------------------------
# Shape / empty / weights validation
# ---------------------------------------------------------------------


def test_empty_scored_picks_df_returns_empty_frame_with_columns() -> None:
    empty = pd.DataFrame(columns=SCORED_DRAFT_PICK_COLUMNS)
    result = build_team_draft_grades(empty)
    assert list(result.columns) == TEAM_DRAFT_GRADE_COLUMNS
    assert result.empty


def test_draft_grade_weights_reject_negative_value() -> None:
    with pytest.raises(ValueError):
        DraftGradeWeights(vor=-0.1)


def test_draft_grade_weights_reject_both_zero() -> None:
    with pytest.raises(ValueError):
        DraftGradeWeights(vor=0.0, value=0.0)


# =======================================================================
# FFA-080: build_draft_talking_points
# =======================================================================


def test_talking_points_field_derivation_from_toy_example() -> None:
    picks = _toy_four_team_picks()
    grades = build_team_draft_grades(picks)
    talking_points = build_draft_talking_points(grades, picks)

    assert list(talking_points.columns) == DRAFT_TALKING_POINT_COLUMNS
    assert (talking_points["num_teams"] == 4).all()

    def _get_tp(roster_id: int) -> pd.Series:
        match = talking_points[talking_points["roster_id"] == roster_id]
        assert len(match) == 1
        return match.iloc[0]

    # total_vor descending: team1(40) > team2(20) > team3(10) > team4(-10).
    assert _get_tp(1)["total_vor_rank"] == pytest.approx(1.0)
    assert _get_tp(3)["total_vor_rank"] == pytest.approx(3.0)
    # avg_pick_value descending: team3(15) > team1(5) > team2(-5) > team4(-15).
    assert _get_tp(1)["avg_pick_value_rank"] == pytest.approx(2.0)
    assert _get_tp(3)["avg_pick_value_rank"] == pytest.approx(1.0)

    # threshold = REACH_VALUE_THRESHOLD = 0.30 (value-scale, not num_teams).
    # team1 pick_value=5 > 0.30 -> value_count=1, reach_count=0.
    # team3 pick_value=15 > 0.30 -> value_count=1, reach_count=0.
    assert _get_tp(1)["value_count"] == 1
    assert _get_tp(1)["reach_count"] == 0
    assert _get_tp(3)["value_count"] == 1
    assert _get_tp(3)["reach_count"] == 0

    # Every pick in this fixture is position "RB" -> trivially most-drafted.
    assert _get_tp(1)["most_drafted_position"] == "RB"
    assert _get_tp(1)["position_counts"] == {"RB": 1}
    assert _get_tp(3)["most_drafted_position"] == "RB"
    assert _get_tp(3)["position_counts"] == {"RB": 1}

    # Passed straight through from team_grades_df.
    assert _get_tp(1)["grade_letter"] == _get_grade(grades, 1)["grade_letter"]
    assert _get_tp(1)["best_pick_player"] == "p1"


def test_talking_points_zero_reach_and_zero_value() -> None:
    # threshold = REACH_VALUE_THRESHOLD = 0.30. pick_value=0.1 is within
    # +/-0.30 for both teams.
    picks = pd.DataFrame(
        [
            _pick(1, "Team A", "pa", pick_no=10, vor=10.0, pick_value=0.1),
            _pick(2, "Team B", "pb", pick_no=10, vor=-10.0, pick_value=-0.1),
        ]
    )
    grades = build_team_draft_grades(picks)
    talking_points = build_draft_talking_points(grades, picks)
    assert (talking_points["reach_count"] == 0).all()
    assert (talking_points["value_count"] == 0).all()


def test_talking_points_position_tie_breaks_alphabetically() -> None:
    """A team with 3 RB and 3 WR picks (a tie) reports 'RB', the
    alphabetically-first position -- asserting the implemented behavior,
    not just the documented rule."""
    rb_picks = [
        _pick(
            1,
            "Team A",
            f"rb{i}",
            pick_no=i,
            position="RB",
            expected_pick_source="unscored",
        )
        for i in range(1, 4)
    ]
    wr_picks = [
        _pick(
            1,
            "Team A",
            f"wr{i}",
            pick_no=i + 3,
            position="WR",
            expected_pick_source="unscored",
        )
        for i in range(1, 4)
    ]
    picks = pd.DataFrame(rb_picks + wr_picks)
    grades = build_team_draft_grades(picks)
    talking_points = build_draft_talking_points(grades, picks)

    row = talking_points[talking_points["roster_id"] == 1].iloc[0]
    assert row["most_drafted_position"] == "RB"
    assert row["position_counts"] == {"RB": 3, "WR": 3}


def test_talking_points_position_counts_include_keepers_and_unscored() -> None:
    picks = pd.DataFrame(
        [
            _pick(
                1,
                "Team A",
                "p1",
                pick_no=1,
                position="QB",
                expected_pick_source="unscored",
            ),
            _pick(
                1,
                "Team A",
                "p2",
                pick_no=2,
                position="RB",
                excluded_reason="keeper",
            ),
            _pick(1, "Team A", "p3", pick_no=3, position="RB", vor=5.0, pick_value=1.0),
        ]
    )
    grades = build_team_draft_grades(picks)
    talking_points = build_draft_talking_points(grades, picks)
    row = talking_points[talking_points["roster_id"] == 1].iloc[0]
    assert row["position_counts"] == {"QB": 1, "RB": 2}
    assert row["most_drafted_position"] == "RB"


def test_talking_points_unknown_position_grouped() -> None:
    picks = pd.DataFrame(
        [
            _pick(
                1,
                "Team A",
                "p1",
                pick_no=1,
                position=None,
                expected_pick_source="unscored",
            ),
        ]
    )
    grades = build_team_draft_grades(picks)
    talking_points = build_draft_talking_points(grades, picks)
    row = talking_points[talking_points["roster_id"] == 1].iloc[0]
    assert row["position_counts"] == {"UNKNOWN": 1}
    assert row["most_drafted_position"] == "UNKNOWN"


def test_empty_team_grades_df_returns_empty_talking_points_frame() -> None:
    empty_grades = pd.DataFrame(columns=TEAM_DRAFT_GRADE_COLUMNS)
    empty_picks = pd.DataFrame(columns=SCORED_DRAFT_PICK_COLUMNS)
    result = build_draft_talking_points(empty_grades, empty_picks)
    assert list(result.columns) == DRAFT_TALKING_POINT_COLUMNS
    assert result.empty

"""Tests for the fitted, real-points-scale draft value curve (FFA-085).

All tests operate on small hand-built frames -- no HTTP calls, no live
Sleeper/nflverse access, matching ``test_draft_grade.py``'s convention.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from fantasy_analyzer.league.draft import NORMALIZED_DRAFT_PICK_COLUMNS
from fantasy_analyzer.players.draft_board import DRAFT_BOARD_COLUMNS
from fantasy_analyzer.players.draft_grade import SCORED_DRAFT_PICK_COLUMNS
from fantasy_analyzer.players.draft_points_value import (
    POINTS_VALUE_PICK_COLUMNS,
    PointsValueCurve,
    fit_points_value_curve,
    score_points_value,
)


def _historical_pick_row(
    sleeper_player_id: str,
    pick_no: int,
    *,
    position: str = "RB",
    is_keeper: bool | None = None,
) -> dict:
    return {
        "season": 2025,
        "league_id": "league1",
        "draft_id": "draft1",
        "round": 1,
        "pick_no": pick_no,
        "draft_slot": pick_no,
        "roster_id": 1,
        "owner_id": "owner1",
        "team_name": "Team A",
        "sleeper_player_id": sleeper_player_id,
        "player_name": sleeper_player_id,
        "position": position,
        "nfl_team": "AAA",
        "is_keeper": is_keeper,
    }


def _prior_row(sleeper_player_id: str, points_above_replacement: float) -> dict:
    return {
        "sleeper_player_id": sleeper_player_id,
        "points_above_replacement": points_above_replacement,
    }


def _scored_pick_row(
    sleeper_player_id: str | None,
    pick_no: int | None,
    *,
    roster_id: int = 1,
    excluded_reason: str | None = None,
) -> dict:
    row = {column: None for column in SCORED_DRAFT_PICK_COLUMNS}
    row.update(
        {
            "season": 2026,
            "league_id": "league1",
            "draft_id": "draft1",
            "round": 1,
            "pick_no": pick_no,
            "draft_slot": pick_no,
            "roster_id": roster_id,
            "owner_id": f"owner{roster_id}",
            "team_name": f"Team {roster_id}",
            "sleeper_player_id": sleeper_player_id,
            "player_name": sleeper_player_id,
            "position": "RB",
            "nfl_team": "AAA",
            "is_keeper": None,
            "excluded_reason": excluded_reason,
        }
    )
    return row


def _board_row(sleeper_player_id: str, *, draft_rank: float | None) -> dict:
    row = {column: None for column in DRAFT_BOARD_COLUMNS}
    row.update(
        {
            "sleeper_player_id": sleeper_player_id,
            "player_name": sleeper_player_id,
            "position": "RB",
            "nfl_team": "AAA",
            "draft_rank": draft_rank,
        }
    )
    return row


# ---------------------------------------------------------------------
# fit_points_value_curve: toy example (hand-checked in the module
# docstring). pick_no in {1, 2, 4, 8}, ln() falls on an evenly-spaced grid
# (0, ln2, 2ln2, 3ln2); points_above_replacement chosen exactly linear in
# that grid -> a perfect fit.
# ---------------------------------------------------------------------


def test_toy_example_perfect_fit() -> None:
    picks = pd.DataFrame(
        [
            _historical_pick_row("p1", 1),
            _historical_pick_row("p2", 2),
            _historical_pick_row("p4", 4),
            _historical_pick_row("p8", 8),
        ]
    )
    prior = pd.DataFrame(
        [
            _prior_row("p1", 30.0),
            _prior_row("p2", 20.0),
            _prior_row("p4", 10.0),
            _prior_row("p8", 0.0),
        ]
    )
    curve = fit_points_value_curve(picks, prior)
    assert curve is not None
    assert curve.n_picks == 4
    assert curve.slope == pytest.approx(-10.0 / math.log(2))
    assert curve.intercept == pytest.approx(30.0)
    assert curve.r_squared == pytest.approx(1.0)

    assert curve.value_at(1) == pytest.approx(30.0)
    assert curve.value_at(2) == pytest.approx(20.0)
    assert curve.value_at(4) == pytest.approx(10.0)
    assert curve.value_at(8) == pytest.approx(0.0)
    # Extrapolated beyond the observed range -- still just the same line.
    assert curve.value_at(16) == pytest.approx(-10.0)


def test_value_at_clamps_x_below_one() -> None:
    curve = PointsValueCurve(intercept=10.0, slope=-5.0, n_picks=4, r_squared=0.5)
    assert curve.value_at(0.0) == pytest.approx(10.0)
    assert curve.value_at(-3.0) == pytest.approx(10.0)
    assert curve.value_at(1.0) == pytest.approx(10.0)


# ---------------------------------------------------------------------
# fit_points_value_curve: keeper and excluded-position exclusion
# ---------------------------------------------------------------------


def test_keeper_picks_excluded_from_fit() -> None:
    picks = pd.DataFrame(
        [
            _historical_pick_row("p1", 1),
            _historical_pick_row("p2", 2),
            _historical_pick_row("p4", 4),
            _historical_pick_row("p8", 8),
            # A keeper picked absurdly early relative to its true value --
            # if this were included it would badly distort the fit.
            _historical_pick_row("keeper1", 1, is_keeper=True),
        ]
    )
    prior = pd.DataFrame(
        [
            _prior_row("p1", 30.0),
            _prior_row("p2", 20.0),
            _prior_row("p4", 10.0),
            _prior_row("p8", 0.0),
            _prior_row("keeper1", -50.0),
        ]
    )
    curve = fit_points_value_curve(picks, prior)
    assert curve is not None
    assert curve.n_picks == 4
    assert curve.r_squared == pytest.approx(1.0)


def test_excluded_positions_dropped_from_fit() -> None:
    picks = pd.DataFrame(
        [
            _historical_pick_row("p1", 1),
            _historical_pick_row("p2", 2),
            _historical_pick_row("p4", 4),
            _historical_pick_row("p8", 8),
            _historical_pick_row("kicker1", 3, position="K"),
        ]
    )
    prior = pd.DataFrame(
        [
            _prior_row("p1", 30.0),
            _prior_row("p2", 20.0),
            _prior_row("p4", 10.0),
            _prior_row("p8", 0.0),
            _prior_row("kicker1", 999.0),
        ]
    )
    curve = fit_points_value_curve(picks, prior)
    assert curve is not None
    assert curve.n_picks == 4
    assert curve.r_squared == pytest.approx(1.0)


# ---------------------------------------------------------------------
# fit_points_value_curve: missing values / degenerate cases
# ---------------------------------------------------------------------


def test_empty_frames_return_none() -> None:
    assert fit_points_value_curve(pd.DataFrame(), pd.DataFrame()) is None
    picks = pd.DataFrame([_historical_pick_row("p1", 1)])
    assert fit_points_value_curve(picks, pd.DataFrame()) is None
    prior = pd.DataFrame([_prior_row("p1", 10.0)])
    assert fit_points_value_curve(pd.DataFrame(), prior) is None


def test_fewer_than_two_usable_pairs_returns_none() -> None:
    picks = pd.DataFrame([_historical_pick_row("p1", 1), _historical_pick_row("p2", 2)])
    # Only p1 joins; p2 has no prior row.
    prior = pd.DataFrame([_prior_row("p1", 30.0)])
    assert fit_points_value_curve(picks, prior) is None


def test_zero_variance_in_ln_pick_no_returns_none() -> None:
    # Every usable pick shares the same pick_no -> ss_xx == 0.
    picks = pd.DataFrame(
        [
            _historical_pick_row("p1", 5),
            _historical_pick_row("p2", 5),
        ]
    )
    prior = pd.DataFrame([_prior_row("p1", 10.0), _prior_row("p2", 20.0)])
    assert fit_points_value_curve(picks, prior) is None


def test_unmatched_player_id_is_dropped_not_treated_as_zero() -> None:
    picks = pd.DataFrame(
        [
            _historical_pick_row("p1", 1),
            _historical_pick_row("p2", 2),
            _historical_pick_row("p4", 4),
            _historical_pick_row("p8", 8),
            _historical_pick_row("no_match", 6),
        ]
    )
    prior = pd.DataFrame(
        [
            _prior_row("p1", 30.0),
            _prior_row("p2", 20.0),
            _prior_row("p4", 10.0),
            _prior_row("p8", 0.0),
        ]
    )
    curve = fit_points_value_curve(picks, prior)
    assert curve is not None
    assert curve.n_picks == 4


# ---------------------------------------------------------------------
# score_points_value
# ---------------------------------------------------------------------

_CURVE = PointsValueCurve(
    intercept=30.0, slope=-10.0 / math.log(2), n_picks=4, r_squared=1.0
)


def test_score_points_value_toy_example() -> None:
    """draft_rank=2 -> projected 20.0; pick_no=4 -> expected slot value 10.0.
    pick_value_points = 20.0 - 10.0 = +10.0 (a steal: player ranked for a
    much better slot than the one actually spent).
    """
    scored_picks = pd.DataFrame([_scored_pick_row("p1", pick_no=4)])
    board = pd.DataFrame([_board_row("p1", draft_rank=2.0)])
    result = score_points_value(scored_picks, board, _CURVE)
    row = result.iloc[0]
    assert row["projected_points_value"] == pytest.approx(20.0)
    assert row["expected_points_value_at_pick"] == pytest.approx(10.0)
    assert row["pick_value_points"] == pytest.approx(10.0)


def test_score_points_value_reach_case() -> None:
    """draft_rank=8 -> projected 0.0; pick_no=1 -> expected slot value 30.0.
    pick_value_points = 0.0 - 30.0 = -30.0 (a reach).
    """
    scored_picks = pd.DataFrame([_scored_pick_row("p1", pick_no=1)])
    board = pd.DataFrame([_board_row("p1", draft_rank=8.0)])
    result = score_points_value(scored_picks, board, _CURVE)
    row = result.iloc[0]
    assert row["pick_value_points"] == pytest.approx(-30.0)


def test_none_curve_forces_every_new_column_nan() -> None:
    scored_picks = pd.DataFrame([_scored_pick_row("p1", pick_no=4)])
    board = pd.DataFrame([_board_row("p1", draft_rank=2.0)])
    result = score_points_value(scored_picks, board, None)
    row = result.iloc[0]
    assert pd.isna(row["projected_points_value"])
    assert pd.isna(row["expected_points_value_at_pick"])
    assert pd.isna(row["pick_value_points"])


def test_no_board_match_leaves_expected_value_at_pick_populated() -> None:
    """expected_points_value_at_pick depends only on pick_no and the
    curve -- unaffected by this pick's own player having no board match.
    """
    scored_picks = pd.DataFrame([_scored_pick_row("unmatched", pick_no=4)])
    board = pd.DataFrame([_board_row("someone_else", draft_rank=2.0)])
    result = score_points_value(scored_picks, board, _CURVE)
    row = result.iloc[0]
    assert pd.isna(row["projected_points_value"])
    assert row["expected_points_value_at_pick"] == pytest.approx(10.0)
    assert pd.isna(row["pick_value_points"])


def test_missing_pick_no_forces_expected_value_and_pick_value_nan() -> None:
    scored_picks = pd.DataFrame([_scored_pick_row("p1", pick_no=None)])
    board = pd.DataFrame([_board_row("p1", draft_rank=2.0)])
    result = score_points_value(scored_picks, board, _CURVE)
    row = result.iloc[0]
    assert row["projected_points_value"] == pytest.approx(20.0)
    assert pd.isna(row["expected_points_value_at_pick"])
    assert pd.isna(row["pick_value_points"])


def test_keeper_forces_pick_value_points_nan_but_keeps_projected_value() -> None:
    scored_picks = pd.DataFrame(
        [_scored_pick_row("p1", pick_no=4, excluded_reason="keeper")]
    )
    board = pd.DataFrame([_board_row("p1", draft_rank=2.0)])
    result = score_points_value(scored_picks, board, _CURVE)
    row = result.iloc[0]
    assert row["projected_points_value"] == pytest.approx(20.0)
    assert pd.isna(row["pick_value_points"])


def test_empty_scored_picks_df_returns_empty_frame_with_columns() -> None:
    scored_picks = pd.DataFrame(columns=SCORED_DRAFT_PICK_COLUMNS)
    board = pd.DataFrame(columns=DRAFT_BOARD_COLUMNS)
    result = score_points_value(scored_picks, board, _CURVE)
    assert list(result.columns) == POINTS_VALUE_PICK_COLUMNS
    assert result.empty


def test_excluded_reason_stays_real_none_not_nan_across_many_rows() -> None:
    """Regression test: pandas' DataFrame-from-records constructor infers a
    mixed string/``None`` column (a real string on a minority of rows,
    ``None`` elsewhere -- exactly ``excluded_reason``'s shape) as a string
    dtype that silently turns ``None`` into ``NaN``, which breaks any
    ``is None`` check downstream. A single-row frame doesn't reproduce
    this (needs a real mix across enough rows), so this test builds one
    non-keeper pick per roster across many rosters, plus one keeper.
    """
    scored_picks = pd.DataFrame(
        [
            *[
                _scored_pick_row(f"p{i}", pick_no=i, roster_id=i)
                for i in range(1, 40)
            ],
            _scored_pick_row(
                "keeper1", pick_no=40, roster_id=40, excluded_reason="keeper"
            ),
        ]
    )
    board = pd.DataFrame(
        [_board_row(f"p{i}", draft_rank=float(i)) for i in range(1, 40)]
        + [_board_row("keeper1", draft_rank=40.0)]
    )
    result = score_points_value(scored_picks, board, _CURVE)
    is_keeper = result["sleeper_player_id"] == "keeper1"
    non_keeper_reasons = result.loc[~is_keeper, "excluded_reason"]
    assert (non_keeper_reasons.apply(lambda v: v is None)).all()
    keeper_row = result[result["sleeper_player_id"] == "keeper1"].iloc[0]
    assert keeper_row["excluded_reason"] == "keeper"
    assert pd.isna(keeper_row["pick_value_points"])


def test_output_columns_are_scored_pick_columns_then_points_columns() -> None:
    scored_picks = pd.DataFrame([_scored_pick_row("p1", pick_no=4)])
    board = pd.DataFrame([_board_row("p1", draft_rank=2.0)])
    result = score_points_value(scored_picks, board, _CURVE)
    assert list(result.columns) == SCORED_DRAFT_PICK_COLUMNS + [
        "projected_points_value",
        "expected_points_value_at_pick",
        "pick_value_points",
    ]


def test_every_pick_produces_exactly_one_output_row() -> None:
    scored_picks = pd.DataFrame(
        [
            _scored_pick_row("p1", pick_no=1, roster_id=1),
            _scored_pick_row("p2", pick_no=2, roster_id=2),
            _scored_pick_row(None, pick_no=3, roster_id=3),
        ]
    )
    board = pd.DataFrame([_board_row("p1", draft_rank=1.0)])
    result = score_points_value(scored_picks, board, _CURVE)
    assert len(result) == 3


def test_normalized_draft_pick_columns_still_referenced_for_fixture_shape() -> None:
    """Sanity check that this test module's historical-pick fixtures stay
    aligned with the real FFA-077 contract (not read by the module under
    test directly, but load-bearing for these fixtures' validity)."""
    assert "pick_no" in NORMALIZED_DRAFT_PICK_COLUMNS
    assert "is_keeper" in NORMALIZED_DRAFT_PICK_COLUMNS

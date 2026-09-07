"""Tests for pick-level draft value grading (FFA-078, revised FFA-084).

All tests operate on small hand-built ``picks_df``/``board_df`` frames --
no HTTP calls, no live Sleeper/nflverse access -- matching
``test_draft_board.py``'s convention. ``board_df`` rows are plain dicts
shaped like ``DRAFT_BOARD_COLUMNS`` (no need to call the real
``build_draft_board()``); ``picks_df`` rows are plain dicts shaped like
``NORMALIZED_DRAFT_PICK_COLUMNS``.

``pick_value`` is now a value-scale quantity (``draft_score`` of the
player taken minus the board's interpolated value curve at ``pick_no``),
not a rank-scale one -- see ``draft_grade.py``'s module docstring for the
full rationale (the old rank-diff formula had both a sign bug and an
ordinal-scale bug). Board fixtures below always set ``draft_rank`` and
``draft_score`` together with ``adp_pool_rank`` (a real board always
carries all three; ``draft_rank`` is *derived from* ``draft_score``) since
the value curve is built from ``(draft_rank, draft_score)`` pairs.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.league.draft import NORMALIZED_DRAFT_PICK_COLUMNS
from fantasy_analyzer.players.draft_board import DRAFT_BOARD_COLUMNS
from fantasy_analyzer.players.draft_grade import (
    SCORED_DRAFT_PICK_COLUMNS,
    score_draft_picks,
)


def _pick_row(
    sleeper_player_id: str | None,
    pick_no: int,
    *,
    round_no: int = 1,
    roster_id: int = 1,
    team_name: str = "Team A",
    player_name: str | None = None,
    position: str | None = "RB",
    is_keeper: bool | None = None,
) -> dict:
    return {
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
        "player_name": player_name or sleeper_player_id,
        "position": position,
        "nfl_team": "AAA",
        "is_keeper": is_keeper,
    }


def _board_row(
    sleeper_player_id: str,
    *,
    adp_pool_rank: float | None = None,
    draft_rank: float | None = None,
    draft_score: float | None = None,
    vor: float | None = None,
    tier: float | None = None,
    position_rank: float | None = None,
) -> dict:
    row = {column: None for column in DRAFT_BOARD_COLUMNS}
    row.update(
        {
            "sleeper_player_id": sleeper_player_id,
            "player_name": sleeper_player_id,
            "position": "RB",
            "nfl_team": "AAA",
            "adp_pool_rank": adp_pool_rank,
            "draft_rank": draft_rank,
            "draft_score": draft_score,
            "vor": vor,
            "tier": tier,
            "position_rank": position_rank,
        }
    )
    return row


def _get(df: pd.DataFrame, sleeper_player_id: str) -> pd.Series:
    match = df[df["sleeper_player_id"] == sleeper_player_id]
    assert len(match) == 1
    return match.iloc[0]


# ---------------------------------------------------------------------
# Shape / empty
# ---------------------------------------------------------------------


def test_empty_picks_df_returns_empty_frame_with_columns() -> None:
    picks = pd.DataFrame(columns=NORMALIZED_DRAFT_PICK_COLUMNS)
    board = pd.DataFrame(columns=DRAFT_BOARD_COLUMNS)
    result = score_draft_picks(picks, board)
    assert list(result.columns) == SCORED_DRAFT_PICK_COLUMNS
    assert result.empty


def test_every_pick_produces_exactly_one_output_row() -> None:
    picks = pd.DataFrame(
        [
            _pick_row("p1", 1),
            _pick_row("p2", 2),
            _pick_row(None, 3),  # an empty/forfeited slot
        ]
    )
    board = pd.DataFrame(
        [_board_row("p1", adp_pool_rank=1.0, draft_rank=1.0, draft_score=3.0)]
    )
    result = score_draft_picks(picks, board)
    assert len(result) == 3


# ---------------------------------------------------------------------
# Toy example: the five-point value curve from the module docstring.
# rank 1..5 -> draft_score 3.0, 2.0, 1.0, 0.0, -1.0 (linear, for
# hand-checkability -- real boards need not be linear).
# ---------------------------------------------------------------------

_CURVE_BOARD = [
    _board_row("board_filler_1", draft_rank=1.0, draft_score=3.0),
    _board_row("board_filler_2", draft_rank=2.0, draft_score=2.0),
    _board_row("board_filler_3", draft_rank=3.0, draft_score=1.0),
    _board_row("board_filler_4", draft_rank=4.0, draft_score=0.0),
    _board_row("board_filler_5", draft_rank=5.0, draft_score=-1.0),
]


def test_toy_example_reach_and_steal() -> None:
    """Pick 3 on a player whose own draft_score is 1.5:
    expected_value_at_pick = curve(3) = 1.0 (exact rank match),
    pick_value = 1.5 - 1.0 = +0.5 (a steal).

    Pick 2 on a player whose own draft_score is 0.0:
    expected_value_at_pick = curve(2) = 2.0,
    pick_value = 0.0 - 2.0 = -2.0 (a reach).
    """
    picks = pd.DataFrame(
        [
            _pick_row("steal_player", 3),
            _pick_row("reach_player", 2, roster_id=2, team_name="Team B"),
        ]
    )
    board = pd.DataFrame(
        [
            *_CURVE_BOARD,
            _board_row(
                "steal_player", adp_pool_rank=6.0, draft_rank=6.0, draft_score=1.5
            ),
            _board_row(
                "reach_player", adp_pool_rank=7.0, draft_rank=7.0, draft_score=0.0
            ),
        ]
    )
    result = score_draft_picks(picks, board)

    steal = _get(result, "steal_player")
    assert steal["expected_value_at_pick"] == pytest.approx(1.0)
    assert steal["pick_value"] == pytest.approx(0.5)

    reach = _get(result, "reach_player")
    assert reach["expected_value_at_pick"] == pytest.approx(2.0)
    assert reach["pick_value"] == pytest.approx(-2.0)


def test_interpolation_across_a_tie_skipped_rank() -> None:
    """Rank 2 is never assigned (a tie at rank 1 skips it under competition
    ranking), so curve(2) must interpolate halfway between rank 1's 3.0 and
    rank 3's 1.0 -> 2.0, identical to the exact-match case above.

    The picked player's own board row (``p2``) is deliberately placed at
    ``draft_rank=10`` -- far outside the ``[1, 3]`` interpolation window
    being tested -- since ``_build_value_curve`` draws from *every* row in
    ``board_df``, including the player actually taken; placing it inside
    the window would silently add a third curve point and change the
    interpolation this test means to check.
    """
    board = pd.DataFrame(
        [
            _board_row("tied_a", draft_rank=1.0, draft_score=3.0),
            _board_row("tied_b", draft_rank=1.0, draft_score=3.0),
            _board_row("p3", draft_rank=3.0, draft_score=1.0),
            _board_row("p2", adp_pool_rank=2.0, draft_rank=10.0, draft_score=0.0),
        ]
    )
    picks = pd.DataFrame([_pick_row("p2", 2)])
    result = score_draft_picks(picks, board)
    row = _get(result, "p2")
    assert row["expected_value_at_pick"] == pytest.approx(2.0)
    assert row["pick_value"] == pytest.approx(0.0 - 2.0)


def test_value_curve_clamps_outside_observed_rank_range() -> None:
    """pick_no beyond the last curve point clamps to the worst (last) value;
    pick_no before the first clamps to the best (first) value.
    """
    picks = pd.DataFrame(
        [
            _pick_row("early_bird", 0),
            _pick_row("deep_sleeper", 50, roster_id=2, team_name="Team B"),
        ]
    )
    board = pd.DataFrame(
        [
            *_CURVE_BOARD,
            _board_row("early_bird", draft_rank=6.0, draft_score=3.0),
            _board_row("deep_sleeper", draft_rank=7.0, draft_score=-1.0),
        ]
    )
    result = score_draft_picks(picks, board)
    assert _get(result, "early_bird")["expected_value_at_pick"] == pytest.approx(3.0)
    assert _get(result, "deep_sleeper")["expected_value_at_pick"] == pytest.approx(-1.0)


# ---------------------------------------------------------------------
# expected_pick / expected_pick_source: informational, unchanged from the
# original ADP-pool-preferred-over-draft_rank fallback logic. No longer
# drives pick_value (see the toy examples above), but still computed and
# reported.
# ---------------------------------------------------------------------


def test_expected_pick_falls_back_to_draft_rank_when_no_adp_pool_rank() -> None:
    picks = pd.DataFrame([_pick_row("no_adp_player", 20)])
    board = pd.DataFrame(
        [
            *_CURVE_BOARD,
            _board_row(
                "no_adp_player",
                adp_pool_rank=float("nan"),
                draft_rank=15.0,
                draft_score=-1.0,
            ),
        ]
    )
    result = score_draft_picks(picks, board)
    row = _get(result, "no_adp_player")
    assert row["expected_pick"] == pytest.approx(15.0)
    assert row["expected_pick_source"] == "draft_rank"
    # pick_value is unaffected by expected_pick's fallback -- it only
    # depends on this player's own draft_score and the curve at pick_no=20,
    # which clamps to the curve's worst point (rank 15, score -1.0).
    assert row["pick_value"] == pytest.approx(-1.0 - -1.0)


def test_expected_pick_prefers_adp_pool_rank_over_draft_rank_when_both_present() -> (
    None
):
    picks = pd.DataFrame([_pick_row("p1", 10)])
    board = pd.DataFrame(
        [
            *_CURVE_BOARD,
            _board_row("p1", adp_pool_rank=8.0, draft_rank=6.0, draft_score=1.5),
        ]
    )
    result = score_draft_picks(picks, board)
    row = _get(result, "p1")
    assert row["expected_pick"] == pytest.approx(8.0)
    assert row["expected_pick_source"] == "adp_pool_rank"


# ---------------------------------------------------------------------
# Fully unscored: no board match at all
# ---------------------------------------------------------------------


def test_fully_unscored_player_is_not_dropped() -> None:
    picks = pd.DataFrame(
        [
            _pick_row("scored_player", 5),
            _pick_row("unmatched_player", 6),
        ]
    )
    board = pd.DataFrame(
        [
            *_CURVE_BOARD,
            _board_row(
                "scored_player", adp_pool_rank=3.0, draft_rank=3.0, draft_score=1.0
            ),
        ]
    )
    result = score_draft_picks(picks, board)

    assert len(result) == 2
    row = _get(result, "unmatched_player")
    assert pd.isna(row["expected_pick"])
    assert row["expected_pick_source"] == "unscored"
    # expected_value_at_pick depends only on pick_no (6) and the shared
    # curve, not on this pick's own (unmatched) player, so it is still
    # populated: curve(6) clamps to the worst observed point, rank 5's
    # -1.0. Only pick_value (which also needs this player's own
    # draft_score) is NaN.
    assert row["expected_value_at_pick"] == pytest.approx(-1.0)
    assert pd.isna(row["pick_value"])
    assert pd.isna(row["vor"])
    assert pd.isna(row["tier"])
    assert pd.isna(row["draft_score"])
    assert pd.isna(row["position_rank"])


def test_board_row_matched_but_both_ranks_missing_is_unscored() -> None:
    picks = pd.DataFrame([_pick_row("p1", 5)])
    board = pd.DataFrame(
        [
            *_CURVE_BOARD,
            _board_row(
                "p1",
                adp_pool_rank=float("nan"),
                draft_rank=float("nan"),
                draft_score=float("nan"),
            ),
        ]
    )
    result = score_draft_picks(picks, board)
    row = _get(result, "p1")
    assert row["expected_pick_source"] == "unscored"
    assert pd.isna(row["pick_value"])


def test_empty_value_curve_forces_pick_value_nan_even_for_a_scored_player() -> None:
    """A degenerate board with no (draft_rank, draft_score) pairs anywhere:
    the player itself may still carry a draft_score (read straight off its
    own board row), but there is no curve to compare it against.
    """
    picks = pd.DataFrame([_pick_row("p1", 5)])
    board = pd.DataFrame(
        [_board_row("p1", adp_pool_rank=3.0, draft_rank=float("nan"), draft_score=1.0)]
    )
    result = score_draft_picks(picks, board)
    row = _get(result, "p1")
    assert row["expected_pick_source"] == "adp_pool_rank"
    assert row["draft_score"] == pytest.approx(1.0)
    assert pd.isna(row["expected_value_at_pick"])
    assert pd.isna(row["pick_value"])


def test_missing_pick_no_forces_pick_value_nan() -> None:
    picks = pd.DataFrame([_pick_row("p1", None)])
    board = pd.DataFrame(
        [
            *_CURVE_BOARD,
            _board_row("p1", adp_pool_rank=3.0, draft_rank=3.0, draft_score=1.0),
        ]
    )
    result = score_draft_picks(picks, board)
    row = _get(result, "p1")
    assert pd.isna(row["expected_value_at_pick"])
    assert pd.isna(row["pick_value"])


# ---------------------------------------------------------------------
# Keeper exclusion
# ---------------------------------------------------------------------


def test_keeper_forces_pick_value_and_vor_to_nan_and_sets_excluded_reason() -> None:
    picks = pd.DataFrame([_pick_row("keeper_player", 3, is_keeper=True)])
    board = pd.DataFrame(
        [
            *_CURVE_BOARD,
            _board_row(
                "keeper_player",
                adp_pool_rank=40.0,
                draft_rank=6.0,
                draft_score=1.5,
                vor=5.5,
                tier=2.0,
            ),
        ]
    )
    result = score_draft_picks(picks, board)
    row = _get(result, "keeper_player")

    # The board match would otherwise produce a real steal (1.5 - 1.0 =
    # +0.5) and a real vor -- both must be forced to NaN.
    assert pd.isna(row["pick_value"])
    assert pd.isna(row["vor"])
    assert row["excluded_reason"] == "keeper"
    # expected_pick/expected_pick_source/expected_value_at_pick are still
    # computed (not suppressed).
    assert row["expected_pick"] == pytest.approx(40.0)
    assert row["expected_pick_source"] == "adp_pool_rank"
    assert row["expected_value_at_pick"] == pytest.approx(1.0)
    # tier/draft_score/position_rank are unaffected by the keeper flag.
    assert row["tier"] == pytest.approx(2.0)
    assert row["draft_score"] == pytest.approx(1.5)


def test_non_keeper_picks_have_excluded_reason_none() -> None:
    picks = pd.DataFrame(
        [
            _pick_row("p1", 1, is_keeper=False),
            _pick_row("p2", 2, is_keeper=None),
        ]
    )
    board = pd.DataFrame(
        [
            *_CURVE_BOARD,
            _board_row("p1", adp_pool_rank=1.0, draft_rank=6.0, draft_score=1.5),
            _board_row("p2", adp_pool_rank=2.0, draft_rank=7.0, draft_score=1.5),
        ]
    )
    result = score_draft_picks(picks, board)
    assert _get(result, "p1")["excluded_reason"] is None
    assert _get(result, "p2")["excluded_reason"] is None


def test_keeper_unscored_player_still_reports_keeper_exclusion() -> None:
    """A keeper with no board match: unscored *and* excluded, independently."""
    picks = pd.DataFrame([_pick_row("keeper_unscored", 10, is_keeper=True)])
    board = pd.DataFrame(columns=DRAFT_BOARD_COLUMNS)
    result = score_draft_picks(picks, board)
    row = _get(result, "keeper_unscored")
    assert row["expected_pick_source"] == "unscored"
    assert row["excluded_reason"] == "keeper"
    assert pd.isna(row["pick_value"])


# ---------------------------------------------------------------------
# Ties: two picks landing on the same pick_value, computed independently
# ---------------------------------------------------------------------


def test_tied_pick_values_compute_independently_and_correctly() -> None:
    picks = pd.DataFrame(
        [
            _pick_row("tie1", 3, roster_id=1, team_name="Team A"),
            _pick_row("tie2", 4, roster_id=2, team_name="Team B"),
        ]
    )
    # tie1: draft_score=1.5 at pick 3 (curve=1.0) -> +0.5.
    # tie2: draft_score=0.5 at pick 4 (curve=0.0) -> +0.5.
    board = pd.DataFrame(
        [
            *_CURVE_BOARD,
            _board_row("tie1", adp_pool_rank=6.0, draft_rank=6.0, draft_score=1.5),
            _board_row("tie2", adp_pool_rank=7.0, draft_rank=7.0, draft_score=0.5),
        ]
    )
    result = score_draft_picks(picks, board)
    tie1 = _get(result, "tie1")
    tie2 = _get(result, "tie2")
    assert tie1["pick_value"] == pytest.approx(0.5)
    assert tie2["pick_value"] == pytest.approx(0.5)
    assert tie1["pick_value"] == pytest.approx(tie2["pick_value"])


# ---------------------------------------------------------------------
# Carried-through board columns
# ---------------------------------------------------------------------


def test_vor_tier_draft_score_position_rank_carried_through_verbatim() -> None:
    picks = pd.DataFrame([_pick_row("p1", 5)])
    board = pd.DataFrame(
        [
            *_CURVE_BOARD,
            _board_row(
                "p1",
                adp_pool_rank=3.0,
                draft_rank=6.0,
                vor=2.75,
                tier=1.0,
                draft_score=1.9,
                position_rank=4.0,
            ),
        ]
    )
    result = score_draft_picks(picks, board)
    row = _get(result, "p1")
    assert row["vor"] == pytest.approx(2.75)
    assert row["tier"] == pytest.approx(1.0)
    assert row["draft_score"] == pytest.approx(1.9)
    assert row["position_rank"] == pytest.approx(4.0)


def test_picks_own_player_name_position_nfl_team_are_not_overwritten_by_board() -> None:
    """A join collision guard: the picks' own labels must win, not the board's."""
    picks = pd.DataFrame(
        [
            _pick_row(
                "p1", 5, player_name="Pick Label", position="WR"
            )
        ]
    )
    board = pd.DataFrame(
        [
            *_CURVE_BOARD,
            {
                **_board_row("p1", adp_pool_rank=3.0, draft_rank=6.0, draft_score=1.5),
                "player_name": "Board Label",
                "position": "TE",
                "nfl_team": "ZZZ",
            },
        ]
    )
    result = score_draft_picks(picks, board)
    row = _get(result, "p1")
    assert row["player_name"] == "Pick Label"
    assert row["position"] == "WR"
    assert row["nfl_team"] == "AAA"


# ---------------------------------------------------------------------
# Column order
# ---------------------------------------------------------------------


def test_output_columns_are_normalized_pick_columns_then_grading_columns() -> None:
    picks = pd.DataFrame([_pick_row("p1", 1)])
    board = pd.DataFrame(
        [
            *_CURVE_BOARD,
            _board_row("p1", adp_pool_rank=1.0, draft_rank=6.0, draft_score=1.5),
        ]
    )
    result = score_draft_picks(picks, board)
    assert list(result.columns) == NORMALIZED_DRAFT_PICK_COLUMNS + [
        "expected_pick",
        "expected_pick_source",
        "expected_value_at_pick",
        "pick_value",
        "vor",
        "tier",
        "draft_score",
        "position_rank",
        "excluded_reason",
    ]

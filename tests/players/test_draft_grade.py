"""Tests for pick-level draft value grading (FFA-078).

All tests operate on small hand-built ``picks_df``/``board_df`` frames --
no HTTP calls, no live Sleeper/nflverse access -- matching
``test_draft_board.py``'s convention. ``board_df`` rows are plain dicts
shaped like ``DRAFT_BOARD_COLUMNS`` (no need to call the real
``build_draft_board()``); ``picks_df`` rows are plain dicts shaped like
``NORMALIZED_DRAFT_PICK_COLUMNS``.
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
    vor: float | None = None,
    tier: float | None = None,
    draft_score: float | None = None,
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
            "vor": vor,
            "tier": tier,
            "draft_score": draft_score,
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
    board = pd.DataFrame([_board_row("p1", adp_pool_rank=1.0)])
    result = score_draft_picks(picks, board)
    assert len(result) == 3


# ---------------------------------------------------------------------
# Toy example: pick_value = expected_pick - pick_no, both directions
# ---------------------------------------------------------------------


def test_toy_example_reach_and_steal() -> None:
    """pick_no=24, adp_pool_rank=10 -> expected_pick=10,
    pick_value = 10 - 24 = -14 (a 14-spot reach).

    pick_no=24, adp_pool_rank=40 -> expected_pick=40,
    pick_value = 40 - 24 = +16 (a 16-spot steal).
    """
    picks = pd.DataFrame(
        [
            _pick_row("reach_player", 24),
            _pick_row("steal_player", 24, roster_id=2, team_name="Team B"),
        ]
    )
    board = pd.DataFrame(
        [
            _board_row("reach_player", adp_pool_rank=10.0),
            _board_row("steal_player", adp_pool_rank=40.0),
        ]
    )
    result = score_draft_picks(picks, board)

    reach = _get(result, "reach_player")
    assert reach["expected_pick"] == pytest.approx(10.0)
    assert reach["expected_pick_source"] == "adp_pool_rank"
    assert reach["pick_value"] == pytest.approx(-14.0)

    steal = _get(result, "steal_player")
    assert steal["expected_pick"] == pytest.approx(40.0)
    assert steal["expected_pick_source"] == "adp_pool_rank"
    assert steal["pick_value"] == pytest.approx(16.0)


# ---------------------------------------------------------------------
# ADP fallback to draft_rank
# ---------------------------------------------------------------------


def test_expected_pick_falls_back_to_draft_rank_when_no_adp_pool_rank() -> None:
    picks = pd.DataFrame([_pick_row("no_adp_player", 20)])
    board = pd.DataFrame(
        [_board_row("no_adp_player", adp_pool_rank=float("nan"), draft_rank=15.0)]
    )
    result = score_draft_picks(picks, board)
    row = _get(result, "no_adp_player")
    assert row["expected_pick"] == pytest.approx(15.0)
    assert row["expected_pick_source"] == "draft_rank"
    assert row["pick_value"] == pytest.approx(15.0 - 20.0)


def test_expected_pick_prefers_adp_pool_rank_over_draft_rank_when_both_present() -> (
    None
):
    picks = pd.DataFrame([_pick_row("p1", 10)])
    board = pd.DataFrame([_board_row("p1", adp_pool_rank=8.0, draft_rank=25.0)])
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
    board = pd.DataFrame([_board_row("scored_player", adp_pool_rank=3.0)])
    result = score_draft_picks(picks, board)

    assert len(result) == 2
    row = _get(result, "unmatched_player")
    assert pd.isna(row["expected_pick"])
    assert row["expected_pick_source"] == "unscored"
    assert pd.isna(row["pick_value"])
    assert pd.isna(row["vor"])
    assert pd.isna(row["tier"])
    assert pd.isna(row["draft_score"])
    assert pd.isna(row["position_rank"])


def test_board_row_matched_but_both_ranks_missing_is_unscored() -> None:
    picks = pd.DataFrame([_pick_row("p1", 5)])
    board = pd.DataFrame(
        [_board_row("p1", adp_pool_rank=float("nan"), draft_rank=float("nan"))]
    )
    result = score_draft_picks(picks, board)
    row = _get(result, "p1")
    assert row["expected_pick_source"] == "unscored"
    assert pd.isna(row["pick_value"])


# ---------------------------------------------------------------------
# Keeper exclusion
# ---------------------------------------------------------------------


def test_keeper_forces_pick_value_and_vor_to_nan_and_sets_excluded_reason() -> None:
    picks = pd.DataFrame([_pick_row("keeper_player", 24, is_keeper=True)])
    board = pd.DataFrame(
        [
            _board_row(
                "keeper_player", adp_pool_rank=40.0, vor=5.5, tier=2.0, draft_score=1.2
            )
        ]
    )
    result = score_draft_picks(picks, board)
    row = _get(result, "keeper_player")

    # The board match would otherwise produce a real steal (40 - 24 = +16)
    # and a real vor -- both must be forced to NaN.
    assert pd.isna(row["pick_value"])
    assert pd.isna(row["vor"])
    assert row["excluded_reason"] == "keeper"
    # expected_pick/expected_pick_source are still computed (not suppressed).
    assert row["expected_pick"] == pytest.approx(40.0)
    assert row["expected_pick_source"] == "adp_pool_rank"
    # tier/draft_score/position_rank are unaffected by the keeper flag.
    assert row["tier"] == pytest.approx(2.0)
    assert row["draft_score"] == pytest.approx(1.2)


def test_non_keeper_picks_have_excluded_reason_none() -> None:
    picks = pd.DataFrame(
        [
            _pick_row("p1", 1, is_keeper=False),
            _pick_row("p2", 2, is_keeper=None),
        ]
    )
    board = pd.DataFrame(
        [_board_row("p1", adp_pool_rank=1.0), _board_row("p2", adp_pool_rank=2.0)]
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
            _pick_row("tie1", 20, roster_id=1, team_name="Team A"),
            _pick_row("tie2", 25, roster_id=2, team_name="Team B"),
        ]
    )
    # tie1: expected 30 -> 30-20=+10. tie2: expected 35 -> 35-25=+10.
    board = pd.DataFrame(
        [
            _board_row("tie1", adp_pool_rank=30.0),
            _board_row("tie2", adp_pool_rank=35.0),
        ]
    )
    result = score_draft_picks(picks, board)
    tie1 = _get(result, "tie1")
    tie2 = _get(result, "tie2")
    assert tie1["pick_value"] == pytest.approx(10.0)
    assert tie2["pick_value"] == pytest.approx(10.0)
    assert tie1["pick_value"] == pytest.approx(tie2["pick_value"])


# ---------------------------------------------------------------------
# Carried-through board columns
# ---------------------------------------------------------------------


def test_vor_tier_draft_score_position_rank_carried_through_verbatim() -> None:
    picks = pd.DataFrame([_pick_row("p1", 5)])
    board = pd.DataFrame(
        [
            _board_row(
                "p1",
                adp_pool_rank=3.0,
                vor=2.75,
                tier=1.0,
                draft_score=1.9,
                position_rank=4.0,
            )
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
            {
                **_board_row("p1", adp_pool_rank=3.0),
                "player_name": "Board Label",
                "position": "TE",
                "nfl_team": "ZZZ",
            }
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
    board = pd.DataFrame([_board_row("p1", adp_pool_rank=1.0)])
    result = score_draft_picks(picks, board)
    assert list(result.columns) == NORMALIZED_DRAFT_PICK_COLUMNS + [
        "expected_pick",
        "expected_pick_source",
        "pick_value",
        "vor",
        "tier",
        "draft_score",
        "position_rank",
        "excluded_reason",
    ]

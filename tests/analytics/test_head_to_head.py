"""Tests for building manager head-to-head records (FFA-040).

All tests operate on hand-built ``season_matchup_df``/``teams_df`` inputs --
no HTTP calls, no fixtures with opaque values -- so the expected
meetings/wins/losses/ties/avg_points numbers can be verified by hand
arithmetic in each test's docstring/comments, per AGENTS.md's
analytics-ticket requirement for a hand-checkable toy example.
"""

import pandas as pd
import pytest

from fantasy_analyzer.analytics import HEAD_TO_HEAD_COLUMNS, build_head_to_head_records
from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS


def _matchup_row(
    roster_1_id: int,
    roster_2_id: int | None,
    points_1: float | None,
    points_2: float | None,
    winner: int | None,
    loser: int | None,
    is_tie: bool = False,
    is_playoff: bool = False,
    week: int = 1,
    matchup_id: int | None = 1,
    season: str = "2025",
    owner_1: str | None = None,
    owner_2: str | None = None,
) -> dict:
    margin = None
    point_differential = None
    if points_1 is not None and points_2 is not None:
        point_differential = points_1 - points_2
        margin = abs(point_differential)
    return {
        "season": season,
        "week": week,
        "is_playoff": is_playoff,
        "matchup_id": matchup_id,
        "roster_1_id": roster_1_id,
        "roster_2_id": roster_2_id,
        "owner_1": owner_1,
        "owner_2": owner_2,
        "points_1": points_1,
        "points_2": points_2,
        "winner": winner,
        "loser": loser,
        "is_tie": is_tie,
        "margin": margin,
        "point_differential": point_differential,
    }


def _season_matchup_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=SEASON_MATCHUP_COLUMNS)
    return pd.DataFrame(rows, columns=SEASON_MATCHUP_COLUMNS)


def _teams_df(rows: list[dict]) -> pd.DataFrame:
    columns = ["roster_id", "owner_id", "display_name", "team_name"]
    return pd.DataFrame(rows, columns=columns)


def _team_row(roster_id: int, name: str) -> dict:
    return {
        "roster_id": roster_id,
        "owner_id": f"u{roster_id}",
        "display_name": name,
        "team_name": name,
    }


def _row(df: pd.DataFrame, roster_id: int, opponent_roster_id: int) -> pd.Series:
    is_roster = df["roster_id"] == roster_id
    is_opponent = df["opponent_roster_id"] == opponent_roster_id
    match = df.loc[is_roster & is_opponent]
    assert len(match) == 1
    return match.iloc[0]


def _toy_rows() -> list[dict]:
    """Three rosters, three weeks; roster 1 and roster 2 meet twice.

    Week 1: roster 1 (120.0) beats roster 2 (100.0).
    Week 2: roster 1 (90.0) ties roster 3 (90.0).
    Week 3: roster 2 (80.0) beats roster 1 (70.0) (a rematch: roster 1 is now
        ``roster_2_id`` in this row, exercising both directions of pairing).

    Hand-computed roster 1 vs roster 2 (two meetings, week 1 + week 3):
        wins=1, losses=1, ties=0
        total_points = 120.0 + 70.0 = 190.0 -> avg_points = 95.0
        total_opponent_points = 100.0 + 80.0 = 180.0 -> avg_opponent_points = 90.0

    Hand-computed roster 2 vs roster 1 (mirror of the above):
        wins=1, losses=1, ties=0
        total_points = 100.0 + 80.0 = 180.0 -> avg_points = 90.0
        total_opponent_points = 120.0 + 70.0 = 190.0 -> avg_opponent_points = 95.0

    Hand-computed roster 1 vs roster 3 (one meeting, week 2):
        wins=0, losses=0, ties=1
        total_points = 90.0, total_opponent_points = 90.0
        avg_points = avg_opponent_points = 90.0
    """
    return [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=120.0,
            points_2=100.0,
            winner=1,
            loser=2,
            week=1,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=3,
            points_1=90.0,
            points_2=90.0,
            winner=None,
            loser=None,
            is_tie=True,
            week=2,
            matchup_id=2,
        ),
        _matchup_row(
            roster_1_id=2,
            roster_2_id=1,
            points_1=80.0,
            points_2=70.0,
            winner=2,
            loser=1,
            week=3,
            matchup_id=3,
        ),
    ]


def test_toy_example_hand_computed() -> None:
    """Verifies roster 1 vs roster 2 (two meetings) and roster 1 vs roster 3
    (one meeting, a tie) match the hand computation in ``_toy_rows``'s
    docstring.
    """
    df = build_head_to_head_records(_season_matchup_df(_toy_rows()), _teams_df([]))

    assert list(df.columns) == HEAD_TO_HEAD_COLUMNS

    row_1v2 = _row(df, 1, 2)
    assert row_1v2["meetings"] == 2
    assert row_1v2["wins"] == 1
    assert row_1v2["losses"] == 1
    assert row_1v2["ties"] == 0
    assert row_1v2["total_points"] == pytest.approx(190.0)
    assert row_1v2["total_opponent_points"] == pytest.approx(180.0)
    assert row_1v2["avg_points"] == pytest.approx(95.0)
    assert row_1v2["avg_opponent_points"] == pytest.approx(90.0)

    row_1v3 = _row(df, 1, 3)
    assert row_1v3["meetings"] == 1
    assert row_1v3["wins"] == 0
    assert row_1v3["losses"] == 0
    assert row_1v3["ties"] == 1
    assert row_1v3["avg_points"] == pytest.approx(90.0)
    assert row_1v3["avg_opponent_points"] == pytest.approx(90.0)


def test_pair_is_directional_and_mirrored() -> None:
    """roster 1 vs roster 2 and roster 2 vs roster 1 are distinct rows with
    swapped roles/points, per the module's directional-shape design.
    """
    df = build_head_to_head_records(_season_matchup_df(_toy_rows()), _teams_df([]))

    row_1v2 = _row(df, 1, 2)
    row_2v1 = _row(df, 2, 1)

    assert row_1v2["meetings"] == row_2v1["meetings"] == 2
    assert row_1v2["wins"] == row_2v1["losses"] == 1
    assert row_1v2["losses"] == row_2v1["wins"] == 1
    assert row_1v2["total_points"] == pytest.approx(row_2v1["total_opponent_points"])
    assert row_1v2["total_opponent_points"] == pytest.approx(row_2v1["total_points"])
    assert row_1v2["avg_points"] == pytest.approx(row_2v1["avg_opponent_points"])


def test_tie_is_counted_for_both_rosters() -> None:
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=100.0,
            points_2=100.0,
            winner=None,
            loser=None,
            is_tie=True,
        )
    ]
    df = build_head_to_head_records(_season_matchup_df(rows), _teams_df([]))

    row_1v2 = _row(df, 1, 2)
    row_2v1 = _row(df, 2, 1)
    assert row_1v2["ties"] == 1
    assert row_2v1["ties"] == 1
    assert row_1v2["wins"] == row_1v2["losses"] == 0
    assert row_2v1["wins"] == row_2v1["losses"] == 0


def test_bye_row_excluded_and_does_not_pollute_other_pairs() -> None:
    """A bye row (no opponent) must not create a phantom pair, and must not
    affect the totals of a real meeting elsewhere in the season.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=120.0,
            points_2=100.0,
            winner=1,
            loser=2,
            week=1,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=3,
            roster_2_id=None,
            points_1=90.0,
            points_2=None,
            winner=None,
            loser=None,
            week=1,
            matchup_id=None,
        ),
    ]
    df = build_head_to_head_records(_season_matchup_df(rows), _teams_df([]))

    # No pair involving roster 3 exists at all.
    assert not (df["roster_id"] == 3).any()
    assert not (df["opponent_roster_id"] == 3).any()

    # roster 1 vs roster 2 is unaffected by the bye row.
    row_1v2 = _row(df, 1, 2)
    assert row_1v2["meetings"] == 1
    assert row_1v2["total_points"] == pytest.approx(120.0)


def test_missing_points_counts_meeting_but_not_win_loss_tie_or_points() -> None:
    """A row with a present opponent but missing points (e.g. an unloaded
    week) still counts toward meetings for both rosters, but -- since
    outcomes.py never derives a winner/loser/tie without both scores --
    contributes to none of wins/losses/ties, and contributes nothing to the
    points sums.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=None,
            points_2=None,
            winner=None,
            loser=None,
            is_tie=False,
            week=1,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=120.0,
            points_2=100.0,
            winner=1,
            loser=2,
            week=2,
            matchup_id=2,
        ),
    ]
    df = build_head_to_head_records(_season_matchup_df(rows), _teams_df([]))

    row_1v2 = _row(df, 1, 2)
    assert row_1v2["meetings"] == 2
    assert row_1v2["wins"] == 1
    assert row_1v2["losses"] == 0
    assert row_1v2["ties"] == 0
    # Only week 2's points are known and summed.
    assert row_1v2["total_points"] == pytest.approx(120.0)
    assert row_1v2["total_opponent_points"] == pytest.approx(100.0)
    assert row_1v2["avg_points"] == pytest.approx(60.0)  # 120.0 / 2 meetings


def test_empty_season_matchup_df_returns_empty_frame_with_columns() -> None:
    df = build_head_to_head_records(_season_matchup_df([]), _teams_df([]))

    assert df.empty
    assert list(df.columns) == HEAD_TO_HEAD_COLUMNS


def test_all_bye_season_returns_empty_frame_with_columns() -> None:
    """A non-empty season_matchup_df made entirely of bye rows has zero
    real meetings between any two rosters -- the result is empty, not an
    error, and still has the expected columns.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=None,
            points_1=55.5,
            points_2=None,
            winner=None,
            loser=None,
            matchup_id=None,
        )
    ]
    df = build_head_to_head_records(_season_matchup_df(rows), _teams_df([]))

    assert df.empty
    assert list(df.columns) == HEAD_TO_HEAD_COLUMNS


def test_unmapped_owner_gets_none_rather_than_raising() -> None:
    """roster 2 has no row in teams_df -- should not crash the join."""
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=120.0,
            points_2=100.0,
            winner=1,
            loser=2,
        )
    ]
    teams_df = _teams_df([_team_row(1, "Alec")])

    df = build_head_to_head_records(_season_matchup_df(rows), teams_df)

    row_1v2 = _row(df, 1, 2)
    row_2v1 = _row(df, 2, 1)
    assert row_1v2["owner"] == "Alec"
    assert row_1v2["opponent_owner"] is None
    assert row_2v1["owner"] is None
    assert row_2v1["opponent_owner"] == "Alec"


def test_playoff_and_regular_season_rows_are_combined() -> None:
    """FFA-040 combines all rows regardless of ``is_playoff`` -- splitting by
    phase is deferred to FFA-044.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=120.0,
            points_2=100.0,
            winner=1,
            loser=2,
            week=1,
            matchup_id=1,
            is_playoff=False,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=90.0,
            points_2=110.0,
            winner=2,
            loser=1,
            week=16,
            matchup_id=1,
            is_playoff=True,
        ),
    ]
    df = build_head_to_head_records(_season_matchup_df(rows), _teams_df([]))

    row_1v2 = _row(df, 1, 2)
    assert row_1v2["meetings"] == 2
    assert row_1v2["wins"] == 1
    assert row_1v2["losses"] == 1


def test_row_sort_order_is_by_roster_id_then_opponent_roster_id() -> None:
    rows = [
        _matchup_row(
            roster_1_id=3,
            roster_2_id=1,
            points_1=100.0,
            points_2=90.0,
            winner=3,
            loser=1,
            week=1,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=2,
            roster_2_id=1,
            points_1=100.0,
            points_2=90.0,
            winner=2,
            loser=1,
            week=2,
            matchup_id=2,
        ),
    ]
    df = build_head_to_head_records(_season_matchup_df(rows), _teams_df([]))

    pairs = list(zip(df["roster_id"], df["opponent_roster_id"]))
    assert pairs == sorted(pairs)

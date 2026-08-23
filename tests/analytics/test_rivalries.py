"""Tests for rivalry margin and scoring statistics (FFA-042).

All tests operate on hand-built ``season_matchup_df``/``teams_df`` inputs --
no HTTP calls, no fixtures with opaque values -- so every expected
avg_margin / closest game / largest win / largest loss / highest scoring
matchup can be verified by hand arithmetic against the toy season described
in ``_toy_rows``, per AGENTS.md's analytics-ticket requirement for a
hand-checkable toy example.

The helpers mirror ``test_head_to_head.py``'s so the two suites build
identical input shapes.
"""

import math

import pandas as pd
import pytest

from fantasy_analyzer.analytics import (
    RIVALRY_COLUMNS,
    RivalryGame,
    build_head_to_head_records,
    build_rivalry_records,
)
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
    """Three rosters, four weeks; rosters 1 and 2 meet three times.

    Week 1: roster 1 (120.0) beats roster 2 (100.0) -- margin 20.0,
        combined 220.0.
    Week 2: roster 1 (90.0) ties roster 3 (90.0) -- margin 0.0,
        combined 180.0.
    Week 3: roster 2 (80.0) beats roster 1 (70.0) -- margin 10.0,
        combined 150.0. (A rematch with roster 1 as ``roster_2_id``, so both
        pairing directions are exercised.)
    Week 4: roster 1 (130.0) beats roster 2 (95.5) -- margin 34.5,
        combined 225.5.

    Hand-computed rivalry 1 vs 2 (three scored meetings: weeks 1, 3, 4):
        avg_margin = (20.0 + 10.0 + 34.5) / 3 = 64.5 / 3 = 21.5
        closest_game            = week 3 (margin 10.0, the smallest)
        largest_win  (roster 1) = week 4 (margin 34.5 > week 1's 20.0)
        largest_loss (roster 1) = week 3 (its only loss, margin 10.0)
        highest_scoring_matchup = week 4 (225.5 > 220.0 > 150.0)

    Hand-computed rivalry 2 vs 1 (the mirror; same games, flipped roles):
        avg_margin = 21.5 (margin is a magnitude, so it is perspective-free)
        closest_game            = week 3 (same game, now roster 2's 80.0)
        largest_win  (roster 2) = week 3 (its only win, margin 10.0)
        largest_loss (roster 2) = week 4 (margin 34.5)
        highest_scoring_matchup = week 4 (same game, combined 225.5)

    Hand-computed rivalry 1 vs 3 (one scored meeting, a tie):
        avg_margin = 0.0 / 1 = 0.0
        closest_game            = week 2 (margin 0.0)
        largest_win             = None (a tie is neither a win...)
        largest_loss            = None (...nor a loss)
        highest_scoring_matchup = week 2 (combined 180.0)
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
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=130.0,
            points_2=95.5,
            winner=1,
            loser=2,
            week=4,
            matchup_id=4,
        ),
    ]


def test_toy_example_hand_computed() -> None:
    """Rivalry 1 vs 2 matches the hand computation in ``_toy_rows``."""
    df = build_rivalry_records(_season_matchup_df(_toy_rows()), _teams_df([]))

    assert list(df.columns) == RIVALRY_COLUMNS

    row = _row(df, 1, 2)
    assert row["meetings"] == 3
    assert row["scored_meetings"] == 3
    assert row["avg_margin"] == pytest.approx(21.5)

    closest = row["closest_game"]
    assert isinstance(closest, RivalryGame)
    assert closest.week == 3
    assert closest.margin == pytest.approx(10.0)
    assert closest.points == pytest.approx(70.0)
    assert closest.opponent_points == pytest.approx(80.0)
    assert closest.combined_points == pytest.approx(150.0)
    assert closest.roster_id == 1
    assert closest.opponent_roster_id == 2
    assert closest.season == "2025"
    assert closest.matchup_id == 3
    assert closest.is_playoff is False

    largest_win = row["largest_win"]
    assert largest_win.week == 4
    assert largest_win.margin == pytest.approx(34.5)
    assert largest_win.points == pytest.approx(130.0)

    largest_loss = row["largest_loss"]
    assert largest_loss.week == 3
    assert largest_loss.margin == pytest.approx(10.0)
    assert largest_loss.points == pytest.approx(70.0)

    highest = row["highest_scoring_matchup"]
    assert highest.week == 4
    assert highest.combined_points == pytest.approx(225.5)


def test_mirror_perspective_swaps_win_and_loss() -> None:
    """Rivalry 2 vs 1 is the mirror of 1 vs 2: same games, flipped roles,
    identical (unsigned) avg_margin -- per the hand computation in
    ``_toy_rows``.
    """
    df = build_rivalry_records(_season_matchup_df(_toy_rows()), _teams_df([]))

    row_1v2 = _row(df, 1, 2)
    row_2v1 = _row(df, 2, 1)

    assert row_2v1["avg_margin"] == pytest.approx(row_1v2["avg_margin"])
    assert row_2v1["avg_margin"] == pytest.approx(21.5)

    # A's largest win is B's largest loss, and vice versa.
    assert row_2v1["largest_loss"].week == row_1v2["largest_win"].week == 4
    assert row_2v1["largest_win"].week == row_1v2["largest_loss"].week == 3
    assert row_2v1["largest_loss"].margin == pytest.approx(34.5)
    assert row_2v1["largest_win"].margin == pytest.approx(10.0)

    # Same game, points reported from roster 2's perspective.
    assert row_2v1["largest_win"].points == pytest.approx(80.0)
    assert row_2v1["largest_win"].opponent_points == pytest.approx(70.0)

    # Combined score and closest game are perspective-free.
    assert row_2v1["closest_game"].week == row_1v2["closest_game"].week
    assert row_2v1["highest_scoring_matchup"].combined_points == pytest.approx(
        row_1v2["highest_scoring_matchup"].combined_points
    )


def test_tie_only_rivalry_has_no_largest_win_or_loss() -> None:
    """Rivalry 1 vs 3 in the toy season is a single tie: it has a closest
    game and a highest scoring matchup, avg_margin 0.0, and no largest
    win/loss for either side.
    """
    df = build_rivalry_records(_season_matchup_df(_toy_rows()), _teams_df([]))

    for roster_id, opponent_roster_id in ((1, 3), (3, 1)):
        row = _row(df, roster_id, opponent_roster_id)
        assert row["scored_meetings"] == 1
        assert row["avg_margin"] == pytest.approx(0.0)
        assert row["closest_game"].week == 2
        assert row["closest_game"].margin == pytest.approx(0.0)
        assert row["highest_scoring_matchup"].combined_points == pytest.approx(180.0)
        assert row["largest_win"] is None
        assert row["largest_loss"] is None


def test_tie_beats_a_narrow_win_for_closest_game() -> None:
    """A tie has margin 0.0 and is eligible for -- and always wins --
    closest game.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=100.5,
            points_2=100.0,
            winner=1,
            loser=2,
            week=1,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=99.0,
            points_2=99.0,
            winner=None,
            loser=None,
            is_tie=True,
            week=2,
            matchup_id=2,
        ),
    ]
    df = build_rivalry_records(_season_matchup_df(rows), _teams_df([]))

    row = _row(df, 1, 2)
    # avg_margin = (0.5 + 0.0) / 2 = 0.25
    assert row["avg_margin"] == pytest.approx(0.25)
    assert row["closest_game"].week == 2
    assert row["closest_game"].margin == pytest.approx(0.0)
    # The tie is not a win or a loss for either side.
    assert row["largest_win"].week == 1
    assert row["largest_loss"] is None


def test_avg_margin_is_absolute_not_net() -> None:
    """A 30-point win and a 30-point loss average to a 30.0 margin, not to
    0.0 -- avg_margin is the mean absolute margin, not the net differential.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=130.0,
            points_2=100.0,
            winner=1,
            loser=2,
            week=1,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=100.0,
            points_2=130.0,
            winner=2,
            loser=1,
            week=2,
            matchup_id=2,
        ),
    ]
    df = build_rivalry_records(_season_matchup_df(rows), _teams_df([]))

    assert _row(df, 1, 2)["avg_margin"] == pytest.approx(30.0)
    assert _row(df, 2, 1)["avg_margin"] == pytest.approx(30.0)


def test_highest_scoring_uses_combined_total_not_own_points() -> None:
    """Week 1 has roster 1's own highest score (150.0) but a lower combined
    total (190.0) than week 2's 100.0 + 95.0 = 195.0.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=150.0,
            points_2=40.0,
            winner=1,
            loser=2,
            week=1,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=100.0,
            points_2=95.0,
            winner=1,
            loser=2,
            week=2,
            matchup_id=2,
        ),
    ]
    df = build_rivalry_records(_season_matchup_df(rows), _teams_df([]))

    row = _row(df, 1, 2)
    assert row["highest_scoring_matchup"].week == 2
    assert row["highest_scoring_matchup"].combined_points == pytest.approx(195.0)


def test_equal_extrema_resolve_to_the_earliest_game() -> None:
    """Two identical 10.0-margin wins: the earlier row wins the tiebreak."""
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=110.0,
            points_2=100.0,
            winner=1,
            loser=2,
            week=1,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=110.0,
            points_2=100.0,
            winner=1,
            loser=2,
            week=5,
            matchup_id=5,
        ),
    ]
    df = build_rivalry_records(_season_matchup_df(rows), _teams_df([]))

    row = _row(df, 1, 2)
    assert row["closest_game"].week == 1
    assert row["largest_win"].week == 1
    assert row["highest_scoring_matchup"].week == 1
    assert row["avg_margin"] == pytest.approx(10.0)


def test_missing_points_meeting_excluded_from_margin_and_scoring_stats() -> None:
    """A meeting with missing points counts toward ``meetings`` but not
    ``scored_meetings``, and contributes to no margin or scoring statistic.
    Critically, it is not treated as a 0.0-0.0 game: avg_margin is the one
    scored game's margin (20.0), not 20.0 / 2 meetings, and the closest game
    is not a phantom 0.0-margin blank.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=None,
            points_2=None,
            winner=None,
            loser=None,
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
    df = build_rivalry_records(_season_matchup_df(rows), _teams_df([]))

    row = _row(df, 1, 2)
    assert row["meetings"] == 2
    assert row["scored_meetings"] == 1
    assert row["avg_margin"] == pytest.approx(20.0)
    assert row["closest_game"].week == 2
    assert row["closest_game"].margin == pytest.approx(20.0)
    assert row["largest_win"].week == 2
    assert row["largest_loss"] is None
    assert row["highest_scoring_matchup"].combined_points == pytest.approx(220.0)


def test_rivalry_with_only_missing_points_meetings_keeps_row_but_no_stats() -> None:
    """The pair did meet, so the row exists (matching FFA-040), but no
    statistic is defined: avg_margin is NaN and all four game columns are
    None rather than fabricated zeros.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=None,
            points_2=None,
            winner=None,
            loser=None,
            week=1,
            matchup_id=1,
        )
    ]
    df = build_rivalry_records(_season_matchup_df(rows), _teams_df([]))

    row = _row(df, 1, 2)
    assert row["meetings"] == 1
    assert row["scored_meetings"] == 0
    assert math.isnan(row["avg_margin"])
    assert row["closest_game"] is None
    assert row["largest_win"] is None
    assert row["largest_loss"] is None
    assert row["highest_scoring_matchup"] is None


def test_one_sided_rivalry_has_no_largest_loss() -> None:
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
        )
    ]
    df = build_rivalry_records(_season_matchup_df(rows), _teams_df([]))

    row_1v2 = _row(df, 1, 2)
    assert row_1v2["largest_win"].margin == pytest.approx(20.0)
    assert row_1v2["largest_loss"] is None

    row_2v1 = _row(df, 2, 1)
    assert row_2v1["largest_win"] is None
    assert row_2v1["largest_loss"].margin == pytest.approx(20.0)


def test_bye_row_excluded_and_does_not_pollute_other_rivalries() -> None:
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
    df = build_rivalry_records(_season_matchup_df(rows), _teams_df([]))

    assert not (df["roster_id"] == 3).any()
    assert not (df["opponent_roster_id"] == 3).any()

    row = _row(df, 1, 2)
    assert row["meetings"] == 1
    assert row["scored_meetings"] == 1
    assert row["avg_margin"] == pytest.approx(20.0)


def test_pair_that_never_met_has_no_row() -> None:
    """Rosters 2 and 3 both appear in the season but never play each other,
    so no ``(2, 3)`` row is emitted -- there is no zero-meetings row.
    """
    df = build_rivalry_records(_season_matchup_df(_toy_rows()), _teams_df([]))

    pairs = set(zip(df["roster_id"], df["opponent_roster_id"]))
    assert (2, 3) not in pairs
    assert (3, 2) not in pairs
    assert pairs == {(1, 2), (2, 1), (1, 3), (3, 1)}


def test_empty_season_matchup_df_returns_empty_frame_with_columns() -> None:
    df = build_rivalry_records(_season_matchup_df([]), _teams_df([]))

    assert df.empty
    assert list(df.columns) == RIVALRY_COLUMNS


def test_all_bye_season_returns_empty_frame_with_columns() -> None:
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
    df = build_rivalry_records(_season_matchup_df(rows), _teams_df([]))

    assert df.empty
    assert list(df.columns) == RIVALRY_COLUMNS


def test_playoff_and_regular_season_games_are_combined_and_flagged() -> None:
    """FFA-042 applies no phase filter (splitting is FFA-044's job), so a
    playoff game is eligible to be an extremum -- and ``is_playoff`` is
    carried on the reported game.
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
            points_1=150.0,
            points_2=90.0,
            winner=1,
            loser=2,
            week=16,
            matchup_id=1,
            is_playoff=True,
        ),
    ]
    df = build_rivalry_records(_season_matchup_df(rows), _teams_df([]))

    row = _row(df, 1, 2)
    assert row["meetings"] == 2
    assert row["scored_meetings"] == 2
    # avg_margin = (20.0 + 60.0) / 2 = 40.0
    assert row["avg_margin"] == pytest.approx(40.0)
    assert row["largest_win"].week == 16
    assert row["largest_win"].is_playoff is True
    assert row["closest_game"].week == 1
    assert row["closest_game"].is_playoff is False


def test_unmapped_owner_gets_none_rather_than_raising() -> None:
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

    df = build_rivalry_records(_season_matchup_df(rows), teams_df)

    row_1v2 = _row(df, 1, 2)
    row_2v1 = _row(df, 2, 1)
    assert row_1v2["owner"] == "Alec"
    assert row_1v2["opponent_owner"] is None
    assert row_2v1["owner"] is None
    assert row_2v1["opponent_owner"] == "Alec"


def test_row_sort_order_is_by_roster_id_then_opponent_roster_id() -> None:
    df = build_rivalry_records(_season_matchup_df(_toy_rows()), _teams_df([]))

    pairs = list(zip(df["roster_id"], df["opponent_roster_id"]))
    assert pairs == sorted(pairs)


def test_meetings_agrees_with_head_to_head_records() -> None:
    """``meetings`` is defined identically to FFA-040's, so the two frames
    agree row-for-row on the same input (including the missing-points
    meeting, which both count).
    """
    rows = _toy_rows() + [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=None,
            points_2=None,
            winner=None,
            loser=None,
            week=5,
            matchup_id=5,
        )
    ]
    season_matchup_df = _season_matchup_df(rows)

    rivalries = build_rivalry_records(season_matchup_df, _teams_df([]))
    head_to_head = build_head_to_head_records(season_matchup_df, _teams_df([]))

    merged = rivalries.merge(
        head_to_head[["roster_id", "opponent_roster_id", "meetings"]],
        on=["roster_id", "opponent_roster_id"],
        suffixes=("", "_h2h"),
    )
    assert len(merged) == len(rivalries) == len(head_to_head)
    assert (merged["meetings"] == merged["meetings_h2h"]).all()
    # The extra missing-points week is a meeting but not a scored meeting.
    row = _row(rivalries, 1, 2)
    assert row["meetings"] == 4
    assert row["scored_meetings"] == 3

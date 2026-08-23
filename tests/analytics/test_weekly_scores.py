"""Tests for weekly scores and weekly scoring ranks (FFA-050).

All tests operate on hand-built ``season_matchup_df``/``teams_df`` inputs --
no HTTP calls, no fixtures with opaque values -- so the expected ranks can be
verified by hand arithmetic in each test's docstring/comments, per AGENTS.md's
analytics-ticket requirement for a hand-checkable toy example.
"""

import pandas as pd
import pytest

from fantasy_analyzer.analytics import (
    WEEKLY_SCORING_RANK_COLUMNS,
    build_weekly_scoring_ranks,
)
from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS


def _matchup_row(
    roster_1_id: int,
    roster_2_id: int | None,
    points_1: float | None,
    points_2: float | None,
    winner: int | None = None,
    loser: int | None = None,
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


def _row(df: pd.DataFrame, week: int, roster_id: int) -> pd.Series:
    match = df.loc[(df["week"] == week) & (df["roster_id"] == roster_id)]
    assert len(match) == 1
    return match.iloc[0]


def _toy_rows() -> list[dict]:
    """Four rosters, two weeks; one week has a tie, the other a bye.

    Week 1 (two normal matchups):
        roster 1 = 120.0, roster 2 = 100.0, roster 3 = 100.0, roster 4 = 90.0

    Week 2 (one normal matchup, one bye, one missing-points bye):
        roster 1 = 80.0, roster 2 = 95.0, roster 3 = 110.0 (bye -- a real
        score with no opponent), roster 4 = missing points (unloaded).

    Hand-computed week 1 ranks (descending points, "1224" ranking):
        120.0 -> roster 1 -> rank 1
        100.0 -> rosters 2 and 3 tie -> both rank 2
         90.0 -> roster 4 -> rank 4 (rank 3 is skipped by the two-way tie)

    Hand-computed week 2 ranks (three scored rosters; roster 4 is excluded
    entirely because it has no defined score, and is NOT ranked last):
        110.0 -> roster 3 (the bye) -> rank 1
         95.0 -> roster 2 -> rank 2
         80.0 -> roster 1 -> rank 3

    Total rows: 4 (week 1) + 3 (week 2) = 7.
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
            roster_1_id=3,
            roster_2_id=4,
            points_1=100.0,
            points_2=90.0,
            winner=3,
            loser=4,
            week=1,
            matchup_id=2,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=80.0,
            points_2=95.0,
            winner=2,
            loser=1,
            week=2,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=3,
            roster_2_id=None,
            points_1=110.0,
            points_2=None,
            week=2,
            matchup_id=None,
        ),
        _matchup_row(
            roster_1_id=4,
            roster_2_id=None,
            points_1=None,
            points_2=None,
            week=2,
            matchup_id=None,
        ),
    ]


def test_toy_example_hand_computed() -> None:
    """Verifies the full week 1 / week 2 rank assignment hand-computed in
    ``_toy_rows``'s docstring, including the week 1 tie and the week 2 bye.
    """
    df = build_weekly_scoring_ranks(_season_matchup_df(_toy_rows()), _teams_df([]))

    assert list(df.columns) == WEEKLY_SCORING_RANK_COLUMNS
    assert len(df) == 7

    assert _row(df, 1, 1)["weekly_rank"] == 1
    assert _row(df, 1, 2)["weekly_rank"] == 2
    assert _row(df, 1, 3)["weekly_rank"] == 2
    assert _row(df, 1, 4)["weekly_rank"] == 4

    assert _row(df, 2, 3)["weekly_rank"] == 1
    assert _row(df, 2, 2)["weekly_rank"] == 2
    assert _row(df, 2, 1)["weekly_rank"] == 3

    assert _row(df, 1, 1)["points"] == pytest.approx(120.0)
    assert _row(df, 2, 3)["points"] == pytest.approx(110.0)


def test_normal_row_contributes_two_observations_bye_contributes_one() -> None:
    """The wide -> long reshape: two rosters per normal row, one per bye."""
    rows = [
        _matchup_row(
            roster_1_id=1, roster_2_id=2, points_1=100.0, points_2=90.0, week=1
        ),
        _matchup_row(
            roster_1_id=3,
            roster_2_id=None,
            points_1=80.0,
            points_2=None,
            week=1,
            matchup_id=None,
        ),
    ]
    df = build_weekly_scoring_ranks(_season_matchup_df(rows), _teams_df([]))

    assert len(df) == 3
    assert sorted(df["roster_id"]) == [1, 2, 3]


def test_bye_score_is_ranked_alongside_matchup_scores() -> None:
    """A bye is a real score with no opponent, so it competes for rank 1 --
    the one place FFA-050 diverges from FFA-040/FFA-042's exclude-byes rule.
    """
    rows = [
        _matchup_row(
            roster_1_id=1, roster_2_id=2, points_1=100.0, points_2=90.0, week=1
        ),
        _matchup_row(
            roster_1_id=3,
            roster_2_id=None,
            points_1=150.0,
            points_2=None,
            week=1,
            matchup_id=None,
        ),
    ]
    df = build_weekly_scoring_ranks(_season_matchup_df(rows), _teams_df([]))

    # The bye roster outscored everyone and takes rank 1, pushing the two
    # rosters that actually played each other to ranks 2 and 3.
    assert _row(df, 1, 3)["weekly_rank"] == 1
    assert _row(df, 1, 1)["weekly_rank"] == 2
    assert _row(df, 1, 2)["weekly_rank"] == 3


def test_missing_points_observation_is_excluded_not_zero() -> None:
    """A roster-week with no defined score gets no row at all, and must not be
    ranked last as though it had scored 0.0.
    """
    rows = [
        _matchup_row(
            roster_1_id=1, roster_2_id=2, points_1=None, points_2=None, week=1
        ),
        _matchup_row(
            roster_1_id=3,
            roster_2_id=4,
            points_1=100.0,
            points_2=90.0,
            week=1,
            matchup_id=2,
        ),
    ]
    df = build_weekly_scoring_ranks(_season_matchup_df(rows), _teams_df([]))

    assert sorted(df["roster_id"]) == [3, 4]
    assert not (df["points"] == 0.0).any()
    # The surviving field is ranked densely 1..2.
    assert _row(df, 1, 3)["weekly_rank"] == 1
    assert _row(df, 1, 4)["weekly_rank"] == 2


def test_partial_matchup_keeps_the_side_with_a_defined_score() -> None:
    """Exclusion is per observation, not per source row: when only one side's
    points are missing, the other side is still ranked.
    """
    rows = [
        _matchup_row(
            roster_1_id=1, roster_2_id=2, points_1=100.0, points_2=None, week=1
        )
    ]
    df = build_weekly_scoring_ranks(_season_matchup_df(rows), _teams_df([]))

    assert list(df["roster_id"]) == [1]
    assert _row(df, 1, 1)["weekly_rank"] == 1


def test_all_missing_points_returns_empty_frame_with_columns() -> None:
    rows = [
        _matchup_row(roster_1_id=1, roster_2_id=2, points_1=None, points_2=None, week=1)
    ]
    df = build_weekly_scoring_ranks(_season_matchup_df(rows), _teams_df([]))

    assert df.empty
    assert list(df.columns) == WEEKLY_SCORING_RANK_COLUMNS


def test_three_way_tie_shares_rank_and_skips_to_four() -> None:
    """Standard competition ("1224") ranking: three rosters tied at 100.0 all
    get rank 1, and the next roster gets rank 4, not rank 2.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=100.0,
            points_2=100.0,
            is_tie=True,
            week=1,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=3,
            roster_2_id=4,
            points_1=100.0,
            points_2=50.0,
            winner=3,
            loser=4,
            week=1,
            matchup_id=2,
        ),
    ]
    df = build_weekly_scoring_ranks(_season_matchup_df(rows), _teams_df([]))

    assert _row(df, 1, 1)["weekly_rank"] == 1
    assert _row(df, 1, 2)["weekly_rank"] == 1
    assert _row(df, 1, 3)["weekly_rank"] == 1
    assert _row(df, 1, 4)["weekly_rank"] == 4


def test_single_roster_week_ranks_first() -> None:
    """A degenerate week with exactly one scored roster must not crash and
    trivially ranks that roster 1st.
    """
    rows = [
        _matchup_row(
            roster_1_id=7,
            roster_2_id=None,
            points_1=42.0,
            points_2=None,
            week=1,
            matchup_id=None,
        )
    ]
    df = build_weekly_scoring_ranks(_season_matchup_df(rows), _teams_df([]))

    assert len(df) == 1
    assert _row(df, 1, 7)["weekly_rank"] == 1


def test_empty_season_matchup_df_returns_empty_frame_with_columns() -> None:
    df = build_weekly_scoring_ranks(_season_matchup_df([]), _teams_df([]))

    assert df.empty
    assert list(df.columns) == WEEKLY_SCORING_RANK_COLUMNS


def test_weeks_are_ranked_independently() -> None:
    """The same score ranks differently in different weeks -- ranks are
    computed within a week, never across the season.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=100.0,
            points_2=110.0,
            winner=2,
            loser=1,
            week=1,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=100.0,
            points_2=90.0,
            winner=1,
            loser=2,
            week=2,
            matchup_id=1,
        ),
    ]
    df = build_weekly_scoring_ranks(_season_matchup_df(rows), _teams_df([]))

    assert _row(df, 1, 1)["weekly_rank"] == 2
    assert _row(df, 2, 1)["weekly_rank"] == 1


def test_same_week_number_in_two_seasons_is_ranked_separately() -> None:
    """``(season, week)`` -- not ``week`` alone -- is the grouping key."""
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=100.0,
            points_2=90.0,
            week=1,
            season="2024",
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=80.0,
            points_2=70.0,
            week=1,
            season="2025",
        ),
    ]
    df = build_weekly_scoring_ranks(_season_matchup_df(rows), _teams_df([]))

    assert len(df) == 4
    # Both seasons' week 1 have their own rank 1 / rank 2, rather than the
    # 2024 scores outranking the 2025 scores in one combined pool.
    for season in ("2024", "2025"):
        season_rows = df.loc[df["season"] == season]
        assert sorted(season_rows["weekly_rank"]) == [1, 2]


def test_playoff_rows_are_ranked_within_their_week_and_flag_carried_through() -> None:
    """FFA-050 makes no phase distinction: a playoff week is ranked like any
    other week, and ``is_playoff`` rides along as an informational column.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=100.0,
            points_2=90.0,
            winner=1,
            loser=2,
            week=1,
            matchup_id=1,
            is_playoff=False,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=80.0,
            points_2=120.0,
            winner=2,
            loser=1,
            week=16,
            matchup_id=1,
            is_playoff=True,
        ),
    ]
    df = build_weekly_scoring_ranks(_season_matchup_df(rows), _teams_df([]))

    assert bool(_row(df, 1, 1)["is_playoff"]) is False
    assert bool(_row(df, 16, 1)["is_playoff"]) is True
    # The week 16 playoff scores are ranked among themselves, not dropped and
    # not merged into week 1's field.
    assert _row(df, 16, 2)["weekly_rank"] == 1
    assert _row(df, 16, 1)["weekly_rank"] == 2


def test_unmapped_owner_gets_none_rather_than_raising() -> None:
    """roster 2 has no row in teams_df -- should not crash the lookup, and
    must stay ``None`` rather than being coerced to ``NaN``.
    """
    rows = [
        _matchup_row(
            roster_1_id=1, roster_2_id=2, points_1=100.0, points_2=90.0, week=1
        )
    ]
    teams_df = _teams_df([_team_row(1, "Alec")])

    df = build_weekly_scoring_ranks(_season_matchup_df(rows), teams_df)

    assert _row(df, 1, 1)["owner"] == "Alec"
    assert _row(df, 1, 2)["owner"] is None


def test_output_is_sorted_by_season_week_then_rank() -> None:
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=80.0,
            points_2=95.0,
            week=2,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=120.0,
            points_2=100.0,
            week=1,
            matchup_id=1,
        ),
    ]
    df = build_weekly_scoring_ranks(_season_matchup_df(rows), _teams_df([]))

    assert list(zip(df["week"], df["weekly_rank"])) == [(1, 1), (1, 2), (2, 1), (2, 2)]


def test_duplicate_roster_week_raises() -> None:
    """A roster cannot play two matchups in one week; a malformed input that
    says otherwise is rejected rather than double-ranked.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=100.0,
            points_2=90.0,
            week=1,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=3,
            points_1=110.0,
            points_2=95.0,
            week=1,
            matchup_id=2,
        ),
    ]

    with pytest.raises(ValueError, match="cannot play twice"):
        build_weekly_scoring_ranks(_season_matchup_df(rows), _teams_df([]))

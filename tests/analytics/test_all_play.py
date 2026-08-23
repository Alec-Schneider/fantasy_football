"""Tests for all-play standings (FFA-051).

All tests operate on hand-built inputs -- no HTTP calls, no opaque fixture
values -- so every expected win/loss/tie count can be verified by hand
arithmetic from the scores written in each test, per AGENTS.md's
analytics-ticket requirement for a hand-checkable toy example.

Most tests build a ``weekly_scoring_ranks_df``-shaped frame directly, so this
ticket's aggregation is isolated from FFA-050's own reshaping/ranking
correctness. One test
(:func:`test_composes_with_build_weekly_scoring_ranks`) goes through the real
:func:`~fantasy_analyzer.analytics.weekly_scores.build_weekly_scoring_ranks`
to confirm the two functions compose end to end.
"""

import pandas as pd
import pytest

from fantasy_analyzer.analytics import (
    ALL_PLAY_STANDINGS_COLUMNS,
    WEEKLY_SCORING_RANK_COLUMNS,
    build_all_play_standings,
    build_weekly_scoring_ranks,
)
from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS


def _score_row(
    roster_id: int,
    points: float | None,
    week: int = 1,
    weekly_rank: int | None = 1,
    season: str = "2025",
    is_playoff: bool = False,
    owner: str | None = None,
) -> dict:
    """One ``WEEKLY_SCORING_RANK_COLUMNS``-shaped roster-week observation.

    ``weekly_rank`` is carried for shape fidelity only -- ``build_all_play_
    standings`` never reads it -- so tests may leave it at its default rather
    than hand-computing a rank that has no bearing on the assertion.
    """
    return {
        "season": season,
        "week": week,
        "is_playoff": is_playoff,
        "roster_id": roster_id,
        "owner": owner,
        "points": points,
        "weekly_rank": weekly_rank,
    }


def _weekly_scores_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=WEEKLY_SCORING_RANK_COLUMNS)
    frame = pd.DataFrame(rows, columns=WEEKLY_SCORING_RANK_COLUMNS)
    # Keep ``owner`` as object dtype so an unresolved ``None`` stays ``None``
    # rather than being inferred into a string dtype's ``NaN`` -- the same
    # contract FFA-050's real output honors.
    frame["owner"] = pd.Series(frame["owner"].tolist(), dtype=object)
    return frame


def _week(rows: dict[int, float], week: int = 1, season: str = "2025") -> list[dict]:
    """Shorthand for one week's field: ``{roster_id: points}``."""
    return [
        _score_row(roster_id=roster_id, points=points, week=week, season=season)
        for roster_id, points in rows.items()
    ]


def _row(df: pd.DataFrame, roster_id: int) -> pd.Series:
    match = df.loc[df["roster_id"] == roster_id]
    assert len(match) == 1
    return match.iloc[0]


def _toy_rows() -> list[dict]:
    """Four rosters, two weeks; week 1 contains a tie, week 2 a short field.

    Week 1 (all four rosters scored):
        roster 1 = 120.0, roster 2 = 100.0, roster 3 = 100.0, roster 4 = 90.0

    Week 2 (roster 4 has no defined score, so it has no row at all --
    field size 3, not 4):
        roster 1 = 80.0, roster 2 = 95.0, roster 3 = 110.0

    Hand-computed week 1 all-play (each roster vs. the other three):
        roster 1 (120): beats 100, 100, 90            -> 3-0-0
        roster 2 (100): loses to 120, ties 100, beats 90 -> 1-1-1
        roster 3 (100): loses to 120, ties 100, beats 90 -> 1-1-1
        roster 4  (90): loses to 120, 100, 100        -> 0-3-0
        Check: 6 unordered pairs -> (5 wins + 5 losses + 2 ties) / 2 = 6.

    Hand-computed week 2 all-play (each roster vs. the other two):
        roster 3 (110): beats 95, 80  -> 2-0-0
        roster 2  (95): loses to 110, beats 80 -> 1-1-0
        roster 1  (80): loses to 110, 95 -> 0-2-0
        roster 4: no row -> no comparisons, and no credit to anyone against it.

    Hand-computed season totals (weeks_played, W-L-T, games, win_pct):
        roster 1: 2 weeks, 3-2-0, 5 games, 3/5             = 0.6
        roster 2: 2 weeks, 2-2-1, 5 games, (2 + 0.5)/5     = 0.5
        roster 3: 2 weeks, 3-1-1, 5 games, (3 + 0.5)/5     = 0.7
        roster 4: 1 week,  0-3-0, 3 games, 0/3             = 0.0

    Hand-computed ranks (descending win_pct): 3 -> 1, 1 -> 2, 2 -> 3, 4 -> 4.
    """
    return _week({1: 120.0, 2: 100.0, 3: 100.0, 4: 90.0}, week=1) + _week(
        {1: 80.0, 2: 95.0, 3: 110.0}, week=2
    )


def test_toy_example_hand_computed() -> None:
    """Verifies every season total hand-computed in ``_toy_rows``'s docstring."""
    df = build_all_play_standings(_weekly_scores_df(_toy_rows()))

    assert list(df.columns) == ALL_PLAY_STANDINGS_COLUMNS
    assert len(df) == 4

    expected = {
        # roster_id: (weeks_played, wins, losses, ties, games, win_pct, rank)
        1: (2, 3, 2, 0, 5, 0.6, 2),
        2: (2, 2, 2, 1, 5, 0.5, 3),
        3: (2, 3, 1, 1, 5, 0.7, 1),
        4: (1, 0, 3, 0, 3, 0.0, 4),
    }
    for roster_id, (weeks, wins, losses, ties, games, pct, rank) in expected.items():
        row = _row(df, roster_id)
        assert row["weeks_played"] == weeks
        assert row["all_play_wins"] == wins
        assert row["all_play_losses"] == losses
        assert row["all_play_ties"] == ties
        assert row["all_play_games"] == games
        assert row["all_play_win_pct"] == pytest.approx(pct)
        assert row["all_play_rank"] == rank

    # Sorted by descending win_pct.
    assert list(df["roster_id"]) == [3, 1, 2, 4]


def test_all_play_record_is_schedule_independent() -> None:
    """The point of the metric: a roster that lost its actual matchup can
    still have the week's best all-play record.

    Week 1 field: roster 1 = 130.0, roster 2 = 140.0, roster 3 = 90.0,
    roster 4 = 85.0. Roster 1 lost its scheduled matchup to roster 2 but
    still went 2-1-0 all-play, better than rosters 3 and 4 who both went
    worse despite roster 3 having beaten roster 4.
    """
    df = build_all_play_standings(
        _weekly_scores_df(_week({1: 130.0, 2: 140.0, 3: 90.0, 4: 85.0}))
    )

    assert (_row(df, 1)["all_play_wins"], _row(df, 1)["all_play_losses"]) == (2, 1)
    assert (_row(df, 2)["all_play_wins"], _row(df, 2)["all_play_losses"]) == (3, 0)
    assert (_row(df, 3)["all_play_wins"], _row(df, 3)["all_play_losses"]) == (1, 2)
    assert (_row(df, 4)["all_play_wins"], _row(df, 4)["all_play_losses"]) == (0, 3)


def test_tie_is_mutual_not_a_win_and_a_loss() -> None:
    """Two rosters with identical scores each get a tie -- neither gets a win
    or a loss from that pairing.

    Week 1: roster 1 = 100.0, roster 2 = 100.0, roster 3 = 90.0.
        roster 1: ties roster 2, beats roster 3  -> 1-0-1
        roster 2: ties roster 1, beats roster 3  -> 1-0-1
        roster 3: loses twice                    -> 0-2-0
    """
    df = build_all_play_standings(
        _weekly_scores_df(_week({1: 100.0, 2: 100.0, 3: 90.0}))
    )

    for roster_id in (1, 2):
        row = _row(df, roster_id)
        assert (row["all_play_wins"], row["all_play_losses"], row["all_play_ties"]) == (
            1,
            0,
            1,
        )
        # (1 + 0.5 * 1) / 2 = 0.75
        assert row["all_play_win_pct"] == pytest.approx(0.75)

    row_3 = _row(df, 3)
    assert (
        row_3["all_play_wins"],
        row_3["all_play_losses"],
        row_3["all_play_ties"],
    ) == (0, 2, 0)


def test_three_way_tie_at_the_top_of_a_five_roster_week() -> None:
    """A tie group larger than two: three rosters at 100.0 in a five-roster
    week each tie the other two and beat the two lower scores.

    Week 1: rosters 1, 2, 3 = 100.0; roster 4 = 90.0; roster 5 = 80.0.
        rosters 1-3: 2 wins (over 90, 80), 0 losses, 2 ties -> (2 + 1)/4 = 0.75
        roster 4: beats 80, loses to three 100s            -> 1-3-0 = 0.25
        roster 5: loses to everyone                        -> 0-4-0 = 0.0
    """
    df = build_all_play_standings(
        _weekly_scores_df(_week({1: 100.0, 2: 100.0, 3: 100.0, 4: 90.0, 5: 80.0}))
    )

    for roster_id in (1, 2, 3):
        row = _row(df, roster_id)
        assert (row["all_play_wins"], row["all_play_losses"], row["all_play_ties"]) == (
            2,
            0,
            2,
        )
        assert row["all_play_win_pct"] == pytest.approx(0.75)

    assert _row(df, 4)["all_play_win_pct"] == pytest.approx(0.25)
    assert _row(df, 5)["all_play_win_pct"] == pytest.approx(0.0)


def test_tied_win_pct_shares_rank_and_skips_the_next() -> None:
    """Standard competition ("1224") ranking on ``all_play_win_pct``: the
    three rosters tied at 0.75 above all get rank 1 and the next roster gets
    rank 4, not rank 2.
    """
    df = build_all_play_standings(
        _weekly_scores_df(_week({1: 100.0, 2: 100.0, 3: 100.0, 4: 90.0, 5: 80.0}))
    )

    assert _row(df, 1)["all_play_rank"] == 1
    assert _row(df, 2)["all_play_rank"] == 1
    assert _row(df, 3)["all_play_rank"] == 1
    assert _row(df, 4)["all_play_rank"] == 4
    assert _row(df, 5)["all_play_rank"] == 5


def test_league_wide_wins_equal_losses_and_ties_are_even() -> None:
    """Structural invariant: every all-play win for one roster is exactly one
    all-play loss for another, and a tie is credited to both sides -- so
    across the whole league the totals must balance.

    Uses a three-week input mixing a full field, a short field, and a tie.
    """
    rows = (
        _week({1: 120.0, 2: 100.0, 3: 100.0, 4: 90.0}, week=1)
        + _week({1: 80.0, 2: 95.0, 3: 110.0}, week=2)
        + _week({1: 70.0, 2: 70.0, 3: 70.0, 4: 130.0}, week=3)
    )
    df = build_all_play_standings(_weekly_scores_df(rows))

    assert df["all_play_wins"].sum() == df["all_play_losses"].sum()
    assert df["all_play_ties"].sum() % 2 == 0
    # Total comparisons = 2 * (pairs per week summed): C(4,2) + C(3,2) + C(4,2)
    # = 6 + 3 + 6 = 15 unordered pairs -> 30 directional all-play games.
    assert df["all_play_games"].sum() == 30


def test_field_size_varies_so_all_play_games_can_differ_by_roster() -> None:
    """A roster absent from a week accumulates no comparisons that week, and
    the rosters that did play compare against a smaller field.

    Week 1 field size 4 (3 comparisons each); week 2 field size 2 (1 each,
    and only for rosters 1 and 2).
    """
    rows = _week({1: 100.0, 2: 90.0, 3: 80.0, 4: 70.0}, week=1) + _week(
        {1: 60.0, 2: 50.0}, week=2
    )
    df = build_all_play_standings(_weekly_scores_df(rows))

    assert _row(df, 1)["all_play_games"] == 4  # 3 + 1
    assert _row(df, 2)["all_play_games"] == 4  # 3 + 1
    assert _row(df, 3)["all_play_games"] == 3  # week 1 only
    assert _row(df, 4)["all_play_games"] == 3
    assert _row(df, 1)["weeks_played"] == 2
    assert _row(df, 3)["weeks_played"] == 1


def test_single_roster_week_contributes_no_comparisons() -> None:
    """Field size 1: nobody to compare against, so the week adds a
    ``weeks_played`` but zero all-play games -- and no self-comparison.

    Week 1: roster 1 alone at 100.0. Week 2: rosters 1 and 2 both score.
        roster 1: 2 weeks played, but only the week-2 comparison -> 1 game.
    """
    rows = _week({1: 100.0}, week=1) + _week({1: 110.0, 2: 90.0}, week=2)
    df = build_all_play_standings(_weekly_scores_df(rows))

    row_1 = _row(df, 1)
    assert row_1["weeks_played"] == 2
    assert row_1["all_play_games"] == 1
    assert row_1["all_play_wins"] == 1
    assert row_1["all_play_win_pct"] == pytest.approx(1.0)


def test_only_week_has_field_size_one_gives_zero_games_and_zero_pct() -> None:
    """The one legitimate zero-games case: a roster whose only scored week had
    nobody else in it. ``all_play_win_pct`` falls back to ``0.0`` rather than
    dividing by zero or returning ``NaN``.
    """
    df = build_all_play_standings(_weekly_scores_df(_week({7: 42.0})))

    assert len(df) == 1
    row = _row(df, 7)
    assert row["weeks_played"] == 1
    assert row["all_play_games"] == 0
    assert row["all_play_win_pct"] == 0.0
    assert row["all_play_rank"] == 1


def test_roster_with_no_scored_week_is_absent_from_the_output() -> None:
    """Rows are input-driven: a roster that never appears in
    ``weekly_scoring_ranks_df`` gets no row at all, not an all-zero row.
    """
    df = build_all_play_standings(_weekly_scores_df(_week({1: 100.0, 2: 90.0})))

    assert sorted(df["roster_id"]) == [1, 2]
    assert 3 not in set(df["roster_id"])


def test_missing_points_row_is_skipped_not_treated_as_zero() -> None:
    """FFA-050 never emits one, but a missing score in a hand-built input is
    dropped entirely: it earns nobody an all-play win against it, and does not
    count toward its own ``weeks_played``.
    """
    rows = _week({1: 100.0, 2: 90.0}, week=1) + [
        _score_row(roster_id=3, points=None, week=1)
    ]
    df = build_all_play_standings(_weekly_scores_df(rows))

    assert sorted(df["roster_id"]) == [1, 2]
    # Roster 1 beat only roster 2 -- roster 3's missing score is not a 0.0 win.
    assert _row(df, 1)["all_play_wins"] == 1
    assert _row(df, 1)["all_play_games"] == 1


def test_all_missing_points_returns_empty_frame_with_columns() -> None:
    rows = [_score_row(roster_id=1, points=None), _score_row(roster_id=2, points=None)]
    df = build_all_play_standings(_weekly_scores_df(rows))

    assert df.empty
    assert list(df.columns) == ALL_PLAY_STANDINGS_COLUMNS


def test_empty_input_returns_empty_frame_with_columns() -> None:
    df = build_all_play_standings(_weekly_scores_df([]))

    assert df.empty
    assert list(df.columns) == ALL_PLAY_STANDINGS_COLUMNS


def test_weeks_are_compared_independently() -> None:
    """Comparisons never cross weeks: a 200.0 in week 2 does not beat a 100.0
    from week 1.

    Week 1: roster 1 = 100.0, roster 2 = 110.0 (roster 1 loses).
    Week 2: roster 1 = 200.0, roster 2 = 210.0 (roster 1 loses again).
    Roster 1 is 0-2 all-play despite outscoring both week-1 scores in week 2.
    """
    rows = _week({1: 100.0, 2: 110.0}, week=1) + _week({1: 200.0, 2: 210.0}, week=2)
    df = build_all_play_standings(_weekly_scores_df(rows))

    assert (_row(df, 1)["all_play_wins"], _row(df, 1)["all_play_losses"]) == (0, 2)
    assert (_row(df, 2)["all_play_wins"], _row(df, 2)["all_play_losses"]) == (2, 0)


def test_same_week_number_in_two_seasons_is_compared_separately() -> None:
    """``(season, week)`` -- not ``week`` alone -- is the grouping key."""
    rows = _week({1: 100.0, 2: 90.0}, week=1, season="2024") + _week(
        {3: 80.0, 4: 70.0}, week=1, season="2025"
    )
    df = build_all_play_standings(_weekly_scores_df(rows))

    # If the two seasons were pooled, each roster would have 3 games instead
    # of 1, and the 2024 scores would outrank the 2025 ones.
    assert set(df["all_play_games"]) == {1}
    assert _row(df, 3)["all_play_wins"] == 1
    assert _row(df, 3)["all_play_win_pct"] == pytest.approx(1.0)


def test_playoff_and_regular_season_weeks_are_combined() -> None:
    """No phase filter: a playoff week's scores are aggregated alongside the
    regular season's into one combined record.

    Week 1 (regular): roster 1 = 100.0, roster 2 = 90.0  -> roster 1 wins.
    Week 16 (playoff): roster 1 = 80.0, roster 2 = 120.0 -> roster 1 loses.
    Combined, roster 1 is 1-1-0 with 2 all-play games.
    """
    rows = _week({1: 100.0, 2: 90.0}, week=1) + [
        _score_row(roster_id=1, points=80.0, week=16, is_playoff=True),
        _score_row(roster_id=2, points=120.0, week=16, is_playoff=True),
    ]
    df = build_all_play_standings(_weekly_scores_df(rows))

    row_1 = _row(df, 1)
    assert (row_1["all_play_wins"], row_1["all_play_losses"]) == (1, 1)
    assert row_1["all_play_games"] == 2
    assert row_1["weeks_played"] == 2
    assert "is_playoff" not in df.columns


def test_caller_can_get_a_phase_specific_view_by_filtering_the_input() -> None:
    """The documented way to get a regular-season-only all-play record: filter
    ``weekly_scoring_ranks_df`` on ``is_playoff`` before calling.
    """
    rows = _week({1: 100.0, 2: 90.0}, week=1) + [
        _score_row(roster_id=1, points=80.0, week=16, is_playoff=True),
        _score_row(roster_id=2, points=120.0, week=16, is_playoff=True),
    ]
    frame = _weekly_scores_df(rows)

    regular = build_all_play_standings(frame.loc[~frame["is_playoff"]])
    playoffs = build_all_play_standings(frame.loc[frame["is_playoff"]])

    assert (_row(regular, 1)["all_play_wins"], _row(regular, 1)["all_play_losses"]) == (
        1,
        0,
    )
    assert (
        _row(playoffs, 1)["all_play_wins"],
        _row(playoffs, 1)["all_play_losses"],
    ) == (0, 1)


def test_owner_is_read_from_the_input_and_unresolved_stays_none() -> None:
    """``owner`` comes from FFA-050's already-resolved column; a roster with
    no resolved owner stays ``None`` rather than becoming ``NaN`` or raising.
    """
    rows = [
        _score_row(roster_id=1, points=100.0, week=1, owner="Alec"),
        _score_row(roster_id=2, points=90.0, week=1, owner=None),
        _score_row(roster_id=1, points=95.0, week=2, owner="Alec"),
        _score_row(roster_id=2, points=99.0, week=2, owner=None),
    ]
    df = build_all_play_standings(_weekly_scores_df(rows))

    assert _row(df, 1)["owner"] == "Alec"
    assert _row(df, 2)["owner"] is None


def test_output_is_sorted_by_win_pct_then_roster_id() -> None:
    """Deterministic display order; the ``roster_id`` tiebreak orders tied
    rosters without separating their shared rank.
    """
    rows = _week({3: 100.0, 1: 100.0, 2: 50.0})
    df = build_all_play_standings(_weekly_scores_df(rows))

    assert list(df["roster_id"]) == [1, 3, 2]
    assert list(df["all_play_rank"]) == [1, 1, 3]


def test_composes_with_build_weekly_scoring_ranks() -> None:
    """End-to-end: a real ``season_matchup_df`` -> FFA-050 -> FFA-051.

    Week 1: roster 1 (120.0) beat roster 2 (100.0); roster 3 (110.0) beat
    roster 4 (90.0). Hand-computed all-play for the single week:
        roster 1 (120): 3-0-0
        roster 3 (110): 2-1-0
        roster 2 (100): 1-2-0
        roster 4  (90): 0-3-0
    Roster 2 lost its actual matchup but still beat roster 4's score, and
    roster 3 won its matchup while ranking behind roster 1 on all-play.
    """
    matchup_rows = [
        {
            "season": "2025",
            "week": 1,
            "is_playoff": False,
            "matchup_id": 1,
            "roster_1_id": 1,
            "roster_2_id": 2,
            "owner_1": "Alec",
            "owner_2": "Mike",
            "points_1": 120.0,
            "points_2": 100.0,
            "winner": 1,
            "loser": 2,
            "is_tie": False,
            "margin": 20.0,
            "point_differential": 20.0,
        },
        {
            "season": "2025",
            "week": 1,
            "is_playoff": False,
            "matchup_id": 2,
            "roster_1_id": 3,
            "roster_2_id": 4,
            "owner_1": "Joe",
            "owner_2": "Sam",
            "points_1": 110.0,
            "points_2": 90.0,
            "winner": 3,
            "loser": 4,
            "is_tie": False,
            "margin": 20.0,
            "point_differential": 20.0,
        },
    ]
    season_matchup_df = pd.DataFrame(matchup_rows, columns=SEASON_MATCHUP_COLUMNS)
    teams_df = pd.DataFrame(
        [
            {
                "roster_id": roster_id,
                "owner_id": f"u{roster_id}",
                "display_name": name,
                "team_name": name,
            }
            for roster_id, name in [(1, "Alec"), (2, "Mike"), (3, "Joe"), (4, "Sam")]
        ],
        columns=["roster_id", "owner_id", "display_name", "team_name"],
    )

    weekly = build_weekly_scoring_ranks(season_matchup_df, teams_df)
    df = build_all_play_standings(weekly)

    assert list(df["roster_id"]) == [1, 3, 2, 4]
    assert list(df["all_play_wins"]) == [3, 2, 1, 0]
    assert list(df["all_play_losses"]) == [0, 1, 2, 3]
    assert list(df["all_play_rank"]) == [1, 2, 3, 4]
    assert _row(df, 1)["owner"] == "Alec"
    # FFA-050's weekly_rank agrees with the all-play ordering for a week with
    # no tied scores -- a cross-check that the two modules see the same field.
    week_1_ranks = dict(zip(weekly["roster_id"], weekly["weekly_rank"]))
    assert week_1_ranks == {1: 1, 3: 2, 2: 3, 4: 4}

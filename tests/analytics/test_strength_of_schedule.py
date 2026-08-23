"""Tests for strength of schedule (FFA-054).

All tests operate on hand-built ``season_matchup_df``/``teams_df`` inputs --
no HTTP calls, no fixtures with opaque values -- so every average-opponent
number can be verified by hand arithmetic from the scores written in the
test, per AGENTS.md's analytics-ticket requirement for a hand-checkable toy
example.

Like FFA-052's tests, these cannot shortcut the upstream frame: the whole
point of
:func:`~fantasy_analyzer.analytics.strength_of_schedule.build_strength_of_schedule`
is that it derives both the opponent-strength table and the opponent list
from one shared ``season_matchup_df``, so every test builds real matchup rows
and exercises the full ``build_schedule_luck`` composition beneath it.
"""

import inspect

import pandas as pd
import pytest

from fantasy_analyzer.analytics import (
    STRENGTH_OF_SCHEDULE_COLUMNS,
    build_strength_of_schedule,
)
from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS


def _game(
    roster_1_id: int,
    roster_2_id: int | None,
    points_1: float | None,
    points_2: float | None,
    week: int = 1,
    matchup_id: int | None = 1,
    is_playoff: bool = False,
    season: str = "2025",
) -> dict:
    """One ``SEASON_MATCHUP_COLUMNS`` row with outcome fields derived by hand.

    Mirrors :mod:`fantasy_analyzer.matchups.outcomes`' rules exactly: a
    matchup with a missing opponent or a missing score has no winner, no
    loser, no tie, and no margin. Pass ``roster_2_id=None`` for a bye.
    """
    winner: int | None = None
    loser: int | None = None
    is_tie = False
    margin: float | None = None
    point_differential: float | None = None

    if roster_2_id is not None and points_1 is not None and points_2 is not None:
        point_differential = points_1 - points_2
        margin = abs(point_differential)
        if points_1 > points_2:
            winner, loser = roster_1_id, roster_2_id
        elif points_1 < points_2:
            winner, loser = roster_2_id, roster_1_id
        else:
            is_tie = True

    return {
        "season": season,
        "week": week,
        "is_playoff": is_playoff,
        "matchup_id": matchup_id,
        "roster_1_id": roster_1_id,
        "roster_2_id": roster_2_id,
        "owner_1": None,
        "owner_2": None,
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


def _teams_df(names: dict[int, str | None]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "roster_id": roster_id,
                "owner_id": f"u{roster_id}",
                "display_name": name,
                "team_name": name,
            }
            for roster_id, name in names.items()
        ],
        columns=["roster_id", "owner_id", "display_name", "team_name"],
    )


def _empty_teams_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["roster_id", "owner_id", "display_name", "team_name"])


def _row(df: pd.DataFrame, roster_id: int) -> pd.Series:
    match = df.loc[df["roster_id"] == roster_id]
    assert len(match) == 1
    return match.iloc[0]


_FOUR_TEAMS = {1: "Alec", 2: "Mike", 3: "Joe", 4: "Sam"}


# --------------------------------------------------------------------------
# Toy example 1 -- full round robin, hand computed
# --------------------------------------------------------------------------


def _round_robin_rows() -> list[dict]:
    """Four rosters, three weeks, a full single round robin.

    Every roster scores the same value every week -- roster 1: 130, roster 2:
    120, roster 3: 110, roster 4: 100 -- so the stronger roster always wins
    and the actual and all-play orderings coincide exactly:

        week 1: (1 vs 2), (3 vs 4)
        week 2: (1 vs 3), (2 vs 4)
        week 3: (1 vs 4), (2 vs 3)

    Actual records: roster 1 3-0, roster 2 2-1, roster 3 1-2, roster 4 0-3, so
    ``win_pct`` is 1, 2/3, 1/3, 0. Each week's all-play field is the same four
    scores, giving roster 1 3-0, roster 2 2-1, roster 3 1-2, roster 4 0-3 per
    week -- 9 all-play games each over three weeks, so ``all_play_win_pct`` is
    also 1, 2/3, 1/3, 0.

    Because every roster plays every other exactly once, each roster's
    schedule is "everyone but itself", and the averages are:

        roster 1 faces 2, 3, 4 -> (2/3 + 1/3 + 0) / 3 = 1/3
        roster 2 faces 1, 3, 4 -> (1   + 1/3 + 0) / 3 = 4/9
        roster 3 faces 1, 2, 4 -> (1   + 2/3 + 0) / 3 = 5/9
        roster 4 faces 1, 2, 3 -> (1   + 2/3 + 1/3) / 3 = 2/3

    identically for both the ``win_pct`` and the ``all_play_win_pct`` variant,
    since the two underlying columns are equal here. Rank 1 (toughest) is
    therefore roster 4 and rank 4 (easiest) is roster 1 -- the mechanical
    "you never have to play yourself" artifact the module docstring warns
    about, shown at its most extreme.
    """
    return [
        _game(1, 2, 130.0, 120.0, week=1, matchup_id=1),
        _game(3, 4, 110.0, 100.0, week=1, matchup_id=2),
        _game(1, 3, 130.0, 110.0, week=2, matchup_id=1),
        _game(2, 4, 120.0, 100.0, week=2, matchup_id=2),
        _game(1, 4, 130.0, 100.0, week=3, matchup_id=1),
        _game(2, 3, 120.0, 110.0, week=3, matchup_id=2),
    ]


def test_round_robin_hand_computed() -> None:
    """Verifies every number hand-computed in ``_round_robin_rows``' docstring."""
    df = build_strength_of_schedule(
        _season_matchup_df(_round_robin_rows()), _teams_df(_FOUR_TEAMS)
    )

    assert list(df.columns) == STRENGTH_OF_SCHEDULE_COLUMNS
    assert len(df) == 4

    expected = {1: 1 / 3, 2: 4 / 9, 3: 5 / 9, 4: 2 / 3}
    for roster_id, average in expected.items():
        row = _row(df, roster_id)
        assert row["opponent_weeks"] == 3
        assert row["unresolved_opponent_weeks"] == 0
        assert row["avg_opponent_win_pct"] == pytest.approx(average)
        # The two variants coincide in this scenario by construction.
        assert row["avg_opponent_all_play_win_pct"] == pytest.approx(average)


def test_rank_one_is_the_toughest_schedule() -> None:
    """Rank 1 = highest average opponent strength = hardest schedule.

    In the round robin the undefeated roster 1 has the *weakest* schedule
    (1/3) and the winless roster 4 the *strongest* (2/3), so rank 1 goes to
    roster 4. This pins down the rank direction, which is the single most
    misreadable thing about this metric.
    """
    df = build_strength_of_schedule(
        _season_matchup_df(_round_robin_rows()), _teams_df(_FOUR_TEAMS)
    )

    assert list(df["roster_id"]) == [4, 3, 2, 1]
    assert list(df["sos_rank"]) == [1, 2, 3, 4]
    assert list(df["all_play_sos_rank"]) == [1, 2, 3, 4]
    assert _row(df, 4)["sos_rank"] == 1  # toughest, not "best off"
    assert _row(df, 1)["sos_rank"] == 4


# --------------------------------------------------------------------------
# Toy example 2 -- where the two variants disagree, and a tied rank
# --------------------------------------------------------------------------


def _lucky_opponent_rows() -> list[dict]:
    """Four rosters, two identical weeks, with one lucky and one unlucky team.

    Both weeks are the same field and the same pairings:

        roster 1 100.0 beat roster 4 70.0
        roster 2  90.0 beat roster 3 80.0

    Actual records after two weeks: roster 1 2-0, roster 2 2-0, roster 3 0-2,
    roster 4 0-2, so ``win_pct`` is 1.0, 1.0, 0.0, 0.0.

    The all-play field each week is 100, 90, 80, 70, giving roster 1 3-0,
    roster 2 2-1, roster 3 1-2, roster 4 0-3 per week -- 6 all-play games each
    over two weeks, so ``all_play_win_pct`` is 1.0, 2/3, 1/3, 0.0.

    Roster 2 is therefore **lucky**: a perfect 1.0 record on only 2/3 scoring
    strength, because the schedule handed it the third-best scorer twice.
    Roster 3 is the mirror image: 0.0 despite 1/3 scoring strength.

    Each roster faces the same opponent both weeks, so its averages are just
    that opponent's two strength numbers:

        roster 1 faces 4, 4 -> win_pct 0.0, all_play 0.0
        roster 2 faces 3, 3 -> win_pct 0.0, all_play 1/3
        roster 3 faces 2, 2 -> win_pct 1.0, all_play 2/3
        roster 4 faces 1, 1 -> win_pct 1.0, all_play 1.0

    This is the case the module docstring argues for reporting both variants.
    Rosters 3 and 4 are **tied** at 1.0 on ``avg_opponent_win_pct`` -- both
    faced an opponent with a perfect record -- and share ``sos_rank`` 1. But
    roster 3's opponent was the *lucky* roster 2, whose scoring was only 2/3,
    while roster 4's opponent was the genuinely dominant roster 1. On
    ``avg_opponent_all_play_win_pct`` they separate: roster 4 = 1.0 (rank 1),
    roster 3 = 2/3 (rank 2). Rosters 1 and 2 tie at 0.0 on the actual-record
    variant and separate the same way (roster 2's opponent 1/3, roster 1's
    0.0), giving ``all_play_sos_rank`` 3 and 4 respectively.
    """
    return [
        _game(1, 4, 100.0, 70.0, week=1, matchup_id=1),
        _game(2, 3, 90.0, 80.0, week=1, matchup_id=2),
        _game(1, 4, 100.0, 70.0, week=2, matchup_id=1),
        _game(2, 3, 90.0, 80.0, week=2, matchup_id=2),
    ]


def test_both_variants_hand_computed_and_disagree() -> None:
    """Verifies every number hand-computed in ``_lucky_opponent_rows``' docstring.

    The point of the scenario: rosters 3 and 4 look identically hard-done-by
    on ``avg_opponent_win_pct`` (both 1.0) and are clearly separated on
    ``avg_opponent_all_play_win_pct`` (2/3 vs 1.0), because roster 3's
    opponent's perfect record was itself luck.
    """
    df = build_strength_of_schedule(
        _season_matchup_df(_lucky_opponent_rows()), _teams_df(_FOUR_TEAMS)
    )

    expected = {
        # roster_id: (avg_opponent_win_pct, avg_opponent_all_play_win_pct)
        1: (0.0, 0.0),
        2: (0.0, 1 / 3),
        3: (1.0, 2 / 3),
        4: (1.0, 1.0),
    }
    for roster_id, (win_pct, all_play_win_pct) in expected.items():
        row = _row(df, roster_id)
        assert row["opponent_weeks"] == 2
        assert row["unresolved_opponent_weeks"] == 0
        assert row["avg_opponent_win_pct"] == pytest.approx(win_pct)
        assert row["avg_opponent_all_play_win_pct"] == pytest.approx(all_play_win_pct)

    # The two variants really do disagree about rosters 3 and 4.
    assert _row(df, 3)["avg_opponent_win_pct"] == _row(df, 4)["avg_opponent_win_pct"]
    assert _row(df, 3)["avg_opponent_all_play_win_pct"] != pytest.approx(
        _row(df, 4)["avg_opponent_all_play_win_pct"]
    )


def test_tied_averages_share_a_rank_and_each_column_ranks_independently() -> None:
    """Standard competition ("1224") ranking, applied to each column separately.

    ``avg_opponent_win_pct`` is 1.0, 1.0, 0.0, 0.0 for rosters 3, 4, 1, 2, so
    rosters 3 and 4 share ``sos_rank`` 1 and the next distinct rank skips to
    3. ``all_play_sos_rank`` is computed over its own column and has no ties
    at all: 4, 3, 2, 1 -> ranks 1, 2, 3, 4. Rows are ordered by descending
    ``avg_opponent_win_pct`` then ascending ``roster_id``.
    """
    df = build_strength_of_schedule(
        _season_matchup_df(_lucky_opponent_rows()), _teams_df(_FOUR_TEAMS)
    )

    assert list(df["roster_id"]) == [3, 4, 1, 2]
    assert list(df["sos_rank"]) == [1, 1, 3, 3]
    assert list(df["all_play_sos_rank"]) == [2, 1, 4, 3]


# --------------------------------------------------------------------------
# Byes, missing points, and unresolvable opponents
# --------------------------------------------------------------------------


def test_bye_week_is_not_an_opponent_week_at_all() -> None:
    """A bye has no opponent, so it counts toward neither counter.

    Roster 1 gets a week-3 bye at 95.0 on top of ``_lucky_opponent_rows``.
    Its ``opponent_weeks`` stays 2 and its ``unresolved_opponent_weeks`` stays
    0 -- a bye is not an unresolved opponent, it is no opponent. The bye also
    leaves every strength number untouched (a one-roster week produces no
    all-play comparison and no decision), so roster 1's averages are the same
    0.0/0.0 as without it.
    """
    rows = _lucky_opponent_rows() + [
        _game(1, None, 95.0, None, week=3, matchup_id=None)
    ]
    df = build_strength_of_schedule(_season_matchup_df(rows), _teams_df(_FOUR_TEAMS))

    row = _row(df, 1)
    assert row["opponent_weeks"] == 2
    assert row["unresolved_opponent_weeks"] == 0
    assert row["avg_opponent_win_pct"] == pytest.approx(0.0)
    assert row["avg_opponent_all_play_win_pct"] == pytest.approx(0.0)


def test_bye_only_roster_is_absent_from_the_output() -> None:
    """Zero opponent-weeks -> no row, not a 0.0 row that reads as "easiest".

    Roster 5's only appearance is a week-3 bye, so it never faced anyone.
    """
    rows = _lucky_opponent_rows() + [
        _game(5, None, 95.0, None, week=3, matchup_id=None)
    ]
    df = build_strength_of_schedule(
        _season_matchup_df(rows), _teams_df({**_FOUR_TEAMS, 5: "Pat"})
    )

    assert sorted(df["roster_id"]) == [1, 2, 3, 4]


def test_missing_points_with_a_real_opponent_still_counts() -> None:
    """An unloaded week has no score but still has a known opponent.

    Adding an unscored week-3 roster 1 vs roster 2 matchup to
    ``_lucky_opponent_rows`` changes no strength number (no score, no
    decision, so neither ``derive_roster_totals`` nor the all-play chain sees
    it) but does add a third opponent-week to both rosters:

        roster 1 now faces 4, 4, 2 -> win_pct (0 + 0 + 1) / 3 = 1/3
                                      all_play (0 + 0 + 2/3) / 3 = 2/9
        roster 2 now faces 3, 3, 1 -> win_pct (0 + 0 + 1) / 3 = 1/3
                                      all_play (1/3 + 1/3 + 1) / 3 = 5/9

    Contrast the bye test above: there the row was skipped entirely, because
    a bye has no opponent, whereas here the opponent is perfectly well known.
    """
    rows = _lucky_opponent_rows() + [_game(1, 2, None, None, week=3, matchup_id=1)]
    df = build_strength_of_schedule(_season_matchup_df(rows), _teams_df(_FOUR_TEAMS))

    first = _row(df, 1)
    assert first["opponent_weeks"] == 3
    assert first["unresolved_opponent_weeks"] == 0
    assert first["avg_opponent_win_pct"] == pytest.approx(1 / 3)
    assert first["avg_opponent_all_play_win_pct"] == pytest.approx(2 / 9)

    second = _row(df, 2)
    assert second["opponent_weeks"] == 3
    assert second["avg_opponent_win_pct"] == pytest.approx(1 / 3)
    assert second["avg_opponent_all_play_win_pct"] == pytest.approx(5 / 9)

    # Rosters 3 and 4 were not in the unscored week and are unchanged.
    assert _row(df, 3)["opponent_weeks"] == 2
    assert _row(df, 4)["opponent_weeks"] == 2


def test_unresolvable_opponent_is_skipped_from_the_average_but_counted() -> None:
    """A real opponent with no strength of its own is skipped, not guessed at.

    Roster 5 appears only in an unscored week-3 matchup against roster 1, so
    it has zero decided games and ``build_schedule_luck`` emits no row for it
    -- its strength is unknown. Roster 1's week 3 therefore lands in
    ``unresolved_opponent_weeks`` rather than in the average, leaving its
    ``opponent_weeks`` at 2 and its averages at the unchanged 0.0/0.0.

    Roster 5 itself still gets a row: it *did* face a resolvable opponent
    (roster 1, ``win_pct`` 1.0 and ``all_play_win_pct`` 1.0), so its schedule
    is well defined even though its own season is not. Rows come from the
    opponent scan, not from the strength table.
    """
    rows = _lucky_opponent_rows() + [_game(1, 5, None, None, week=3, matchup_id=3)]
    df = build_strength_of_schedule(
        _season_matchup_df(rows), _teams_df({**_FOUR_TEAMS, 5: "Pat"})
    )

    first = _row(df, 1)
    assert first["opponent_weeks"] == 2
    assert first["unresolved_opponent_weeks"] == 1
    assert first["avg_opponent_win_pct"] == pytest.approx(0.0)
    assert first["avg_opponent_all_play_win_pct"] == pytest.approx(0.0)

    fifth = _row(df, 5)
    assert fifth["opponent_weeks"] == 1
    assert fifth["unresolved_opponent_weeks"] == 0
    assert fifth["avg_opponent_win_pct"] == pytest.approx(1.0)
    assert fifth["avg_opponent_all_play_win_pct"] == pytest.approx(1.0)


def test_roster_with_only_unresolvable_opponents_is_absent() -> None:
    """Both rosters' only game is unscored, so neither has a resolvable
    opponent and neither has a defined average: the result is an empty but
    correctly-shaped frame, not two zero rows.
    """
    df = build_strength_of_schedule(
        _season_matchup_df([_game(1, 2, None, None, week=1)]),
        _teams_df({1: "Alec", 2: "Mike"}),
    )

    assert df.empty
    assert list(df.columns) == STRENGTH_OF_SCHEDULE_COLUMNS


def test_frame_of_byes_only_returns_empty_frame_with_columns() -> None:
    rows = [
        _game(1, None, 100.0, None, week=1, matchup_id=None),
        _game(2, None, 90.0, None, week=1, matchup_id=None),
    ]
    df = build_strength_of_schedule(
        _season_matchup_df(rows), _teams_df({1: "Alec", 2: "Mike"})
    )

    assert df.empty
    assert list(df.columns) == STRENGTH_OF_SCHEDULE_COLUMNS


def test_empty_input_returns_empty_frame_with_columns() -> None:
    df = build_strength_of_schedule(_season_matchup_df([]), _teams_df({1: "Alec"}))

    assert df.empty
    assert list(df.columns) == STRENGTH_OF_SCHEDULE_COLUMNS


def test_roster_with_no_matchup_rows_is_absent() -> None:
    """Rows are input-driven: a roster in ``teams_df`` that never appears in
    ``season_matchup_df`` gets no row.
    """
    df = build_strength_of_schedule(
        _season_matchup_df([_game(1, 2, 100.0, 90.0)]),
        _teams_df({1: "Alec", 2: "Mike", 3: "Joe"}),
    )

    assert sorted(df["roster_id"]) == [1, 2]


def test_repeated_opponent_is_weighted_by_meetings() -> None:
    """The opponent list is a multiset: facing a roster twice counts twice.

    Roster 1 plays roster 2 twice (roster 2 finishes 1-1, ``win_pct`` 0.5) and
    roster 3 once (roster 3 finishes 0-1, ``win_pct`` 0.0), so its
    ``avg_opponent_win_pct`` is ``(0.5 + 0.5 + 0.0) / 3 = 1/3`` -- not the
    ``(0.5 + 0.0) / 2 = 0.25`` an unweighted set of distinct opponents would
    give.

    Week 1: roster 1 100.0 beat roster 2 90.0.
    Week 2: roster 1 60.0 lost to roster 2 70.0.
    Week 3: roster 1 120.0 beat roster 3 80.0.
    """
    rows = [
        _game(1, 2, 100.0, 90.0, week=1, matchup_id=1),
        _game(1, 2, 60.0, 70.0, week=2, matchup_id=1),
        _game(1, 3, 120.0, 80.0, week=3, matchup_id=1),
    ]
    df = build_strength_of_schedule(
        _season_matchup_df(rows), _teams_df({1: "Alec", 2: "Mike", 3: "Joe"})
    )

    row = _row(df, 1)
    assert row["opponent_weeks"] == 3
    assert row["avg_opponent_win_pct"] == pytest.approx(1 / 3)


# --------------------------------------------------------------------------
# Regular season vs. playoffs -- the phase-consistency guarantee
# --------------------------------------------------------------------------


def _mixed_phase_rows() -> list[dict]:
    """``_lucky_opponent_rows`` plus a third, playoff week.

    Week 3 (playoff): roster 1 50.0 lost to roster 3 200.0; roster 2 60.0
    beat roster 4 55.0.

    Combined over all three weeks the actual records become roster 1 2-1,
    roster 2 3-0, roster 3 1-2, roster 4 0-3, so ``win_pct`` is 2/3, 1, 1/3,
    0. Week 3's all-play field is 200, 60, 55, 50 -> roster 3 3-0, roster 2
    2-1, roster 4 1-2, roster 1 0-3, which added to the two regular weeks
    gives 9 all-play games each: roster 1 6-3 = 2/3, roster 2 6-3 = 2/3,
    roster 3 5-4 = 5/9, roster 4 1-8 = 1/9.

    Combined averages (3 opponent-weeks each):

        roster 1 faces 4, 4, 3 -> win_pct (0 + 0 + 1/3) / 3       = 1/9
                                  all_play (1/9 + 1/9 + 5/9) / 3  = 7/27
        roster 2 faces 3, 3, 4 -> win_pct (1/3 + 1/3 + 0) / 3     = 2/9
                                  all_play (5/9 + 5/9 + 1/9) / 3  = 11/27
        roster 3 faces 2, 2, 1 -> win_pct (1 + 1 + 2/3) / 3       = 8/9
                                  all_play (2/3 + 2/3 + 2/3) / 3  = 2/3
        roster 4 faces 1, 1, 2 -> win_pct (2/3 + 2/3 + 1) / 3     = 7/9
                                  all_play (2/3 + 2/3 + 2/3) / 3  = 2/3

    Filtering to ``is_playoff == False`` recovers ``_lucky_opponent_rows``'
    numbers exactly, which is the point of the phase test below: the
    opponents' strengths are recomputed over the filtered weeks too, not
    carried over from the full season.
    """
    return _lucky_opponent_rows() + [
        _game(1, 3, 50.0, 200.0, week=3, matchup_id=1, is_playoff=True),
        _game(2, 4, 60.0, 55.0, week=3, matchup_id=2, is_playoff=True),
    ]


def test_playoff_and_regular_season_weeks_are_combined_by_default() -> None:
    """No phase filter of its own: an unfiltered frame yields one combined
    result spanning both phases. See ``_mixed_phase_rows``' docstring.
    """
    df = build_strength_of_schedule(
        _season_matchup_df(_mixed_phase_rows()), _teams_df(_FOUR_TEAMS)
    )

    assert "is_playoff" not in df.columns

    expected = {
        1: (1 / 9, 7 / 27),
        2: (2 / 9, 11 / 27),
        3: (8 / 9, 2 / 3),
        4: (7 / 9, 2 / 3),
    }
    for roster_id, (win_pct, all_play_win_pct) in expected.items():
        row = _row(df, roster_id)
        assert row["opponent_weeks"] == 3
        assert row["avg_opponent_win_pct"] == pytest.approx(win_pct)
        assert row["avg_opponent_all_play_win_pct"] == pytest.approx(all_play_win_pct)


def test_caller_filtering_the_input_keeps_both_halves_phase_consistent() -> None:
    """The documented regular-season-only call: filter ``season_matchup_df``
    on ``is_playoff`` *before* calling.

    Because the opponent-strength table and the opponent list are both rebuilt
    from the filtered frame, they cover the same two weeks -- each roster has
    ``opponent_weeks == 2``, and opponents are measured by their two-week
    records rather than their three-week ones. The filtered answers are
    exactly ``_lucky_opponent_rows``', and they differ from the combined ones,
    so the filter demonstrably changed both halves.
    """
    frame = _season_matchup_df(_mixed_phase_rows())
    teams = _teams_df(_FOUR_TEAMS)

    regular = build_strength_of_schedule(frame.loc[~frame["is_playoff"]], teams)
    combined = build_strength_of_schedule(frame, teams)

    expected = {1: (0.0, 0.0), 2: (0.0, 1 / 3), 3: (1.0, 2 / 3), 4: (1.0, 1.0)}
    for roster_id, (win_pct, all_play_win_pct) in expected.items():
        row = _row(regular, roster_id)
        assert row["opponent_weeks"] == 2
        assert row["avg_opponent_win_pct"] == pytest.approx(win_pct)
        assert row["avg_opponent_all_play_win_pct"] == pytest.approx(all_play_win_pct)

        # The combined frame really is a different answer for every roster.
        assert _row(combined, roster_id)["avg_opponent_win_pct"] != pytest.approx(
            win_pct
        )


def test_playoff_only_filter_drops_rosters_that_never_played_a_playoff_game() -> None:
    """Filtering to ``is_playoff == True`` leaves only the playoff week, and a
    roster with no playoff game simply has no row.
    """
    rows = _mixed_phase_rows() + [_game(5, 6, 95.0, 85.0, week=1, matchup_id=3)]
    frame = _season_matchup_df(rows)
    teams = _teams_df({**_FOUR_TEAMS, 5: "Pat", 6: "Sky"})

    playoffs = build_strength_of_schedule(frame.loc[frame["is_playoff"]], teams)

    assert sorted(playoffs["roster_id"]) == [1, 2, 3, 4]
    for roster_id in (1, 2, 3, 4):
        assert _row(playoffs, roster_id)["opponent_weeks"] == 1


def test_no_parameter_accepts_a_separately_built_strength_table() -> None:
    """Structural guard for the design decision in the module docstring: the
    only inputs are ``season_matchup_df`` and ``teams_df``.

    If a future change added a ``schedule_luck_df``/``standings_df``
    parameter, a caller could supply an opponent-strength table built over a
    different set of games than the opponent list and get a silently
    meaningless average. This test fails if that door is reopened.
    """
    parameters = list(inspect.signature(build_strength_of_schedule).parameters)
    assert parameters == ["season_matchup_df", "teams_df"]


# --------------------------------------------------------------------------
# Owners and multi-season behavior
# --------------------------------------------------------------------------


def test_owner_is_resolved_from_teams_df_and_unmapped_stays_none() -> None:
    """``owner`` comes from ``teams_df["display_name"]``; a roster with no
    mapping stays ``None`` rather than becoming ``NaN`` or raising.
    """
    df = build_strength_of_schedule(
        _season_matchup_df([_game(1, 2, 100.0, 90.0)]), _teams_df({1: "Alec"})
    )

    assert _row(df, 1)["owner"] == "Alec"
    assert _row(df, 2)["owner"] is None


def test_empty_teams_df_resolves_every_owner_to_none() -> None:
    df = build_strength_of_schedule(
        _season_matchup_df([_game(1, 2, 100.0, 90.0)]), _empty_teams_df()
    )

    assert list(df["owner"]) == [None, None]
    assert _row(df, 1)["avg_opponent_win_pct"] == pytest.approx(0.0)


def test_multiple_seasons_are_pooled_into_one_row_per_roster() -> None:
    """Opponent strengths are pooled across seasons, inherited from
    ``build_schedule_luck``.

    2024 week 1: roster 1 100.0 beat roster 2 90.0.
    2025 week 1: roster 1 60.0 lost to roster 2 70.0.
    Each roster finishes 1-1 across the two seasons (``win_pct`` 0.5,
    ``all_play_win_pct`` 0.5) and faced the other twice, so both averages are
    0.5 over 2 opponent-weeks.
    """
    rows = [
        _game(1, 2, 100.0, 90.0, week=1, season="2024"),
        _game(1, 2, 60.0, 70.0, week=1, season="2025"),
    ]
    df = build_strength_of_schedule(
        _season_matchup_df(rows), _teams_df({1: "Alec", 2: "Mike"})
    )

    assert len(df) == 2
    for roster_id in (1, 2):
        row = _row(df, roster_id)
        assert row["opponent_weeks"] == 2
        assert row["avg_opponent_win_pct"] == pytest.approx(0.5)
        assert row["avg_opponent_all_play_win_pct"] == pytest.approx(0.5)


def test_internally_inconsistent_frame_propagates_the_upstream_error() -> None:
    """A decided game on a row with no points makes ``build_schedule_luck``
    raise; this module does not catch it and call the opponent unresolvable.
    """
    row = _game(1, 2, None, None, week=1)
    row["winner"] = 1
    row["loser"] = 2

    with pytest.raises(ValueError, match="no all-play record"):
        build_strength_of_schedule(
            _season_matchup_df([row]), _teams_df({1: "Alec", 2: "Mike"})
        )

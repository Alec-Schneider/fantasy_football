"""Tests for the league power ranking model (FFA-056).

All tests operate on hand-built ``season_matchup_df``/``teams_df`` inputs --
no HTTP calls, no fixtures with opaque values -- so ``power_score`` and every
feature it is built from can be verified by hand arithmetic from the scores
written in the test, per AGENTS.md's analytics-ticket requirement for a
hand-checkable toy example.

Like the strength-of-schedule and schedule-luck tests this cannot shortcut
the upstream frame: :func:`build_power_rankings` composes
``build_schedule_luck`` and ``build_consistency_metrics`` from one shared
``season_matchup_df``, so every test builds real matchup rows and exercises
the full composition beneath it.
"""

import inspect
import statistics

import pandas as pd
import pytest

from fantasy_analyzer.analytics import (
    ALL_PLAY_WIN_PCT_WEIGHT,
    MEAN_POINTS_WEIGHT,
    POWER_RANKING_COLUMNS,
    WIN_PCT_WEIGHT,
    build_power_rankings,
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


def _zscore(values: dict[int, float]) -> dict[int, float]:
    raw = list(values.values())
    mean = statistics.fmean(raw)
    stdev = statistics.pstdev(raw)
    if stdev == 0:
        return dict.fromkeys(values, 0.0)
    return {k: (v - mean) / stdev for k, v in values.items()}


# --------------------------------------------------------------------------
# Toy example -- three rosters, two weeks, hand computed end to end
# --------------------------------------------------------------------------


def _worked_example_rows() -> list[dict]:
    """The module docstring's worked example: 3 rosters, 2 weeks.

    week 1: roster1 100.0 beat roster3 80.0; roster2 100.0 beat roster4 80.0
    week 2: roster1 90.0 beat roster4 70.0; roster2 90.0 beat roster3 70.0

    Actual records: roster1 2-0 (win_pct=1.0), roster2 2-0 (win_pct=1.0),
    roster3 0-2 (win_pct=0.0), roster4 0-2 (win_pct=0.0).

    All-play (each week's field is all 4 scores):
        week1 field {r1:100, r2:100, r3:80, r4:80}:
            r1 vs r2 tie, r1 vs r3 win, r1 vs r4 win -> r1: 2W-0L-1T
            r2 vs r1 tie, r2 vs r3 win, r2 vs r4 win -> r2: 2W-0L-1T
            r3 vs r1 loss, r3 vs r2 loss, r3 vs r4 tie -> r3: 0W-2L-1T
            r4 vs r1 loss, r4 vs r2 loss, r4 vs r3 tie -> r4: 0W-2L-1T
        week2 field {r1:90, r2:90, r3:70, r4:70}: identical shape to week1.

    Season all-play totals (6 comparisons each):
        roster1: 4W-0L-2T -> all_play_win_pct = (4 + 1) / 6 = 5/6
        roster2: 4W-0L-2T -> all_play_win_pct = 5/6
        roster3: 0W-4L-2T -> all_play_win_pct = 1/6
        roster4: 0W-4L-2T -> all_play_win_pct = 1/6

    mean_points: roster1 = (100+90)/2 = 95, roster2 = 95,
                 roster3 = (80+70)/2 = 75, roster4 = 75.

    This scenario is fully symmetric: rosters 1 and 2 are indistinguishable
    on every feature, and so are rosters 3 and 4, giving an exact tie at the
    top and an exact tie at the bottom.
    """
    return [
        _game(1, 3, 100.0, 80.0, week=1, matchup_id=1),
        _game(2, 4, 100.0, 80.0, week=1, matchup_id=2),
        _game(1, 4, 90.0, 70.0, week=2, matchup_id=1),
        _game(2, 3, 90.0, 70.0, week=2, matchup_id=2),
    ]


_FOUR_TEAMS = {1: "Alec", 2: "Mike", 3: "Joe", 4: "Sam"}


def test_worked_example_hand_computed_and_tied() -> None:
    """Verifies every number hand-computed in ``_worked_example_rows``' docstring.

    Rosters 1 and 2 are exact statistical twins (identical win_pct,
    all_play_win_pct, mean_points), so their z-scores and power_score are
    exactly equal -- this is the ticket's required tie-in-composite-score
    case, arising from real, symmetric matchup data rather than being forced
    by hand. Rosters 3 and 4 are likewise twins at the bottom.
    """
    df = build_power_rankings(
        _season_matchup_df(_worked_example_rows()), _teams_df(_FOUR_TEAMS)
    )

    assert list(df.columns) == POWER_RANKING_COLUMNS
    assert len(df) == 4

    expected_win_pct = {1: 1.0, 2: 1.0, 3: 0.0, 4: 0.0}
    expected_all_play = {1: 5 / 6, 2: 5 / 6, 3: 1 / 6, 4: 1 / 6}
    expected_mean_points = {1: 95.0, 2: 95.0, 3: 75.0, 4: 75.0}

    for roster_id in (1, 2, 3, 4):
        row = _row(df, roster_id)
        assert row["games_played"] == 2
        assert row["win_pct"] == pytest.approx(expected_win_pct[roster_id])
        assert row["all_play_win_pct"] == pytest.approx(expected_all_play[roster_id])
        assert row["mean_points"] == pytest.approx(expected_mean_points[roster_id])

    win_pct_z = _zscore(expected_win_pct)
    all_play_z = _zscore(expected_all_play)
    mean_points_z = _zscore(expected_mean_points)

    for roster_id in (1, 2, 3, 4):
        row = _row(df, roster_id)
        assert row["win_pct_z"] == pytest.approx(win_pct_z[roster_id])
        assert row["all_play_win_pct_z"] == pytest.approx(all_play_z[roster_id])
        assert row["mean_points_z"] == pytest.approx(mean_points_z[roster_id])

        expected_score = (
            WIN_PCT_WEIGHT * win_pct_z[roster_id]
            + ALL_PLAY_WIN_PCT_WEIGHT * all_play_z[roster_id]
            + MEAN_POINTS_WEIGHT * mean_points_z[roster_id]
        )
        assert row["power_score"] == pytest.approx(expected_score)

    # Exact ties within each twin pair.
    assert _row(df, 1)["power_score"] == pytest.approx(_row(df, 2)["power_score"])
    assert _row(df, 3)["power_score"] == pytest.approx(_row(df, 4)["power_score"])
    # The two pairs are clearly separated from each other.
    assert _row(df, 1)["power_score"] > _row(df, 3)["power_score"]


def test_tied_composite_scores_share_a_rank_with_standard_competition_ranking() -> None:
    """Standard competition ("1224") ranking: the top pair shares rank 1, and
    the next distinct rank (the bottom pair) skips to 3, not 2.
    """
    df = build_power_rankings(
        _season_matchup_df(_worked_example_rows()), _teams_df(_FOUR_TEAMS)
    )

    assert sorted(df.loc[df["power_rank"] == 1, "roster_id"]) == [1, 2]
    assert sorted(df.loc[df["power_rank"] == 3, "roster_id"]) == [3, 4]
    assert list(df["power_rank"]) == [1, 1, 3, 3]
    # Row order within a tie is ascending roster_id (display only).
    assert list(df["roster_id"]) == [1, 2, 3, 4]


def test_higher_power_score_is_the_intended_reading_of_a_better_roster() -> None:
    """Rank 1 = highest power_score = strongest team, unlike SOS/schedule-luck
    rank columns where rank 1 is not a compliment.
    """
    df = build_power_rankings(
        _season_matchup_df(_worked_example_rows()), _teams_df(_FOUR_TEAMS)
    )

    assert _row(df, 1)["power_rank"] == 1
    assert _row(df, 1)["power_score"] > _row(df, 3)["power_score"]


# --------------------------------------------------------------------------
# Non-tied worked example (module docstring's second, fully separated case)
# --------------------------------------------------------------------------


def _three_roster_worked_example() -> list[dict]:
    """Three rosters, two weeks, one bye each week -- the module docstring's
    fully hand-worked, non-tied example.

    week 1: roster1 120.0 beat roster2 100.0 (roster3 bye at 90.0)
    week 2: roster3 130.0 beat roster1 110.0 (roster2 bye at 95.0)

    Actual records: roster1 1-1 (win_pct=0.5, games_played=2), roster2 0-1
    (win_pct=0.0, games_played=1), roster3 1-0 (win_pct=1.0, games_played=1).

    All-play:
        week1 field {r1:120, r2:100, r3:90} (bye included, FFA-051):
            r1 beats r2, beats r3 -> r1: 2W-0L
            r2 loses to r1, beats r3 -> r2: 1W-1L
            r3 loses to r1, loses to r2 -> r3: 0W-2L
        week2 field {r1:110, r2:95, r3:130}:
            r1 loses to r3, beats r2 -> r1: 1W-1L
            r3 beats r1, beats r2 -> r3: 2W-0L
            r2 loses to r1, loses to r3 -> r2: 0W-2L

    Season all-play totals (4 comparisons each):
        roster1: 3W-1L -> all_play_win_pct = 3/4 = 0.75
        roster2: 1W-3L -> all_play_win_pct = 1/4 = 0.25
        roster3: 2W-2L -> all_play_win_pct = 2/4 = 0.5

    mean_points: roster1 = (120+110)/2 = 115.0, roster2 = (100+95)/2 = 97.5,
                 roster3 = (90+130)/2 = 110.0.
    """
    return [
        _game(1, 2, 120.0, 100.0, week=1, matchup_id=1),
        _game(3, None, 90.0, None, week=1, matchup_id=None),
        _game(1, 3, 110.0, 130.0, week=2, matchup_id=1),
        _game(2, None, 95.0, None, week=2, matchup_id=None),
    ]


_THREE_TEAMS = {1: "Alec", 2: "Mike", 3: "Joe"}


def test_three_roster_worked_example_hand_computed_no_ties() -> None:
    """The module docstring's fully hand-worked z-score/composite example."""
    df = build_power_rankings(
        _season_matchup_df(_three_roster_worked_example()), _teams_df(_THREE_TEAMS)
    )

    assert len(df) == 3

    expected_win_pct = {1: 0.5, 2: 0.0, 3: 1.0}
    expected_all_play = {1: 0.75, 2: 0.25, 3: 0.5}
    expected_mean_points = {1: 115.0, 2: 97.5, 3: 110.0}
    expected_games_played = {1: 2, 2: 1, 3: 1}

    for roster_id in (1, 2, 3):
        row = _row(df, roster_id)
        assert row["games_played"] == expected_games_played[roster_id]
        assert row["win_pct"] == pytest.approx(expected_win_pct[roster_id])
        assert row["all_play_win_pct"] == pytest.approx(expected_all_play[roster_id])
        assert row["mean_points"] == pytest.approx(expected_mean_points[roster_id])

    win_pct_z = _zscore(expected_win_pct)
    all_play_z = _zscore(expected_all_play)
    mean_points_z = _zscore(expected_mean_points)

    expected_power_score = {
        roster_id: (
            WIN_PCT_WEIGHT * win_pct_z[roster_id]
            + ALL_PLAY_WIN_PCT_WEIGHT * all_play_z[roster_id]
            + MEAN_POINTS_WEIGHT * mean_points_z[roster_id]
        )
        for roster_id in (1, 2, 3)
    }
    for roster_id in (1, 2, 3):
        assert _row(df, roster_id)["power_score"] == pytest.approx(
            expected_power_score[roster_id]
        )

    # Fully separated: roster1 strongest, roster3 second, roster2 weakest.
    assert list(df["roster_id"]) == [1, 3, 2]
    assert list(df["power_rank"]) == [1, 2, 3]


# --------------------------------------------------------------------------
# Missing / undetermined values
# --------------------------------------------------------------------------


def test_bye_only_roster_has_zero_decided_games_and_is_absent() -> None:
    """A roster with a scored week but never a decided game (bye-only) gets
    no row: it has a ``mean_points`` in the consistency table but no
    ``win_pct``, so the composite has nothing to combine.
    """
    rows = _three_roster_worked_example() + [
        _game(4, None, 999.0, None, week=1, matchup_id=None)
    ]
    df = build_power_rankings(
        _season_matchup_df(rows), _teams_df({**_THREE_TEAMS, 4: "Pat"})
    )

    assert sorted(df["roster_id"]) == [1, 2, 3]


def test_roster_with_no_matchup_rows_is_absent() -> None:
    """Rows are input-driven: a roster in ``teams_df`` that never appears in
    ``season_matchup_df`` gets no row.
    """
    df = build_power_rankings(
        _season_matchup_df([_game(1, 2, 100.0, 90.0)]),
        _teams_df({1: "Alec", 2: "Mike", 3: "Joe"}),
    )

    assert sorted(df["roster_id"]) == [1, 2]


def test_final_placement_is_not_consulted() -> None:
    """FFA-056 deliberately excludes FFA-055's final placements -- see the
    module docstring's "Playoff placement (FFA-055) is a listed dependency,
    and is deliberately excluded" section. Structural guard: the function
    signature has no bracket/placement parameter at all, so a caller cannot
    even attempt to hand in a separately-built, possibly-incomplete
    placement table.
    """
    parameters = list(inspect.signature(build_power_rankings).parameters)
    assert parameters == ["season_matchup_df", "teams_df"]
    assert "placement" not in POWER_RANKING_COLUMNS


# --------------------------------------------------------------------------
# Empty input and single-roster / zero-variance edge cases
# --------------------------------------------------------------------------


def test_empty_input_returns_empty_frame_with_columns() -> None:
    df = build_power_rankings(_season_matchup_df([]), _teams_df({1: "Alec"}))

    assert df.empty
    assert list(df.columns) == POWER_RANKING_COLUMNS


def test_frame_of_byes_only_returns_empty_frame_with_columns() -> None:
    rows = [
        _game(1, None, 100.0, None, week=1, matchup_id=None),
        _game(2, None, 90.0, None, week=1, matchup_id=None),
    ]
    df = build_power_rankings(
        _season_matchup_df(rows), _teams_df({1: "Alec", 2: "Mike"})
    )

    assert df.empty
    assert list(df.columns) == POWER_RANKING_COLUMNS


def test_bye_only_frame_leaves_zero_decided_games_and_an_empty_result() -> None:
    """A roster whose only appearance is a bye has zero decided games, so it
    never reaches the power-ranking row set at all (see the empty-frame
    tests above for the general "byes only" case).
    """
    df = build_power_rankings(
        _season_matchup_df([_game(1, None, 100.0, None, week=1, matchup_id=None)]),
        _teams_df({1: "Alec"}),
    )

    assert df.empty


def test_two_roster_frame_orders_the_decided_winner_first() -> None:
    """A minimal, genuinely-decided two-roster frame: roster 1's win_pct,
    all_play_win_pct and mean_points are all strictly higher than roster 2's,
    so it unambiguously outranks roster 2 (no zero-variance columns here,
    since every feature actually differs between the two rosters).
    """
    df = build_power_rankings(
        _season_matchup_df([_game(1, 2, 100.0, 90.0, week=1, matchup_id=1)]),
        _teams_df({1: "Alec", 2: "Mike"}),
    )

    assert len(df) == 2
    assert _row(df, 1)["power_rank"] == 1
    assert _row(df, 2)["power_rank"] == 2


def test_zero_variance_columns_yield_zero_z_scores_not_a_division_by_zero() -> None:
    """When every roster in the row set has an identical value on a feature,
    that feature's z-score is 0.0 for everyone rather than ``NaN`` or an
    error -- see the module docstring's "zero-variance rule".

    Two rosters that split two identical head-to-head results (each wins
    once, by the same margin) finish with identical ``win_pct`` (0.5),
    identical ``all_play_win_pct`` (0.5), and identical ``mean_points`` --
    zero variance on *every* column at once, the most extreme case.
    """
    rows = [
        _game(1, 2, 100.0, 90.0, week=1, matchup_id=1),
        _game(1, 2, 90.0, 100.0, week=2, matchup_id=1),
    ]
    df = build_power_rankings(
        _season_matchup_df(rows), _teams_df({1: "Alec", 2: "Mike"})
    )

    assert len(df) == 2
    for roster_id in (1, 2):
        row = _row(df, roster_id)
        assert row["win_pct_z"] == pytest.approx(0.0)
        assert row["all_play_win_pct_z"] == pytest.approx(0.0)
        assert row["mean_points_z"] == pytest.approx(0.0)
        assert row["power_score"] == pytest.approx(0.0)
    assert list(df["power_rank"]) == [1, 1]


# --------------------------------------------------------------------------
# Regular season vs. playoffs
# --------------------------------------------------------------------------


def _mixed_phase_rows() -> list[dict]:
    """``_three_roster_worked_example`` plus a third, playoff week that
    flips roster2's fortunes: it blows out roster1 in the playoff week.
    """
    return _three_roster_worked_example() + [
        _game(1, 2, 60.0, 200.0, week=3, matchup_id=1, is_playoff=True),
    ]


def test_playoff_and_regular_season_weeks_are_combined_by_default() -> None:
    """No phase filter of its own: an unfiltered frame folds the playoff week
    into every feature, changing ``mean_points``, ``win_pct`` and the
    resulting ranking relative to the regular-season-only view.
    """
    frame = _season_matchup_df(_mixed_phase_rows())
    teams = _teams_df(_THREE_TEAMS)

    combined = build_power_rankings(frame, teams)
    regular = build_power_rankings(frame.loc[~frame["is_playoff"]], teams)

    assert "is_playoff" not in combined.columns
    # roster1 now has a 3rd, badly-losing week folded into mean_points and
    # win_pct, so its combined mean_points must be lower than its
    # regular-season-only mean_points (115.0 -- see the worked example).
    assert _row(combined, 1)["mean_points"] < _row(regular, 1)["mean_points"]
    assert _row(combined, 1)["win_pct"] < _row(regular, 1)["win_pct"]


def test_caller_filtering_the_input_recovers_the_regular_season_only_view() -> None:
    """Filtering ``season_matchup_df`` to ``is_playoff == False`` before
    calling reproduces ``_three_roster_worked_example``'s numbers exactly.
    """
    frame = _season_matchup_df(_mixed_phase_rows())
    teams = _teams_df(_THREE_TEAMS)

    regular = build_power_rankings(frame.loc[~frame["is_playoff"]], teams)

    assert _row(regular, 1)["mean_points"] == pytest.approx(115.0)
    assert _row(regular, 1)["win_pct"] == pytest.approx(0.5)
    assert _row(regular, 2)["mean_points"] == pytest.approx(97.5)


def test_playoff_only_filter_drops_rosters_that_never_played_a_playoff_game() -> None:
    frame = _season_matchup_df(_mixed_phase_rows())
    teams = _teams_df(_THREE_TEAMS)

    playoffs = build_power_rankings(frame.loc[frame["is_playoff"]], teams)

    # Only rosters 1 and 2 played a playoff game; roster 3 never did.
    assert sorted(playoffs["roster_id"]) == [1, 2]
    assert _row(playoffs, 2)["power_rank"] == 1  # blew out roster 1


# --------------------------------------------------------------------------
# Owners, multi-season pooling, and internal-consistency propagation
# --------------------------------------------------------------------------


def test_owner_is_resolved_from_teams_df_and_unmapped_stays_none() -> None:
    df = build_power_rankings(
        _season_matchup_df([_game(1, 2, 100.0, 90.0)]), _teams_df({1: "Alec"})
    )

    assert _row(df, 1)["owner"] == "Alec"
    assert _row(df, 2)["owner"] is None


def test_empty_teams_df_resolves_every_owner_to_none() -> None:
    df = build_power_rankings(
        _season_matchup_df([_game(1, 2, 100.0, 90.0)]), _empty_teams_df()
    )

    assert list(df["owner"]) == [None, None]


def test_multiple_seasons_are_pooled_into_one_row_per_roster() -> None:
    """2024 week 1: roster1 100.0 beat roster2 90.0.
    2025 week 1: roster1 60.0 lost to roster2 70.0.

    Each roster finishes 1-1 across the two seasons (win_pct=0.5), and the
    all-play field in each of the two separately-grouped weeks is just the
    two of them, so each is 1-1 all-play too (all_play_win_pct=0.5).
    mean_points: roster1 = (100+60)/2 = 80.0, roster2 = (90+70)/2 = 80.0.
    Every feature is identical between the two rosters -- zero variance on
    every column -- so both get power_score = 0.0 and share rank 1.
    """
    rows = [
        _game(1, 2, 100.0, 90.0, week=1, season="2024"),
        _game(1, 2, 60.0, 70.0, week=1, season="2025"),
    ]
    df = build_power_rankings(
        _season_matchup_df(rows), _teams_df({1: "Alec", 2: "Mike"})
    )

    assert len(df) == 2
    for roster_id in (1, 2):
        row = _row(df, roster_id)
        assert row["win_pct"] == pytest.approx(0.5)
        assert row["all_play_win_pct"] == pytest.approx(0.5)
        assert row["mean_points"] == pytest.approx(80.0)
        assert row["power_score"] == pytest.approx(0.0)
    assert list(df["power_rank"]) == [1, 1]


def test_internally_inconsistent_frame_propagates_the_upstream_error() -> None:
    """A decided game on a row with no points makes ``build_schedule_luck``
    raise; this module does not catch it and silently drop the roster.
    """
    row = _game(1, 2, None, None, week=1)
    row["winner"] = 1
    row["loser"] = 2

    with pytest.raises(ValueError, match="no all-play record"):
        build_power_rankings(
            _season_matchup_df([row]), _teams_df({1: "Alec", 2: "Mike"})
        )

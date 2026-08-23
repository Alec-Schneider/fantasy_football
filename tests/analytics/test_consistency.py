"""Tests for team consistency metrics (FFA-053).

All tests operate on hand-built inputs -- no HTTP calls, no opaque fixture
values -- so every mean, median, standard deviation, coefficient of variation
and boom/bust count can be verified by hand arithmetic from the scores
written in each test, per AGENTS.md's analytics-ticket requirement for a
hand-checkable toy example.

Most tests build a ``weekly_scoring_ranks_df``-shaped frame directly, so this
ticket's aggregation is isolated from FFA-050's own reshaping/ranking
correctness. One test
(:func:`test_composes_with_build_weekly_scoring_ranks`) goes through the real
:func:`~fantasy_analyzer.analytics.weekly_scores.build_weekly_scoring_ranks`
to confirm the two functions compose end to end, following FFA-051's test
precedent.

Standard deviations are population (``ddof = 0``) throughout -- see the
module docstring of :mod:`fantasy_analyzer.analytics.consistency` -- so the
hand arithmetic in these docstrings divides the sum of squared deviations by
``n``, not by ``n - 1``.
"""

import math

import pandas as pd
import pytest

from fantasy_analyzer.analytics import (
    BOOM_BUST_THRESHOLD_STDEVS,
    CONSISTENCY_METRICS_COLUMNS,
    WEEKLY_SCORING_RANK_COLUMNS,
    build_consistency_metrics,
    build_weekly_scoring_ranks,
)
from fantasy_analyzer.analytics.consistency import (
    MIN_WEEKS_FOR_BOOM_BUST,
    MIN_WEEKS_FOR_DISPERSION,
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

    ``weekly_rank``, ``season``, ``week`` and ``is_playoff`` are carried for
    shape fidelity only -- ``build_consistency_metrics`` reads none of them --
    so tests may leave them at their defaults.
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


def _season(roster_id: int, points: list[float], season: str = "2025") -> list[dict]:
    """Shorthand for one roster's weekly scores, in weeks 1..len(points)."""
    return [
        _score_row(roster_id=roster_id, points=value, week=week, season=season)
        for week, value in enumerate(points, start=1)
    ]


def _row(df: pd.DataFrame, roster_id: int) -> pd.Series:
    match = df.loc[df["roster_id"] == roster_id]
    assert len(match) == 1
    return match.iloc[0]


# --------------------------------------------------------------------------
# Hand-checkable toy example
# --------------------------------------------------------------------------


def _toy_rows() -> list[dict]:
    """Three rosters with deliberately different volatility profiles, 4 weeks.

    All arithmetic below uses the **population** standard deviation
    (divide by ``n = 4``) and the default threshold ``k = 1.0``.

    Roster 1 -- metronome: 98, 100, 100, 102
        mean   = 400 / 4 = 100.0
        median = sorted(98, 100, 100, 102) -> (100 + 100) / 2 = 100.0
        devs   = -2, 0, 0, +2 -> squares 4, 0, 0, 4 -> sum 8 -> 8/4 = 2
        stdev  = sqrt(2)      = 1.41421356...
        cv     = sqrt(2) / 100 = 0.0141421356...
        floor  = 98.0, ceiling = 102.0
        boom band > 100 + 1.4142 = 101.4142 -> 102 only          -> 1 boom
        bust band <  100 - 1.4142 = 98.5858 ->  98 only          -> 1 bust
        boom_pct = bust_pct = 1/4 = 0.25

    Roster 2 -- chaos: 60, 150, 70, 120
        mean   = 400 / 4 = 100.0 (identical level to roster 1)
        median = sorted(60, 70, 120, 150) -> (70 + 120) / 2 = 95.0
        devs   = -40, +50, -30, +20
                 -> squares 1600, 2500, 900, 400 -> sum 5400 -> 1350
        stdev  = sqrt(1350)     = 36.74234614...
        cv     = sqrt(1350)/100 = 0.3674234614...
        floor  = 60.0, ceiling = 150.0
        boom band > 136.7423 -> 150 only  -> 1 boom
        bust band <  63.2577 ->  60 only  -> 1 bust
        boom_pct = bust_pct = 0.25

    Roster 3 -- one spike: 90, 90, 90, 170
        mean   = 440 / 4 = 110.0
        median = sorted(90, 90, 90, 170) -> (90 + 90) / 2 = 90.0
                 (mean well above median: the spike drags the mean up)
        devs   = -20, -20, -20, +60
                 -> squares 400, 400, 400, 3600 -> sum 4800 -> 1200
        stdev  = sqrt(1200)     = 34.64101615...
        cv     = sqrt(1200)/110 = 0.3149183286...
        floor  = 90.0, ceiling = 170.0
        boom band > 144.6410 -> 170 only            -> 1 boom
        bust band <  75.3590 -> none (90 is above)  -> 0 busts
                 i.e. three below-mean weeks and still zero busts
        boom_pct = 0.25, bust_pct = 0.0
    """
    return (
        _season(1, [98.0, 100.0, 100.0, 102.0])
        + _season(2, [60.0, 150.0, 70.0, 120.0])
        + _season(3, [90.0, 90.0, 90.0, 170.0])
    )


def test_toy_example_hand_computed() -> None:
    """Verifies every number hand-computed in ``_toy_rows``'s docstring."""
    df = build_consistency_metrics(_weekly_scores_df(_toy_rows()))

    assert list(df.columns) == CONSISTENCY_METRICS_COLUMNS
    assert len(df) == 3

    expected = {
        # roster_id: (mean, median, stdev, cv, floor, ceiling, booms, busts)
        1: (100.0, 100.0, math.sqrt(2), math.sqrt(2) / 100, 98.0, 102.0, 1, 1),
        2: (100.0, 95.0, math.sqrt(1350), math.sqrt(1350) / 100, 60.0, 150.0, 1, 1),
        3: (110.0, 90.0, math.sqrt(1200), math.sqrt(1200) / 110, 90.0, 170.0, 1, 0),
    }
    for roster_id, values in expected.items():
        mean, med, stdev, cv, floor, ceiling, booms, busts = values
        row = _row(df, roster_id)
        assert row["weeks_played"] == 4
        assert row["mean_points"] == pytest.approx(mean)
        assert row["median_points"] == pytest.approx(med)
        assert row["stdev_points"] == pytest.approx(stdev)
        assert row["cv"] == pytest.approx(cv)
        assert row["scoring_floor"] == pytest.approx(floor)
        assert row["scoring_ceiling"] == pytest.approx(ceiling)
        assert row["boom_weeks"] == booms
        assert row["bust_weeks"] == busts
        assert row["boom_pct"] == pytest.approx(booms / 4)
        assert row["bust_pct"] == pytest.approx(busts / 4)

    # Deterministic display order: ascending roster_id, no rank column.
    assert list(df["roster_id"]) == [1, 2, 3]
    assert "rank" not in df.columns
    assert not [column for column in df.columns if column.endswith("_rank")]


def test_stdev_separates_two_rosters_with_the_same_mean() -> None:
    """The point of the ticket: rosters 1 and 2 of the toy both average
    exactly 100.0, and only the dispersion columns tell them apart.
    """
    df = build_consistency_metrics(_weekly_scores_df(_toy_rows()))

    assert _row(df, 1)["mean_points"] == _row(df, 2)["mean_points"]
    assert _row(df, 1)["stdev_points"] < _row(df, 2)["stdev_points"]
    assert _row(df, 1)["cv"] < _row(df, 2)["cv"]
    assert (
        _row(df, 2)["scoring_ceiling"] - _row(df, 2)["scoring_floor"]
        > _row(df, 1)["scoring_ceiling"] - _row(df, 1)["scoring_floor"]
    )


def test_boom_pct_is_frequency_not_magnitude() -> None:
    """Documented caveat, locked in: because the threshold is measured in the
    roster's *own* standard deviations, the metronome (roster 1, boomed by 2
    points) and the chaos team (roster 2, boomed by 50) record the same
    ``boom_pct``. Magnitude lives in ``stdev_points``/``scoring_ceiling``.
    """
    df = build_consistency_metrics(_weekly_scores_df(_toy_rows()))

    assert _row(df, 1)["boom_pct"] == _row(df, 2)["boom_pct"] == 0.25
    assert _row(df, 1)["stdev_points"] != _row(df, 2)["stdev_points"]


def test_below_the_mean_is_not_automatically_a_bust() -> None:
    """Roster 3 spends three of four weeks below its own mean and still
    records zero busts: a bust is a full standard deviation below, not merely
    a below-average week.
    """
    df = build_consistency_metrics(_weekly_scores_df(_toy_rows()))

    row = _row(df, 3)
    assert row["mean_points"] == 110.0
    assert row["median_points"] == 90.0  # three of four weeks sit at 90
    assert row["bust_weeks"] == 0
    assert row["bust_pct"] == 0.0


# --------------------------------------------------------------------------
# Center, spread and extremes
# --------------------------------------------------------------------------


def test_median_of_an_odd_number_of_weeks_is_the_middle_score() -> None:
    """3 weeks: sorted(90, 100, 140) -> 100.0, which is an actual weekly score.

    mean = 330 / 3 = 110.0, so mean and median differ.
    """
    df = build_consistency_metrics(_weekly_scores_df(_season(1, [90.0, 140.0, 100.0])))

    row = _row(df, 1)
    assert row["median_points"] == 100.0
    assert row["mean_points"] == pytest.approx(110.0)


def test_median_of_an_even_number_of_weeks_averages_the_two_middle() -> None:
    """4 weeks: sorted(80, 90, 110, 140) -> (90 + 110) / 2 = 100.0, a value
    the roster never actually scored. Documented, intentional convention.
    """
    df = build_consistency_metrics(
        _weekly_scores_df(_season(1, [140.0, 80.0, 110.0, 90.0]))
    )

    row = _row(df, 1)
    assert row["median_points"] == 100.0
    assert 100.0 not in {80.0, 90.0, 110.0, 140.0}


def test_duplicate_weekly_scores_are_handled_by_median_floor_and_ceiling() -> None:
    """Repeated values need no ties convention -- they are ordinary members of
    the multiset.

    Weeks: 80, 80, 80, 120.
        mean   = 360 / 4 = 90.0
        median = (80 + 80) / 2 = 80.0
        floor  = 80.0 (three weeks share it), ceiling = 120.0
        devs   = -10, -10, -10, +30 -> squares 100*3 + 900 = 1200 -> 300
        stdev  = sqrt(300) = 17.3205...
        boom band > 107.32 -> 120 only -> 1 boom; bust band < 72.68 -> 0
    """
    df = build_consistency_metrics(
        _weekly_scores_df(_season(1, [80.0, 80.0, 80.0, 120.0]))
    )

    row = _row(df, 1)
    assert row["weeks_played"] == 4
    assert row["mean_points"] == pytest.approx(90.0)
    assert row["median_points"] == 80.0
    assert row["scoring_floor"] == 80.0
    assert row["scoring_ceiling"] == 120.0
    assert row["stdev_points"] == pytest.approx(math.sqrt(300))
    assert row["boom_weeks"] == 1
    assert row["bust_weeks"] == 0


def test_stdev_is_population_not_sample() -> None:
    """``ddof = 0``, deliberately: the weeks in the frame are the complete set
    of weeks played, not a sample drawn from a wider population.

    Weeks: 90, 100, 110. Sum of squared deviations = 100 + 0 + 100 = 200.
        population (divide by 3): sqrt(200/3) = 8.16496...
        sample     (divide by 2): sqrt(100)   = 10.0
    The assertion pins the first and explicitly rejects the second, which is
    what ``pandas.Series.std()`` would return by default.
    """
    points = [90.0, 100.0, 110.0]
    df = build_consistency_metrics(_weekly_scores_df(_season(1, points)))

    row = _row(df, 1)
    assert row["stdev_points"] == pytest.approx(math.sqrt(200 / 3))
    assert row["stdev_points"] != pytest.approx(10.0)
    # The sample standard deviation is what a naive pandas recomputation gives.
    assert pd.Series(points).std() == pytest.approx(10.0)
    assert pd.Series(points).std(ddof=0) == pytest.approx(row["stdev_points"])


def test_zero_variance_roster_is_perfectly_consistent_with_no_booms() -> None:
    """Five identical weeks: stdev and cv are a genuine 0.0 (unlike the
    one-week case), floor == ceiling == mean == median, and strict inequality
    against a threshold equal to the mean yields zero booms and zero busts
    with no special-casing.
    """
    df = build_consistency_metrics(_weekly_scores_df(_season(1, [100.0] * 5)))

    row = _row(df, 1)
    assert row["weeks_played"] == 5
    assert row["mean_points"] == 100.0
    assert row["median_points"] == 100.0
    assert row["stdev_points"] == 0.0
    assert row["cv"] == 0.0
    assert row["scoring_floor"] == row["scoring_ceiling"] == 100.0
    assert row["boom_weeks"] == 0
    assert row["bust_weeks"] == 0
    assert row["boom_pct"] == 0.0
    assert row["bust_pct"] == 0.0


# --------------------------------------------------------------------------
# Small-sample rules
# --------------------------------------------------------------------------


def test_single_week_roster_has_undefined_stdev_cv_and_boom_bust() -> None:
    """A one-week roster's center and extremes are its single score, but it
    has no spread: reported as ``NaN``, never ``0.0``, so it cannot sort to
    the top of a "most consistent" ranking alongside a genuinely steady team.
    """
    df = build_consistency_metrics(_weekly_scores_df(_season(1, [123.45])))

    row = _row(df, 1)
    assert row["weeks_played"] == 1
    assert row["mean_points"] == pytest.approx(123.45)
    assert row["median_points"] == pytest.approx(123.45)
    assert row["scoring_floor"] == pytest.approx(123.45)
    assert row["scoring_ceiling"] == pytest.approx(123.45)
    for column in ("stdev_points", "cv", "boom_weeks", "boom_pct"):
        assert pd.isna(row[column])
    for column in ("bust_weeks", "bust_pct"):
        assert pd.isna(row[column])


def test_two_week_roster_has_dispersion_but_no_boom_bust() -> None:
    """Two weeks clear ``MIN_WEEKS_FOR_DISPERSION`` but not
    ``MIN_WEEKS_FOR_BOOM_BUST``.

    Weeks: 90, 110. mean = 100.0, devs -10/+10 -> squares 100 + 100 = 200,
    /2 = 100, stdev = 10.0, cv = 0.10. Both are reported.

    The boom/bust columns are not, because with two scores each observation
    sits *exactly* one population standard deviation from the mean
    (``110 - 100 == 10 == stdev``), so the classification depends only on
    whether ``k < 1`` and never on the scores -- and at floating-point
    precision the comparison is decided by rounding noise.
    """
    assert MIN_WEEKS_FOR_DISPERSION == 2
    assert MIN_WEEKS_FOR_BOOM_BUST == 3

    df = build_consistency_metrics(_weekly_scores_df(_season(1, [90.0, 110.0])))

    row = _row(df, 1)
    assert row["weeks_played"] == 2
    assert row["stdev_points"] == pytest.approx(10.0)
    assert row["cv"] == pytest.approx(0.10)
    for column in ("boom_weeks", "boom_pct", "bust_weeks", "bust_pct"):
        assert pd.isna(row[column])


def test_two_week_boom_bust_is_suppressed_even_for_ragged_scores() -> None:
    """The two-week suppression is not a clean-numbers artifact: a pair of
    ragged real-looking scores is suppressed too, which is the case where
    rounding noise would otherwise decide the answer.
    """
    df = build_consistency_metrics(_weekly_scores_df(_season(1, [161.33, 150.95])))

    row = _row(df, 1)
    assert row["stdev_points"] == pytest.approx(5.19)
    assert pd.isna(row["boom_weeks"])
    assert pd.isna(row["bust_weeks"])


def test_three_week_roster_does_get_boom_bust() -> None:
    """Three weeks is the documented minimum, and at ``n = 3`` the answer does
    depend on the data.

    Weeks: 90, 100, 140. mean = 110.0, devs -20, -10, +30 -> squares
    400 + 100 + 900 = 1400, /3 = 466.67, stdev = sqrt(1400/3) = 21.6025.
        boom band > 131.60 -> 140 only            -> 1 boom  (1/3)
        bust band <  88.40 -> none (90 is above)  -> 0 busts (0.0)
    """
    df = build_consistency_metrics(_weekly_scores_df(_season(1, [90.0, 100.0, 140.0])))

    row = _row(df, 1)
    assert row["stdev_points"] == pytest.approx(math.sqrt(1400 / 3))
    assert row["boom_weeks"] == 1
    assert row["boom_pct"] == pytest.approx(1 / 3)
    assert row["bust_weeks"] == 0
    assert row["bust_pct"] == 0.0


# --------------------------------------------------------------------------
# Coefficient of variation "where appropriate"
# --------------------------------------------------------------------------


def test_cv_is_undefined_for_a_zero_mean_roster() -> None:
    """``stdev / mean`` with a zero mean is a division by zero, so ``cv`` is
    ``NaN`` -- not ``0.0``, not an infinity, not an exception. The other
    columns are still reported.
    """
    df = build_consistency_metrics(_weekly_scores_df(_season(1, [0.0, 0.0, 0.0])))

    row = _row(df, 1)
    assert row["mean_points"] == 0.0
    assert row["stdev_points"] == 0.0
    assert pd.isna(row["cv"])
    assert row["boom_weeks"] == 0


def test_cv_is_undefined_for_a_negative_mean_roster() -> None:
    """A negative mean would make ``stdev / mean`` a negative "volatility",
    which is uninterpretable, so it is suppressed the same way. Boom/bust does
    not need a positive mean and is still reported.

    Weeks: -5, -10, -15. mean = -10.0, stdev = sqrt(50/3) = 4.0825.
        boom band > -5.918 -> -5 -> 1 boom; bust band < -14.082 -> -15 -> 1.
    """
    df = build_consistency_metrics(_weekly_scores_df(_season(1, [-5.0, -10.0, -15.0])))

    row = _row(df, 1)
    assert row["mean_points"] == pytest.approx(-10.0)
    assert row["stdev_points"] == pytest.approx(math.sqrt(50 / 3))
    assert pd.isna(row["cv"])
    assert row["boom_weeks"] == 1
    assert row["bust_weeks"] == 1


# --------------------------------------------------------------------------
# Threshold parameter
# --------------------------------------------------------------------------


def test_default_threshold_is_one_standard_deviation() -> None:
    assert BOOM_BUST_THRESHOLD_STDEVS == 1.0


def test_lower_threshold_classifies_more_weeks() -> None:
    """The toy's roster 3 (90, 90, 90, 170; mean 110, stdev 34.641) has zero
    busts at ``k = 1.0`` but three at ``k = 0.5``: the band narrows to
    ``110 +/- 17.32``, i.e. ``(92.68, 127.32)``, and all three 90s fall below
    it. The boom stays at one (170 clears both bands).
    """
    frame = _weekly_scores_df(_season(3, [90.0, 90.0, 90.0, 170.0]))

    strict = _row(build_consistency_metrics(frame), 3)
    loose = _row(build_consistency_metrics(frame, boom_bust_threshold=0.5), 3)

    assert strict["bust_weeks"] == 0
    assert loose["bust_weeks"] == 3
    assert loose["bust_pct"] == pytest.approx(0.75)
    assert strict["boom_weeks"] == loose["boom_weeks"] == 1
    # The threshold changes only the classification, never the distribution.
    assert strict["stdev_points"] == loose["stdev_points"]


def test_zero_threshold_counts_weeks_strictly_off_the_mean() -> None:
    """``k = 0`` degenerates to "above/below the mean", and strict inequality
    keeps the two exactly-average weeks in neither bucket.

    Weeks: 98, 100, 100, 102, mean 100.0 -> 1 boom (102), 1 bust (98).
    """
    df = build_consistency_metrics(
        _weekly_scores_df(_season(1, [98.0, 100.0, 100.0, 102.0])),
        boom_bust_threshold=0.0,
    )

    row = _row(df, 1)
    assert row["boom_weeks"] == 1
    assert row["bust_weeks"] == 1


def test_negative_threshold_raises() -> None:
    """A negative threshold would put the boom band below the bust band and
    let one week count as both.
    """
    frame = _weekly_scores_df(_season(1, [90.0, 100.0, 110.0]))

    with pytest.raises(ValueError, match="non-negative"):
        build_consistency_metrics(frame, boom_bust_threshold=-1.0)


# --------------------------------------------------------------------------
# Row set, missing values and phases
# --------------------------------------------------------------------------


def test_roster_with_no_scored_week_is_absent_from_the_output() -> None:
    """Rows are input-driven: a roster that never appears in
    ``weekly_scoring_ranks_df`` gets no row at all, not a row of nulls.
    """
    df = build_consistency_metrics(
        _weekly_scores_df(_season(1, [100.0, 90.0]) + _season(2, [80.0, 70.0]))
    )

    assert sorted(df["roster_id"]) == [1, 2]
    assert 3 not in set(df["roster_id"])


def test_missing_points_week_is_skipped_not_treated_as_zero() -> None:
    """FFA-050 never emits a missing score, but a hand-built input might: the
    week is dropped from the distribution entirely rather than dragging the
    mean and the floor down to zero.

    Weeks kept: 100, 110, 120 -> mean 110.0, floor 100.0, weeks_played 3.
    A 0.0 for the missing week would give mean 82.5 and floor 0.0.
    """
    rows = _season(1, [100.0, 110.0, 120.0]) + [
        _score_row(roster_id=1, points=None, week=4)
    ]
    df = build_consistency_metrics(_weekly_scores_df(rows))

    row = _row(df, 1)
    assert row["weeks_played"] == 3
    assert row["mean_points"] == pytest.approx(110.0)
    assert row["scoring_floor"] == 100.0


def test_roster_with_only_missing_points_is_absent() -> None:
    rows = _season(1, [100.0, 90.0]) + [
        _score_row(roster_id=2, points=None, week=1),
        _score_row(roster_id=2, points=None, week=2),
    ]
    df = build_consistency_metrics(_weekly_scores_df(rows))

    assert list(df["roster_id"]) == [1]


def test_all_missing_points_returns_empty_frame_with_columns() -> None:
    rows = [_score_row(roster_id=1, points=None), _score_row(roster_id=2, points=None)]
    df = build_consistency_metrics(_weekly_scores_df(rows))

    assert df.empty
    assert list(df.columns) == CONSISTENCY_METRICS_COLUMNS


def test_empty_input_returns_empty_frame_with_columns() -> None:
    df = build_consistency_metrics(_weekly_scores_df([]))

    assert df.empty
    assert list(df.columns) == CONSISTENCY_METRICS_COLUMNS


def test_playoff_and_regular_season_weeks_are_combined() -> None:
    """No phase filter: a playoff week enters the same distribution as the
    regular season's.

    Weeks 1-3 (regular): 100, 100, 100. Week 16 (playoff): 140.
    Combined mean = 440 / 4 = 110.0 and the distribution is no longer
    zero-variance.
    """
    rows = _season(1, [100.0, 100.0, 100.0]) + [
        _score_row(roster_id=1, points=140.0, week=16, is_playoff=True)
    ]
    df = build_consistency_metrics(_weekly_scores_df(rows))

    row = _row(df, 1)
    assert row["weeks_played"] == 4
    assert row["mean_points"] == pytest.approx(110.0)
    assert row["scoring_ceiling"] == 140.0
    assert row["stdev_points"] > 0
    assert "is_playoff" not in df.columns


def test_caller_can_get_a_phase_specific_view_by_filtering_the_input() -> None:
    """The documented way to get a regular-season-only consistency profile:
    filter ``weekly_scoring_ranks_df`` on ``is_playoff`` before calling. The
    mean and standard deviation are then recomputed within the filtered weeks.
    """
    rows = _season(1, [100.0, 100.0, 100.0]) + [
        _score_row(roster_id=1, points=140.0, week=16, is_playoff=True)
    ]
    frame = _weekly_scores_df(rows)

    regular = build_consistency_metrics(frame.loc[~frame["is_playoff"]])
    playoffs = build_consistency_metrics(frame.loc[frame["is_playoff"]])

    assert _row(regular, 1)["weeks_played"] == 3
    assert _row(regular, 1)["mean_points"] == pytest.approx(100.0)
    assert _row(regular, 1)["stdev_points"] == 0.0
    # A one-week playoff run: center is reported, dispersion is not.
    assert _row(playoffs, 1)["weeks_played"] == 1
    assert _row(playoffs, 1)["mean_points"] == pytest.approx(140.0)
    assert pd.isna(_row(playoffs, 1)["stdev_points"])


def test_multiple_seasons_are_pooled_into_one_row_per_roster() -> None:
    """Documented behavior (and documented caveat): two seasons are pooled,
    so a between-season level shift is reported as week-to-week volatility.

    2024: 100, 100. 2025: 200, 200. Pooled mean = 150.0 and stdev = 50.0 even
    though the roster was perfectly steady within each season.
    """
    rows = _season(1, [100.0, 100.0], season="2024") + _season(
        1, [200.0, 200.0], season="2025"
    )
    df = build_consistency_metrics(_weekly_scores_df(rows))

    assert len(df) == 1
    row = _row(df, 1)
    assert row["weeks_played"] == 4
    assert row["mean_points"] == pytest.approx(150.0)
    assert row["stdev_points"] == pytest.approx(50.0)


def test_owner_is_read_from_the_input_and_unresolved_stays_none() -> None:
    """``owner`` comes from FFA-050's already-resolved column; a roster with
    no resolved owner stays ``None`` rather than becoming ``NaN`` or raising.
    """
    rows = [
        _score_row(roster_id=1, points=100.0, week=1, owner="Alec"),
        _score_row(roster_id=1, points=110.0, week=2, owner="Alec"),
        _score_row(roster_id=2, points=90.0, week=1, owner=None),
        _score_row(roster_id=2, points=95.0, week=2, owner=None),
    ]
    df = build_consistency_metrics(_weekly_scores_df(rows))

    assert _row(df, 1)["owner"] == "Alec"
    assert _row(df, 2)["owner"] is None


def test_column_dtypes_are_stable_whether_or_not_a_roster_is_short() -> None:
    """Every metric column is ``float64`` in both cases, so a caller's dtype
    does not depend on whether some roster fell below the minimum week counts.
    """
    full = build_consistency_metrics(
        _weekly_scores_df(_season(1, [90.0, 100.0, 110.0, 120.0]))
    )
    mixed = build_consistency_metrics(
        _weekly_scores_df(_season(1, [90.0, 100.0, 110.0, 120.0]) + _season(2, [95.0]))
    )

    for frame in (full, mixed):
        assert frame["weeks_played"].dtype == "int64"
        assert frame["owner"].dtype == object
        for column in (
            "mean_points",
            "median_points",
            "stdev_points",
            "cv",
            "scoring_floor",
            "scoring_ceiling",
            "boom_weeks",
            "boom_pct",
            "bust_weeks",
            "bust_pct",
        ):
            assert frame[column].dtype == "float64", column


# --------------------------------------------------------------------------
# End-to-end composition with FFA-050
# --------------------------------------------------------------------------


def test_composes_with_build_weekly_scoring_ranks() -> None:
    """End-to-end: a real ``season_matchup_df`` -> FFA-050 -> FFA-053,
    including a bye week (which FFA-050 emits as a real score with no
    opponent, and which therefore belongs in the distribution).

    Roster 1: 100 (w1), 130 (w2), 70 (w3), 110 (w4 bye)
        mean   = 410 / 4 = 102.5
        median = sorted(70, 100, 110, 130) -> (100 + 110) / 2 = 105.0
        devs   = -2.5, +27.5, -32.5, +7.5
                 -> squares 6.25, 756.25, 1056.25, 56.25 -> 1875 -> 468.75
        stdev  = sqrt(468.75) = 21.6506...
        boom band > 124.15 -> 130 -> 1 boom; bust band < 80.85 -> 70 -> 1 bust

    Roster 2: 90 (w1), 95 (w2), 91 (w3) -- no week 4 at all
        mean   = 276 / 3 = 92.0
        median = 91.0
        devs   = -2, +3, -1 -> squares 4, 9, 1 -> 14 -> 14/3 = 4.6667
        stdev  = sqrt(14/3) = 2.1602...
        boom band > 94.16 -> 95 -> 1 boom; bust band < 89.84 -> none -> 0
    """
    matchup_rows = [
        _matchup(week=1, points_1=100.0, points_2=90.0),
        _matchup(week=2, points_1=130.0, points_2=95.0),
        _matchup(week=3, points_1=70.0, points_2=91.0),
        # Week 4: roster 1 has a bye -- a real score with no opponent.
        {
            "season": "2025",
            "week": 4,
            "is_playoff": False,
            "matchup_id": None,
            "roster_1_id": 1,
            "roster_2_id": None,
            "owner_1": "Alec",
            "owner_2": None,
            "points_1": 110.0,
            "points_2": None,
            "winner": None,
            "loser": None,
            "is_tie": False,
            "margin": None,
            "point_differential": None,
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
            for roster_id, name in [(1, "Alec"), (2, "Mike")]
        ],
        columns=["roster_id", "owner_id", "display_name", "team_name"],
    )

    weekly = build_weekly_scoring_ranks(season_matchup_df, teams_df)
    df = build_consistency_metrics(weekly)

    assert list(df["roster_id"]) == [1, 2]

    row_1 = _row(df, 1)
    assert row_1["owner"] == "Alec"
    assert row_1["weeks_played"] == 4  # the bye week counts
    assert row_1["mean_points"] == pytest.approx(102.5)
    assert row_1["median_points"] == pytest.approx(105.0)
    assert row_1["stdev_points"] == pytest.approx(math.sqrt(468.75))
    assert row_1["scoring_floor"] == 70.0
    assert row_1["scoring_ceiling"] == 130.0
    assert row_1["boom_weeks"] == 1
    assert row_1["bust_weeks"] == 1

    row_2 = _row(df, 2)
    assert row_2["owner"] == "Mike"
    assert row_2["weeks_played"] == 3
    assert row_2["mean_points"] == pytest.approx(92.0)
    assert row_2["median_points"] == pytest.approx(91.0)
    assert row_2["stdev_points"] == pytest.approx(math.sqrt(14 / 3))
    assert row_2["boom_weeks"] == 1
    assert row_2["bust_weeks"] == 0

    # The whole point of the metric, on a real pipeline: roster 1 scored more
    # on average and swung far harder.
    assert row_1["cv"] > row_2["cv"]


def _matchup(week: int, points_1: float, points_2: float) -> dict:
    """One ``SEASON_MATCHUP_COLUMNS`` row between rosters 1 and 2, with the
    outcome fields derived by hand exactly as
    :mod:`fantasy_analyzer.matchups.outcomes` would.
    """
    point_differential = points_1 - points_2
    return {
        "season": "2025",
        "week": week,
        "is_playoff": False,
        "matchup_id": 1,
        "roster_1_id": 1,
        "roster_2_id": 2,
        "owner_1": "Alec",
        "owner_2": "Mike",
        "points_1": points_1,
        "points_2": points_2,
        "winner": 1 if points_1 > points_2 else 2,
        "loser": 2 if points_1 > points_2 else 1,
        "is_tie": False,
        "margin": abs(point_differential),
        "point_differential": point_differential,
    }

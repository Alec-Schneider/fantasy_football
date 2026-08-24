"""Tests for team-level positional strength metrics (FFA-066).

All tests operate on hand-built ``player_week_df``-shaped inputs -- no HTTP
calls, no opaque fixture values -- so every total, mean, median, standard
deviation, coefficient of variation, boom/bust count, share, rank, and
depth count can be verified by hand arithmetic from the scores written in
each test, per AGENTS.md's analytics-ticket requirement for a
hand-checkable toy example.

Standard deviations are population (``ddof = 0``) throughout, matching
:mod:`fantasy_analyzer.players.position_strength`'s module docstring, so
hand arithmetic in these docstrings divides the sum of squared deviations by
``n``, not ``n - 1``.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from fantasy_analyzer.players import (
    MIN_WEEKS_FOR_BOOM_BUST,
    MIN_WEEKS_FOR_DISPERSION,
    PLAYER_WEEK_COLUMNS,
    POSITION_BOOM_BUST_THRESHOLD_STDEVS,
    POSITION_STRENGTH_COLUMNS,
    build_position_strength_metrics,
)

#: A minimal set of provider-style raw stat columns, used across tests. Only
#: their non-null-ness matters for the depth "game played" test -- their
#: values are otherwise irrelevant (fantasy_points is already computed).
STAT_COLUMNS = ["receptions", "receiving_yards"]

PLAYER_WEEK_TEST_COLUMNS = PLAYER_WEEK_COLUMNS + STAT_COLUMNS + ["fantasy_points"]


def _row(
    season: int,
    week: int,
    sleeper_player_id: str,
    fantasy_team: str,
    position: str,
    fantasy_points: float | None,
    started: bool = True,
    played: bool = True,
    roster_id: int = 1,
    player_name: str | None = "Player",
    nfl_team: str | None = "SF",
) -> dict:
    """One ``player_week_df``-shaped row.

    ``played=False`` mimics FFA-064's documented bye/inactive convention:
    every raw stat column ``NaN`` and ``fantasy_points`` forced to ``0.0``
    (never left ``None``), matching the real fact table's contract.
    """
    return {
        "season": season,
        "week": week,
        "roster_id": roster_id,
        "fantasy_team": fantasy_team,
        "sleeper_player_id": sleeper_player_id,
        "gsis_id": f"g-{sleeper_player_id}",
        "player_name": player_name,
        "position": position,
        "nfl_team": nfl_team,
        "started": started,
        "bench": not started,
        "receptions": None if not played else 4.0,
        "receiving_yards": None if not played else 50.0,
        "fantasy_points": 0.0 if not played else fantasy_points,
    }


def _df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=PLAYER_WEEK_TEST_COLUMNS)
    frame = pd.DataFrame(rows, columns=PLAYER_WEEK_TEST_COLUMNS)
    label_columns = (
        "player_name",
        "position",
        "nfl_team",
        "sleeper_player_id",
        "fantasy_team",
    )
    for column in label_columns:
        frame[column] = pd.Series(frame[column].tolist(), dtype=object)
    return frame


def _get_row(
    df: pd.DataFrame, fantasy_team: str, position: str, season: int = 2025
) -> pd.Series:
    match = df.loc[
        (df["fantasy_team"] == fantasy_team)
        & (df["position"] == position)
        & (df["season"] == season)
    ]
    assert len(match) == 1
    return match.iloc[0]


# --------------------------------------------------------------------------
# Hand-checkable toy example
# --------------------------------------------------------------------------


def _toy_rows() -> list[dict]:
    """Team Alpha, RB and WR groups, season 2025, weeks 1-4.

    RB1 (started every week): 10, 12, 8, 10
    RB2 (started every week): 5, 5, 5, 5
    Weekly RB total: 15, 17, 13, 15
        total=60, ppg=15.0
        median: sorted(13,15,15,17) -> (15+15)/2 = 15.0
        devs: -0, +2, -2, -0 -> squares 0,4,4,0 -> sum 8 -> /4 = 2
        stdev = sqrt(2) = 1.41421356...
        cv = sqrt(2)/15 = 0.09428090...
        floor=13.0, ceiling=17.0
        boom band > 16.41421 -> week2 (17) only -> 1 boom
        bust band < 13.58579 -> week3 (13) only -> 1 bust

    WR1 (started weeks 1-3, benched week 4): 20, 20, 20, (bench 5)
    WR2 (benched every week, real production): (bench 8) all 4 weeks
    Weekly WR total (started only): 20, 20, 20
        total=60, ppg=20.0, median=20.0, stdev=0.0, cv=0.0
        floor=ceiling=20.0, 0 booms, 0 busts (zero variance)

    RB depth: RB1, RB2 both started+played every week -> 2 distinct players.
    WR depth: WR1 (started+played) and WR2 (bench-only, played) both count
    -> 2 distinct players, demonstrating bench-only players still count
    toward depth even though WR2 never contributes to WR production.

    Team total (RB total + WR total) = 60 + 60 = 120.
    share_of_team_points: RB = 60/120 = 0.5, WR = 60/120 = 0.5.
    """
    rows = []
    for week, points in zip([1, 2, 3, 4], [10.0, 12.0, 8.0, 10.0]):
        rows.append(_row(2025, week, "RB1", "Alpha", "RB", points, started=True))
    for week, points in zip([1, 2, 3, 4], [5.0, 5.0, 5.0, 5.0]):
        rows.append(_row(2025, week, "RB2", "Alpha", "RB", points, started=True))
    for week, points in zip([1, 2, 3], [20.0, 20.0, 20.0]):
        rows.append(_row(2025, week, "WR1", "Alpha", "WR", points, started=True))
    rows.append(_row(2025, 4, "WR1", "Alpha", "WR", 5.0, started=False))
    for week in [1, 2, 3, 4]:
        rows.append(_row(2025, week, "WR2", "Alpha", "WR", 8.0, started=False))
    return rows


def test_toy_example_hand_computed() -> None:
    df = build_position_strength_metrics(_df(_toy_rows()))

    assert list(df.columns) == POSITION_STRENGTH_COLUMNS
    assert len(df) == 2

    rb = _get_row(df, "Alpha", "RB")
    assert rb["weeks_played"] == 4
    assert rb["total_points"] == pytest.approx(60.0)
    assert rb["points_per_game"] == pytest.approx(15.0)
    assert rb["median_points"] == pytest.approx(15.0)
    assert rb["stdev_points"] == pytest.approx(math.sqrt(2))
    assert rb["cv"] == pytest.approx(math.sqrt(2) / 15)
    assert rb["scoring_floor"] == pytest.approx(13.0)
    assert rb["scoring_ceiling"] == pytest.approx(17.0)
    assert rb["boom_weeks"] == 1
    assert rb["bust_weeks"] == 1
    assert rb["boom_pct"] == pytest.approx(0.25)
    assert rb["bust_pct"] == pytest.approx(0.25)
    assert rb["positional_depth"] == 2
    assert rb["positional_rank"] == 1  # only RB team in the frame

    wr = _get_row(df, "Alpha", "WR")
    assert wr["weeks_played"] == 3
    assert wr["total_points"] == pytest.approx(60.0)
    assert wr["points_per_game"] == pytest.approx(20.0)
    assert wr["median_points"] == pytest.approx(20.0)
    assert wr["stdev_points"] == pytest.approx(0.0)
    assert wr["cv"] == pytest.approx(0.0)
    assert wr["scoring_floor"] == pytest.approx(20.0)
    assert wr["scoring_ceiling"] == pytest.approx(20.0)
    assert wr["boom_weeks"] == 0
    assert wr["bust_weeks"] == 0
    assert wr["positional_depth"] == 2  # WR1 (started) + WR2 (bench-only)

    assert rb["share_of_team_points"] == pytest.approx(0.5)
    assert wr["share_of_team_points"] == pytest.approx(0.5)
    assert rb["share_of_team_points"] + wr["share_of_team_points"] == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Started vs. all weeks: the central design decision
# --------------------------------------------------------------------------


def test_bench_only_weeks_do_not_contribute_to_production() -> None:
    """A player benched every week (real production) contributes nothing to
    the position's weekly totals, even though he counts toward depth.
    """
    rows = [
        _row(2025, 1, "A", "Alpha", "TE", 30.0, started=False),
        _row(2025, 2, "A", "Alpha", "TE", 30.0, started=False),
    ]
    df = build_position_strength_metrics(_df(rows))

    # No started week at TE for Alpha at all -> no row.
    assert df.loc[(df["fantasy_team"] == "Alpha") & (df["position"] == "TE")].empty


def test_weeks_with_zero_starters_are_not_zero_filled() -> None:
    """Team starts a TE in weeks 1 and 3 only (bye/streamed in week 2); the
    weekly series has n=2, not n=3 with an inserted zero.

    Weeks: 10.0, 14.0 (week 2 has no started TE at all, and contributes no
    observation). mean=12.0, dev -2/+2 -> squares 4+4=8, /2=4, stdev=2.0.
    """
    rows = [
        _row(2025, 1, "A", "Alpha", "TE", 10.0, started=True),
        _row(2025, 3, "A", "Alpha", "TE", 14.0, started=True),
    ]
    df = build_position_strength_metrics(_df(rows))

    row = _get_row(df, "Alpha", "TE")
    assert row["weeks_played"] == 2
    assert row["total_points"] == pytest.approx(24.0)
    assert row["points_per_game"] == pytest.approx(12.0)
    assert row["stdev_points"] == pytest.approx(2.0)


def test_multiple_starters_same_week_are_summed() -> None:
    """Two starting running backs in the same week produce one weekly
    observation equal to their combined score.
    """
    rows = [
        _row(2025, 1, "A", "Alpha", "RB", 10.0, started=True),
        _row(2025, 1, "B", "Alpha", "RB", 7.0, started=True),
    ]
    df = build_position_strength_metrics(_df(rows))

    row = _get_row(df, "Alpha", "RB")
    assert row["weeks_played"] == 1
    assert row["total_points"] == pytest.approx(17.0)
    assert row["positional_depth"] == 2


# --------------------------------------------------------------------------
# Positional depth
# --------------------------------------------------------------------------


def test_depth_requires_a_qualifying_game_not_just_a_roster_spot() -> None:
    """A rostered player who never has real provider stats (bye/inactive
    every week) does not count toward depth, even if fantasy_points happens
    to be nonzero-argued (FFA-064's contract forces 0.0, but this asserts
    the module does not rely on that contract to exclude him).
    """
    rows = [
        _row(2025, 1, "A", "Alpha", "RB", 10.0, started=True, played=True),
        _row(2025, 1, "B", "Alpha", "RB", 0.0, started=False, played=False),
        _row(2025, 2, "B", "Alpha", "RB", 0.0, started=False, played=False),
    ]
    df = build_position_strength_metrics(_df(rows))

    row = _get_row(df, "Alpha", "RB")
    assert row["positional_depth"] == 1  # only A ever had a qualifying game


def test_depth_counts_distinct_players_not_player_weeks() -> None:
    rows = [
        _row(2025, 1, "A", "Alpha", "RB", 10.0, started=True),
        _row(2025, 2, "A", "Alpha", "RB", 12.0, started=True),
        _row(2025, 3, "A", "Alpha", "RB", 8.0, started=True),
    ]
    df = build_position_strength_metrics(_df(rows))

    row = _get_row(df, "Alpha", "RB")
    assert row["positional_depth"] == 1


def test_no_stat_columns_means_depth_is_zero_but_row_still_emitted() -> None:
    """Degenerate input: with zero raw stat columns no player-week can ever
    satisfy the depth "game played" test, but production/consistency don't
    depend on that test at all, so the row is still emitted with
    positional_depth = 0.
    """
    frame = pd.DataFrame(
        [
            {
                "season": 2025,
                "week": 1,
                "roster_id": 1,
                "fantasy_team": "Alpha",
                "sleeper_player_id": "A",
                "gsis_id": "g-A",
                "player_name": "Player",
                "position": "RB",
                "nfl_team": "SF",
                "started": True,
                "bench": False,
                "fantasy_points": 20.0,
            }
        ],
        columns=PLAYER_WEEK_COLUMNS + ["fantasy_points"],
    )
    df = build_position_strength_metrics(frame)

    row = _get_row(df, "Alpha", "RB")
    assert row["total_points"] == pytest.approx(20.0)
    assert row["positional_depth"] == 0


# --------------------------------------------------------------------------
# positional_rank
# --------------------------------------------------------------------------


def test_positional_rank_orders_teams_by_total_points_descending() -> None:
    rows = [
        _row(2025, 1, "A", "Alpha", "RB", 100.0, started=True),
        _row(2025, 1, "B", "Beta", "RB", 80.0, started=True),
        _row(2025, 1, "C", "Gamma", "RB", 60.0, started=True),
    ]
    df = build_position_strength_metrics(_df(rows))

    assert _get_row(df, "Alpha", "RB")["positional_rank"] == 1
    assert _get_row(df, "Beta", "RB")["positional_rank"] == 2
    assert _get_row(df, "Gamma", "RB")["positional_rank"] == 3


def test_positional_rank_ties_use_standard_competition_ranking() -> None:
    """Alpha and Beta tie for the RB lead; Gamma is third and should be
    ranked 3, not 2 -- the "1224" skip-on-tie convention.
    """
    rows = [
        _row(2025, 1, "A", "Alpha", "RB", 100.0, started=True),
        _row(2025, 1, "B", "Beta", "RB", 100.0, started=True),
        _row(2025, 1, "C", "Gamma", "RB", 60.0, started=True),
    ]
    df = build_position_strength_metrics(_df(rows))

    assert _get_row(df, "Alpha", "RB")["positional_rank"] == 1
    assert _get_row(df, "Beta", "RB")["positional_rank"] == 1
    assert _get_row(df, "Gamma", "RB")["positional_rank"] == 3


def test_rank_field_only_includes_teams_with_a_row_at_that_position() -> None:
    """Alpha never starts a TE; Beta does. Beta's TE rank is 1 among a field
    of one, not compared against a phantom zero for Alpha.
    """
    rows = [
        _row(2025, 1, "A", "Alpha", "RB", 10.0, started=True),
        _row(2025, 1, "B", "Beta", "TE", 5.0, started=True),
    ]
    df = build_position_strength_metrics(_df(rows))

    te_rows = df.loc[df["position"] == "TE"]
    assert len(te_rows) == 1
    assert te_rows.iloc[0]["positional_rank"] == 1
    assert te_rows.iloc[0]["fantasy_team"] == "Beta"


# --------------------------------------------------------------------------
# share_of_team_points
# --------------------------------------------------------------------------


def test_share_of_team_points_partitions_a_teams_total() -> None:
    rows = [
        _row(2025, 1, "A", "Alpha", "QB", 30.0, started=True),
        _row(2025, 1, "B", "Alpha", "RB", 10.0, started=True),
        _row(2025, 1, "C", "Alpha", "WR", 60.0, started=True),
    ]
    df = build_position_strength_metrics(_df(rows))

    alpha = df.loc[df["fantasy_team"] == "Alpha"]
    assert alpha["share_of_team_points"].sum() == pytest.approx(1.0)
    assert _get_row(df, "Alpha", "QB")["share_of_team_points"] == pytest.approx(0.3)
    assert _get_row(df, "Alpha", "RB")["share_of_team_points"] == pytest.approx(0.1)
    assert _get_row(df, "Alpha", "WR")["share_of_team_points"] == pytest.approx(0.6)


def test_share_of_team_points_is_nan_when_team_total_is_non_positive() -> None:
    rows = [
        _row(2025, 1, "A", "Alpha", "DEF", -5.0, started=True),
    ]
    df = build_position_strength_metrics(_df(rows))

    row = _get_row(df, "Alpha", "DEF")
    assert pd.isna(row["share_of_team_points"])


def test_negative_position_can_push_another_positions_share_above_one() -> None:
    """QB total 30, DEF total -10 -> team total 20. QB share = 30/20 = 1.5,
    DEF share = -10/20 = -0.5. Not clamped -- a literal reading of "share".
    """
    rows = [
        _row(2025, 1, "A", "Alpha", "QB", 30.0, started=True),
        _row(2025, 1, "B", "Alpha", "DEF", -10.0, started=True),
    ]
    df = build_position_strength_metrics(_df(rows))

    assert _get_row(df, "Alpha", "QB")["share_of_team_points"] == pytest.approx(1.5)
    assert _get_row(df, "Alpha", "DEF")["share_of_team_points"] == pytest.approx(-0.5)


# --------------------------------------------------------------------------
# Small-sample rules (mirrors consistency.py's n<2 / n<3 guards)
# --------------------------------------------------------------------------


def test_single_week_group_has_undefined_stdev_cv_and_boom_bust() -> None:
    rows = [_row(2025, 1, "A", "Alpha", "QB", 15.5, started=True)]
    df = build_position_strength_metrics(_df(rows))

    row = _get_row(df, "Alpha", "QB")
    assert row["weeks_played"] == 1
    assert row["points_per_game"] == pytest.approx(15.5)
    undefined_columns = (
        "stdev_points",
        "cv",
        "boom_weeks",
        "boom_pct",
        "bust_weeks",
        "bust_pct",
    )
    for column in undefined_columns:
        assert pd.isna(row[column])


def test_two_week_group_has_dispersion_but_no_boom_bust() -> None:
    assert MIN_WEEKS_FOR_DISPERSION == 2
    assert MIN_WEEKS_FOR_BOOM_BUST == 3

    rows = [
        _row(2025, 1, "A", "Alpha", "QB", 9.0, started=True),
        _row(2025, 2, "A", "Alpha", "QB", 11.0, started=True),
    ]
    df = build_position_strength_metrics(_df(rows))

    row = _get_row(df, "Alpha", "QB")
    assert row["stdev_points"] == pytest.approx(1.0)
    assert row["cv"] == pytest.approx(0.10)
    for column in ("boom_weeks", "boom_pct", "bust_weeks", "bust_pct"):
        assert pd.isna(row[column])


def test_three_week_group_does_get_boom_bust() -> None:
    """Weeks: 9, 10, 14. mean = 11.0, devs -2, -1, +3 -> squares 4+1+9=14,
    /3 = 4.6667, stdev = sqrt(14/3) = 2.1602.
        boom band > 13.16 -> 14 only -> 1 boom (1/3)
        bust band <  8.84 -> none     -> 0 busts
    """
    rows = [
        _row(2025, 1, "A", "Alpha", "QB", 9.0, started=True),
        _row(2025, 2, "A", "Alpha", "QB", 10.0, started=True),
        _row(2025, 3, "A", "Alpha", "QB", 14.0, started=True),
    ]
    df = build_position_strength_metrics(_df(rows))

    row = _get_row(df, "Alpha", "QB")
    assert row["stdev_points"] == pytest.approx(math.sqrt(14 / 3))
    assert row["boom_weeks"] == 1
    assert row["boom_pct"] == pytest.approx(1 / 3)
    assert row["bust_weeks"] == 0


def test_cv_is_undefined_for_a_zero_mean_group() -> None:
    rows = [
        _row(2025, 1, "A", "Alpha", "QB", 0.0, started=True),
        _row(2025, 2, "A", "Alpha", "QB", 0.0, started=True),
        _row(2025, 3, "A", "Alpha", "QB", 0.0, started=True),
    ]
    df = build_position_strength_metrics(_df(rows))

    row = _get_row(df, "Alpha", "QB")
    assert row["points_per_game"] == 0.0
    assert row["stdev_points"] == 0.0
    assert pd.isna(row["cv"])


def test_default_threshold_is_one_standard_deviation() -> None:
    assert POSITION_BOOM_BUST_THRESHOLD_STDEVS == 1.0


def test_negative_threshold_raises() -> None:
    rows = [
        _row(2025, 1, "A", "Alpha", "QB", 9.0, started=True),
        _row(2025, 2, "A", "Alpha", "QB", 10.0, started=True),
        _row(2025, 3, "A", "Alpha", "QB", 14.0, started=True),
    ]
    with pytest.raises(ValueError, match="non-negative"):
        build_position_strength_metrics(_df(rows), boom_bust_threshold=-1.0)


# --------------------------------------------------------------------------
# Grouping key: missing labels, seasons
# --------------------------------------------------------------------------


def test_row_with_missing_position_is_skipped_and_excluded_from_team_total() -> None:
    rows = [
        _row(2025, 1, "A", "Alpha", "RB", 10.0, started=True),
        _row(2025, 1, "B", "Alpha", None, 100.0, started=True),
    ]
    df = build_position_strength_metrics(_df(rows))

    assert list(df["position"]) == ["RB"]
    row = _get_row(df, "Alpha", "RB")
    # share is 1.0, not 10/110 -- the unresolved-position row's points never
    # enter the team-total denominator.
    assert row["share_of_team_points"] == pytest.approx(1.0)


def test_row_with_missing_fantasy_team_is_skipped() -> None:
    rows = [
        _row(2025, 1, "A", None, "RB", 10.0, started=True),
        _row(2025, 1, "B", "Alpha", "RB", 20.0, started=True),
    ]
    df = build_position_strength_metrics(_df(rows))

    assert len(df) == 1
    row = _get_row(df, "Alpha", "RB")
    assert row["total_points"] == pytest.approx(20.0)


def test_multiple_seasons_are_not_pooled() -> None:
    rows = [
        _row(2024, 1, "A", "Alpha", "QB", 10.0, started=True),
        _row(2024, 2, "A", "Alpha", "QB", 10.0, started=True),
        _row(2025, 1, "A", "Alpha", "QB", 40.0, started=True),
        _row(2025, 2, "A", "Alpha", "QB", 40.0, started=True),
    ]
    df = build_position_strength_metrics(_df(rows))

    row_2024 = _get_row(df, "Alpha", "QB", season=2024)
    row_2025 = _get_row(df, "Alpha", "QB", season=2025)
    assert row_2024["points_per_game"] == pytest.approx(10.0)
    assert row_2025["points_per_game"] == pytest.approx(40.0)


# --------------------------------------------------------------------------
# Empty input / column shape
# --------------------------------------------------------------------------


def test_empty_input_returns_empty_frame_with_columns() -> None:
    df = build_position_strength_metrics(_df([]))

    assert df.empty
    assert list(df.columns) == POSITION_STRENGTH_COLUMNS


def test_no_team_has_a_started_week_returns_empty_frame() -> None:
    rows = [_row(2025, 1, "A", "Alpha", "RB", 30.0, started=False)]
    df = build_position_strength_metrics(_df(rows))

    assert df.empty
    assert list(df.columns) == POSITION_STRENGTH_COLUMNS


def test_column_dtypes() -> None:
    df = build_position_strength_metrics(_df(_toy_rows()))

    assert df["season"].dtype == "int64"
    assert df["weeks_played"].dtype == "int64"
    assert df["positional_rank"].dtype == "int64"
    assert df["positional_depth"].dtype == "int64"
    assert df["fantasy_team"].dtype == object
    assert df["position"].dtype == object
    for column in (
        "total_points",
        "points_per_game",
        "median_points",
        "stdev_points",
        "cv",
        "scoring_floor",
        "scoring_ceiling",
        "boom_weeks",
        "boom_pct",
        "bust_weeks",
        "bust_pct",
        "share_of_team_points",
    ):
        assert df[column].dtype == "float64", column

"""Tests for season-level player performance metrics (FFA-065).

All tests operate on hand-built ``player_week_df``-shaped inputs -- no HTTP
calls, no opaque fixture values -- so every total, mean, median, standard
deviation, coefficient of variation and boom/bust count can be verified by
hand arithmetic from the scores written in each test, per AGENTS.md's
analytics-ticket requirement for a hand-checkable toy example.

Standard deviations are population (``ddof = 0``) throughout, matching
:mod:`fantasy_analyzer.players.performance`'s module docstring, so hand
arithmetic in these docstrings divides the sum of squared deviations by
``n``, not ``n - 1``.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from fantasy_analyzer.players import (
    MIN_GAMES_FOR_BOOM_BUST,
    MIN_GAMES_FOR_DISPERSION,
    PLAYER_BOOM_BUST_THRESHOLD_STDEVS,
    PLAYER_PERFORMANCE_COLUMNS,
    PLAYER_WEEK_COLUMNS,
    build_player_performance_metrics,
)

#: A minimal set of provider-style raw stat columns, used across tests. Only
#: their non-null-ness matters for the "game played" test -- their values are
#: otherwise irrelevant to this module (fantasy_points is already computed).
STAT_COLUMNS = ["receptions", "receiving_yards"]

PLAYER_WEEK_TEST_COLUMNS = PLAYER_WEEK_COLUMNS + STAT_COLUMNS + ["fantasy_points"]


def _row(
    season: int,
    week: int,
    sleeper_player_id: str,
    fantasy_points: float | None,
    played: bool = True,
    player_name: str | None = "Player",
    position: str | None = "WR",
    nfl_team: str | None = "SF",
    roster_id: int = 1,
    started: bool = True,
) -> dict:
    """One ``player_week_df``-shaped row.

    ``played=False`` mimics FFA-064's documented bye/inactive convention:
    every raw stat column ``NaN`` and ``fantasy_points`` forced to ``0.0``
    (never left ``None``), regardless of the ``fantasy_points`` argument --
    matching the real fact table's contract that a non-played week is always
    zero-scored, never missing.
    """
    return {
        "season": season,
        "week": week,
        "roster_id": roster_id,
        "fantasy_team": "Alec",
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
    for column in ("player_name", "position", "nfl_team", "sleeper_player_id"):
        frame[column] = pd.Series(frame[column].tolist(), dtype=object)
    return frame


def _season_rows(
    sleeper_player_id: str,
    points: list[float],
    season: int = 2025,
    start_week: int = 1,
    **kwargs,
) -> list[dict]:
    """Shorthand: one player's weekly fantasy points, starting at ``start_week``."""
    return [
        _row(
            season=season,
            week=week,
            sleeper_player_id=sleeper_player_id,
            fantasy_points=value,
            **kwargs,
        )
        for week, value in enumerate(points, start=start_week)
    ]


def _get_row(df: pd.DataFrame, sleeper_player_id: str, season: int = 2025) -> pd.Series:
    match = df.loc[
        (df["sleeper_player_id"] == sleeper_player_id) & (df["season"] == season)
    ]
    assert len(match) == 1
    return match.iloc[0]


# --------------------------------------------------------------------------
# Hand-checkable toy example
# --------------------------------------------------------------------------


def _toy_rows() -> list[dict]:
    """Two players, four weeks each, deliberately different volatility.

    Player A -- metronome: 8, 10, 10, 12
        total  = 40.0, ppg = 10.0
        median = sorted(8, 10, 10, 12) -> (10 + 10) / 2 = 10.0
        devs   = -2, 0, 0, +2 -> squares 4, 0, 0, 4 -> sum 8 -> /4 = 2
        stdev  = sqrt(2) = 1.41421356...
        cv     = sqrt(2) / 10 = 0.141421356...
        floor  = 8.0, ceiling = 12.0
        boom band > 11.41 -> 12 only -> 1 boom
        bust band < 8.586  ->  8 only -> 1 bust

    Player B -- boom/bust: 2, 30, 5, 3
        total  = 40.0 (identical total to Player A), ppg = 10.0
        median = sorted(2, 3, 5, 30) -> (3 + 5) / 2 = 4.0
        devs   = -8, +20, -5, -7 -> squares 64, 400, 25, 49 -> 538 -> /4=134.5
        stdev  = sqrt(134.5) = 11.59741...
        cv     = sqrt(134.5) / 10 = 1.159741...
        floor  = 2.0, ceiling = 30.0
        boom band > 21.597 -> 30 only -> 1 boom
        bust band < -1.597 -> none    -> 0 busts
    """
    return _season_rows("A", [8.0, 10.0, 10.0, 12.0]) + _season_rows(
        "B", [2.0, 30.0, 5.0, 3.0]
    )


def test_toy_example_hand_computed() -> None:
    df = build_player_performance_metrics(_df(_toy_rows()))

    assert list(df.columns) == PLAYER_PERFORMANCE_COLUMNS
    assert len(df) == 2

    row_a = _get_row(df, "A")
    assert row_a["games_played"] == 4
    assert row_a["total_points"] == pytest.approx(40.0)
    assert row_a["points_per_game"] == pytest.approx(10.0)
    assert row_a["median_points"] == pytest.approx(10.0)
    assert row_a["stdev_points"] == pytest.approx(math.sqrt(2))
    assert row_a["cv"] == pytest.approx(math.sqrt(2) / 10)
    assert row_a["scoring_floor"] == pytest.approx(8.0)
    assert row_a["scoring_ceiling"] == pytest.approx(12.0)
    assert row_a["boom_games"] == 1
    assert row_a["bust_games"] == 1
    assert row_a["boom_pct"] == pytest.approx(0.25)
    assert row_a["bust_pct"] == pytest.approx(0.25)

    row_b = _get_row(df, "B")
    assert row_b["games_played"] == 4
    assert row_b["total_points"] == pytest.approx(40.0)
    assert row_b["points_per_game"] == pytest.approx(10.0)
    assert row_b["median_points"] == pytest.approx(4.0)
    assert row_b["stdev_points"] == pytest.approx(math.sqrt(134.5))
    assert row_b["cv"] == pytest.approx(math.sqrt(134.5) / 10)
    assert row_b["scoring_floor"] == pytest.approx(2.0)
    assert row_b["scoring_ceiling"] == pytest.approx(30.0)
    assert row_b["boom_games"] == 1
    assert row_b["bust_games"] == 0
    assert row_b["boom_pct"] == pytest.approx(0.25)
    assert row_b["bust_pct"] == 0.0

    # Same total and ppg, only dispersion tells them apart -- the point of
    # the ticket.
    assert row_a["points_per_game"] == row_b["points_per_game"]
    assert row_a["stdev_points"] < row_b["stdev_points"]
    assert row_a["cv"] < row_b["cv"]

    # Deterministic display order: ascending (season, sleeper_player_id).
    assert list(df["sleeper_player_id"]) == ["A", "B"]
    assert "rank" not in df.columns


# --------------------------------------------------------------------------
# Bye / inactive-week exclusion: the central design decision
# --------------------------------------------------------------------------


def test_bye_week_is_not_counted_as_a_zero_point_game() -> None:
    """A rostered player with a bye week (NaN stats, fantasy_points forced to
    0.0 by FFA-064's contract) must not have that week silently counted as a
    zero-point game -- this test would fail if that bug were reintroduced.

    Played weeks: 20, 20 (bye), 20. If the bye were wrongly counted as a
    third game worth 0.0, games_played would be 3 and points_per_game would
    be (20+0+20)/3 = 13.33 with a floor of 0.0. Correctly excluding it gives
    games_played = 2, points_per_game = 20.0, floor = ceiling = 20.0.
    """
    rows = [
        _row(2025, 1, "A", fantasy_points=20.0, played=True),
        _row(2025, 2, "A", fantasy_points=None, played=False),  # bye week
        _row(2025, 3, "A", fantasy_points=20.0, played=True),
    ]
    df = build_player_performance_metrics(_df(rows))

    row = _get_row(df, "A")
    assert row["games_played"] == 2
    assert row["points_per_game"] == pytest.approx(20.0)
    assert row["total_points"] == pytest.approx(40.0)
    assert row["scoring_floor"] == pytest.approx(20.0)
    assert row["scoring_ceiling"] == pytest.approx(20.0)
    assert row["stdev_points"] == 0.0


def test_played_zero_point_game_is_still_counted_as_a_game() -> None:
    """A player who was active and has real (non-null) provider stats but
    scored zero fantasy points is a played game, not a bye -- distinguishing
    "played and produced nothing" from "did not play" is the whole point of
    keying off raw stat non-nullness rather than fantasy_points.
    """
    rows = [
        _row(2025, 1, "A", fantasy_points=20.0, played=True),
        _row(2025, 2, "A", fantasy_points=0.0, played=True),  # played, scored 0
        _row(2025, 3, "A", fantasy_points=20.0, played=True),
    ]
    df = build_player_performance_metrics(_df(rows))

    row = _get_row(df, "A")
    assert row["games_played"] == 3
    assert row["scoring_floor"] == 0.0
    assert row["total_points"] == pytest.approx(40.0)


def test_no_stat_columns_at_all_means_no_row_qualifies() -> None:
    """Degenerate input: a player_week_df with zero raw stat columns can
    never satisfy the "game played" rule, so every player is excluded.
    """
    frame = pd.DataFrame(
        [
            {
                "season": 2025,
                "week": 1,
                "roster_id": 1,
                "fantasy_team": "Alec",
                "sleeper_player_id": "A",
                "gsis_id": "g-A",
                "player_name": "Player",
                "position": "WR",
                "nfl_team": "SF",
                "started": True,
                "bench": False,
                "fantasy_points": 20.0,
            }
        ],
        columns=PLAYER_WEEK_COLUMNS + ["fantasy_points"],
    )
    df = build_player_performance_metrics(frame)

    assert df.empty
    assert list(df.columns) == PLAYER_PERFORMANCE_COLUMNS


# --------------------------------------------------------------------------
# Started vs. bench
# --------------------------------------------------------------------------


def test_benched_games_are_included_in_the_distribution() -> None:
    """Both started and bench weeks count, since this table describes
    on-field performance regardless of the fantasy manager's start/sit call.
    """
    rows = [
        _row(2025, 1, "A", fantasy_points=10.0, started=True),
        _row(2025, 2, "A", fantasy_points=30.0, started=False),  # benched
    ]
    df = build_player_performance_metrics(_df(rows))

    row = _get_row(df, "A")
    assert row["games_played"] == 2
    assert row["total_points"] == pytest.approx(40.0)
    assert row["scoring_ceiling"] == pytest.approx(30.0)


# --------------------------------------------------------------------------
# Small-sample rules (mirrors consistency.py's n<2 / n<3 guards)
# --------------------------------------------------------------------------


def test_single_game_player_has_undefined_stdev_cv_and_boom_bust() -> None:
    df = build_player_performance_metrics(_df(_season_rows("A", [15.5])))

    row = _get_row(df, "A")
    assert row["games_played"] == 1
    assert row["points_per_game"] == pytest.approx(15.5)
    assert row["total_points"] == pytest.approx(15.5)
    assert row["scoring_floor"] == pytest.approx(15.5)
    assert row["scoring_ceiling"] == pytest.approx(15.5)
    undefined_columns = (
        "stdev_points",
        "cv",
        "boom_games",
        "boom_pct",
        "bust_games",
        "bust_pct",
    )
    for column in undefined_columns:
        assert pd.isna(row[column])


def test_two_game_player_has_dispersion_but_no_boom_bust() -> None:
    """Weeks: 9, 11. mean = 10.0, devs -1/+1 -> squares 1+1=2, /2=1,
    stdev = 1.0, cv = 0.10. Boom/bust suppressed -- each observation sits
    exactly one population standard deviation from the mean.
    """
    assert MIN_GAMES_FOR_DISPERSION == 2
    assert MIN_GAMES_FOR_BOOM_BUST == 3

    df = build_player_performance_metrics(_df(_season_rows("A", [9.0, 11.0])))

    row = _get_row(df, "A")
    assert row["games_played"] == 2
    assert row["stdev_points"] == pytest.approx(1.0)
    assert row["cv"] == pytest.approx(0.10)
    for column in ("boom_games", "boom_pct", "bust_games", "bust_pct"):
        assert pd.isna(row[column])


def test_three_game_player_does_get_boom_bust() -> None:
    """Weeks: 9, 10, 14. mean = 11.0, devs -2, -1, +3 -> squares 4+1+9=14,
    /3 = 4.6667, stdev = sqrt(14/3) = 2.1602.
        boom band > 13.16 -> 14 only -> 1 boom (1/3)
        bust band <  8.84 -> none     -> 0 busts
    """
    df = build_player_performance_metrics(_df(_season_rows("A", [9.0, 10.0, 14.0])))

    row = _get_row(df, "A")
    assert row["stdev_points"] == pytest.approx(math.sqrt(14 / 3))
    assert row["boom_games"] == 1
    assert row["boom_pct"] == pytest.approx(1 / 3)
    assert row["bust_games"] == 0
    assert row["bust_pct"] == 0.0


def test_zero_variance_player_is_perfectly_consistent_with_no_booms() -> None:
    df = build_player_performance_metrics(_df(_season_rows("A", [12.0] * 5)))

    row = _get_row(df, "A")
    assert row["games_played"] == 5
    assert row["points_per_game"] == 12.0
    assert row["median_points"] == 12.0
    assert row["stdev_points"] == 0.0
    assert row["cv"] == 0.0
    assert row["scoring_floor"] == row["scoring_ceiling"] == 12.0
    assert row["boom_games"] == 0
    assert row["bust_games"] == 0


# --------------------------------------------------------------------------
# Coefficient of variation "where appropriate"
# --------------------------------------------------------------------------


def test_cv_is_undefined_for_a_zero_mean_player() -> None:
    df = build_player_performance_metrics(_df(_season_rows("A", [0.0, 0.0, 0.0])))

    row = _get_row(df, "A")
    assert row["points_per_game"] == 0.0
    assert row["stdev_points"] == 0.0
    assert pd.isna(row["cv"])
    assert row["boom_games"] == 0


# --------------------------------------------------------------------------
# Threshold parameter
# --------------------------------------------------------------------------


def test_default_threshold_is_one_standard_deviation() -> None:
    assert PLAYER_BOOM_BUST_THRESHOLD_STDEVS == 1.0


def test_negative_threshold_raises() -> None:
    frame = _df(_season_rows("A", [9.0, 10.0, 14.0]))

    with pytest.raises(ValueError, match="non-negative"):
        build_player_performance_metrics(frame, boom_bust_threshold=-1.0)


def test_lower_threshold_classifies_more_games() -> None:
    """Toy player B (2, 30, 5, 3; mean 10.0, stdev sqrt(134.5)=11.597) has
    zero busts at k=1.0. At k=0.2 the bust band narrows to
    10 - 0.2*11.597 = 7.68, and 2, 5, 3 all fall below it -> 3 busts.
    """
    frame = _df(_season_rows("B", [2.0, 30.0, 5.0, 3.0]))

    strict = _get_row(build_player_performance_metrics(frame), "B")
    loose = _get_row(
        build_player_performance_metrics(frame, boom_bust_threshold=0.2), "B"
    )

    assert strict["bust_games"] == 0
    assert loose["bust_games"] == 3
    assert loose["bust_pct"] == pytest.approx(0.75)
    assert strict["stdev_points"] == loose["stdev_points"]


# --------------------------------------------------------------------------
# Grouping key: players and seasons
# --------------------------------------------------------------------------


def test_player_with_no_qualifying_game_is_absent_from_output() -> None:
    """A player rostered every week but on bye/inactive every week (never a
    qualifying game) gets no row at all -- not a row of NaN/zero metrics.
    """
    rows = [
        _row(2025, 1, "A", fantasy_points=None, played=False),
        _row(2025, 2, "A", fantasy_points=None, played=False),
        _row(2025, 1, "B", fantasy_points=10.0, played=True),
    ]
    df = build_player_performance_metrics(_df(rows))

    assert list(df["sleeper_player_id"]) == ["B"]
    assert "A" not in set(df["sleeper_player_id"])


def test_multiple_seasons_for_the_same_player_are_not_pooled() -> None:
    """2024: 10, 10. 2025: 40, 40. Two separate rows, not one pooled row --
    unlike consistency.py's team-level pooling default.
    """
    rows = _season_rows("A", [10.0, 10.0], season=2024) + _season_rows(
        "A", [40.0, 40.0], season=2025
    )
    df = build_player_performance_metrics(_df(rows))

    assert len(df) == 2
    row_2024 = _get_row(df, "A", season=2024)
    row_2025 = _get_row(df, "A", season=2025)
    assert row_2024["games_played"] == 2
    assert row_2024["points_per_game"] == pytest.approx(10.0)
    assert row_2024["stdev_points"] == 0.0
    assert row_2025["games_played"] == 2
    assert row_2025["points_per_game"] == pytest.approx(40.0)
    assert row_2025["stdev_points"] == 0.0
    # Ordered by ascending season within a player.
    assert list(df["season"]) == [2024, 2025]


def test_label_columns_use_majority_vote_with_first_seen_tiebreak() -> None:
    """A midseason trade: player is on SF for weeks 1-2, KC for week 3.
    SF has more occurrences (2 vs 1), so nfl_team resolves to SF.
    """
    rows = [
        _row(2025, 1, "A", fantasy_points=10.0, nfl_team="SF"),
        _row(2025, 2, "A", fantasy_points=10.0, nfl_team="SF"),
        _row(2025, 3, "A", fantasy_points=10.0, nfl_team="KC"),
    ]
    df = build_player_performance_metrics(_df(rows))

    row = _get_row(df, "A")
    assert row["nfl_team"] == "SF"


def test_label_tie_is_broken_by_first_occurrence() -> None:
    """A 1-1 tie in nfl_team: SF appears first, so SF wins."""
    rows = [
        _row(2025, 1, "A", fantasy_points=10.0, nfl_team="SF"),
        _row(2025, 2, "A", fantasy_points=10.0, nfl_team="KC"),
    ]
    df = build_player_performance_metrics(_df(rows))

    row = _get_row(df, "A")
    assert row["nfl_team"] == "SF"


def test_label_evidence_includes_non_played_weeks() -> None:
    """A bye week's row still carries a legitimate identity label and counts
    as label evidence even though it does not count as a played game.
    """
    rows = [
        _row(2025, 1, "A", fantasy_points=10.0, played=True, position="WR"),
        _row(2025, 2, "A", fantasy_points=None, played=False, position="WR"),
        _row(2025, 3, "A", fantasy_points=10.0, played=True, position="WR"),
    ]
    df = build_player_performance_metrics(_df(rows))

    row = _get_row(df, "A")
    assert row["games_played"] == 2  # the bye week is not a played game...
    assert row["position"] == "WR"  # ...but still contributed a label vote


def test_ties_in_weekly_points_need_no_special_handling() -> None:
    """Repeated fantasy_points values are ordinary members of the multiset;
    median/floor/ceiling handle them with no special ties convention.

    Weeks: 5, 5, 5, 15. total=30, ppg=7.5, median=(5+5)/2=5.0, floor=5.0,
    ceiling=15.0.
    """
    df = build_player_performance_metrics(_df(_season_rows("A", [5.0, 5.0, 5.0, 15.0])))

    row = _get_row(df, "A")
    assert row["total_points"] == pytest.approx(30.0)
    assert row["points_per_game"] == pytest.approx(7.5)
    assert row["median_points"] == pytest.approx(5.0)
    assert row["scoring_floor"] == pytest.approx(5.0)
    assert row["scoring_ceiling"] == pytest.approx(15.0)


# --------------------------------------------------------------------------
# Empty input / column shape
# --------------------------------------------------------------------------


def test_empty_input_returns_empty_frame_with_columns() -> None:
    df = build_player_performance_metrics(_df([]))

    assert df.empty
    assert list(df.columns) == PLAYER_PERFORMANCE_COLUMNS


def test_column_dtypes() -> None:
    df = build_player_performance_metrics(_df(_toy_rows()))

    assert df["season"].dtype == "int64"
    assert df["games_played"].dtype == "int64"
    assert df["sleeper_player_id"].dtype == object
    assert df["player_name"].dtype == object
    assert df["position"].dtype == object
    assert df["nfl_team"].dtype == object
    for column in (
        "total_points",
        "points_per_game",
        "median_points",
        "stdev_points",
        "cv",
        "scoring_floor",
        "scoring_ceiling",
        "boom_games",
        "boom_pct",
        "bust_games",
        "bust_pct",
    ):
        assert df[column].dtype == "float64", column

"""Tests for weekly lineup efficiency and season roster efficiency (FFA-067).

All tests operate on hand-built ``player_week_df``-shaped inputs plus an
explicit ``roster_positions`` slot list -- no HTTP calls, no opaque fixture
values -- so every optimal lineup, points-left-on-bench value, efficiency
percentage, and start/sit count can be verified by hand arithmetic from the
scores written in each test, per AGENTS.md's analytics-ticket requirement
for a hand-checkable toy example.

The optimization is exact and deterministic: the hand-computed "optimal
lineup" in each test is the best *legal* lineup under the test's
``roster_positions``, and the tests deliberately include cases (a
high-scoring bench quarterback, a FLEX tie) where a naive top-N-by-points
or non-deterministic tie-break would give a different answer.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.players import (
    LINEUP_EFFICIENCY_COLUMNS,
    PLAYER_WEEK_COLUMNS,
    ROSTER_EFFICIENCY_COLUMNS,
    build_lineup_efficiency_metrics,
    build_roster_efficiency_metrics,
)

#: A minimal set of provider-style raw stat columns, matching the sibling
#: player-analytics test files. Their values are irrelevant here -- this
#: module reads only identity/lineup columns and ``fantasy_points``.
STAT_COLUMNS = ["receptions", "receiving_yards"]

PLAYER_WEEK_TEST_COLUMNS = PLAYER_WEEK_COLUMNS + STAT_COLUMNS + ["fantasy_points"]


def _row(
    season: int,
    week: int,
    sleeper_player_id: str,
    fantasy_points: float | None,
    position: str | None,
    started: bool,
    roster_id: int = 1,
    fantasy_team: str = "Alpha",
    player_name: str | None = "Player",
    nfl_team: str | None = "SF",
) -> dict:
    """One ``player_week_df``-shaped row.

    ``fantasy_points=None`` deliberately mimics a hand-built frame with a
    missing value (FFA-064 itself never emits one) to exercise the
    documented "``NaN`` treated as ``0.0``" rule.
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
        "receptions": 4.0,
        "receiving_yards": 50.0,
        "fantasy_points": fantasy_points,
    }


def _df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=PLAYER_WEEK_TEST_COLUMNS)
    frame = pd.DataFrame(rows, columns=PLAYER_WEEK_TEST_COLUMNS)
    for column in (
        "player_name",
        "position",
        "nfl_team",
        "sleeper_player_id",
        "fantasy_team",
    ):
        frame[column] = pd.Series(frame[column].tolist(), dtype=object)
    return frame


def _weekly_row(
    df: pd.DataFrame, season: int = 2025, week: int = 1, roster_id: int = 1
) -> pd.Series:
    match = df.loc[
        (df["season"] == season) & (df["week"] == week) & (df["roster_id"] == roster_id)
    ]
    assert len(match) == 1
    return match.iloc[0]


def _season_row(df: pd.DataFrame, season: int = 2025, roster_id: int = 1) -> pd.Series:
    match = df.loc[(df["season"] == season) & (df["roster_id"] == roster_id)]
    assert len(match) == 1
    return match.iloc[0]


# --------------------------------------------------------------------------
# Hand-checkable toy example
# --------------------------------------------------------------------------

#: Two-QB league: two QB slots, two RB, one WR, one FLEX, one bench spot.
#: The FLEX accepts RB/WR/TE, so the third-best RB competes with the second
#: and third WRs and the tight end for the last slot.
TOY_ROSTER_POSITIONS = ["QB", "QB", "RB", "RB", "WR", "FLEX", "BN"]


def _toy_rows(week: int = 1) -> list[dict]:
    """Team Alpha, week 1, season 2025, in the two-QB league above.

    Rostered players (started marked *):
        QB1* 30, QB2 25, QB3* 10
        RB1* 20, RB2* 18, RB3 15
        WR1* 12, WR2 11, WR3 9
        TE1* 8   (started in the FLEX slot)

    Actual lineup (six started): 30 + 10 + 20 + 18 + 12 + 8 = 98.
    Optimal lineup: QB1 + QB2 (55, the second QB outscoring the started
    QB3), RB1 + RB2 (38), WR1 (12), FLEX = RB3 (15 -- outpoints WR2's 11,
    WR3's 9 and TE1's 8, so the third running back takes the FLEX).
    Optimal total: 55 + 38 + 12 + 15 = 120.
    points_left_on_bench: 120 - 98 = 22.
    efficiency: 98 / 120 = 49/60 = 0.81666...
    suboptimal_starts: QB3 and TE1 were started but are not in the optimal
    lineup -> 2. suboptimal_sits: QB2 and RB3 were benched but are in it
    -> 2. bench_points: 25 + 15 + 11 + 9 = 60 (includes QB2, whose points
    could not all be started).
    """
    return [
        _row(2025, week, "QB1", 30.0, "QB", started=True),
        _row(2025, week, "QB2", 25.0, "QB", started=False),
        _row(2025, week, "QB3", 10.0, "QB", started=True),
        _row(2025, week, "RB1", 20.0, "RB", started=True),
        _row(2025, week, "RB2", 18.0, "RB", started=True),
        _row(2025, week, "RB3", 15.0, "RB", started=False),
        _row(2025, week, "WR1", 12.0, "WR", started=True),
        _row(2025, week, "WR2", 11.0, "WR", started=False),
        _row(2025, week, "WR3", 9.0, "WR", started=False),
        _row(2025, week, "TE1", 8.0, "TE", started=True),
    ]


def test_toy_example_hand_computed() -> None:
    df = build_lineup_efficiency_metrics(_df(_toy_rows()), TOY_ROSTER_POSITIONS)

    assert list(df.columns) == LINEUP_EFFICIENCY_COLUMNS
    assert len(df) == 1

    row = _weekly_row(df)
    assert row["actual_points"] == pytest.approx(98.0)
    assert row["optimal_points"] == pytest.approx(120.0)
    assert row["bench_points"] == pytest.approx(60.0)
    assert row["points_left_on_bench"] == pytest.approx(22.0)
    assert row["efficiency_pct"] == pytest.approx(98.0 / 120.0)
    assert row["is_suboptimal"]
    assert row["suboptimal_starts"] == 2
    assert row["suboptimal_sits"] == 2


# --------------------------------------------------------------------------
# The optimizer respects roster-position rules
# --------------------------------------------------------------------------

#: Standard one-QB league: QB, 2 RB, 2 WR, TE, FLEX, K, DEF, 2 bench spots.
STANDARD_ROSTER_POSITIONS = [
    "QB",
    "RB",
    "RB",
    "WR",
    "WR",
    "TE",
    "FLEX",
    "K",
    "DEF",
    "BN",
    "BN",
]


def test_high_scoring_bench_qb_cannot_displace_starting_rb() -> None:
    """The ticket's headline legality case.

    Team Beta, week 1, standard league (no SuperFlex):
        QB1* 50, QB2 45   <- the bench QB (45) is the roster's second-
        RB1* 5,  RB2* 5      highest scorer and higher than any WR/TE
        WR1* 10, WR2* 10, WR3 20
        TE1* 8              <- the manager left the FLEX slot empty

    Actual: 50 + 5 + 5 + 10 + 10 + 8 = 88.
    A naive "sort every rostered player by points, take the top 7" lineup
    would be 50 + 45 + 20 + 10 + 10 + 8 + 5 = 148 -- illegal, because it
    starts only one RB and would let the bench QB displace a starting RB.
    The legal optimum must keep both RBs (the only RBs on the roster),
    keep QB1 (50 > 45), and fill the empty FLEX with WR3:
        50 + 5 + 5 + 10 + 10 + 8 + 20 = 108.
    """
    rows = [
        _row(2025, 1, "QB1", 50.0, "QB", started=True, fantasy_team="Beta"),
        _row(2025, 1, "QB2", 45.0, "QB", started=False, fantasy_team="Beta"),
        _row(2025, 1, "RB1", 5.0, "RB", started=True, fantasy_team="Beta"),
        _row(2025, 1, "RB2", 5.0, "RB", started=True, fantasy_team="Beta"),
        _row(2025, 1, "WR1", 10.0, "WR", started=True, fantasy_team="Beta"),
        _row(2025, 1, "WR2", 10.0, "WR", started=True, fantasy_team="Beta"),
        _row(2025, 1, "WR3", 20.0, "WR", started=False, fantasy_team="Beta"),
        _row(2025, 1, "TE1", 8.0, "TE", started=True, fantasy_team="Beta"),
    ]
    df = build_lineup_efficiency_metrics(_df(rows), STANDARD_ROSTER_POSITIONS)

    row = _weekly_row(df)
    assert row["optimal_points"] == pytest.approx(108.0)
    assert row["actual_points"] == pytest.approx(88.0)
    assert row["points_left_on_bench"] == pytest.approx(20.0)
    assert row["is_suboptimal"]
    # The bench QB's 45 points are unusable (no SuperFlex), so they count
    # toward the raw bench total but never toward points_left_on_bench.
    assert row["bench_points"] == pytest.approx(65.0)
    # All six started players are in the optimal lineup; only WR3 was a
    # wrong sit -- the bench QB was never a wrong start.
    assert row["suboptimal_starts"] == 0
    assert row["suboptimal_sits"] == 1


def test_super_flex_slot_does_allow_a_bench_qb() -> None:
    """Contrast with the previous test: with a SUPER_FLEX slot the same
    bench quarterback is legally startable, and the optimal lineup uses him.
    """
    rows = [
        _row(2025, 1, "QB1", 30.0, "QB", started=True, fantasy_team="Gamma"),
        _row(2025, 1, "QB2", 45.0, "QB", started=False, fantasy_team="Gamma"),
        _row(2025, 1, "RB1", 10.0, "RB", started=False, fantasy_team="Gamma"),
    ]
    df = build_lineup_efficiency_metrics(_df(rows), ["QB", "SUPER_FLEX", "BN"])

    row = _weekly_row(df)
    # QB slot takes QB2 (45), SUPER_FLEX takes QB1 (30): 75 total.
    assert row["optimal_points"] == pytest.approx(75.0)
    assert row["actual_points"] == pytest.approx(30.0)
    assert row["points_left_on_bench"] == pytest.approx(45.0)
    assert row["suboptimal_starts"] == 0
    assert row["suboptimal_sits"] == 1


# --------------------------------------------------------------------------
# Ties: deterministic, and ties are never mistakes
# --------------------------------------------------------------------------


def test_bench_player_tying_a_started_player_is_not_suboptimal() -> None:
    """A benched RB who exactly ties the started RB cannot displace him; a
    tie is not a mistake, so nothing is counted suboptimal.
    """
    rows = [
        _row(2025, 1, "RB1", 10.0, "RB", started=True),
        _row(2025, 1, "RB2", 10.0, "RB", started=False),
    ]
    df = build_lineup_efficiency_metrics(_df(rows), ["RB", "BN"])

    row = _weekly_row(df)
    assert row["actual_points"] == pytest.approx(10.0)
    assert row["optimal_points"] == pytest.approx(10.0)
    assert row["points_left_on_bench"] == pytest.approx(0.0)
    assert row["efficiency_pct"] == pytest.approx(1.0)
    assert not row["is_suboptimal"]
    assert row["suboptimal_starts"] == 0
    assert row["suboptimal_sits"] == 0


def test_tied_flex_candidates_are_resolved_deterministically() -> None:
    """Two benched players tie exactly for the FLEX slot (RB3 15 vs WR2 15)
    while the WR slot is locked by the started WR1 (25). Either choice
    scores the same (78) and sits one player, so the chosen lineup must be
    deterministic -- and invariant to the input row order -- with identical
    metrics under either choice: optimal 78, actual 63, left 15,
    0 wrong starts (all three started players are in either optimal
    lineup), 1 wrong sit.
    """
    rows = [
        _row(2025, 1, "RB1", 20.0, "RB", started=True),
        _row(2025, 1, "RB2", 18.0, "RB", started=True),
        _row(2025, 1, "RB3", 15.0, "RB", started=False),
        _row(2025, 1, "WR1", 25.0, "WR", started=True),
        _row(2025, 1, "WR2", 15.0, "WR", started=False),
    ]
    roster_positions = ["RB", "RB", "WR", "FLEX", "BN"]

    df = build_lineup_efficiency_metrics(_df(rows), roster_positions)
    row = _weekly_row(df)
    assert row["optimal_points"] == pytest.approx(78.0)
    assert row["actual_points"] == pytest.approx(63.0)
    assert row["points_left_on_bench"] == pytest.approx(15.0)
    assert row["suboptimal_starts"] == 0
    assert row["suboptimal_sits"] == 1

    # Same metrics regardless of the order rows arrive in.
    df_reversed = build_lineup_efficiency_metrics(
        _df(list(reversed(rows))), roster_positions
    )
    row_reversed = _weekly_row(df_reversed)
    assert row_reversed["optimal_points"] == pytest.approx(78.0)
    assert row_reversed["suboptimal_starts"] == 0
    assert row_reversed["suboptimal_sits"] == 1


# --------------------------------------------------------------------------
# Missing values
# --------------------------------------------------------------------------


def test_nan_fantasy_points_are_treated_as_zero() -> None:
    """A started QB with missing fantasy_points contributes 0.0 to actual
    (not NaN), and a benched QB's real 20 points win the QB slot.
    """
    rows = [
        _row(2025, 1, "QB1", None, "QB", started=True),
        _row(2025, 1, "QB2", 20.0, "QB", started=False),
    ]
    df = build_lineup_efficiency_metrics(_df(rows), ["QB", "BN"])

    row = _weekly_row(df)
    assert row["actual_points"] == pytest.approx(0.0)
    assert row["optimal_points"] == pytest.approx(20.0)
    assert row["efficiency_pct"] == pytest.approx(0.0)
    assert row["is_suboptimal"]
    assert row["suboptimal_starts"] == 1
    assert row["suboptimal_sits"] == 1


def test_player_with_missing_position_is_ineligible() -> None:
    """A 100-point player with an unresolvable position (None) counts
    toward bench_points but can never be started in the optimal lineup.
    """
    rows = [
        _row(2025, 1, "RB1", 5.0, "RB", started=True),
        _row(2025, 1, "RB2", 3.0, "RB", started=False),
        _row(2025, 1, "X", 100.0, None, started=False),
    ]
    df = build_lineup_efficiency_metrics(_df(rows), ["RB", "BN"])

    row = _weekly_row(df)
    assert row["actual_points"] == pytest.approx(5.0)
    assert row["optimal_points"] == pytest.approx(5.0)
    assert row["bench_points"] == pytest.approx(103.0)
    assert row["points_left_on_bench"] == pytest.approx(0.0)
    assert row["suboptimal_starts"] == 0
    assert row["suboptimal_sits"] == 0


def test_row_with_missing_roster_id_is_skipped() -> None:
    rows = [
        _row(2025, 1, "RB1", 10.0, "RB", started=True),
        _row(2025, 1, "RB2", 20.0, "RB", started=True, roster_id=None),
    ]
    df = build_lineup_efficiency_metrics(_df(rows), ["RB", "BN"])

    assert len(df) == 1
    row = _weekly_row(df)
    assert row["actual_points"] == pytest.approx(10.0)


def test_duplicate_player_ids_are_deduplicated() -> None:
    """The same player appearing twice in one roster-week (should not occur
    in real data) is counted once in actual_points and started once at
    most.
    """
    rows = [
        _row(2025, 1, "RB1", 10.0, "RB", started=True),
        _row(2025, 1, "RB1", 10.0, "RB", started=True),
        _row(2025, 1, "RB2", 7.0, "RB", started=False),
    ]
    df = build_lineup_efficiency_metrics(_df(rows), ["RB", "BN"])

    row = _weekly_row(df)
    assert row["actual_points"] == pytest.approx(10.0)
    assert row["optimal_points"] == pytest.approx(10.0)
    assert row["suboptimal_starts"] == 0


# --------------------------------------------------------------------------
# Byes, empty slots, and negative scorers
# --------------------------------------------------------------------------


def test_slot_with_no_legal_player_is_left_empty() -> None:
    """Team has no tight end rostered at all; the optimal lineup leaves the
    TE slot empty instead of inventing an illegal fill, and the week is
    not suboptimal (there was nothing better to do).
    """
    rows = [
        _row(2025, 1, "QB1", 30.0, "QB", started=True),
        _row(2025, 1, "RB1", 15.0, "RB", started=True),
        _row(2025, 1, "WR1", 10.0, "WR", started=True),
    ]
    df = build_lineup_efficiency_metrics(_df(rows), ["QB", "RB", "TE", "FLEX", "BN"])

    row = _weekly_row(df)
    assert row["actual_points"] == pytest.approx(55.0)
    assert row["optimal_points"] == pytest.approx(55.0)
    assert not row["is_suboptimal"]
    assert row["suboptimal_starts"] == 0
    assert row["suboptimal_sits"] == 0


def test_negative_scoring_defense_is_better_left_empty() -> None:
    """A started defense scoring -5 makes the empty lineup (0.0) strictly
    better; efficiency is NaN because the optimal denominator is <= 0.
    """
    rows = [_row(2025, 1, "DEF1", -5.0, "DEF", started=True)]
    df = build_lineup_efficiency_metrics(_df(rows), ["DEF", "BN"])

    row = _weekly_row(df)
    assert row["actual_points"] == pytest.approx(-5.0)
    assert row["optimal_points"] == pytest.approx(0.0)
    assert row["points_left_on_bench"] == pytest.approx(5.0)
    assert pd.isna(row["efficiency_pct"])
    assert row["is_suboptimal"]
    assert row["suboptimal_starts"] == 1
    assert row["suboptimal_sits"] == 0


def test_week_with_no_started_players_still_gets_a_row() -> None:
    rows = [
        _row(2025, 1, "QB1", 25.0, "QB", started=False),
        _row(2025, 1, "RB1", 10.0, "RB", started=False),
    ]
    df = build_lineup_efficiency_metrics(_df(rows), ["QB", "RB", "BN"])

    row = _weekly_row(df)
    assert row["actual_points"] == pytest.approx(0.0)
    assert row["optimal_points"] == pytest.approx(35.0)
    assert row["is_suboptimal"]
    assert row["suboptimal_starts"] == 0
    assert row["suboptimal_sits"] == 2


def test_no_starting_slots_means_zero_optimal_and_nan_efficiency() -> None:
    """Degenerate league shape: with no starting slots the only legal
    lineup is the empty one (0 points), so a manager who scored 30 cannot
    have done better -- ``is_suboptimal`` is False and ``efficiency_pct``
    is NaN (division by a zero denominator).
    """
    rows = [_row(2025, 1, "QB1", 30.0, "QB", started=True)]
    df = build_lineup_efficiency_metrics(_df(rows), ["BN", "BN"])

    row = _weekly_row(df)
    assert row["actual_points"] == pytest.approx(30.0)
    assert row["optimal_points"] == pytest.approx(0.0)
    assert pd.isna(row["efficiency_pct"])
    assert not row["is_suboptimal"]


# --------------------------------------------------------------------------
# Regular season vs. playoffs: phase-agnostic, caller filters first
# --------------------------------------------------------------------------


def test_all_input_weeks_are_processed_identically() -> None:
    """The player-week fact table has no ``is_playoff`` column, so this
    module cannot and does not distinguish phases: a week 9 (a playoff week
    under any boundary <= 9) enters the same optimization and aggregation
    as a regular-season week. Callers filter ``player_week_df`` on ``week``
    against their league's playoff-start boundary before calling for a
    phase-specific view.
    """
    week1_rows = _toy_rows(week=1)
    week9_rows = _toy_rows(week=9)
    df = build_lineup_efficiency_metrics(
        _df(week1_rows + week9_rows), TOY_ROSTER_POSITIONS
    )

    assert len(df) == 2
    row_week1 = _weekly_row(df, week=1)
    row_week9 = _weekly_row(df, week=9)
    for column in LINEUP_EFFICIENCY_COLUMNS:
        if column in ("week", "fantasy_team"):
            continue
        if column == "is_suboptimal":
            assert row_week9[column] == row_week1[column]
        else:
            assert row_week9[column] == row_week1[column], column

    # The season summary aggregates playoff weeks too: filter the input
    # first for a regular-season-only view.
    season_all = build_roster_efficiency_metrics(
        _df(week1_rows + week9_rows), TOY_ROSTER_POSITIONS
    )
    season_regular = build_roster_efficiency_metrics(
        _df(week1_rows), TOY_ROSTER_POSITIONS
    )
    assert _season_row(season_all)["weeks_played"] == 2
    assert _season_row(season_regular)["weeks_played"] == 1


# --------------------------------------------------------------------------
# Season roster-efficiency summary
# --------------------------------------------------------------------------


def test_season_summary_aggregates_weekly_metrics() -> None:
    """Two weeks for team Alpha in the two-QB league.

    Week 1: the toy week -- actual 98, optimal 120, bench 60, left 22,
    2 wrong starts, 2 wrong sits, suboptimal.
    Week 2: the manager starts the optimal lineup -- QB1* 30, QB2* 25,
    RB1* 20, RB2* 18, RB3* 15, WR1* 12 (the toy's optimal set):
    actual = 30 + 25 + 20 + 18 + 15 + 12 = 120 = optimal, left 0,
    bench = 10 + 11 + 9 + 8 = 38, 0 starts, 0 sits, not suboptimal.

    Season: weeks 2, total_actual 98 + 120 = 218, total_optimal 240,
    total_bench 60 + 38 = 98, total_left 22, efficiency 218/240 =
    109/120 = 0.90833..., suboptimal_weeks 1 (pct 0.5),
    total starts 2, total sits 2.
    """
    week2_rows = [
        _row(2025, 2, "QB1", 30.0, "QB", started=True),
        _row(2025, 2, "QB2", 25.0, "QB", started=True),
        _row(2025, 2, "QB3", 10.0, "QB", started=False),
        _row(2025, 2, "RB1", 20.0, "RB", started=True),
        _row(2025, 2, "RB2", 18.0, "RB", started=True),
        _row(2025, 2, "RB3", 15.0, "RB", started=True),
        _row(2025, 2, "WR1", 12.0, "WR", started=True),
        _row(2025, 2, "WR2", 11.0, "WR", started=False),
        _row(2025, 2, "WR3", 9.0, "WR", started=False),
        _row(2025, 2, "TE1", 8.0, "TE", started=False),
    ]
    df = build_roster_efficiency_metrics(
        _df(_toy_rows(week=1) + week2_rows), TOY_ROSTER_POSITIONS
    )

    assert list(df.columns) == ROSTER_EFFICIENCY_COLUMNS
    assert len(df) == 1

    row = _season_row(df)
    assert row["weeks_played"] == 2
    assert row["total_actual_points"] == pytest.approx(218.0)
    assert row["total_optimal_points"] == pytest.approx(240.0)
    assert row["total_bench_points"] == pytest.approx(98.0)
    assert row["total_points_left_on_bench"] == pytest.approx(22.0)
    assert row["efficiency_pct"] == pytest.approx(218.0 / 240.0)
    assert row["suboptimal_weeks"] == 1
    assert row["suboptimal_week_pct"] == pytest.approx(0.5)
    assert row["total_suboptimal_starts"] == 2
    assert row["total_suboptimal_sits"] == 2


def test_season_summary_has_multiple_rosters_and_seasons() -> None:
    rows = [
        _row(2025, 1, "RB1", 10.0, "RB", started=True, roster_id=1),
        _row(2025, 1, "RB2", 8.0, "RB", started=True, roster_id=2),
        _row(2024, 1, "RB1", 40.0, "RB", started=True, roster_id=1),
    ]
    df = build_roster_efficiency_metrics(_df(rows), ["RB", "BN"])

    assert len(df) == 3
    row_2025_1 = _season_row(df, season=2025, roster_id=1)
    row_2025_2 = _season_row(df, season=2025, roster_id=2)
    row_2024_1 = _season_row(df, season=2024, roster_id=1)
    assert row_2025_1["total_actual_points"] == pytest.approx(10.0)
    assert row_2025_2["total_actual_points"] == pytest.approx(8.0)
    assert row_2024_1["total_actual_points"] == pytest.approx(40.0)
    # Seasons are never pooled.
    assert row_2025_1["weeks_played"] == 1
    assert row_2024_1["weeks_played"] == 1


# --------------------------------------------------------------------------
# Empty input / column shape / dtypes
# --------------------------------------------------------------------------


def test_empty_input_returns_empty_frames_with_columns() -> None:
    weekly = build_lineup_efficiency_metrics(_df([]), STANDARD_ROSTER_POSITIONS)
    season = build_roster_efficiency_metrics(_df([]), STANDARD_ROSTER_POSITIONS)

    assert weekly.empty
    assert list(weekly.columns) == LINEUP_EFFICIENCY_COLUMNS
    assert season.empty
    assert list(season.columns) == ROSTER_EFFICIENCY_COLUMNS


def test_empty_roster_positions_is_treated_like_an_all_bench_league() -> None:
    rows = [_row(2025, 1, "QB1", 30.0, "QB", started=True)]
    df = build_lineup_efficiency_metrics(_df(rows), [])

    row = _weekly_row(df)
    assert row["optimal_points"] == pytest.approx(0.0)
    assert pd.isna(row["efficiency_pct"])


def test_column_dtypes() -> None:
    weekly = build_lineup_efficiency_metrics(
        _df(_toy_rows(week=1) + _toy_rows(week=2)), TOY_ROSTER_POSITIONS
    )
    season = build_roster_efficiency_metrics(
        _df(_toy_rows(week=1) + _toy_rows(week=2)), TOY_ROSTER_POSITIONS
    )

    assert weekly["season"].dtype == "int64"
    assert weekly["week"].dtype == "int64"
    assert weekly["roster_id"].dtype == "int64"
    assert weekly["is_suboptimal"].dtype == bool
    assert weekly["suboptimal_starts"].dtype == "int64"
    assert weekly["suboptimal_sits"].dtype == "int64"
    assert weekly["fantasy_team"].dtype == object
    for column in (
        "actual_points",
        "optimal_points",
        "bench_points",
        "points_left_on_bench",
        "efficiency_pct",
    ):
        assert weekly[column].dtype == "float64", column

    assert season["season"].dtype == "int64"
    assert season["roster_id"].dtype == "int64"
    assert season["weeks_played"].dtype == "int64"
    assert season["suboptimal_weeks"].dtype == "int64"
    assert season["total_suboptimal_starts"].dtype == "int64"
    assert season["total_suboptimal_sits"].dtype == "int64"
    assert season["fantasy_team"].dtype == object
    for column in (
        "total_actual_points",
        "total_optimal_points",
        "total_bench_points",
        "total_points_left_on_bench",
        "efficiency_pct",
        "suboptimal_week_pct",
    ):
        assert season[column].dtype == "float64", column

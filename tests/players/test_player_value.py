"""Tests for league-relative player value and positional scarcity (FFA-068).

All tests operate on hand-built ``performance_df``-shaped inputs -- no HTTP
calls, no opaque fixture values -- so every position mean, replacement
level, VORP, rank, gap and scarcity ratio can be verified by hand
arithmetic from the values written in each test, per AGENTS.md's
analytics-ticket requirement for a hand-checkable toy example.

The replacement methodology under test: per ``(season, position)``, the
league's starter cutoff is ``num_teams`` times the number of starting slots
eligible for that position (counting flex slots at every eligible
position, via ``START_SLOT_ELIGIBILITY``), and ``replacement_ppg`` is the
``points_per_game`` of the player ranked at that cutoff by descending
``points_per_game`` -- clamped to the worst rostered player when the
league does not roster enough players at the position, or has no starting
slots there at all.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.players import (
    PLAYER_PERFORMANCE_COLUMNS,
    PLAYER_VALUE_COLUMNS,
    POSITION_SCARCITY_COLUMNS,
    build_player_value_metrics,
    build_position_scarcity_metrics,
)

#: The columns FFA-065 emits; only the value-relevant subset is populated
#: by the helpers below (the dispersion/boom columns are filled with NaN,
#: which this module never reads).
PERFORMANCE_TEST_COLUMNS = PLAYER_PERFORMANCE_COLUMNS


def _row(
    season: int,
    sleeper_player_id: str,
    position: str,
    points_per_game: float,
    total_points: float,
    games_played: int,
    player_name: str | None = "Player",
    nfl_team: str | None = "SF",
) -> dict:
    """One ``performance_df``-shaped row with the value columns populated."""
    return {
        "season": season,
        "sleeper_player_id": sleeper_player_id,
        "player_name": player_name,
        "position": position,
        "nfl_team": nfl_team,
        "games_played": games_played,
        "total_points": total_points,
        "points_per_game": points_per_game,
        "median_points": float("nan"),
        "stdev_points": float("nan"),
        "cv": float("nan"),
        "scoring_floor": float("nan"),
        "scoring_ceiling": float("nan"),
        "boom_games": float("nan"),
        "boom_pct": float("nan"),
        "bust_games": float("nan"),
        "bust_pct": float("nan"),
    }


def _df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=PERFORMANCE_TEST_COLUMNS)
    frame = pd.DataFrame(rows, columns=PERFORMANCE_TEST_COLUMNS)
    label_columns = (
        "player_name",
        "position",
        "nfl_team",
        "sleeper_player_id",
    )
    for column in label_columns:
        frame[column] = pd.Series(frame[column].tolist(), dtype=object)
    return frame


def _get_row(df: pd.DataFrame, sleeper_player_id: str, season: int = 2025) -> pd.Series:
    match = df.loc[
        (df["sleeper_player_id"] == sleeper_player_id) & (df["season"] == season)
    ]
    assert len(match) == 1
    return match.iloc[0]


def _get_position_row(df: pd.DataFrame, position: str, season: int = 2025) -> pd.Series:
    match = df.loc[(df["position"] == position) & (df["season"] == season)]
    assert len(match) == 1
    return match.iloc[0]


# --------------------------------------------------------------------------
# Hand-checkable toy example
# --------------------------------------------------------------------------


def _toy_rows() -> list[dict]:
    """Two teams, one QB/RB/WR/TE/FLEX slot each, season 2025.

    League: num_teams = 2, roster_positions = [QB, RB, WR, TE, FLEX, BN, BN].
    Starting slots per team (FLEX counts at every eligible position):
        QB: 1 -> cutoff 2;  RB: 1+1(FLEX) = 2 -> cutoff 4
        WR: 1+1(FLEX) = 2 -> cutoff 4;  TE: 1+1(FLEX) = 2 -> cutoff 4

    Players (ppg, total, games):
        QB1 30/480/16, QB2 20/320/16, QB3 10/150/15
        RB1 20/300/15, RB2 15/240/16, RB3 5/80/16
        WR1 24/384/16, WR2 18/288/16, WR3 18/270/15, WR4 14/224/16, WR5 14/168/12
        TE1 12/192/16, TE2 8/128/16,  TE3 8/120/15

    Position summaries (season 2025):
        QB: field 3, cutoff 2, sorted 30,20,10 -> rank 2 -> repl 20.0
            mean_ppg = 60/3 = 20.0, mean_total = 950/3 = 316.6667
        RB: field 3, cutoff 4 -> clamped rank 3 -> repl 5.0
            mean_ppg = 40/3 = 13.3333, mean_total = 620/3 = 206.6667
        WR: field 5, cutoff 4, sorted 24,18,18,14,14 -> rank 4 -> repl 14.0
            (WR4 and WR5 tie at the cutoff: value-invariant)
            mean_ppg = 88/5 = 17.6, mean_total = 1334/5 = 266.8
        TE: field 3, cutoff 4 -> clamped rank 3, sorted 12,8,8 -> repl 8.0
            (TE2/TE3 tie at the clamped rank: value-invariant)
            mean_ppg = 28/3 = 9.3333, mean_total = 440/3 = 146.6667

    VORP (total - repl*games):
        QB1 480-320=160, QB2 320-320=0,   QB3 150-300=-150
        RB1 300-75=225,  RB2 240-80=160,  RB3 80-80=0
        WR1 384-224=160, WR2 288-224=64,  WR3 270-210=60, WR4 224-224=0, WR5 168-168=0
        TE1 192-128=64,  TE2 128-128=0,   TE3 120-120=0

    value_rank (standard competition, descending VORP, within season):
        225: RB1 -> 1
        160: QB1, RB2, WR1 -> 2
        64:  WR2, TE1 -> 5
        60:  WR3 -> 7
        0:   QB2, RB3, WR4, WR5, TE2, TE3 -> 8
        -150: QB3 -> 14
    """
    return [
        _row(2025, "QB1", "QB", 30.0, 480.0, 16),
        _row(2025, "QB2", "QB", 20.0, 320.0, 16),
        _row(2025, "QB3", "QB", 10.0, 150.0, 15),
        _row(2025, "RB1", "RB", 20.0, 300.0, 15),
        _row(2025, "RB2", "RB", 15.0, 240.0, 16),
        _row(2025, "RB3", "RB", 5.0, 80.0, 16),
        _row(2025, "WR1", "WR", 24.0, 384.0, 16),
        _row(2025, "WR2", "WR", 18.0, 288.0, 16),
        _row(2025, "WR3", "WR", 18.0, 270.0, 15),
        _row(2025, "WR4", "WR", 14.0, 224.0, 16),
        _row(2025, "WR5", "WR", 14.0, 168.0, 12),
        _row(2025, "TE1", "TE", 12.0, 192.0, 16),
        _row(2025, "TE2", "TE", 8.0, 128.0, 16),
        _row(2025, "TE3", "TE", 8.0, 120.0, 15),
    ]


ROSTER_POSITIONS = ["QB", "RB", "WR", "TE", "FLEX", "BN", "BN"]
NUM_TEAMS = 2


def test_toy_example_hand_computed_player_frame() -> None:
    df = build_player_value_metrics(_df(_toy_rows()), ROSTER_POSITIONS, NUM_TEAMS)

    assert list(df.columns) == PLAYER_VALUE_COLUMNS
    assert len(df) == 14

    # Position-level context is identical for every player at a position.
    for player_id in ("QB1", "QB2", "QB3"):
        row = _get_row(df, player_id)
        assert row["position_players"] == 3
        assert row["position_mean_ppg"] == pytest.approx(20.0)
        assert row["position_mean_total"] == pytest.approx(950 / 3)
        assert row["replacement_ppg"] == pytest.approx(20.0)

    qb1 = _get_row(df, "QB1")
    assert qb1["points_per_game"] == pytest.approx(30.0)
    assert qb1["total_points"] == pytest.approx(480.0)
    assert qb1["games_played"] == 16
    assert qb1["ppg_above_position_average"] == pytest.approx(10.0)
    assert qb1["total_above_position_average"] == pytest.approx(480 - 950 / 3)
    assert qb1["ppg_above_replacement"] == pytest.approx(10.0)
    assert qb1["points_above_replacement"] == pytest.approx(160.0)
    assert qb1["value_rank"] == 2

    qb3 = _get_row(df, "QB3")
    assert qb3["ppg_above_position_average"] == pytest.approx(-10.0)
    assert qb3["total_above_position_average"] == pytest.approx(150 - 950 / 3)
    assert qb3["ppg_above_replacement"] == pytest.approx(-10.0)
    assert qb3["points_above_replacement"] == pytest.approx(-150.0)
    assert qb3["value_rank"] == 14

    rb1 = _get_row(df, "RB1")
    assert rb1["replacement_ppg"] == pytest.approx(5.0)
    assert rb1["position_mean_ppg"] == pytest.approx(40 / 3)
    assert rb1["position_mean_total"] == pytest.approx(620 / 3)
    assert rb1["ppg_above_replacement"] == pytest.approx(15.0)
    assert rb1["points_above_replacement"] == pytest.approx(225.0)
    assert rb1["value_rank"] == 1  # league-best VORP

    wr1 = _get_row(df, "WR1")
    assert wr1["replacement_ppg"] == pytest.approx(14.0)
    assert wr1["position_mean_ppg"] == pytest.approx(17.6)
    assert wr1["position_mean_total"] == pytest.approx(266.8)
    assert wr1["ppg_above_position_average"] == pytest.approx(6.4)
    assert wr1["total_above_position_average"] == pytest.approx(117.2)
    assert wr1["points_above_replacement"] == pytest.approx(160.0)
    assert wr1["value_rank"] == 2

    te1 = _get_row(df, "TE1")
    assert te1["replacement_ppg"] == pytest.approx(8.0)
    assert te1["position_mean_ppg"] == pytest.approx(28 / 3)
    assert te1["ppg_above_replacement"] == pytest.approx(4.0)
    assert te1["points_above_replacement"] == pytest.approx(64.0)
    assert te1["value_rank"] == 5

    # value_rank uses standard competition ("1224") ranking with ties.
    assert list(df["value_rank"]) == [
        1,  # RB1
        2,
        2,
        2,  # QB1, RB2, WR1
        5,
        5,  # TE1, WR2
        7,  # WR3
        8,
        8,
        8,
        8,
        8,
        8,  # QB2, RB3, TE2, TE3, WR4, WR5
        14,  # QB3
    ]
    # Leaderboard display order: ascending (season, value_rank, player_id).
    assert list(df["sleeper_player_id"]) == [
        "RB1",
        "QB1",
        "RB2",
        "WR1",
        "TE1",
        "WR2",
        "WR3",
        "QB2",
        "RB3",
        "TE2",
        "TE3",
        "WR4",
        "WR5",
        "QB3",
    ]


def test_toy_example_hand_computed_scarcity_frame() -> None:
    df = build_position_scarcity_metrics(_df(_toy_rows()), ROSTER_POSITIONS, NUM_TEAMS)

    assert list(df.columns) == POSITION_SCARCITY_COLUMNS
    assert len(df) == 4

    qb = _get_position_row(df, "QB")
    assert qb["players"] == 3
    assert qb["position_starters"] == 2
    assert qb["replacement_rank"] == 2
    assert qb["best_ppg"] == pytest.approx(30.0)
    assert qb["replacement_ppg"] == pytest.approx(20.0)
    assert qb["ppg_gap_to_replacement"] == pytest.approx(10.0)
    assert qb["scarcity_ratio"] == pytest.approx(0.5)

    rb = _get_position_row(df, "RB")
    assert rb["players"] == 3
    assert rb["position_starters"] == 4  # RB slot + FLEX, per team, x2 teams
    assert rb["replacement_rank"] == 3  # clamped: field 3 < cutoff 4
    assert rb["best_ppg"] == pytest.approx(20.0)
    assert rb["replacement_ppg"] == pytest.approx(5.0)
    assert rb["ppg_gap_to_replacement"] == pytest.approx(15.0)
    assert rb["scarcity_ratio"] == pytest.approx(3.0)

    wr = _get_position_row(df, "WR")
    assert wr["players"] == 5
    assert wr["position_starters"] == 4
    assert wr["replacement_rank"] == 4
    assert wr["best_ppg"] == pytest.approx(24.0)
    assert wr["replacement_ppg"] == pytest.approx(14.0)
    assert wr["ppg_gap_to_replacement"] == pytest.approx(10.0)
    assert wr["scarcity_ratio"] == pytest.approx(10 / 14)

    te = _get_position_row(df, "TE")
    assert te["players"] == 3
    assert te["position_starters"] == 4
    assert te["replacement_rank"] == 3  # clamped, tie at the clamp
    assert te["best_ppg"] == pytest.approx(12.0)
    assert te["replacement_ppg"] == pytest.approx(8.0)
    assert te["ppg_gap_to_replacement"] == pytest.approx(4.0)
    assert te["scarcity_ratio"] == pytest.approx(0.5)


def test_ties_at_the_cutoff_are_value_invariant() -> None:
    """WR4 and WR5 tie at the WR cutoff (both 14 ppg, cutoff rank 4) and TE2
    and TE3 tie at the clamped TE rank (both 8 ppg, rank 3): whichever of
    the tied players the deterministic sort picks, the replacement value is
    the same, and both tied players sit exactly at replacement (VORP 0).
    """
    df = build_player_value_metrics(_df(_toy_rows()), ROSTER_POSITIONS, NUM_TEAMS)

    for player_id in ("WR4", "WR5"):
        row = _get_row(df, player_id)
        assert row["replacement_ppg"] == pytest.approx(14.0)
        assert row["ppg_above_replacement"] == pytest.approx(0.0)
        assert row["points_above_replacement"] == pytest.approx(0.0)
    for player_id in ("TE2", "TE3"):
        row = _get_row(df, player_id)
        assert row["replacement_ppg"] == pytest.approx(8.0)
        assert row["ppg_above_replacement"] == pytest.approx(0.0)
        assert row["points_above_replacement"] == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Starter-cutoff conventions: flex slots, bench slots, clamping
# --------------------------------------------------------------------------


def test_flex_slot_counts_at_every_eligible_position() -> None:
    """One team, one QB/RB/WR/TE slot: adding a FLEX raises the RB, WR and
    TE cutoffs (FLEX accepts all three) but not the QB cutoff (FLEX is not
    eligible for QB).
    """
    rows = [
        _row(2025, "QB1", "QB", 30.0, 480.0, 16),
        _row(2025, "RB1", "RB", 20.0, 300.0, 15),
        _row(2025, "WR1", "WR", 24.0, 384.0, 16),
        _row(2025, "TE1", "TE", 12.0, 192.0, 16),
    ]
    without_flex = build_position_scarcity_metrics(
        _df(rows), ["QB", "RB", "WR", "TE"], 1
    )
    with_flex = build_position_scarcity_metrics(
        _df(rows), ["QB", "RB", "WR", "TE", "FLEX"], 1
    )

    assert _get_position_row(without_flex, "RB")["position_starters"] == 1
    assert _get_position_row(without_flex, "WR")["position_starters"] == 1
    assert _get_position_row(with_flex, "RB")["position_starters"] == 2
    assert _get_position_row(with_flex, "WR")["position_starters"] == 2
    assert _get_position_row(with_flex, "TE")["position_starters"] == 2
    assert _get_position_row(with_flex, "QB")["position_starters"] == 1


def test_bench_and_unrecognized_slots_do_not_inflate_starter_counts() -> None:
    rows = [
        _row(2025, "QB1", "QB", 30.0, 480.0, 16),
        _row(2025, "QB2", "QB", 20.0, 320.0, 16),
    ]
    df = build_position_scarcity_metrics(
        _df(rows), ["QB", "BN", "BN", "IR", "MYSTERY_SLOT"], 2
    )

    qb = _get_position_row(df, "QB")
    assert qb["position_starters"] == 2
    assert qb["replacement_ppg"] == pytest.approx(20.0)


def test_cutoff_clamps_to_worst_rostered_player_when_field_is_small() -> None:
    """Two teams, two TE slots per team (cutoff 4), three rostered TEs: the
    league does not roster enough TEs to fill its own starting slots, so
    the baseline clamps to the worst rostered player (rank 3, 8.0 ppg) --
    the tightest observable upper bound on a free agent's production.
    """
    rows = [
        _row(2025, "TE1", "TE", 12.0, 192.0, 16),
        _row(2025, "TE2", "TE", 8.0, 128.0, 16),
        _row(2025, "TE3", "TE", 4.0, 60.0, 15),
    ]
    df = build_player_value_metrics(_df(rows), ["TE", "TE"], 2)
    scarcity = build_position_scarcity_metrics(_df(rows), ["TE", "TE"], 2)

    assert _get_position_row(scarcity, "TE")["position_starters"] == 4
    assert _get_position_row(scarcity, "TE")["replacement_rank"] == 3
    assert _get_position_row(scarcity, "TE")["replacement_ppg"] == pytest.approx(4.0)
    assert _get_row(df, "TE1")["points_above_replacement"] == pytest.approx(128.0)
    assert _get_row(df, "TE2")["points_above_replacement"] == pytest.approx(64.0)
    assert _get_row(df, "TE3")["points_above_replacement"] == pytest.approx(0.0)


def test_single_starter_position_uses_best_player_as_baseline() -> None:
    """One team, one TE slot (cutoff 1): the league's only starter at the
    position is the marginal starter, so the baseline is the best player
    and every backup scores below replacement.
    """
    rows = [
        _row(2025, "TE1", "TE", 12.0, 192.0, 16),
        _row(2025, "TE2", "TE", 8.0, 128.0, 16),
        _row(2025, "TE3", "TE", 4.0, 60.0, 15),
    ]
    df = build_player_value_metrics(_df(rows), ["TE"], 1)
    scarcity = build_position_scarcity_metrics(_df(rows), ["TE"], 1)

    assert _get_position_row(scarcity, "TE")["position_starters"] == 1
    assert _get_position_row(scarcity, "TE")["replacement_rank"] == 1
    assert _get_position_row(scarcity, "TE")["replacement_ppg"] == pytest.approx(12.0)
    assert _get_row(df, "TE1")["points_above_replacement"] == pytest.approx(0.0)
    assert _get_row(df, "TE2")["points_above_replacement"] == pytest.approx(-64.0)
    assert _get_row(df, "TE3")["points_above_replacement"] == pytest.approx(-120.0)


def test_num_teams_zero_uses_worst_rostered_player_as_replacement() -> None:
    """With no teams the cutoff is below 1, so the baseline is the worst
    rostered player at each position -- the documented conservative bound.
    """
    rows = [
        _row(2025, "QB1", "QB", 30.0, 480.0, 16),
        _row(2025, "QB2", "QB", 20.0, 320.0, 16),
        _row(2025, "RB1", "RB", 20.0, 300.0, 15),
    ]
    df = build_player_value_metrics(_df(rows), ["QB", "RB"], 0)

    assert _get_row(df, "QB1")["replacement_ppg"] == pytest.approx(20.0)
    assert _get_row(df, "QB2")["replacement_ppg"] == pytest.approx(20.0)
    assert _get_row(df, "RB1")["replacement_ppg"] == pytest.approx(20.0)
    # QB1 and RB1 are both above the worst player at their position.
    assert _get_row(df, "QB1")["points_above_replacement"] == pytest.approx(160.0)
    assert _get_row(df, "RB1")["points_above_replacement"] == pytest.approx(0.0)


def test_empty_roster_positions_means_no_starting_slots() -> None:
    rows = [
        _row(2025, "QB1", "QB", 30.0, 480.0, 16),
        _row(2025, "QB2", "QB", 20.0, 320.0, 16),
    ]
    df = build_position_scarcity_metrics(_df(rows), [], 2)

    qb = _get_position_row(df, "QB")
    assert qb["position_starters"] == 0
    assert qb["replacement_rank"] == 2  # worst rostered player
    assert qb["replacement_ppg"] == pytest.approx(20.0)


# --------------------------------------------------------------------------
# Negative scoring / scarcity ratio guard
# --------------------------------------------------------------------------


def test_scarcity_ratio_is_nan_when_replacement_ppg_is_non_positive() -> None:
    """A defense position whose best player scores negative: the gap and
    VORP are still well-defined, but the scarcity ratio has no percentage
    meaning against a non-positive baseline.
    """
    rows = [
        _row(2025, "DEF1", "DEF", -1.0, -16.0, 16),
        _row(2025, "DEF2", "DEF", -5.0, -80.0, 16),
    ]
    df = build_player_value_metrics(_df(rows), ["DEF"], 1)
    scarcity = build_position_scarcity_metrics(_df(rows), ["DEF"], 1)

    row = _get_position_row(scarcity, "DEF")
    assert row["replacement_ppg"] == pytest.approx(-1.0)
    assert row["ppg_gap_to_replacement"] == pytest.approx(0.0)
    assert pd.isna(row["scarcity_ratio"])

    assert _get_row(df, "DEF2")["ppg_above_replacement"] == pytest.approx(-4.0)
    assert _get_row(df, "DEF2")["points_above_replacement"] == pytest.approx(-64.0)


# --------------------------------------------------------------------------
# Missing values / ungroupable rows
# --------------------------------------------------------------------------


def test_row_with_missing_position_is_skipped() -> None:
    """A player whose position was never resolved cannot be assigned to a
    position group: he contributes to no field, mean, or replacement level,
    and gets no value row -- mirroring performance.py's handling.
    """
    rows = [
        _row(2025, "QB1", "QB", 30.0, 480.0, 16),
        _row(2025, "QB2", "QB", 20.0, 320.0, 16),
        _row(2025, "GHOST", None, 100.0, 1600.0, 16),
    ]
    df = build_player_value_metrics(_df(rows), ["QB"], 2)
    scarcity = build_position_scarcity_metrics(_df(rows), ["QB"], 2)

    assert list(df["sleeper_player_id"]) == ["QB1", "QB2"]
    assert list(scarcity["position"]) == ["QB"]
    qb = _get_position_row(scarcity, "QB")
    assert qb["players"] == 2  # GHOST never enters the field size


def test_row_with_missing_value_columns_is_skipped() -> None:
    """Not expected under FFA-065's contract, but a hand-built input with a
    NaN points_per_game must not corrupt the position mean or a VORP.
    """
    rows = [
        _row(2025, "QB1", "QB", 30.0, 480.0, 16),
        _row(2025, "QB2", "QB", 20.0, 320.0, 16),
        _row(2025, "BROKEN", "QB", float("nan"), 160.0, 16),
    ]
    df = build_player_value_metrics(_df(rows), ["QB"], 2)

    assert list(df["sleeper_player_id"]) == ["QB1", "QB2"]
    assert _get_row(df, "QB1")["position_mean_ppg"] == pytest.approx(25.0)


def test_row_with_missing_season_or_player_id_is_skipped() -> None:
    rows = [
        _row(2025, "QB1", "QB", 30.0, 480.0, 16),
        _row(2025, "QB2", "QB", 20.0, 320.0, 16),
        _row(None, "QB3", "QB", 10.0, 150.0, 15),
        _row(2025, None, "QB", 10.0, 150.0, 15),
    ]
    df = build_player_value_metrics(_df(rows), ["QB"], 2)

    assert list(df["sleeper_player_id"]) == ["QB1", "QB2"]


# --------------------------------------------------------------------------
# Grouping key: seasons and extra columns
# --------------------------------------------------------------------------


def test_multiple_seasons_are_not_pooled() -> None:
    """Replacement and value ranks are computed within each season: 2024 has
    a 20.0 QB baseline, 2025 a 30.0 one, and ranks restart per season.
    """
    rows = [
        _row(2024, "QB1", "QB", 30.0, 480.0, 16),
        _row(2024, "QB2", "QB", 20.0, 320.0, 16),
        _row(2025, "QB1", "QB", 40.0, 640.0, 16),
        _row(2025, "QB2", "QB", 30.0, 480.0, 16),
        _row(2025, "QB3", "QB", 20.0, 320.0, 16),
    ]
    df = build_player_value_metrics(_df(rows), ["QB"], 2)

    assert _get_row(df, "QB1", season=2024)["replacement_ppg"] == pytest.approx(20.0)
    assert _get_row(df, "QB1", season=2025)["replacement_ppg"] == pytest.approx(30.0)
    # Same 160.0 VORP both years, but the 2024 field is only two deep.
    assert _get_row(df, "QB1", season=2024)["value_rank"] == 1
    assert _get_row(df, "QB1", season=2025)["value_rank"] == 1
    assert _get_row(df, "QB2", season=2024)["value_rank"] == 2
    assert _get_row(df, "QB2", season=2025)["value_rank"] == 2
    assert _get_row(df, "QB3", season=2025)["value_rank"] == 3


def test_extra_columns_are_ignored_phase_agnostic() -> None:
    """The input has no is_playoff column (FFA-064's fact table has none),
    matching performance.py's phase-agnostic contract; a caller filters
    weeks before building the performance frame. An extra column is
    harmless proof that nothing here depends on it.
    """
    rows = [
        _row(2025, "QB1", "QB", 30.0, 480.0, 16),
        _row(2025, "QB2", "QB", 20.0, 320.0, 16),
    ]
    frame = _df(rows)
    frame["is_playoff"] = False
    df = build_player_value_metrics(frame, ["QB"], 2)

    assert _get_row(df, "QB1")["replacement_ppg"] == pytest.approx(20.0)


# --------------------------------------------------------------------------
# Positions outside QB/RB/WR/TE, empty input, dtypes
# --------------------------------------------------------------------------


def test_positions_outside_qb_rb_wr_te_are_included() -> None:
    rows = [
        _row(2025, "K1", "K", 10.0, 160.0, 16),
        _row(2025, "K2", "K", 6.0, 96.0, 16),
    ]
    df = build_position_scarcity_metrics(_df(rows), ["K"], 1)

    k = _get_position_row(df, "K")
    assert k["players"] == 2
    assert k["position_starters"] == 1
    assert k["replacement_ppg"] == pytest.approx(10.0)


def test_empty_input_returns_empty_frames_with_columns() -> None:
    player_df = build_player_value_metrics(_df([]), ROSTER_POSITIONS, NUM_TEAMS)
    scarcity_df = build_position_scarcity_metrics(_df([]), ROSTER_POSITIONS, NUM_TEAMS)

    assert player_df.empty
    assert list(player_df.columns) == PLAYER_VALUE_COLUMNS
    assert scarcity_df.empty
    assert list(scarcity_df.columns) == POSITION_SCARCITY_COLUMNS


def test_column_dtypes() -> None:
    player_df = build_player_value_metrics(
        _df(_toy_rows()), ROSTER_POSITIONS, NUM_TEAMS
    )
    scarcity_df = build_position_scarcity_metrics(
        _df(_toy_rows()), ROSTER_POSITIONS, NUM_TEAMS
    )

    assert player_df["season"].dtype == "int64"
    assert player_df["games_played"].dtype == "int64"
    assert player_df["position_players"].dtype == "int64"
    assert player_df["value_rank"].dtype == "int64"
    assert player_df["sleeper_player_id"].dtype == object
    assert player_df["player_name"].dtype == object
    assert player_df["position"].dtype == object
    assert player_df["nfl_team"].dtype == object
    for column in (
        "points_per_game",
        "total_points",
        "position_mean_ppg",
        "ppg_above_position_average",
        "position_mean_total",
        "total_above_position_average",
        "replacement_ppg",
        "ppg_above_replacement",
        "points_above_replacement",
    ):
        assert player_df[column].dtype == "float64", column

    assert scarcity_df["season"].dtype == "int64"
    assert scarcity_df["players"].dtype == "int64"
    assert scarcity_df["position_starters"].dtype == "int64"
    assert scarcity_df["replacement_rank"].dtype == "int64"
    assert scarcity_df["position"].dtype == object
    for column in (
        "best_ppg",
        "replacement_ppg",
        "ppg_gap_to_replacement",
        "scarcity_ratio",
    ):
        assert scarcity_df[column].dtype == "float64", column

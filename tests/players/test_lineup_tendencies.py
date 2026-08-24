"""Tests for manager lineup-tendency analytics (FFA-070).

All tests operate on hand-built ``player_week_df``-shaped inputs plus, where
relevant, an explicit ``roster_positions`` slot list -- no HTTP calls, no
opaque fixture values -- so every count, share, and rank can be verified by
hand arithmetic from the rows written in each test, per AGENTS.md's
analytics-ticket requirement for a hand-checkable toy example.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.players import (
    BENCH_ALLOCATION_COLUMNS,
    FLEX_USAGE_COLUMNS,
    PLAYER_WEEK_COLUMNS,
    POSITIONAL_PREFERENCE_COLUMNS,
    ROSTER_CONSTRUCTION_COLUMNS,
    ROSTER_EFFICIENCY_COLUMNS,
    START_SIT_TENDENCY_COLUMNS,
    build_bench_allocation_metrics,
    build_flex_usage_metrics,
    build_positional_preference_metrics,
    build_roster_construction_metrics,
    build_start_sit_tendency_metrics,
)

#: A minimal set of provider-style raw stat columns, matching the sibling
#: player-analytics test files. Their values are irrelevant here.
STAT_COLUMNS = ["receptions", "receiving_yards"]

PLAYER_WEEK_TEST_COLUMNS = PLAYER_WEEK_COLUMNS + STAT_COLUMNS + ["fantasy_points"]


def _row(
    season: int,
    week: int,
    sleeper_player_id,
    position,
    started: bool,
    roster_id: int = 1,
    fantasy_team: str = "Alpha",
    fantasy_points: float = 10.0,
    bench: bool | None = None,
) -> dict:
    """One ``player_week_df``-shaped row.

    ``bench`` defaults to ``not started`` (FFA-064's contract); a caller can
    override it to exercise this module's defensive "started wins ties"
    resolution rule.
    """
    return {
        "season": season,
        "week": week,
        "roster_id": roster_id,
        "fantasy_team": fantasy_team,
        "sleeper_player_id": sleeper_player_id,
        "gsis_id": f"g-{sleeper_player_id}",
        "player_name": f"Player {sleeper_player_id}",
        "position": position,
        "nfl_team": "SF",
        "started": started,
        "bench": (not started) if bench is None else bench,
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


def _rows_for(df: pd.DataFrame, **filters) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    for column, value in filters.items():
        mask &= df[column] == value
    return df.loc[mask]


def _one_row(df: pd.DataFrame, **filters) -> pd.Series:
    match = _rows_for(df, **filters)
    assert len(match) == 1, f"expected exactly one row for {filters}, got {len(match)}"
    return match.iloc[0]


# --------------------------------------------------------------------------
# Roster construction
# --------------------------------------------------------------------------


def test_roster_construction_toy_example() -> None:
    """Team Alpha, 2025: RB1 rostered weeks 1-2, RB2 rostered week 1 only,
    WR1 rostered weeks 1-2.

    RB: 3 player-weeks, 2 distinct players. WR: 2 player-weeks, 1 distinct
    player. Team total = 5. roster_share: RB = 3/5 = 0.6, WR = 2/5 = 0.4.
    """
    rows = [
        _row(2025, 1, "RB1", "RB", started=True),
        _row(2025, 2, "RB1", "RB", started=True),
        _row(2025, 1, "RB2", "RB", started=False),
        _row(2025, 1, "WR1", "WR", started=True),
        _row(2025, 2, "WR1", "WR", started=False),
    ]
    df = build_roster_construction_metrics(_df(rows))

    assert list(df.columns) == ROSTER_CONSTRUCTION_COLUMNS
    assert len(df) == 2

    rb = _one_row(df, position="RB")
    assert rb["distinct_players"] == 2
    assert rb["rostered_player_weeks"] == 3
    assert rb["roster_share"] == pytest.approx(0.6)

    wr = _one_row(df, position="WR")
    assert wr["distinct_players"] == 1
    assert wr["rostered_player_weeks"] == 2
    assert wr["roster_share"] == pytest.approx(0.4)


def test_roster_construction_missing_player_id_skips_distinct_count() -> None:
    rows = [
        _row(2025, 1, "RB1", "RB", started=True),
        _row(2025, 1, None, "RB", started=True),
    ]
    df = build_roster_construction_metrics(_df(rows))

    row = _one_row(df, position="RB")
    assert row["rostered_player_weeks"] == 2
    assert row["distinct_players"] == 1


def test_roster_construction_row_missing_position_is_skipped() -> None:
    rows = [
        _row(2025, 1, "RB1", "RB", started=True),
        _row(2025, 1, "X", None, started=True),
    ]
    df = build_roster_construction_metrics(_df(rows))

    assert len(df) == 1
    assert df.iloc[0]["position"] == "RB"
    assert df.iloc[0]["rostered_player_weeks"] == 1


def test_roster_construction_multiple_teams_and_seasons() -> None:
    rows = [
        _row(2025, 1, "RB1", "RB", started=True, fantasy_team="Alpha"),
        _row(2025, 1, "RB2", "RB", started=True, fantasy_team="Beta"),
        _row(2024, 1, "RB1", "RB", started=True, fantasy_team="Alpha"),
    ]
    df = build_roster_construction_metrics(_df(rows))

    assert len(df) == 3
    alpha_2025 = _one_row(df, season=2025, fantasy_team="Alpha")
    beta_2025 = _one_row(df, season=2025, fantasy_team="Beta")
    alpha_2024 = _one_row(df, season=2024, fantasy_team="Alpha")
    # Each team-season's share is computed only within its own totals.
    assert alpha_2025["roster_share"] == pytest.approx(1.0)
    assert beta_2025["roster_share"] == pytest.approx(1.0)
    assert alpha_2024["roster_share"] == pytest.approx(1.0)


def test_roster_construction_empty_input() -> None:
    df = build_roster_construction_metrics(_df([]))
    assert df.empty
    assert list(df.columns) == ROSTER_CONSTRUCTION_COLUMNS


def test_roster_construction_column_dtypes() -> None:
    df = build_roster_construction_metrics(
        _df([_row(2025, 1, "RB1", "RB", started=True)])
    )
    assert df["season"].dtype == "int64"
    assert df["distinct_players"].dtype == "int64"
    assert df["rostered_player_weeks"].dtype == "int64"
    assert df["roster_share"].dtype == "float64"
    assert df["fantasy_team"].dtype == object
    assert df["position"].dtype == object


# --------------------------------------------------------------------------
# Bench allocation
# --------------------------------------------------------------------------


def test_bench_allocation_toy_example() -> None:
    """Team Alpha, 2025: RB2 benched weeks 1-2 (2 bench weeks), WR2 benched
    week 1 only (1 bench week). RB1/WR1 started every week and are never
    benched, so they get no row. Team bench total = 3.
    bench_share: RB = 2/3, WR = 1/3.
    """
    rows = [
        _row(2025, 1, "RB1", "RB", started=True),
        _row(2025, 2, "RB1", "RB", started=True),
        _row(2025, 1, "RB2", "RB", started=False),
        _row(2025, 2, "RB2", "RB", started=False),
        _row(2025, 1, "WR1", "WR", started=True),
        _row(2025, 1, "WR2", "WR", started=False),
    ]
    df = build_bench_allocation_metrics(_df(rows))

    assert list(df.columns) == BENCH_ALLOCATION_COLUMNS
    assert len(df) == 2

    rb = _one_row(df, position="RB")
    assert rb["bench_weeks"] == 2
    assert rb["bench_share"] == pytest.approx(2 / 3)

    wr = _one_row(df, position="WR")
    assert wr["bench_weeks"] == 1
    assert wr["bench_share"] == pytest.approx(1 / 3)


def test_bench_allocation_position_never_benched_has_no_row() -> None:
    rows = [_row(2025, 1, "QB1", "QB", started=True)]
    df = build_bench_allocation_metrics(_df(rows))
    assert df.empty
    assert list(df.columns) == BENCH_ALLOCATION_COLUMNS


def test_bench_allocation_started_and_bench_both_true_counts_as_started() -> None:
    """Defensive handling: a malformed row with both flags True is treated
    as started (never benched), per the module's tie-break rule.
    """
    rows = [_row(2025, 1, "RB1", "RB", started=True, bench=True)]
    df = build_bench_allocation_metrics(_df(rows))
    assert df.empty


def test_bench_allocation_empty_input() -> None:
    df = build_bench_allocation_metrics(_df([]))
    assert df.empty
    assert list(df.columns) == BENCH_ALLOCATION_COLUMNS


# --------------------------------------------------------------------------
# FLEX usage
# --------------------------------------------------------------------------

#: Two-RB, one-FLEX league. FLEX accepts RB/WR/TE, so RB/WR/TE are all
#: FLEX-eligible, with fixed_slot_count RB=2, WR=0, TE=0.
TOY_FLEX_ROSTER_POSITIONS = ["RB", "RB", "FLEX", "BN"]


def test_flex_usage_toy_example() -> None:
    """Team Alpha, 2025, in the two-RB-one-FLEX league above.

    Week 1: 3 RBs started, 0 WR/TE started. RB excess = 3 - 2 = 1.
    Week 2: 2 RBs started, 1 WR started. RB excess = 0, WR excess = 1 - 0 = 1.

    Season: RB flex_starts = 1, WR flex_starts = 1 -- tied at rank 1,
    flex_start_share = 0.5 each.
    """
    rows = [
        _row(2025, 1, "RB1", "RB", started=True),
        _row(2025, 1, "RB2", "RB", started=True),
        _row(2025, 1, "RB3", "RB", started=True),
        _row(2025, 2, "RB1", "RB", started=True),
        _row(2025, 2, "RB2", "RB", started=True),
        _row(2025, 2, "WR1", "WR", started=True),
    ]
    df = build_flex_usage_metrics(_df(rows), TOY_FLEX_ROSTER_POSITIONS)

    assert list(df.columns) == FLEX_USAGE_COLUMNS
    assert len(df) == 2

    rb = _one_row(df, position="RB")
    assert rb["flex_starts"] == 1
    assert rb["flex_start_share"] == pytest.approx(0.5)
    assert rb["flex_usage_rank"] == 1

    wr = _one_row(df, position="WR")
    assert wr["flex_starts"] == 1
    assert wr["flex_start_share"] == pytest.approx(0.5)
    assert wr["flex_usage_rank"] == 1


def test_flex_usage_rank_breaks_tie_for_dominant_position() -> None:
    """RB fills FLEX twice, WR once -- RB is the clear rank-1 flex user."""
    rows = [
        # Week 1: 3 RBs started (excess 1), no WR.
        _row(2025, 1, "RB1", "RB", started=True),
        _row(2025, 1, "RB2", "RB", started=True),
        _row(2025, 1, "RB3", "RB", started=True),
        # Week 2: 3 RBs started again (excess 1).
        _row(2025, 2, "RB1", "RB", started=True),
        _row(2025, 2, "RB2", "RB", started=True),
        _row(2025, 2, "RB3", "RB", started=True),
        # Week 3: 2 RBs, 1 WR started (WR excess 1).
        _row(2025, 3, "RB1", "RB", started=True),
        _row(2025, 3, "RB2", "RB", started=True),
        _row(2025, 3, "WR1", "WR", started=True),
    ]
    df = build_flex_usage_metrics(_df(rows), TOY_FLEX_ROSTER_POSITIONS)

    rb = _one_row(df, position="RB")
    wr = _one_row(df, position="WR")
    assert rb["flex_starts"] == 2
    assert wr["flex_starts"] == 1
    assert rb["flex_usage_rank"] == 1
    assert wr["flex_usage_rank"] == 2
    assert rb["flex_start_share"] == pytest.approx(2 / 3)
    assert wr["flex_start_share"] == pytest.approx(1 / 3)


def test_flex_usage_no_flex_slots_returns_empty() -> None:
    """A league with no FLEX-type slot at all has no FLEX-eligible position,
    so this function returns an empty frame regardless of the lineup.
    """
    rows = [
        _row(2025, 1, "RB1", "RB", started=True),
        _row(2025, 1, "RB2", "RB", started=True),
        _row(2025, 1, "RB3", "RB", started=True),
    ]
    df = build_flex_usage_metrics(_df(rows), ["RB", "RB", "BN"])
    assert df.empty
    assert list(df.columns) == FLEX_USAGE_COLUMNS


def test_flex_usage_no_excess_returns_empty() -> None:
    """Nobody ever exceeds their dedicated slot count -- no flex usage to
    report, even though a FLEX slot exists (it was left empty or filled by
    a position with 0 fixed slots, e.g. TE, which never happened either).
    """
    rows = [
        _row(2025, 1, "RB1", "RB", started=True),
        _row(2025, 1, "RB2", "RB", started=True),
    ]
    df = build_flex_usage_metrics(_df(rows), TOY_FLEX_ROSTER_POSITIONS)
    assert df.empty


def test_flex_usage_super_flex_attributes_extra_qb() -> None:
    """A SUPER_FLEX league: QB is flex-eligible (fixed QB slots = 1). A
    team starting 2 QBs has QB excess = 1.
    """
    rows = [
        _row(2025, 1, "QB1", "QB", started=True),
        _row(2025, 1, "QB2", "QB", started=True),
    ]
    df = build_flex_usage_metrics(_df(rows), ["QB", "SUPER_FLEX", "BN"])
    qb = _one_row(df, position="QB")
    assert qb["flex_starts"] == 1
    assert qb["flex_usage_rank"] == 1


def test_flex_usage_empty_input() -> None:
    df = build_flex_usage_metrics(_df([]), TOY_FLEX_ROSTER_POSITIONS)
    assert df.empty
    assert list(df.columns) == FLEX_USAGE_COLUMNS


# --------------------------------------------------------------------------
# Start/sit tendencies (thin wrapper over FFA-067's roster efficiency)
# --------------------------------------------------------------------------

STANDARD_ROSTER_POSITIONS = ["QB", "RB", "RB", "WR", "FLEX", "BN"]


def test_start_sit_tendency_wraps_roster_efficiency_and_adds_rates() -> None:
    """Team Alpha, week 1, in the QB/RB/RB/WR/FLEX league: QB1* 20, RB1* 10,
    RB2* 10, WR1* 5, RB3 (bench) 30.

    Actual = 20 + 10 + 10 + 5 = 45. The WR slot is locked to WR1 (the only
    rostered WR), but the FLEX slot (RB/WR/TE-eligible) should have taken
    RB3 (30) instead of being left empty: optimal = 20 + 10 + 10 + 5 + 30 =
    75. points_left_on_bench = 30, 0 suboptimal starts (WR1 stays), 1
    suboptimal sit (RB3). One week played, so the per-week rates equal the
    season totals.
    """
    rows = [
        _row(2025, 1, "QB1", "QB", started=True, fantasy_points=20.0),
        _row(2025, 1, "RB1", "RB", started=True, fantasy_points=10.0),
        _row(2025, 1, "RB2", "RB", started=True, fantasy_points=10.0),
        _row(2025, 1, "WR1", "WR", started=True, fantasy_points=5.0),
        _row(2025, 1, "RB3", "RB", started=False, fantasy_points=30.0),
    ]
    df = build_start_sit_tendency_metrics(_df(rows), STANDARD_ROSTER_POSITIONS)

    assert list(df.columns) == START_SIT_TENDENCY_COLUMNS
    assert len(df) == 1
    row = df.iloc[0]
    assert row["weeks_played"] == 1
    assert row["total_actual_points"] == pytest.approx(45.0)
    assert row["total_optimal_points"] == pytest.approx(75.0)
    assert row["total_suboptimal_starts"] == 0
    assert row["total_suboptimal_sits"] == 1
    assert row["suboptimal_starts_per_week"] == pytest.approx(0.0)
    assert row["suboptimal_sits_per_week"] == pytest.approx(1.0)


def test_start_sit_tendency_rate_over_multiple_weeks() -> None:
    """Two weeks: week 1 is the suboptimal week above (1 wrong sit); week 2
    has no WR rostered at all (QB1, RB1, RB2, RB3 all started), so the
    third RB legally fills FLEX and the lineup is already optimal (0 wrong
    sits). The per-week sit rate is therefore 0.5, not 1.0.
    """
    week1 = [
        _row(2025, 1, "QB1", "QB", started=True, fantasy_points=20.0),
        _row(2025, 1, "RB1", "RB", started=True, fantasy_points=10.0),
        _row(2025, 1, "RB2", "RB", started=True, fantasy_points=10.0),
        _row(2025, 1, "WR1", "WR", started=True, fantasy_points=5.0),
        _row(2025, 1, "RB3", "RB", started=False, fantasy_points=30.0),
    ]
    week2 = [
        _row(2025, 2, "QB1", "QB", started=True, fantasy_points=20.0),
        _row(2025, 2, "RB1", "RB", started=True, fantasy_points=10.0),
        _row(2025, 2, "RB2", "RB", started=True, fantasy_points=10.0),
        _row(2025, 2, "RB3", "RB", started=True, fantasy_points=30.0),
    ]
    df = build_start_sit_tendency_metrics(_df(week1 + week2), STANDARD_ROSTER_POSITIONS)

    row = df.iloc[0]
    assert row["weeks_played"] == 2
    assert row["total_suboptimal_starts"] == 0
    assert row["total_suboptimal_sits"] == 1
    assert row["suboptimal_starts_per_week"] == pytest.approx(0.0)
    assert row["suboptimal_sits_per_week"] == pytest.approx(0.5)


def test_start_sit_tendency_matches_roster_efficiency_columns() -> None:
    """Every ``ROSTER_EFFICIENCY_COLUMNS`` value is passed through unchanged."""
    from fantasy_analyzer.players import build_roster_efficiency_metrics

    rows = [
        _row(2025, 1, "QB1", "QB", started=True, fantasy_points=20.0),
        _row(2025, 1, "RB1", "RB", started=True, fantasy_points=10.0),
    ]
    tendency_df = build_start_sit_tendency_metrics(_df(rows), STANDARD_ROSTER_POSITIONS)
    efficiency_df = build_roster_efficiency_metrics(
        _df(rows), STANDARD_ROSTER_POSITIONS
    )

    for column in ROSTER_EFFICIENCY_COLUMNS:
        assert tendency_df.iloc[0][column] == efficiency_df.iloc[0][column]


def test_start_sit_tendency_empty_input() -> None:
    df = build_start_sit_tendency_metrics(_df([]), STANDARD_ROSTER_POSITIONS)
    assert df.empty
    assert list(df.columns) == START_SIT_TENDENCY_COLUMNS


# --------------------------------------------------------------------------
# Positional preferences (rollup)
# --------------------------------------------------------------------------


def test_positional_preference_toy_example() -> None:
    """Team Alpha, 2025: RB1 started weeks 1-2 (2 started weeks), RB2
    benched weeks 1-2 (2 bench weeks) -- 4 rostered player-weeks at RB.
    WR1 started week 1 only, benched week 2 -- 1 started, 1 bench, 2
    rostered player-weeks at WR.

    Team totals: rostered = 6, started = 3, bench = 3.
    RB: roster_share 4/6, start_share 2/3, bench_share 2/3.
    WR: roster_share 2/6, start_share 1/3, bench_share 1/3.
    """
    rows = [
        _row(2025, 1, "RB1", "RB", started=True),
        _row(2025, 2, "RB1", "RB", started=True),
        _row(2025, 1, "RB2", "RB", started=False),
        _row(2025, 2, "RB2", "RB", started=False),
        _row(2025, 1, "WR1", "WR", started=True),
        _row(2025, 2, "WR1", "WR", started=False),
    ]
    df = build_positional_preference_metrics(_df(rows))

    assert list(df.columns) == POSITIONAL_PREFERENCE_COLUMNS
    assert len(df) == 2

    rb = _one_row(df, position="RB")
    assert rb["distinct_players"] == 2
    assert rb["rostered_player_weeks"] == 4
    assert rb["roster_share"] == pytest.approx(4 / 6)
    assert rb["started_weeks"] == 2
    assert rb["start_share"] == pytest.approx(2 / 3)
    assert rb["bench_weeks"] == 2
    assert rb["bench_share"] == pytest.approx(2 / 3)

    wr = _one_row(df, position="WR")
    assert wr["rostered_player_weeks"] == 2
    assert wr["roster_share"] == pytest.approx(2 / 6)
    assert wr["started_weeks"] == 1
    assert wr["start_share"] == pytest.approx(1 / 3)
    assert wr["bench_weeks"] == 1
    assert wr["bench_share"] == pytest.approx(1 / 3)


def test_positional_preference_position_never_benched_has_zero_bench_share() -> None:
    """Unlike build_bench_allocation_metrics, this function still emits a
    row for a position that was rostered/started but never benched, with
    bench_weeks == 0 and bench_share == 0.0 (not NaN, since other positions
    contribute a positive team-season bench total).
    """
    rows = [
        _row(2025, 1, "QB1", "QB", started=True),
        _row(2025, 1, "RB1", "RB", started=False),
    ]
    df = build_positional_preference_metrics(_df(rows))

    qb = _one_row(df, position="QB")
    assert qb["bench_weeks"] == 0
    assert qb["bench_share"] == pytest.approx(0.0)
    assert qb["started_weeks"] == 1
    assert qb["start_share"] == pytest.approx(1.0)

    rb = _one_row(df, position="RB")
    assert rb["started_weeks"] == 0
    assert rb["start_share"] == pytest.approx(0.0)
    assert rb["bench_weeks"] == 1
    assert rb["bench_share"] == pytest.approx(1.0)


def test_positional_preference_all_bench_team_season_has_nan_start_share() -> None:
    """A team-season with zero started weeks at all makes start_share
    undefined (division by a zero team total), even though bench_share is
    still defined.
    """
    rows = [_row(2025, 1, "RB1", "RB", started=False)]
    df = build_positional_preference_metrics(_df(rows))

    row = _one_row(df, position="RB")
    assert pd.isna(row["start_share"])
    assert row["bench_share"] == pytest.approx(1.0)


def test_positional_preference_empty_input() -> None:
    df = build_positional_preference_metrics(_df([]))
    assert df.empty
    assert list(df.columns) == POSITIONAL_PREFERENCE_COLUMNS


def test_positional_preference_row_missing_season_is_skipped() -> None:
    rows = [
        _row(2025, 1, "RB1", "RB", started=True),
        _row(None, 1, "RB2", "RB", started=True),
    ]
    df = build_positional_preference_metrics(_df(rows))
    assert len(df) == 1
    assert df.iloc[0]["rostered_player_weeks"] == 1


# --------------------------------------------------------------------------
# Regular season vs. playoffs: phase-agnostic, caller filters first
# --------------------------------------------------------------------------


def test_all_functions_are_phase_agnostic() -> None:
    """The player-week fact table has no ``is_playoff`` column, so every
    function in this module processes a week 9 row (a playoff week under
    any boundary <= 9) identically to a regular-season week 1 row.
    """
    week1 = [_row(2025, 1, "RB1", "RB", started=True)]
    week9 = [_row(2025, 9, "RB1", "RB", started=True)]

    combined = build_roster_construction_metrics(_df(week1 + week9))
    regular_only = build_roster_construction_metrics(_df(week1))

    assert _one_row(combined, position="RB")["rostered_player_weeks"] == 2
    assert _one_row(regular_only, position="RB")["rostered_player_weeks"] == 1

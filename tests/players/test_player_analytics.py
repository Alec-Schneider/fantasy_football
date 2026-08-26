"""Tests for the PlayerAnalytics composition service (FFA-071).

``PlayerAnalytics`` is pure composition over FFA-064 through FFA-070's already
tested ``build_*`` functions -- it defines no new metrics of its own. These
tests therefore check that each exposed frame equals what calling the
underlying ``build_*`` function directly would produce (the composition is
wired to the right inputs, per AGENTS.md's composition-only requirement), plus
the construction-time behavior (``player_season_df`` is built once and reused
by the value frames), the threshold passthroughs, and the documented edge
cases (empty input, ``num_teams=None``, missing values, ties, the
caller-filters-the-phase-first contract, and the ``ValueError`` the two
FFA-069 frames raise when the optional ``season_matchup_df`` was omitted).

One hand-computed toy example is included so the wiring is verified against
arithmetic and not only against the builders themselves: a composition bug
that passed, say, the wrong ``roster_positions`` would still satisfy an
equality test written with the same wrong argument.

Inputs are hand-built ``player_week_df``-shaped (and, for FFA-069,
``season_matchup_df``-shaped) frames -- no HTTP calls.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS
from fantasy_analyzer.players import (
    PLAYER_WEEK_COLUMNS,
    PlayerAnalytics,
    build_bench_allocation_metrics,
    build_flex_usage_metrics,
    build_lineup_efficiency_metrics,
    build_matchup_player_contributions,
    build_player_analytics,
    build_player_performance_metrics,
    build_player_value_metrics,
    build_position_scarcity_metrics,
    build_position_strength_metrics,
    build_positional_matchup_advantage,
    build_positional_preference_metrics,
    build_roster_construction_metrics,
    build_roster_efficiency_metrics,
    build_start_sit_tendency_metrics,
)

#: A minimal set of provider-style raw stat columns, matching the sibling
#: player-analytics test files. A row with every stat column ``None`` is a
#: player who did not play, per FFA-064/FFA-065's "game played" rule.
STAT_COLUMNS = ["receptions", "receiving_yards"]

PLAYER_WEEK_TEST_COLUMNS = PLAYER_WEEK_COLUMNS + STAT_COLUMNS + ["fantasy_points"]

#: One QB, one RB, one WR, one FLEX (RB/WR/TE) and a bench slot.
ROSTER_POSITIONS = ["QB", "RB", "WR", "FLEX", "BN"]

NUM_TEAMS = 2


def _row(
    season: int,
    week: int,
    sleeper_player_id: str,
    fantasy_points: float | None,
    position: str | None,
    started: bool,
    roster_id: int = 1,
    fantasy_team: str = "Alpha",
    played: bool = True,
) -> dict:
    """One ``player_week_df``-shaped row.

    ``played=False`` blanks every raw stat column, the FFA-064 shape of a
    rostered player with no provider data that week.
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
        "bench": not started,
        "receptions": 4.0 if played else None,
        "receiving_yards": 50.0 if played else None,
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


def _toy_rows() -> list[dict]:
    """Two rosters, two weeks, five players each -- see the hand check below.

    Roster 1 ("Alpha") starts p1 (QB), p2 (RB), p3 (WR) and p4 (RB, in the
    FLEX), and benches p5 (WR). Roster 2 ("Bravo") starts p6 (QB), p7 (RB),
    p8 (WR) and p9 (TE, in the FLEX), and benches p10 (RB). Week 2 repeats
    the same lineups with different scores.
    """
    week_1 = [
        _row(2025, 1, "p1", 20.0, "QB", True),
        _row(2025, 1, "p2", 10.0, "RB", True),
        _row(2025, 1, "p3", 5.0, "WR", True),
        _row(2025, 1, "p4", 8.0, "RB", True),
        _row(2025, 1, "p5", 12.0, "WR", False),
        _row(2025, 1, "p6", 15.0, "QB", True, roster_id=2, fantasy_team="Bravo"),
        _row(2025, 1, "p7", 6.0, "RB", True, roster_id=2, fantasy_team="Bravo"),
        _row(2025, 1, "p8", 9.0, "WR", True, roster_id=2, fantasy_team="Bravo"),
        _row(2025, 1, "p9", 3.0, "TE", True, roster_id=2, fantasy_team="Bravo"),
        _row(2025, 1, "p10", 1.0, "RB", False, roster_id=2, fantasy_team="Bravo"),
    ]
    week_2 = [
        _row(2025, 2, "p1", 10.0, "QB", True),
        _row(2025, 2, "p2", 20.0, "RB", True),
        _row(2025, 2, "p3", 5.0, "WR", True),
        _row(2025, 2, "p4", 2.0, "RB", True),
        _row(2025, 2, "p5", 0.0, "WR", False),
        _row(2025, 2, "p6", 15.0, "QB", True, roster_id=2, fantasy_team="Bravo"),
        _row(2025, 2, "p7", 6.0, "RB", True, roster_id=2, fantasy_team="Bravo"),
        _row(2025, 2, "p8", 9.0, "WR", True, roster_id=2, fantasy_team="Bravo"),
        _row(2025, 2, "p9", 3.0, "TE", True, roster_id=2, fantasy_team="Bravo"),
        _row(2025, 2, "p10", 1.0, "RB", False, roster_id=2, fantasy_team="Bravo"),
    ]
    return week_1 + week_2


def _toy_df() -> pd.DataFrame:
    return _df(_toy_rows())


def _toy_matchup_df() -> pd.DataFrame:
    """The paired matchups the toy fact table's two rosters played.

    Roster 1 beats roster 2 in both weeks; ``points_1``/``points_2`` are the
    sums of each roster's started ``fantasy_points`` above (week 1:
    20+10+5+8 = 43 vs. 15+6+9+3 = 33; week 2: 10+20+5+2 = 37 vs. 33), so the
    two hand-built frames are mutually consistent.
    """
    rows = [
        {
            "season": 2025,
            "week": week,
            "is_playoff": False,
            "matchup_id": 1,
            "roster_1_id": 1,
            "roster_2_id": 2,
            "owner_1": "Alpha",
            "owner_2": "Bravo",
            "points_1": points_1,
            "points_2": 33.0,
            "winner": 1,
            "loser": 2,
            "is_tie": False,
            "margin": points_1 - 33.0,
            "point_differential": points_1 - 33.0,
        }
        for week, points_1 in ((1, 43.0), (2, 37.0))
    ]
    return pd.DataFrame(rows, columns=SEASON_MATCHUP_COLUMNS)


def _toy_analytics(**kwargs) -> PlayerAnalytics:
    kwargs.setdefault("player_week_df", _toy_df())
    kwargs.setdefault("roster_positions", ROSTER_POSITIONS)
    kwargs.setdefault("num_teams", NUM_TEAMS)
    return PlayerAnalytics(**kwargs)


def _toy_matchup_analytics(**kwargs) -> PlayerAnalytics:
    """A :func:`_toy_analytics` that also carries the matchup frame."""
    kwargs.setdefault("season_matchup_df", _toy_matchup_df())
    return _toy_analytics(**kwargs)


# --- hand-checkable toy example -------------------------------------------


def test_lineup_efficiency_week_one_matches_hand_arithmetic() -> None:
    """Week 1, roster 1, under ``["QB", "RB", "WR", "FLEX", "BN"]``.

    Actual starters: p1 20 + p2 10 + p3 5 + p4 8 = 43.
    Optimal legal lineup: QB p1 20, RB p2 10 (better than p4 8), WR p5 12
    (the benched receiver beats p3 5), FLEX p4 8 (the best remaining
    RB/WR/TE, ahead of p3 5) = 50.
    Bench points: p5 12. Points left on bench: 50 - 43 = 7.
    Efficiency: 43 / 50 = 0.86. One wrong start (p3) and one wrong sit (p5).
    """
    weekly = _toy_analytics().lineup_efficiency_df
    row = weekly.loc[(weekly["week"] == 1) & (weekly["roster_id"] == 1)].iloc[0]

    assert row["actual_points"] == pytest.approx(43.0)
    assert row["optimal_points"] == pytest.approx(50.0)
    assert row["bench_points"] == pytest.approx(12.0)
    assert row["points_left_on_bench"] == pytest.approx(7.0)
    assert row["efficiency_pct"] == pytest.approx(0.86)
    assert bool(row["is_suboptimal"]) is True
    assert int(row["suboptimal_starts"]) == 1
    assert int(row["suboptimal_sits"]) == 1


# --- player_weekly_df ------------------------------------------------------


def test_player_weekly_df_returns_the_input_frame_unchanged() -> None:
    player_week_df = _toy_df()
    analytics = _toy_analytics(player_week_df=player_week_df)

    assert analytics.player_weekly_df is player_week_df
    pd.testing.assert_frame_equal(analytics.player_weekly_df, analytics.player_week_df)


# --- player_season_df ------------------------------------------------------


def test_player_season_df_matches_direct_call() -> None:
    analytics = _toy_analytics()

    expected = build_player_performance_metrics(_toy_df())
    pd.testing.assert_frame_equal(analytics.player_season_df, expected)


def test_player_season_df_passes_through_custom_threshold() -> None:
    analytics = _toy_analytics(player_boom_bust_threshold=0.5)

    expected = build_player_performance_metrics(_toy_df(), boom_bust_threshold=0.5)
    pd.testing.assert_frame_equal(analytics.player_season_df, expected)


def test_negative_player_threshold_raises_at_construction() -> None:
    """The eager frame means the builder's ValueError surfaces immediately."""
    with pytest.raises(ValueError, match="boom_bust_threshold"):
        _toy_analytics(player_boom_bust_threshold=-1.0)


# --- position_summary_df ---------------------------------------------------


def test_position_summary_df_matches_direct_call() -> None:
    analytics = _toy_analytics()

    expected = build_position_strength_metrics(_toy_df())
    pd.testing.assert_frame_equal(analytics.position_summary_df, expected)


def test_position_summary_df_passes_through_custom_threshold() -> None:
    analytics = _toy_analytics(position_boom_bust_threshold=0.5)

    expected = build_position_strength_metrics(_toy_df(), boom_bust_threshold=0.5)
    pd.testing.assert_frame_equal(analytics.position_summary_df, expected)


def test_negative_position_threshold_raises_only_on_access() -> None:
    """The lazy frame means construction succeeds and the read raises."""
    analytics = _toy_analytics(position_boom_bust_threshold=-1.0)

    with pytest.raises(ValueError, match="boom_bust_threshold"):
        analytics.position_summary_df


# --- lineup_efficiency_df / roster_efficiency_df ---------------------------


def test_lineup_efficiency_df_matches_direct_call() -> None:
    analytics = _toy_analytics()

    expected = build_lineup_efficiency_metrics(_toy_df(), ROSTER_POSITIONS)
    pd.testing.assert_frame_equal(analytics.lineup_efficiency_df, expected)


def test_roster_efficiency_df_matches_direct_call() -> None:
    analytics = _toy_analytics()

    expected = build_roster_efficiency_metrics(_toy_df(), ROSTER_POSITIONS)
    pd.testing.assert_frame_equal(analytics.roster_efficiency_df, expected)


def test_efficiency_frames_use_the_leagues_roster_positions() -> None:
    """A different slot list must produce a different optimal lineup, proving
    ``roster_positions`` reaches the optimizer rather than a default.
    """
    two_flex = ROSTER_POSITIONS + ["FLEX"]
    analytics = _toy_analytics(roster_positions=two_flex)

    expected = build_lineup_efficiency_metrics(_toy_df(), two_flex)
    pd.testing.assert_frame_equal(analytics.lineup_efficiency_df, expected)

    default_week_1 = _toy_analytics().lineup_efficiency_df
    default_row = default_week_1.loc[
        (default_week_1["week"] == 1) & (default_week_1["roster_id"] == 1)
    ].iloc[0]
    two_flex_week_1 = analytics.lineup_efficiency_df
    two_flex_row = two_flex_week_1.loc[
        (two_flex_week_1["week"] == 1) & (two_flex_week_1["roster_id"] == 1)
    ].iloc[0]

    # The extra FLEX seats p3 (5.0), the last unused starter-eligible player.
    assert two_flex_row["optimal_points"] == pytest.approx(
        default_row["optimal_points"] + 5.0
    )


# --- player_value_df / position_scarcity_df --------------------------------


def test_player_value_df_matches_chained_composition() -> None:
    """Hand-verifies the composition wiring per the ticket's requirement: the
    result must equal chaining build_player_performance_metrics into
    build_player_value_metrics on the same inputs, not some parallel path.
    """
    analytics = _toy_analytics()

    expected = build_player_value_metrics(
        build_player_performance_metrics(_toy_df()), ROSTER_POSITIONS, NUM_TEAMS
    )
    pd.testing.assert_frame_equal(analytics.player_value_df, expected)


def test_player_value_df_uses_the_eagerly_built_player_season_df() -> None:
    """The frame ``player_value_df`` is built from is the cached attribute,
    not a freshly rebuilt performance frame.
    """
    analytics = _toy_analytics()

    expected = build_player_value_metrics(
        analytics.player_season_df, ROSTER_POSITIONS, NUM_TEAMS
    )
    pd.testing.assert_frame_equal(analytics.player_value_df, expected)


def test_player_value_df_reflects_the_custom_player_threshold_frame() -> None:
    """The value frames consume this instance's own performance frame, so a
    custom player threshold flows through to them too.
    """
    analytics = _toy_analytics(player_boom_bust_threshold=0.5)

    expected = build_player_value_metrics(
        build_player_performance_metrics(_toy_df(), boom_bust_threshold=0.5),
        ROSTER_POSITIONS,
        NUM_TEAMS,
    )
    pd.testing.assert_frame_equal(analytics.player_value_df, expected)


def test_position_scarcity_df_matches_chained_composition() -> None:
    analytics = _toy_analytics()

    expected = build_position_scarcity_metrics(
        build_player_performance_metrics(_toy_df()), ROSTER_POSITIONS, NUM_TEAMS
    )
    pd.testing.assert_frame_equal(analytics.position_scarcity_df, expected)


def test_num_teams_none_passes_through_without_raising() -> None:
    """``LeagueSettings.total_rosters`` is optional; FFA-068 documents ``None``
    as the worst-rostered baseline rather than an error.
    """
    analytics = _toy_analytics(num_teams=None)

    expected = build_player_value_metrics(
        build_player_performance_metrics(_toy_df()), ROSTER_POSITIONS, None
    )
    pd.testing.assert_frame_equal(analytics.player_value_df, expected)
    assert not analytics.player_value_df.empty


def test_num_teams_reaches_the_replacement_cutoff() -> None:
    """A larger league starts more players, so the replacement baseline moves
    -- proving ``num_teams`` reaches FFA-068 rather than a default.
    """
    small = _toy_analytics(num_teams=1).position_scarcity_df
    large = _toy_analytics(num_teams=5).position_scarcity_df

    small_rb = small.loc[small["position"] == "RB"].iloc[0]
    large_rb = large.loc[large["position"] == "RB"].iloc[0]

    assert int(small_rb["position_starters"]) < int(large_rb["position_starters"])
    assert small_rb["replacement_ppg"] >= large_rb["replacement_ppg"]


# --- FFA-070 lineup tendency frames ---------------------------------------


def test_roster_construction_df_matches_direct_call() -> None:
    analytics = _toy_analytics()

    expected = build_roster_construction_metrics(_toy_df())
    pd.testing.assert_frame_equal(analytics.roster_construction_df, expected)


def test_roster_construction_df_matches_hand_arithmetic() -> None:
    """Roster 1 ("Alpha") over two weeks: one QB (p1), two RBs (p2, p4) and
    two WRs (p3, p5) rostered every week -- 2 + 4 + 4 = 10 rostered
    player-weeks, so the shares are 0.2 / 0.4 / 0.4.
    """
    frame = _toy_analytics().roster_construction_df
    alpha = frame.loc[frame["fantasy_team"] == "Alpha"].set_index("position")

    assert int(alpha.loc["QB", "distinct_players"]) == 1
    assert int(alpha.loc["RB", "distinct_players"]) == 2
    assert int(alpha.loc["QB", "rostered_player_weeks"]) == 2
    assert int(alpha.loc["RB", "rostered_player_weeks"]) == 4
    assert alpha.loc["QB", "roster_share"] == pytest.approx(0.2)
    assert alpha.loc["RB", "roster_share"] == pytest.approx(0.4)
    assert alpha.loc["WR", "roster_share"] == pytest.approx(0.4)


def test_bench_allocation_df_matches_direct_call() -> None:
    analytics = _toy_analytics()

    expected = build_bench_allocation_metrics(_toy_df())
    pd.testing.assert_frame_equal(analytics.bench_allocation_df, expected)


def test_bench_allocation_df_matches_hand_arithmetic() -> None:
    """Alpha benches only p5 (WR), both weeks: one row, 2 weeks, share 1.0."""
    frame = _toy_analytics().bench_allocation_df
    alpha = frame.loc[frame["fantasy_team"] == "Alpha"]

    assert list(alpha["position"]) == ["WR"]
    assert int(alpha.iloc[0]["bench_weeks"]) == 2
    assert alpha.iloc[0]["bench_share"] == pytest.approx(1.0)


def test_flex_usage_df_matches_direct_call() -> None:
    analytics = _toy_analytics()

    expected = build_flex_usage_metrics(_toy_df(), ROSTER_POSITIONS)
    pd.testing.assert_frame_equal(analytics.flex_usage_df, expected)


def test_flex_usage_df_uses_the_leagues_roster_positions() -> None:
    """Alpha starts two RBs against one dedicated RB slot, so the FLEX is
    RB-filled in both weeks (2 flex starts, share 1.0, rank 1). Dropping the
    FLEX slot from the league's list must empty the frame, proving
    ``roster_positions`` reaches the builder rather than a default.
    """
    frame = _toy_analytics().flex_usage_df
    alpha = frame.loc[frame["fantasy_team"] == "Alpha"]

    assert list(alpha["position"]) == ["RB"]
    assert int(alpha.iloc[0]["flex_starts"]) == 2
    assert alpha.iloc[0]["flex_start_share"] == pytest.approx(1.0)
    assert int(alpha.iloc[0]["flex_usage_rank"]) == 1

    no_flex = [slot for slot in ROSTER_POSITIONS if slot != "FLEX"]
    assert _toy_analytics(roster_positions=no_flex).flex_usage_df.empty


def test_start_sit_tendency_df_matches_direct_call() -> None:
    analytics = _toy_analytics()

    expected = build_start_sit_tendency_metrics(_toy_df(), ROSTER_POSITIONS)
    pd.testing.assert_frame_equal(analytics.start_sit_tendency_df, expected)


def test_start_sit_tendency_df_wraps_the_roster_efficiency_frame() -> None:
    """Every ``roster_efficiency_df`` column is carried through unchanged,
    plus the two per-week rates: roster 1's week 1 lineup has one wrong start
    (p3) and one wrong sit (p5) while its week 2 lineup is already optimal,
    so both season totals are 1 over 2 weeks played, i.e. 0.5 per week.
    """
    analytics = _toy_analytics()
    tendencies = analytics.start_sit_tendency_df
    efficiency = analytics.roster_efficiency_df

    for column in efficiency.columns:
        pd.testing.assert_series_equal(tendencies[column], efficiency[column])

    row = tendencies.loc[tendencies["roster_id"] == 1].iloc[0]
    assert int(row["weeks_played"]) == 2
    assert int(row["total_suboptimal_starts"]) == 1
    assert int(row["total_suboptimal_sits"]) == 1
    assert row["suboptimal_starts_per_week"] == pytest.approx(0.5)
    assert row["suboptimal_sits_per_week"] == pytest.approx(0.5)


def test_positional_preference_df_matches_direct_call() -> None:
    analytics = _toy_analytics()

    expected = build_positional_preference_metrics(_toy_df())
    pd.testing.assert_frame_equal(analytics.positional_preference_df, expected)


def test_positional_preference_df_matches_hand_arithmetic() -> None:
    """Alpha's WRs: 4 rostered weeks (p3, p5 x2), 2 started (p3) and 2
    benched (p5); 8 started player-weeks across the team-season, so the WR
    start share is 2/8 = 0.25.
    """
    frame = _toy_analytics().positional_preference_df
    alpha = frame.loc[frame["fantasy_team"] == "Alpha"].set_index("position")

    assert int(alpha.loc["WR", "rostered_player_weeks"]) == 4
    assert int(alpha.loc["WR", "started_weeks"]) == 2
    assert int(alpha.loc["WR", "bench_weeks"]) == 2
    assert alpha.loc["WR", "start_share"] == pytest.approx(0.25)


def test_tendency_frames_do_not_need_season_matchup_df() -> None:
    """All five FFA-070 frames must work on an instance built without the
    optional matchup frame, and must be identical when one is supplied.
    """
    without = _toy_analytics()
    with_matchups = _toy_matchup_analytics()

    assert without.season_matchup_df is None
    for attribute in (
        "roster_construction_df",
        "bench_allocation_df",
        "flex_usage_df",
        "start_sit_tendency_df",
        "positional_preference_df",
    ):
        frame = getattr(without, attribute)
        assert not frame.empty
        pd.testing.assert_frame_equal(frame, getattr(with_matchups, attribute))


# --- FFA-069 matchup contribution frames ----------------------------------


def test_player_contribution_df_matches_direct_call() -> None:
    analytics = _toy_matchup_analytics()

    expected = build_matchup_player_contributions(_toy_matchup_df(), _toy_df())
    pd.testing.assert_frame_equal(analytics.player_contribution_df, expected)


def test_player_contribution_df_matches_hand_arithmetic() -> None:
    """Week 1, roster 1: starters 20 + 10 + 5 + 8 = 43 against Bravo's 33, so
    the margin is +10 and p1's share is 20/43. p1 is the roster's best
    starter that week (rank 1). Bench p5 (12.0) never appears.
    """
    frame = _toy_matchup_analytics().player_contribution_df
    week_1 = frame.loc[(frame["week"] == 1) & (frame["roster_id"] == 1)]

    assert list(week_1["sleeper_player_id"]) == ["p1", "p2", "p4", "p3"]
    assert "p5" not in set(frame["sleeper_player_id"])

    top = week_1.iloc[0]
    assert int(top["contribution_rank"]) == 1
    assert top["fantasy_points"] == pytest.approx(20.0)
    assert top["team_points"] == pytest.approx(43.0)
    assert top["opponent_points"] == pytest.approx(33.0)
    assert top["margin"] == pytest.approx(10.0)
    assert top["result"] == "win"
    assert top["share_of_team_points"] == pytest.approx(20.0 / 43.0)


def test_positional_advantage_df_matches_direct_call() -> None:
    analytics = _toy_matchup_analytics()

    expected = build_positional_matchup_advantage(_toy_matchup_df(), _toy_df())
    pd.testing.assert_frame_equal(analytics.positional_advantage_df, expected)


def test_positional_advantage_df_matches_hand_arithmetic() -> None:
    """Week 1, roster 1 vs. roster 2: QB 20 - 15 = +5, RB (10+8) - 6 = +12,
    WR 5 - 9 = -4, TE 0 - 3 = -3 (a position Alpha never started, but Bravo
    did). The four sum to the week's +10 margin.
    """
    frame = _toy_matchup_analytics().positional_advantage_df
    week_1 = frame.loc[(frame["week"] == 1) & (frame["roster_id"] == 1)]
    advantage = week_1.set_index("position")["positional_advantage"]

    assert advantage.loc["QB"] == pytest.approx(5.0)
    assert advantage.loc["RB"] == pytest.approx(12.0)
    assert advantage.loc["WR"] == pytest.approx(-4.0)
    assert advantage.loc["TE"] == pytest.approx(-3.0)
    assert advantage.sum() == pytest.approx(10.0)
    assert int(week_1.set_index("position").loc["TE", "own_starters"]) == 0


def test_matchup_frames_raise_without_season_matchup_df() -> None:
    """The documented wiring error: no empty frame, no partial result."""
    analytics = _toy_analytics()

    with pytest.raises(ValueError, match="season_matchup_df"):
        analytics.player_contribution_df
    with pytest.raises(ValueError, match="season_matchup_df"):
        analytics.positional_advantage_df


def test_missing_season_matchup_df_does_not_break_construction() -> None:
    """The ``ValueError`` is raised on access, not at construction, so every
    other frame stays reachable on the same instance.
    """
    analytics = _toy_analytics()

    assert not analytics.player_season_df.empty
    assert not analytics.roster_efficiency_df.empty
    with pytest.raises(ValueError, match="season_matchup_df"):
        analytics.player_contribution_df


def test_empty_season_matchup_df_is_a_valid_input() -> None:
    """An empty matchup frame is data, not a missing argument: the builders'
    own empty-input behavior applies and nothing raises.
    """
    empty = pd.DataFrame(columns=SEASON_MATCHUP_COLUMNS)
    analytics = _toy_analytics(season_matchup_df=empty)

    assert analytics.player_contribution_df.empty
    assert analytics.positional_advantage_df.empty


def test_matchup_frames_reflect_a_phase_filtered_matchup_frame() -> None:
    """Filtering both inputs on the same week boundary is the caller's job;
    the FFA-069 frames must then cover only those weeks.
    """
    week_1_players = _toy_df().loc[lambda frame: frame["week"] < 2]
    week_1_matchups = _toy_matchup_df().loc[lambda frame: frame["week"] < 2]
    analytics = _toy_analytics(
        player_week_df=week_1_players, season_matchup_df=week_1_matchups
    )

    assert set(analytics.player_contribution_df["week"]) == {1}
    assert set(analytics.positional_advantage_df["week"]) == {1}
    pd.testing.assert_frame_equal(
        analytics.player_contribution_df,
        build_matchup_player_contributions(week_1_matchups, week_1_players),
    )


# --- ties and missing values ----------------------------------------------


def test_tied_players_share_a_value_rank() -> None:
    """Two players with identical production tie; the composition preserves
    FFA-068's standard competition ranking rather than splitting them.
    """
    rows = [
        _row(2025, 1, "p1", 10.0, "RB", True),
        _row(2025, 1, "p2", 10.0, "RB", True, roster_id=2, fantasy_team="Bravo"),
        _row(2025, 1, "p3", 4.0, "RB", True, roster_id=2, fantasy_team="Bravo"),
    ]
    analytics = _toy_analytics(player_week_df=_df(rows))

    value_df = analytics.player_value_df.set_index("sleeper_player_id")
    assert int(value_df.loc["p1", "value_rank"]) == 1
    assert int(value_df.loc["p2", "value_rank"]) == 1
    assert int(value_df.loc["p3", "value_rank"]) == 3


def test_missing_points_and_unresolved_position_do_not_raise() -> None:
    """A ``NaN`` ``fantasy_points``, an unresolvable position and a rostered
    player who never played are each handled by the composed builders;
    nothing here re-raises or special-cases them.
    """
    rows = [
        _row(2025, 1, "p1", 12.0, "QB", True),
        _row(2025, 1, "p2", None, "RB", True),
        _row(2025, 1, "p3", 7.0, None, False),
        # Rostered but never played: no stats, so no performance row.
        _row(2025, 1, "p4", 0.0, "WR", False, played=False),
    ]
    analytics = _toy_analytics(player_week_df=_df(rows))

    # p2's game has NaN points (skipped by FFA-065) and p4 never played, so
    # neither gets a player-season row; p3 does, with position None.
    assert set(analytics.player_season_df["sleeper_player_id"]) == {"p1", "p3"}
    # p3 has no resolvable position, so FFA-068 gives it no value row.
    assert set(analytics.player_value_df["sleeper_player_id"]) == {"p1"}
    # FFA-067 counts p2's NaN start as 0.0 rather than dropping the week.
    weekly = analytics.lineup_efficiency_df.iloc[0]
    assert weekly["actual_points"] == pytest.approx(12.0)


# --- phase filtering (caller filters first) --------------------------------


def test_phase_filtering_is_the_callers_job_and_changes_every_frame() -> None:
    """Constructing from a week-filtered fact table is the documented way to
    get a phase-specific view; the frames must reflect only those weeks.
    """
    regular_season_only = _toy_df().loc[lambda frame: frame["week"] < 2]
    analytics = _toy_analytics(player_week_df=regular_season_only)

    pd.testing.assert_frame_equal(
        analytics.player_season_df,
        build_player_performance_metrics(regular_season_only),
    )
    pd.testing.assert_frame_equal(
        analytics.lineup_efficiency_df,
        build_lineup_efficiency_metrics(regular_season_only, ROSTER_POSITIONS),
    )
    assert set(analytics.lineup_efficiency_df["week"]) == {1}
    # Every player played exactly one game in the filtered frame.
    assert set(analytics.player_season_df["games_played"]) == {1}


# --- empty input -----------------------------------------------------------


def test_empty_player_week_df_produces_empty_frames_everywhere() -> None:
    analytics = _toy_matchup_analytics(player_week_df=_df([]))

    assert analytics.player_weekly_df.empty
    assert analytics.player_season_df.empty
    assert analytics.position_summary_df.empty
    assert analytics.lineup_efficiency_df.empty
    assert analytics.roster_efficiency_df.empty
    assert analytics.player_value_df.empty
    assert analytics.position_scarcity_df.empty
    assert analytics.roster_construction_df.empty
    assert analytics.bench_allocation_df.empty
    assert analytics.flex_usage_df.empty
    assert analytics.start_sit_tendency_df.empty
    assert analytics.positional_preference_df.empty
    assert analytics.player_contribution_df.empty
    assert analytics.positional_advantage_df.empty


# --- build_player_analytics factory ---------------------------------------


def test_build_player_analytics_factory_matches_direct_construction() -> None:
    player_week_df = _toy_df()

    via_factory = build_player_analytics(player_week_df, ROSTER_POSITIONS, NUM_TEAMS)
    via_constructor = PlayerAnalytics(
        player_week_df=player_week_df,
        roster_positions=ROSTER_POSITIONS,
        num_teams=NUM_TEAMS,
    )

    assert isinstance(via_factory, PlayerAnalytics)
    pd.testing.assert_frame_equal(
        via_factory.player_season_df, via_constructor.player_season_df
    )
    pd.testing.assert_frame_equal(
        via_factory.player_value_df, via_constructor.player_value_df
    )
    pd.testing.assert_frame_equal(
        via_factory.roster_efficiency_df, via_constructor.roster_efficiency_df
    )
    pd.testing.assert_frame_equal(
        via_factory.positional_preference_df, via_constructor.positional_preference_df
    )


def test_build_player_analytics_factory_defaults_season_matchup_df_to_none() -> None:
    """The positional three-argument call every existing caller uses must keep
    working, leaving the FFA-069 frames unavailable rather than empty.
    """
    analytics = build_player_analytics(_toy_df(), ROSTER_POSITIONS, NUM_TEAMS)

    assert analytics.season_matchup_df is None
    assert not analytics.roster_construction_df.empty
    with pytest.raises(ValueError, match="season_matchup_df"):
        analytics.player_contribution_df


def test_build_player_analytics_factory_passes_through_season_matchup_df() -> None:
    season_matchup_df = _toy_matchup_df()
    analytics = build_player_analytics(
        _toy_df(),
        ROSTER_POSITIONS,
        NUM_TEAMS,
        season_matchup_df=season_matchup_df,
    )

    assert analytics.season_matchup_df is season_matchup_df
    pd.testing.assert_frame_equal(
        analytics.player_contribution_df,
        build_matchup_player_contributions(season_matchup_df, _toy_df()),
    )
    pd.testing.assert_frame_equal(
        analytics.positional_advantage_df,
        build_positional_matchup_advantage(season_matchup_df, _toy_df()),
    )


def test_build_player_analytics_factory_defaults_thresholds() -> None:
    analytics = build_player_analytics(_toy_df(), ROSTER_POSITIONS, NUM_TEAMS)

    assert analytics.player_boom_bust_threshold == 1.0
    assert analytics.position_boom_bust_threshold == 1.0
    pd.testing.assert_frame_equal(
        analytics.player_season_df, build_player_performance_metrics(_toy_df())
    )


def test_build_player_analytics_factory_passes_through_thresholds() -> None:
    analytics = build_player_analytics(
        _toy_df(),
        ROSTER_POSITIONS,
        NUM_TEAMS,
        player_boom_bust_threshold=0.5,
        position_boom_bust_threshold=2.0,
    )

    pd.testing.assert_frame_equal(
        analytics.player_season_df,
        build_player_performance_metrics(_toy_df(), boom_bust_threshold=0.5),
    )
    pd.testing.assert_frame_equal(
        analytics.position_summary_df,
        build_position_strength_metrics(_toy_df(), boom_bust_threshold=2.0),
    )

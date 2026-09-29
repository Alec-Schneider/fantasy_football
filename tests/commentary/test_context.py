"""Tests for the commentary context builders (FFA-090/FFA-091).

All tests operate on hand-built ``season_matchup_df``/``player_week_df``/
``rosters_df``/``teams_df`` inputs -- no HTTP calls, no fixtures with opaque
values -- so every score, streak, revenge-game flag, standings-movement, and
schedule-luck number can be verified by hand arithmetic in each test's
comments, per AGENTS.md's analytics-ticket requirement for a hand-checkable
toy example.

Shared toy season (used across most tests)
-------------------------------------------

Four rosters, two fixed pods, three weeks:

- Pod A: roster 1 vs roster 2 every week.
- Pod B: roster 3 vs roster 4 every week.

::

    week  pairing        points          winner
    1     1 vs 2          120 - 100       1
    1     3 vs 4           90 -  80       3
    2     1 vs 2          115 - 140       2
    2     3 vs 4           95 -  70       3
    3     1 vs 2          100 -  95       1
    3     3 vs 4           80 -  90       4

Entering week 3: roster 1 has W-L (won wk1, lost wk2) against roster 2 --
no active streak (a single result isn't a streak). Roster 3 has W-W against
roster 4 -- an active 2-game win streak -- and then *loses* week 3, so the
streak should be reported as active entering the week, and snapped by the
week-3 result; roster 4's week-3 win is also a revenge game (it lost their
most recent prior meeting, week 2).
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.analytics.league_analytics import LeagueAnalytics
from fantasy_analyzer.analytics.standings import build_standings
from fantasy_analyzer.commentary.context import (
    STREAK_MIN_LENGTH,
    build_league_week_context,
    build_matchup_context,
)
from fantasy_analyzer.league.settings import LeagueSettings
from fantasy_analyzer.league.snapshot import LeagueSnapshot
from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS
from fantasy_analyzer.players.player_week import PLAYER_WEEK_COLUMNS

# --------------------------------------------------------------------------
# Row / frame builders
# --------------------------------------------------------------------------

STAT_COLUMNS = ["receptions"]
PLAYER_WEEK_TEST_COLUMNS = PLAYER_WEEK_COLUMNS + STAT_COLUMNS + ["fantasy_points"]


def _matchup_row(
    roster_1_id: int,
    roster_2_id: int | None,
    points_1: float | None,
    points_2: float | None,
    winner: int | None,
    loser: int | None,
    week: int,
    matchup_id: int,
    is_tie: bool = False,
    is_playoff: bool = False,
    season: str = "2025",
    owner_1: str | None = None,
    owner_2: str | None = None,
) -> dict:
    margin = None
    point_differential = None
    if points_1 is not None and points_2 is not None:
        point_differential = points_1 - points_2
        margin = abs(point_differential)
    return {
        "season": season,
        "week": week,
        "is_playoff": is_playoff,
        "matchup_id": matchup_id,
        "roster_1_id": roster_1_id,
        "roster_2_id": roster_2_id,
        "owner_1": owner_1,
        "owner_2": owner_2,
        "points_1": points_1,
        "points_2": points_2,
        "winner": winner,
        "loser": loser,
        "is_tie": is_tie,
        "margin": margin,
        "point_differential": point_differential,
    }


def _matchup_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=SEASON_MATCHUP_COLUMNS)
    return pd.DataFrame(rows, columns=SEASON_MATCHUP_COLUMNS)


def _toy_season_matchup_df() -> pd.DataFrame:
    return _matchup_df(
        [
            _matchup_row(1, 2, 120, 100, 1, 2, week=1, matchup_id=11),
            _matchup_row(3, 4, 90, 80, 3, 4, week=1, matchup_id=12),
            _matchup_row(1, 2, 115, 140, 2, 1, week=2, matchup_id=21),
            _matchup_row(3, 4, 95, 70, 3, 4, week=2, matchup_id=22),
            _matchup_row(1, 2, 100, 95, 1, 2, week=3, matchup_id=31),
            _matchup_row(3, 4, 80, 90, 4, 3, week=3, matchup_id=32),
        ]
    )


def _teams_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "display_name": "Alice",
                "team_name": "Alice",
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "display_name": "Bob",
                "team_name": "Bob",
            },
            {
                "roster_id": 3,
                "owner_id": "u3",
                "display_name": "Cara",
                "team_name": "Cara",
            },
            {
                "roster_id": 4,
                "owner_id": "u4",
                "display_name": "Dan",
                "team_name": "Dan",
            },
        ]
    )


def _player_row(
    week: int,
    roster_id: int,
    sleeper_player_id: str,
    fantasy_points: float,
    position: str,
    started: bool,
    player_name: str,
) -> dict:
    return {
        "season": "2025",
        "week": week,
        "roster_id": roster_id,
        "fantasy_team": None,
        "sleeper_player_id": sleeper_player_id,
        "gsis_id": f"g-{sleeper_player_id}",
        "player_name": player_name,
        "position": position,
        "nfl_team": "SF",
        "started": started,
        "bench": not started,
        "receptions": 0.0,
        "fantasy_points": fantasy_points,
    }


def _player_week_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=PLAYER_WEEK_TEST_COLUMNS)
    frame = pd.DataFrame(rows, columns=PLAYER_WEEK_TEST_COLUMNS)
    for column in ("player_name", "position", "sleeper_player_id", "fantasy_team"):
        frame[column] = pd.Series(frame[column].tolist(), dtype=object)
    return frame


def _week3_player_week_df() -> pd.DataFrame:
    """Player-level detail for pod A (rosters 1, 2) at week 3 only.

    Roster 1 (``roster_positions=["RB", "RB", "BN"]``): started P1a (30
    pts) and P1b (20 pts), actual = 50; bench P1c scores 45, higher than
    P1b's 20, so the optimal legal lineup is P1a + P1c = 75, leaving 25
    points on the bench.

    Roster 2: started Q1 and Q2, tied at 25 points each (both rank 1, per
    ``contribution_rank``'s standard-competition-ranking / ascending-
    ``sleeper_player_id`` tie-break), actual = 50; bench Q3 scores only 10,
    so the optimal lineup already matches the actual lineup (0 points left
    on the bench).
    """
    return _player_week_df(
        [
            _player_row(3, 1, "p1a", 30.0, "RB", True, "P1a"),
            _player_row(3, 1, "p1b", 20.0, "RB", True, "P1b"),
            _player_row(3, 1, "p1c", 45.0, "RB", False, "P1c"),
            _player_row(3, 2, "q1", 25.0, "RB", True, "Q1"),
            _player_row(3, 2, "q2", 25.0, "RB", True, "Q2"),
            _player_row(3, 2, "q3", 10.0, "RB", False, "Q3"),
        ]
    )


def _snapshot(roster_positions: list[str] | None = None) -> LeagueSnapshot:
    league = LeagueSettings(
        league_id="league-1",
        name="Toy League",
        season="2025",
        season_type="regular",
        status="in_season",
        total_rosters=4,
        scoring_settings={},
        roster_positions=roster_positions or [],
    )
    return LeagueSnapshot(
        league=league,
        teams_df=_teams_df(),
        users_df=pd.DataFrame(columns=["user_id", "display_name", "team_name"]),
        rosters_df=pd.DataFrame(
            columns=[
                "roster_id",
                "owner_id",
                "wins",
                "losses",
                "ties",
                "fpts",
                "fpts_against",
                "players",
                "starters",
            ]
        ),
        players_df=pd.DataFrame(),
        scoring_settings={},
        roster_positions=roster_positions or [],
    )


# --------------------------------------------------------------------------
# build_matchup_context
# --------------------------------------------------------------------------


def test_build_matchup_context_empty_season_matchup_df_returns_empty_list() -> None:
    snapshot = _snapshot()
    contexts = build_matchup_context(
        snapshot, _matchup_df([]), _player_week_df([]), week=3
    )
    assert contexts == []


def test_build_matchup_context_excludes_bye_rows() -> None:
    """A bye row (``roster_2_id`` is ``None``) is not a pairing and is skipped."""
    season_matchup_df = _matchup_df(
        [
            _matchup_row(1, 2, 100, 90, 1, 2, week=1, matchup_id=1),
            _matchup_row(3, None, 50, None, None, None, week=1, matchup_id=2),
        ]
    )
    contexts = build_matchup_context(
        _snapshot(), season_matchup_df, _player_week_df([]), week=1
    )
    assert len(contexts) == 1
    assert contexts[0].team_1.roster_id == 1
    assert contexts[0].team_2.roster_id == 2


def test_build_matchup_context_no_player_week_data_leaves_player_fields_empty() -> None:
    """Missing ``player_week_df`` rows for a roster-week: no crash, empty/None."""
    contexts = build_matchup_context(
        _snapshot(roster_positions=["RB", "BN"]),
        _toy_season_matchup_df(),
        _player_week_df([]),
        week=1,
    )
    pod_a = next(c for c in contexts if c.team_1.roster_id == 1)
    assert pod_a.team_1.top_contributors == []
    assert pod_a.team_1.points_left_on_bench is None
    assert pod_a.team_1.top_bench_scorer is None
    # All-play is independent of player-level data -- still populated.
    assert pod_a.team_1.all_play is not None


def test_build_matchup_context_toy_week3_hand_checked() -> None:
    snapshot = _snapshot(roster_positions=["RB", "RB", "BN"])
    contexts = build_matchup_context(
        snapshot,
        _toy_season_matchup_df(),
        _week3_player_week_df(),
        week=3,
    )
    assert len(contexts) == 2

    pod_a = next(c for c in contexts if c.team_1.roster_id == 1)
    pod_b = next(c for c in contexts if c.team_1.roster_id == 3)

    # -- Final score / margin --------------------------------------------
    assert pod_a.team_1.points == pytest.approx(100.0)
    assert pod_a.team_2.points == pytest.approx(95.0)
    assert pod_a.margin == pytest.approx(5.0)
    assert pod_a.winner_roster_id == 1
    assert pod_a.loser_roster_id == 2
    assert pod_a.is_tie is False
    # No projection provider was supplied.
    assert pod_a.team_1.projected_points is None

    # -- Top contributors (roster 1: 30, 20 -- both started) --------------
    assert [c.player_name for c in pod_a.team_1.top_contributors] == ["P1a", "P1b"]
    assert pod_a.team_1.top_contributors[0].fantasy_points == pytest.approx(30.0)
    assert pod_a.team_1.top_contributors[0].contribution_rank == 1
    assert pod_a.team_1.top_contributors[0].share_of_team_points == pytest.approx(
        30.0 / 100.0
    )
    assert pod_a.team_1.top_contributors[1].contribution_rank == 2

    # Roster 2: Q1/Q2 tied at 25 points -- both rank 1, Q1 first (ascending
    # sleeper_player_id tie-break).
    assert [c.player_name for c in pod_a.team_2.top_contributors] == ["Q1", "Q2"]
    assert pod_a.team_2.top_contributors[0].contribution_rank == 1
    assert pod_a.team_2.top_contributors[1].contribution_rank == 1
    assert pod_a.team_2.top_contributors[0].share_of_team_points == pytest.approx(
        25.0 / 95.0
    )

    # -- Bench points left on the table ------------------------------------
    # Roster 1: actual 30 + 20 = 50, optimal 30 + 45 (bench P1c) = 75.
    assert pod_a.team_1.points_left_on_bench == pytest.approx(25.0)
    assert pod_a.team_1.top_bench_scorer.player_name == "P1c"
    assert pod_a.team_1.top_bench_scorer.fantasy_points == pytest.approx(45.0)
    # Roster 2: bench Q3 (10) never beats a starter -- nothing left on the table.
    assert pod_a.team_2.points_left_on_bench == pytest.approx(0.0)
    assert pod_a.team_2.top_bench_scorer.player_name == "Q3"

    # -- All-play record for week 3 (scores: r1=100, r2=95, r4=90, r3=80) --
    assert pod_a.team_1.all_play.wins == 3
    assert pod_a.team_1.all_play.losses == 0
    assert pod_a.team_1.all_play.rank == 1
    assert pod_a.team_2.all_play.wins == 2
    assert pod_a.team_2.all_play.losses == 1
    assert pod_a.team_2.all_play.rank == 2

    # -- Head-to-head entering week 3: 1 meeting each way, split 1-1 -------
    assert pod_a.head_to_head.meetings == 2
    assert pod_a.head_to_head.roster_1_wins == 1
    assert pod_a.head_to_head.roster_1_losses == 1
    assert pod_a.head_to_head.ties == 0
    assert pod_a.head_to_head.last_meeting_week == 2
    assert pod_a.head_to_head.last_meeting_winner_roster_id == 2

    # -- Streak: a single result isn't a streak (length < STREAK_MIN_LENGTH) --
    assert STREAK_MIN_LENGTH == 2
    assert pod_a.streak.holder_roster_id is None
    assert pod_a.streak.length == 0
    assert pod_a.streak.snapped_this_week is False
    # Roster 1 lost the most recent prior meeting (week 2) and won this
    # week -- a revenge game.
    assert pod_a.streak.is_revenge_game is True

    # -- Pod B: roster 3 had a 2-game win streak snapped by roster 4's win --
    assert pod_b.head_to_head.meetings == 2
    assert pod_b.head_to_head.roster_1_wins == 2
    assert pod_b.head_to_head.roster_1_losses == 0
    assert pod_b.winner_roster_id == 4
    assert pod_b.streak.holder_roster_id == 3
    assert pod_b.streak.length == 2
    assert pod_b.streak.snapped_this_week is True
    # Roster 4 lost the most recent prior meeting (week 2) and won this
    # week -- also a revenge game.
    assert pod_b.streak.is_revenge_game is True
    # No player_week_df rows were supplied for pod B.
    assert pod_b.team_1.top_contributors == []
    assert pod_b.team_1.points_left_on_bench is None


def test_build_matchup_context_first_meeting_has_no_history_or_streak() -> None:
    """Two rosters with no meeting before ``week`` get an empty head-to-head."""
    season_matchup_df = _matchup_df(
        [_matchup_row(5, 6, 80, 70, 5, 6, week=1, matchup_id=1)]
    )
    contexts = build_matchup_context(
        _snapshot(), season_matchup_df, _player_week_df([]), week=1
    )
    assert len(contexts) == 1
    context = contexts[0]
    assert context.head_to_head.meetings == 0
    assert context.head_to_head.roster_1_wins == 0
    assert context.head_to_head.last_meeting_week is None
    assert context.streak.holder_roster_id is None
    assert context.streak.length == 0
    assert context.streak.snapped_this_week is False
    assert context.streak.is_revenge_game is False


# --------------------------------------------------------------------------
# build_league_week_context
# --------------------------------------------------------------------------


def _rosters_df(rows: list[dict]) -> pd.DataFrame:
    columns = [
        "roster_id",
        "owner_id",
        "wins",
        "losses",
        "ties",
        "fpts",
        "fpts_against",
        "players",
        "starters",
    ]
    return pd.DataFrame(rows, columns=columns)


def _standings_after_week3() -> pd.DataFrame:
    # r1: 2-1-0, fpts 335 (120+115+100), against 335 (100+140+95)
    # r2: 1-2-0, fpts 335 (100+140+95), against 335 (120+115+100)
    # r3: 2-1-0, fpts 265 (90+95+80), against 240 (80+70+90)
    # r4: 1-2-0, fpts 240 (80+70+90), against 265 (90+95+80)
    rosters_df = _rosters_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "wins": 2,
                "losses": 1,
                "ties": 0,
                "fpts": 335.0,
                "fpts_against": 335.0,
                "players": [],
                "starters": [],
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "wins": 1,
                "losses": 2,
                "ties": 0,
                "fpts": 335.0,
                "fpts_against": 335.0,
                "players": [],
                "starters": [],
            },
            {
                "roster_id": 3,
                "owner_id": "u3",
                "wins": 2,
                "losses": 1,
                "ties": 0,
                "fpts": 265.0,
                "fpts_against": 240.0,
                "players": [],
                "starters": [],
            },
            {
                "roster_id": 4,
                "owner_id": "u4",
                "wins": 1,
                "losses": 2,
                "ties": 0,
                "fpts": 240.0,
                "fpts_against": 265.0,
                "players": [],
                "starters": [],
            },
        ]
    )
    return build_standings(rosters_df, _teams_df())


def _standings_after_week2() -> pd.DataFrame:
    # r1: 1-1-0, fpts 235 (120+115), against 240 (100+140)
    # r2: 1-1-0, fpts 240 (100+140), against 235 (120+115)
    # r3: 2-0-0, fpts 185 (90+95), against 150 (80+70)
    # r4: 0-2-0, fpts 150 (80+70), against 185 (90+95)
    rosters_df = _rosters_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "wins": 1,
                "losses": 1,
                "ties": 0,
                "fpts": 235.0,
                "fpts_against": 240.0,
                "players": [],
                "starters": [],
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "wins": 1,
                "losses": 1,
                "ties": 0,
                "fpts": 240.0,
                "fpts_against": 235.0,
                "players": [],
                "starters": [],
            },
            {
                "roster_id": 3,
                "owner_id": "u3",
                "wins": 2,
                "losses": 0,
                "ties": 0,
                "fpts": 185.0,
                "fpts_against": 150.0,
                "players": [],
                "starters": [],
            },
            {
                "roster_id": 4,
                "owner_id": "u4",
                "wins": 0,
                "losses": 2,
                "ties": 0,
                "fpts": 150.0,
                "fpts_against": 185.0,
                "players": [],
                "starters": [],
            },
        ]
    )
    return build_standings(rosters_df, _teams_df())


def test_build_league_week_context_empty_analytics_returns_empty_context() -> None:
    analytics = LeagueAnalytics(season_matchup_df=_matchup_df([]), teams_df=_teams_df())
    context = build_league_week_context(
        _snapshot(), analytics, standings_df=pd.DataFrame(), week=1
    )
    assert context.standings == []
    assert context.power_ranking_deltas == []
    assert context.weekly_leaderboard.highest_score is None
    assert context.schedule_luck_outliers.luckiest is None


def test_build_league_week_context_toy_week3_hand_checked() -> None:
    analytics = LeagueAnalytics(
        season_matchup_df=_toy_season_matchup_df(), teams_df=_teams_df()
    )
    context = build_league_week_context(
        _snapshot(),
        analytics,
        standings_df=_standings_after_week3(),
        week=3,
        previous_standings_df=_standings_after_week2(),
    )

    assert context.season == "2025"
    assert context.week == 3

    # -- Standings + movement (hand-computed in the module docstring above) --
    by_roster = {row.roster_id: row for row in context.standings}
    assert by_roster[1].rank == 1
    assert by_roster[3].rank == 2
    assert by_roster[2].rank == 3
    assert by_roster[4].rank == 4
    # Previous-week ranks: r3=1, r2=2, r1=3, r4=4.
    assert by_roster[1].previous_rank == 3
    assert by_roster[1].rank_change == 2  # moved up two spots
    assert by_roster[2].previous_rank == 2
    assert by_roster[2].rank_change == -1
    assert by_roster[3].previous_rank == 1
    assert by_roster[3].rank_change == -1
    assert by_roster[4].previous_rank == 4
    assert by_roster[4].rank_change == 0

    # -- Weekly scoring leaderboard (week 3 scores: 100, 95, 80, 90) --------
    assert context.weekly_leaderboard.highest_score.roster_id == 1
    assert context.weekly_leaderboard.highest_score.points == pytest.approx(100.0)
    assert context.weekly_leaderboard.lowest_score.roster_id == 3
    assert context.weekly_leaderboard.lowest_score.points == pytest.approx(80.0)
    # Pod A margin = 5, pod B margin = 10.
    assert context.weekly_leaderboard.biggest_blowout.roster_1_id == 3
    assert context.weekly_leaderboard.biggest_blowout.margin == pytest.approx(10.0)
    assert context.weekly_leaderboard.closest_game.roster_1_id == 1
    assert context.weekly_leaderboard.closest_game.margin == pytest.approx(5.0)

    # -- Schedule luck outliers through week 3 (hand-computed) --------------
    # all_play_win_pct: r1=8/9, r2=7/9, r3=2/9, r4=1/9 (order each week is
    # r1 > r2 > (r3 or r4) > (r4 or r3), see module docstring).
    # schedule_luck = wins - all_play_win_pct * games_played:
    #   r1 = 2 - (8/9)*3 = -0.6667 (unlucky)
    #   r2 = 1 - (7/9)*3 = -1.3333 (most unlucky)
    #   r3 = 2 - (2/9)*3 = +1.3333 (luckiest)
    #   r4 = 1 - (1/9)*3 = +0.6667 (lucky)
    assert context.schedule_luck_outliers.luckiest.roster_id == 3
    assert context.schedule_luck_outliers.luckiest.schedule_luck == pytest.approx(
        4.0 / 3.0
    )
    assert context.schedule_luck_outliers.unluckiest.roster_id == 2
    assert context.schedule_luck_outliers.unluckiest.schedule_luck == pytest.approx(
        -4.0 / 3.0
    )

    # -- Power ranking deltas: structural checks (z-score math is already
    # covered by test_power_rankings.py; this ticket only composes it) -----
    assert len(context.power_ranking_deltas) == 4
    ranks = sorted(delta.power_rank for delta in context.power_ranking_deltas)
    assert ranks == [1, 2, 3, 4]
    for delta in context.power_ranking_deltas:
        assert delta.previous_power_rank is not None
        assert delta.power_score_delta is not None


def test_build_league_week_context_week1_has_no_previous_power_rankings() -> None:
    analytics = LeagueAnalytics(
        season_matchup_df=_toy_season_matchup_df(), teams_df=_teams_df()
    )
    context = build_league_week_context(
        _snapshot(),
        analytics,
        standings_df=_standings_after_week3(),
        week=1,
    )
    assert len(context.power_ranking_deltas) == 4
    for delta in context.power_ranking_deltas:
        assert delta.previous_power_rank is None
        assert delta.power_score_delta is None
    # No previous_standings_df was supplied either.
    for movement in context.standings:
        assert movement.previous_rank is None
        assert movement.rank_change is None

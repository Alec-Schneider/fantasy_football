"""Tests for opponent and schedule context (FFA-099).

Hand-built schedules and scored player-weeks only -- no nflverse or
Sleeper access -- so every multiplier below is checkable by the arithmetic
in the module docstring's worked example.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from fantasy_analyzer.players.opponent_strength import (
    DEFENSE_VS_POSITION_COLUMNS,
    MATCHUP_CONTEXT_COLUMNS,
    TEAM_WEEK_SCHEDULE_COLUMNS,
    add_matchup_context,
    build_defense_vs_position,
    bye_weeks,
    completed_nfl_weeks,
    normalize_schedule,
    normalize_team,
    started_nfl_teams,
)

# A two-team, three-week toy league. Each team has one bye.
GAMES = pd.DataFrame(
    [
        {
            "season": 2026,
            "game_type": "REG",
            "week": 1,
            "home_team": "SF",
            "away_team": "LA",
            "total_line": 44.0,
            "spread_line": 6.0,
        },
        {
            "season": 2026,
            "game_type": "REG",
            "week": 2,
            "home_team": "LA",
            "away_team": "SF",
            "total_line": 50.0,
            "spread_line": -3.0,
        },
        {
            "season": 2026,
            "game_type": "POST",
            "week": 3,
            "home_team": "SF",
            "away_team": "LA",
            "total_line": 40.0,
            "spread_line": 1.0,
        },
    ]
)


def _week(player_id, season, week, position, points, team, opponent):
    return {
        "season": season,
        "week": week,
        "player_id": player_id,
        "player_name": player_id,
        "position": position,
        "fantasy_points": points,
        "team": team,
        "opponent_team": opponent,
    }


# --------------------------------------------------------------------------
# normalize_team / normalize_schedule
# --------------------------------------------------------------------------


def test_normalize_team_maps_only_the_disagreements() -> None:
    assert normalize_team("LAR") == "LA"
    assert normalize_team("OAK") == "LV"
    assert normalize_team("KC") == "KC"
    assert normalize_team(None) is None
    assert normalize_team("") is None
    assert normalize_team(float("nan")) is None


def test_normalize_schedule_splits_games_and_drops_postseason() -> None:
    schedule = normalize_schedule(GAMES, 2026)

    assert list(schedule.columns) == TEAM_WEEK_SCHEDULE_COLUMNS
    # Two REG games -> four team-weeks; the POST game is excluded.
    assert len(schedule) == 4
    assert set(schedule["week"]) == {1, 2}


def test_implied_team_total_uses_the_home_side_spread_convention() -> None:
    """spread_line is stated from the home team's perspective.

    Week 1: SF at home, total 44.0, spread +6.0 -> SF implied
    ``44/2 + 6/2 = 25.0``, LA implied ``44/2 - 6/2 = 19.0``. The two must
    sum to the total.
    """
    schedule = normalize_schedule(GAMES, 2026)
    week1 = schedule[schedule["week"] == 1].set_index("team")

    assert week1.loc["SF", "implied_team_total"] == pytest.approx(25.0)
    assert week1.loc["LA", "implied_team_total"] == pytest.approx(19.0)
    assert week1.loc["SF", "is_home"] is True or bool(week1.loc["SF", "is_home"])
    assert week1.loc["SF", "implied_team_total"] + week1.loc[
        "LA", "implied_team_total"
    ] == pytest.approx(44.0)


def test_implied_team_total_when_the_away_team_is_favored() -> None:
    """Week 2: LA home, spread -3.0 means the *away* team is favored."""
    schedule = normalize_schedule(GAMES, 2026)
    week2 = schedule[schedule["week"] == 2].set_index("team")

    assert week2.loc["LA", "implied_team_total"] == pytest.approx(23.5)
    assert week2.loc["SF", "implied_team_total"] == pytest.approx(26.5)


def test_normalize_schedule_empty_and_missing_season() -> None:
    assert normalize_schedule(pd.DataFrame(), 2026).empty
    assert normalize_schedule(GAMES, 1999).empty
    assert list(normalize_schedule(GAMES, 1999).columns) == TEAM_WEEK_SCHEDULE_COLUMNS


def test_bye_weeks_from_missing_weeks() -> None:
    """Each team plays weeks 1 and 2, so week 3 is the bye in a 3-week season."""
    schedule = normalize_schedule(GAMES, 2026)
    assert bye_weeks(schedule, season_end_week=3) == {"SF": 3, "LA": 3}
    # No missing week inside the window -> no bye.
    assert bye_weeks(schedule, season_end_week=2) == {"SF": None, "LA": None}
    assert bye_weeks(pd.DataFrame(), season_end_week=3) == {}


# --------------------------------------------------------------------------
# completed_nfl_weeks (FFA-108)
# --------------------------------------------------------------------------


def _scored_week(week, games, scored, season=2026, game_type="REG"):
    """``games`` rows for ``week``, of which the first ``scored`` have scores."""
    return [
        {
            "season": season,
            "game_type": game_type,
            "week": week,
            "home_team": f"H{index}",
            "away_team": f"A{index}",
            "home_score": 20.0 if index < scored else float("nan"),
            "away_score": 17.0 if index < scored else float("nan"),
        }
        for index in range(games)
    ]


def test_completed_nfl_weeks_requires_every_game_scored() -> None:
    """The 2026-09-21 case: week 2 had 15 of 16 games final before MNF.

    Week 1 is fully scored, week 2 is missing only its Monday night game,
    week 3 has not started. Only week 1 is complete.
    """
    schedule = pd.DataFrame(
        _scored_week(1, 16, 16) + _scored_week(2, 16, 15) + _scored_week(3, 16, 0)
    )
    assert completed_nfl_weeks(schedule, 2026) == [1]


def test_completed_nfl_weeks_once_monday_night_lands() -> None:
    schedule = pd.DataFrame(
        _scored_week(1, 16, 16) + _scored_week(2, 16, 16) + _scored_week(3, 16, 0)
    )
    assert completed_nfl_weeks(schedule, 2026) == [1, 2]


def test_completed_nfl_weeks_needs_both_scores() -> None:
    """A half-written row (home score only) is not a final."""
    rows = _scored_week(1, 2, 2)
    rows[1]["away_score"] = None
    assert completed_nfl_weeks(pd.DataFrame(rows), 2026) == []


def test_completed_nfl_weeks_scopes_to_regular_season_and_season() -> None:
    schedule = pd.DataFrame(
        _scored_week(1, 2, 2)
        + _scored_week(19, 2, 2, game_type="WC")
        + _scored_week(2, 2, 2, season=2025)
    )
    assert completed_nfl_weeks(schedule, 2026) == [1]
    assert completed_nfl_weeks(schedule, 2025) == [2]
    assert completed_nfl_weeks(schedule, 1999) == []


def test_completed_nfl_weeks_empty_or_scoreless_input() -> None:
    assert completed_nfl_weeks(pd.DataFrame(), 2026) == []
    # normalize_schedule's output has no scores; it cannot answer this.
    assert completed_nfl_weeks(normalize_schedule(GAMES, 2026), 2026) == []


# --------------------------------------------------------------------------
# build_defense_vs_position
# --------------------------------------------------------------------------


# The module docstring's worked example: D1 allows 20 and 40 to WRs, D2
# allows 10 and 10. League mean 20.0; raw multipliers 1.5 and 0.5.
DVP_WEEKS = pd.DataFrame(
    [
        _week("w1", 2026, 1, "WR", 20.0, "A", "D1"),
        _week("w1", 2026, 2, "WR", 40.0, "A", "D1"),
        _week("w2", 2026, 1, "WR", 10.0, "B", "D2"),
        _week("w2", 2026, 2, "WR", 10.0, "B", "D2"),
    ]
)


def test_defense_vs_position_worked_example() -> None:
    result = build_defense_vs_position(DVP_WEEKS, 2026, 2).set_index("defense")

    assert list(result.reset_index().columns) == DEFENSE_VS_POSITION_COLUMNS
    assert result.loc["D1", "points_allowed_per_game"] == pytest.approx(30.0)
    assert result.loc["D2", "points_allowed_per_game"] == pytest.approx(10.0)
    assert result.loc["D1", "league_mean_points_allowed"] == pytest.approx(20.0)
    assert result.loc["D1", "raw_multiplier"] == pytest.approx(1.5)
    assert result.loc["D2", "raw_multiplier"] == pytest.approx(0.5)

    # Shrunk at k = 6 with n = 2: (2 * 1.5 + 6) / 8 and (2 * 0.5 + 6) / 8.
    assert result.loc["D1", "dvp_multiplier"] == pytest.approx(1.125)
    assert result.loc["D2", "dvp_multiplier"] == pytest.approx(0.875)


def test_defense_vs_position_shrinkage_pulls_toward_one() -> None:
    """More games means more of the raw signal survives."""
    light = build_defense_vs_position(DVP_WEEKS, 2026, 2).set_index("defense")
    none = build_defense_vs_position(DVP_WEEKS, 2026, 2, shrinkage_games=0).set_index(
        "defense"
    )
    heavy = build_defense_vs_position(
        DVP_WEEKS, 2026, 2, shrinkage_games=100
    ).set_index("defense")

    assert none.loc["D1", "dvp_multiplier"] == pytest.approx(1.5)
    assert heavy.loc["D1", "dvp_multiplier"] == pytest.approx((2 * 1.5 + 100) / 102)
    assert 1.0 < light.loc["D1", "dvp_multiplier"] < none.loc["D1", "dvp_multiplier"]


def test_defense_vs_position_sums_a_position_group_within_a_week() -> None:
    """Two WRs against the same defense in one week are one week's allowance."""
    weeks = pd.DataFrame(
        [
            _week("w1", 2026, 1, "WR", 12.0, "A", "D1"),
            _week("w2", 2026, 1, "WR", 8.0, "A", "D1"),
            _week("w3", 2026, 1, "WR", 20.0, "B", "D2"),
        ]
    )
    result = build_defense_vs_position(weeks, 2026, 1).set_index("defense")
    assert result.loc["D1", "games"] == 1
    assert result.loc["D1", "points_allowed_per_game"] == pytest.approx(20.0)
    assert result.loc["D1", "raw_multiplier"] == pytest.approx(1.0)


def test_defense_vs_position_ignores_rows_with_no_opponent() -> None:
    """Future weeks carry no opponent_team and must not be attributed."""
    weeks = pd.DataFrame(
        [
            _week("w1", 2026, 1, "WR", 20.0, "A", "D1"),
            _week("w1", 2026, 2, "WR", 999.0, "A", None),
        ]
    )
    result = build_defense_vs_position(weeks, 2026, 2).set_index("defense")
    assert result.loc["D1", "games"] == 1
    assert result.loc["D1", "points_allowed_per_game"] == pytest.approx(20.0)


def test_defense_vs_position_respects_the_week_window_and_season() -> None:
    result = build_defense_vs_position(DVP_WEEKS, 2026, 1).set_index("defense")
    assert result.loc["D1", "games"] == 1
    assert result.loc["D1", "points_allowed_per_game"] == pytest.approx(20.0)
    assert build_defense_vs_position(DVP_WEEKS, 2025, 2).empty


def test_defense_vs_position_edge_cases() -> None:
    assert build_defense_vs_position(pd.DataFrame(), 2026, 2).empty
    # No opponent_team column at all (an older provider).
    no_opponent = DVP_WEEKS.drop(columns=["opponent_team"])
    assert build_defense_vs_position(no_opponent, 2026, 2).empty
    with pytest.raises(ValueError, match="shrinkage_games"):
        build_defense_vs_position(DVP_WEEKS, 2026, 2, shrinkage_games=-1)


# --------------------------------------------------------------------------
# add_matchup_context
# --------------------------------------------------------------------------


RANKINGS = pd.DataFrame(
    [
        {"player_id": "1", "team": "SF", "position": "WR", "projected_ppg": 10.0},
        {"player_id": "2", "team": "LAR", "position": "WR", "projected_ppg": 8.0},
        {"player_id": "3", "team": None, "position": "WR", "projected_ppg": 5.0},
        {
            "player_id": "4",
            "team": "SF",
            "position": "WR",
            "projected_ppg": float("nan"),
        },
    ]
)

# SF's week-2 opponent is LA; give LA a soft WR defense and SF a tough one.
DVP = pd.DataFrame(
    [
        {
            "defense": "LA",
            "position": "WR",
            "games": 1,
            "points_allowed_per_game": 30.0,
            "league_mean_points_allowed": 20.0,
            "raw_multiplier": 1.5,
            "dvp_multiplier": 1.2,
        },
        {
            "defense": "SF",
            "position": "WR",
            "games": 1,
            "points_allowed_per_game": 10.0,
            "league_mean_points_allowed": 20.0,
            "raw_multiplier": 0.5,
            "dvp_multiplier": 0.8,
        },
    ]
)


def test_matchup_context_applies_the_opponent_multiplier() -> None:
    schedule = normalize_schedule(GAMES, 2026)
    result = add_matchup_context(
        RANKINGS, schedule, DVP, week=1, season_end_week=2
    ).set_index("player_id")

    assert set(MATCHUP_CONTEXT_COLUMNS).issubset(result.reset_index().columns)

    # SF plays at LA in week 2; LA's WR multiplier is 1.2.
    assert result.loc["1", "week_opponent"] == "LA"
    assert result.loc["1", "week_is_home"] is False
    assert result.loc["1", "week_dvp_multiplier"] == pytest.approx(1.2)
    assert result.loc["1", "matchup_adjusted_ppg"] == pytest.approx(12.0)
    assert result.loc["1", "week_implied_team_total"] == pytest.approx(26.5)

    # LAR is normalized to LA, which hosts SF; SF's WR multiplier is 0.8.
    assert result.loc["2", "nfl_team"] == "LA"
    assert result.loc["2", "week_opponent"] == "SF"
    assert result.loc["2", "matchup_adjusted_ppg"] == pytest.approx(6.4)


def test_matchup_context_never_overwrites_the_projection() -> None:
    schedule = normalize_schedule(GAMES, 2026)
    result = add_matchup_context(RANKINGS, schedule, DVP, week=1, season_end_week=2)
    pd.testing.assert_series_equal(
        result["projected_ppg"], RANKINGS["projected_ppg"], check_names=False
    )


def test_matchup_context_handles_no_team_and_no_projection() -> None:
    schedule = normalize_schedule(GAMES, 2026)
    result = add_matchup_context(
        RANKINGS, schedule, DVP, week=1, season_end_week=2
    ).set_index("player_id")

    # Unsigned player: no fabricated matchup.
    assert result.loc["3", "nfl_team"] is None
    assert result.loc["3", "week_opponent"] is None
    assert pd.isna(result.loc["3", "matchup_adjusted_ppg"])

    # Real team, no projection: the matchup is known, the adjusted ppg is not.
    assert result.loc["4", "week_opponent"] == "LA"
    assert result.loc["4", "week_dvp_multiplier"] == pytest.approx(1.2)
    assert pd.isna(result.loc["4", "matchup_adjusted_ppg"])


def test_matchup_context_bye_week_yields_no_opponent() -> None:
    """Week 3 is both teams' bye, so nobody has a week-3 opponent."""
    schedule = normalize_schedule(GAMES, 2026)
    result = add_matchup_context(
        RANKINGS, schedule, DVP, week=2, season_end_week=3
    ).set_index("player_id")

    assert result.loc["1", "week_opponent"] is None
    assert pd.isna(result.loc["1", "matchup_adjusted_ppg"])
    assert result.loc["1", "bye_week"] == 3
    # Nothing left on the schedule after week 2.
    assert result.loc["1", "remaining_games_scheduled"] == pytest.approx(0.0)
    assert result.loc["1", "schedule_adjusted_ros_points"] == pytest.approx(0.0)


def test_remaining_games_is_bye_aware() -> None:
    """The bye-blind ``remaining_games`` overstatement is corrected here.

    From week 0, weeks 1 and 2 have games but week 3 is a bye, so a
    rest-of-season window of 3 weeks contains only 2 games.
    """
    schedule = normalize_schedule(GAMES, 2026)
    result = add_matchup_context(
        RANKINGS, schedule, DVP, week=0, season_end_week=3
    ).set_index("player_id")

    assert result.loc["1", "remaining_games_scheduled"] == pytest.approx(2.0)
    # SF faces LA twice (weeks 1 and 2), so the mean multiplier is LA's 1.2.
    assert result.loc["1", "remaining_schedule_multiplier"] == pytest.approx(1.2)
    assert result.loc["1", "schedule_adjusted_ros_points"] == pytest.approx(
        10.0 * 1.2 * 2
    )


def test_matchup_context_with_empty_dvp_is_a_no_op_multiplier() -> None:
    schedule = normalize_schedule(GAMES, 2026)
    empty_dvp = pd.DataFrame(columns=DEFENSE_VS_POSITION_COLUMNS)
    result = add_matchup_context(
        RANKINGS, schedule, empty_dvp, week=1, season_end_week=2
    ).set_index("player_id")

    assert result.loc["1", "week_dvp_multiplier"] == pytest.approx(1.0)
    assert result.loc["1", "matchup_adjusted_ppg"] == pytest.approx(10.0)


def test_matchup_context_empty_inputs() -> None:
    empty = add_matchup_context(
        RANKINGS.iloc[0:0],
        normalize_schedule(GAMES, 2026),
        DVP,
        week=1,
        season_end_week=2,
    )
    assert empty.empty
    assert set(MATCHUP_CONTEXT_COLUMNS).issubset(empty.columns)

    no_schedule = add_matchup_context(
        RANKINGS, pd.DataFrame(), DVP, week=1, season_end_week=2
    )
    assert len(no_schedule) == len(RANKINGS)
    assert no_schedule["week_opponent"].isna().all()


# --------------------------------------------------------------------------
# started_nfl_teams -- game locks
# --------------------------------------------------------------------------


def _game(week, home, away, gameday, gametime, scored=False, game_type="REG"):
    return {
        "season": 2026,
        "game_type": game_type,
        "week": week,
        "home_team": home,
        "away_team": away,
        "gameday": gameday,
        "gametime": gametime,
        "home_score": 27.0 if scored else float("nan"),
        "away_score": 24.0 if scored else float("nan"),
    }


# Week 4 of 2026 in miniature: Thursday night, a London morning game,
# Sunday 1 pm, Monday night. Times are US Eastern, as nflverse states them.
LOCK_WEEK = pd.DataFrame(
    [
        _game(4, "CLE", "PIT", "2026-10-01", "20:15", scored=True),
        _game(4, "WAS", "IND", "2026-10-04", "09:30"),
        _game(4, "BAL", "TEN", "2026-10-04", "13:00"),
        _game(4, "NO", "ATL", "2026-10-05", "20:15"),
        _game(3, "GB", "ATL", "2026-09-24", "20:15", scored=True),
    ]
)


def test_started_nfl_teams_after_thursday_night() -> None:
    """Saturday: only the Thursday game has started; week 3 is ignored."""
    saturday = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    assert started_nfl_teams(LOCK_WEEK, 2026, 4, saturday) == {"CLE", "PIT"}


def test_started_nfl_teams_reads_kickoff_in_eastern_time() -> None:
    """9:30 ET in October is 13:30 UTC; an unscored game in progress counts.

    One minute before kickoff the London game is open; at kickoff it is
    locked, scores or not.
    """
    before = datetime(2026, 10, 4, 13, 29, tzinfo=timezone.utc)
    at = datetime(2026, 10, 4, 13, 30, tzinfo=timezone.utc)
    assert started_nfl_teams(LOCK_WEEK, 2026, 4, before) == {"CLE", "PIT"}
    assert started_nfl_teams(LOCK_WEEK, 2026, 4, at) == {"CLE", "PIT", "WAS", "IND"}


def test_started_nfl_teams_counts_a_scored_game_whatever_the_clock() -> None:
    """A final score locks a game even if the cached kickoff is later."""
    early = datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert started_nfl_teams(LOCK_WEEK, 2026, 4, early) == {"CLE", "PIT"}


def test_started_nfl_teams_edge_inputs() -> None:
    now = datetime(2026, 10, 3, tzinfo=timezone.utc)
    assert started_nfl_teams(pd.DataFrame(), 2026, 4, now) == frozenset()
    assert started_nfl_teams(LOCK_WEEK, 2026, 9, now) == frozenset()
    assert started_nfl_teams(LOCK_WEEK, 2025, 4, now) == frozenset()
    playoff = pd.DataFrame(
        [_game(19, "KC", "BUF", "2027-01-10", "16:30", True, game_type="WC")]
    )
    assert started_nfl_teams(playoff, 2026, 19, now) == frozenset()
    # No kickoff columns: the scores alone decide.
    scores_only = LOCK_WEEK.drop(columns=["gameday", "gametime"])
    assert started_nfl_teams(scores_only, 2026, 4, now) == {"CLE", "PIT"}
    with pytest.raises(ValueError):
        started_nfl_teams(LOCK_WEEK, 2026, 4, datetime(2026, 10, 3))

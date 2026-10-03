"""Tests for the matchup-preview comparison builders (FFA-115).

Toy league: rosters 1-4, regular-season weeks 1-4 plus playoff week 5.

    week  matchup            points        note
    1     1 v 2              100 - 90
    1     3 v 4              80 - 80       tie
    2     1 v 3              110 - 70
    2     2 bye              88            bye, not a game
    2     4 bye              60            bye, not a game
    3     1 v 2              90 - 100
    3     3 v 4              120 - None    missing points, not a game
    4     1 v 3              60 - 130
    5     1 v 2              500 - 0       playoff, always excluded
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from fantasy_analyzer.analytics.matchup_preview import (
    MATCHUP_TEAM_STATS_COLUMNS,
    build_matchup_team_stats,
    build_position_comparison,
    build_season_head_to_head,
)
from fantasy_analyzer.analytics.power_rankings import build_power_rankings
from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS


def _m(week, r1, r2, p1, p2, *, playoff=False) -> dict:
    if r2 is None or p1 is None or p2 is None:
        winner = loser = None
        tie = False
    elif p1 == p2:
        winner = loser = None
        tie = True
    else:
        winner, loser = (r1, r2) if p1 > p2 else (r2, r1)
        tie = False
    return {
        "season": 2026, "week": week, "is_playoff": playoff,
        "matchup_id": None if r2 is None else week * 10 + r1,
        "roster_1_id": r1, "roster_2_id": r2,
        "owner_1": f"o{r1}", "owner_2": None if r2 is None else f"o{r2}",
        "points_1": p1, "points_2": p2,
        "winner": winner, "loser": loser, "is_tie": tie,
        "margin": None, "point_differential": None,
    }


@pytest.fixture
def matchups() -> pd.DataFrame:
    rows = [
        _m(1, 1, 2, 100.0, 90.0), _m(1, 3, 4, 80.0, 80.0),
        _m(2, 1, 3, 110.0, 70.0), _m(2, 2, None, 88.0, None),
        _m(2, 4, None, 60.0, None),
        _m(3, 1, 2, 90.0, 100.0), _m(3, 3, 4, 120.0, None),
        _m(4, 1, 3, 60.0, 130.0),
        _m(5, 1, 2, 500.0, 0.0, playoff=True),
    ]
    return pd.DataFrame(rows, columns=SEASON_MATCHUP_COLUMNS)


@pytest.fixture
def teams() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"roster_id": r, "owner_id": f"u{r}", "display_name": f"o{r}",
             "team_name": f"T{r}"}
            for r in (1, 2, 3, 4)
        ]
    )


def _stats(df: pd.DataFrame) -> pd.DataFrame:
    return df.set_index("roster_id")


def test_team_stats_through_week_3_hand_computed(matchups, teams) -> None:
    out = build_matchup_team_stats(matchups, teams, 3)
    assert list(out.columns) == MATCHUP_TEAM_STATS_COLUMNS
    assert list(out["roster_id"]) == [1, 2, 3, 4]
    s = _stats(out)
    # Played games through week 3: W1 1v2, W1 3v4 (tie), W2 1v3, W3 1v2.
    # Byes (W2) and the missing-points game (W3 3v4) are not games; the
    # playoff week is excluded.
    assert s.loc[1, ["wins", "losses", "ties"]].tolist() == [2, 1, 0]
    assert s.loc[2, ["wins", "losses", "ties"]].tolist() == [1, 1, 0]
    assert s.loc[3, ["wins", "losses", "ties"]].tolist() == [0, 1, 1]
    assert s.loc[4, ["wins", "losses", "ties"]].tolist() == [0, 0, 1]
    # PF: 1 = 100+110+90, 2 = 90+100, 3 = 80+70, 4 = 80 (bye 60 ignored).
    assert s["points_for"].tolist() == [300.0, 190.0, 150.0, 80.0]
    assert s["points_against"].tolist() == [260.0, 190.0, 190.0, 80.0]
    # win_pct 1=.667, 2=.5, 4=.5, 3=.25; 2 and 4 tie on win_pct, PF splits.
    assert s["rank"].tolist() == [1, 2, 4, 3]
    # ppg: PF / games played (3, 2, 2, 1).
    assert s["ppg"].tolist() == [100.0, 95.0, 75.0, 80.0]
    # Fewer than 3 games: last3 is the mean of what exists.
    assert s["last3_ppg"].tolist() == [100.0, 95.0, 75.0, 80.0]
    assert s["high"].tolist() == [110.0, 100.0, 80.0, 80.0]
    assert s["low"].tolist() == [90.0, 90.0, 70.0, 80.0]
    # Population SD: 1 -> sqrt(((0)^2+10^2+10^2)/3); 2, 3 -> 5; 4 has 1 week.
    assert s.loc[1, "stdev_points"] == pytest.approx(math.sqrt(200 / 3))
    assert s.loc[2, "stdev_points"] == pytest.approx(5.0)
    assert s.loc[3, "stdev_points"] == pytest.approx(5.0)
    assert math.isnan(s.loc[4, "stdev_points"])
    # All-play over played games only: W1 {100,90,80,80}, W2 {110,70},
    # W3 {90,100}.
    assert s[["all_play_wins", "all_play_losses", "all_play_ties"]].values.tolist() == [
        [4, 1, 0], [3, 1, 0], [0, 3, 1], [0, 2, 1],
    ]
    assert s.loc[1, "power_rank"] == 1.0


def test_power_columns_come_from_build_power_rankings(matchups, teams) -> None:
    out = _stats(build_matchup_team_stats(matchups, teams, 3))
    truncated = matchups[(matchups["week"] <= 3) & ~matchups["is_playoff"]]
    expected = build_power_rankings(truncated, teams).set_index("roster_id")
    for roster_id in (1, 2, 3, 4):
        assert out.loc[roster_id, "power_rank"] == expected.loc[roster_id, "power_rank"]
        assert out.loc[roster_id, "power_score"] == pytest.approx(
            expected.loc[roster_id, "power_score"]
        )


def test_through_week_truncation_and_last3(matchups, teams) -> None:
    s = _stats(build_matchup_team_stats(matchups, teams, 4))
    # Roster 1 played weeks 1-4: 100, 110, 90, 60. ppg = 360/4; last 3 = weeks
    # 2-4 = (110+90+60)/3.
    assert s.loc[1, "ppg"] == 90.0
    assert s.loc[1, "last3_ppg"] == pytest.approx(260 / 3)
    assert s.loc[1, "low"] == 60.0
    # Through week 5 adds only a playoff game, which is excluded.
    s5 = _stats(build_matchup_team_stats(matchups, teams, 5))
    assert s5.loc[1, "points_for"] == 360.0
    assert s5.loc[2, "points_for"] == 190.0
    # Through week 1 only the first games count.
    s1 = _stats(build_matchup_team_stats(matchups, teams, 1))
    assert s1.loc[1, "points_for"] == 100.0
    assert s1.loc[3, ["wins", "losses", "ties"]].tolist() == [0, 0, 1]


def test_through_week_zero_returns_zero_or_nan(matchups, teams) -> None:
    out = build_matchup_team_stats(matchups, teams, 0)
    assert len(out) == 4
    assert (out[["wins", "losses", "ties", "points_for"]] == 0).all().all()
    assert (out[["all_play_wins", "all_play_losses", "all_play_ties"]] == 0).all().all()
    for column in ("ppg", "last3_ppg", "high", "low", "stdev_points",
                   "power_rank", "power_score"):
        assert out[column].isna().all(), column


def test_empty_inputs(matchups, teams) -> None:
    assert build_matchup_team_stats(matchups, teams.iloc[0:0], 3).empty
    empty = matchups.iloc[0:0]
    assert len(build_matchup_team_stats(empty, teams, 3)) == 4


def test_head_to_head_two_meetings(matchups) -> None:
    h = build_season_head_to_head(matchups, 1, 2, 3)
    assert h == {
        "meetings": 2, "wins": 1, "losses": 1, "ties": 0,
        "games": [
            {"week": 1, "points": 100.0, "opponent_points": 90.0},
            {"week": 3, "points": 90.0, "opponent_points": 100.0},
        ],
    }
    # Playoff week-5 meeting never counts, even with through_week=5.
    assert build_season_head_to_head(matchups, 1, 2, 5)["meetings"] == 2


def test_head_to_head_perspective_and_truncation(matchups) -> None:
    h = build_season_head_to_head(matchups, 2, 1, 2)
    assert h["games"] == [{"week": 1, "points": 90.0, "opponent_points": 100.0}]
    assert (h["wins"], h["losses"], h["ties"]) == (0, 1, 0)


def test_head_to_head_zero_meetings_and_unplayed(matchups) -> None:
    assert build_season_head_to_head(matchups, 2, 4, 5) == {
        "meetings": 0, "wins": 0, "losses": 0, "ties": 0, "games": [],
    }
    # 3 v 4: week-1 tie counts; the week-3 missing-points game does not.
    h = build_season_head_to_head(matchups, 3, 4, 3)
    assert (h["meetings"], h["ties"]) == (1, 1)
    assert build_season_head_to_head(matchups.iloc[0:0], 1, 2, 3)["meetings"] == 0


def test_position_comparison_ordering_and_missing() -> None:
    df = pd.DataFrame(
        [
            ("me", "WR", 30.0, 2), ("me", "QB", 21.0, 3), ("me", "FB", 2.0, 1),
            ("me", "DEF", 8.0, 5), ("opp", "QB", 17.5, 9), ("opp", "WR", 25.0, 6),
            ("opp", "K", 7.0, 4), ("opp", "AA", 1.0, 2),
        ],
        columns=["fantasy_team", "position", "points_per_game", "positional_rank"],
    )
    out = build_position_comparison(df, "me", "opp")
    assert [r["position"] for r in out] == ["QB", "WR", "K", "DEF", "AA", "FB"]
    assert out[0] == {"position": "QB", "me_ppg": 21.0, "me_rank": 3,
                      "opponent_ppg": 17.5, "opponent_rank": 9}
    k = out[2]
    assert k["me_ppg"] is None and k["me_rank"] is None and k["opponent_rank"] == 4
    assert build_position_comparison(df.iloc[0:0], "me", "opp") == []

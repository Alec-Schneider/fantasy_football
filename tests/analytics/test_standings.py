"""Tests for base league standings (FFA-020).

These tests operate on hand-built ``rosters_df``/``teams_df`` inputs -- no
HTTP calls, no fixtures with opaque values -- so that the expected
``win_pct``/``point_diff``/``rank`` numbers can be verified by hand
arithmetic in each test's comments, per AGENTS.md's analytics-ticket
requirement for a hand-checkable toy example.
"""

import pandas as pd
import pytest

from fantasy_analyzer.analytics import build_standings
from fantasy_analyzer.analytics.standings import STANDINGS_COLUMNS


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


def _teams_df(rows: list[dict]) -> pd.DataFrame:
    columns = ["roster_id", "owner_id", "display_name", "team_name"]
    return pd.DataFrame(rows, columns=columns)


def test_build_standings_toy_example_hand_computed() -> None:
    """Three-team toy example with win_pct/point_diff/rank computed by hand.

    Team A (roster 1): 8-4-1 (13 games), fpts=1200.0, fpts_against=1100.0
        win_pct     = (8 + 0.5*1) / 13 = 8.5 / 13 = 0.6538461538461539
        point_diff  = 1200.0 - 1100.0 = 100.0
    Team B (roster 2): 6-6-1 (13 games), fpts=1150.0, fpts_against=1150.0
        win_pct     = (6 + 0.5*1) / 13 = 6.5 / 13 = 0.5
        point_diff  = 1150.0 - 1150.0 = 0.0
    Team C (roster 3): 4-9-0 (13 games), fpts=1000.0, fpts_against=1200.0
        win_pct     = 4 / 13 = 0.3076923076923077
        point_diff  = 1000.0 - 1200.0 = -200.0

    Sorted descending by win_pct: A (0.6538), B (0.5), C (0.3077) -> no ties,
    so rank = 1, 2, 3 respectively.
    """
    rosters_df = _rosters_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "wins": 8,
                "losses": 4,
                "ties": 1,
                "fpts": 1200.0,
                "fpts_against": 1100.0,
                "players": [],
                "starters": [],
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "wins": 6,
                "losses": 6,
                "ties": 1,
                "fpts": 1150.0,
                "fpts_against": 1150.0,
                "players": [],
                "starters": [],
            },
            {
                "roster_id": 3,
                "owner_id": "u3",
                "wins": 4,
                "losses": 9,
                "ties": 0,
                "fpts": 1000.0,
                "fpts_against": 1200.0,
                "players": [],
                "starters": [],
            },
        ]
    )
    teams_df = _teams_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "display_name": "Alice",
                "team_name": "Team Alice",
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "display_name": "Bob",
                "team_name": "Team Bob",
            },
            {
                "roster_id": 3,
                "owner_id": "u3",
                "display_name": "Cara",
                "team_name": "Team Cara",
            },
        ]
    )

    standings = build_standings(rosters_df, teams_df)

    assert list(standings.columns) == STANDINGS_COLUMNS
    assert list(standings["roster_id"]) == [1, 2, 3]

    row_a = standings.loc[standings["roster_id"] == 1].iloc[0]
    assert row_a["wins"] == 8
    assert row_a["losses"] == 4
    assert row_a["ties"] == 1
    assert row_a["win_pct"] == pytest.approx(0.6538461538461539)
    assert row_a["points_for"] == 1200.0
    assert row_a["points_against"] == 1100.0
    assert row_a["point_diff"] == pytest.approx(100.0)
    assert row_a["rank"] == 1

    row_b = standings.loc[standings["roster_id"] == 2].iloc[0]
    assert row_b["win_pct"] == pytest.approx(0.5)
    assert row_b["point_diff"] == pytest.approx(0.0)
    assert row_b["rank"] == 2

    row_c = standings.loc[standings["roster_id"] == 3].iloc[0]
    assert row_c["win_pct"] == pytest.approx(0.3076923076923077)
    assert row_c["point_diff"] == pytest.approx(-200.0)
    assert row_c["rank"] == 3


def test_build_standings_reconciles_wins_losses_ties_points_unchanged() -> None:
    """wins/losses/ties/points_for/points_against pass through unmodified."""
    rosters_df = _rosters_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "wins": 7,
                "losses": 6,
                "ties": 0,
                "fpts": 999.42,
                "fpts_against": 888.15,
                "players": [],
                "starters": [],
            }
        ]
    )
    teams_df = _teams_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "display_name": "Alice",
                "team_name": "Team Alice",
            }
        ]
    )

    standings = build_standings(rosters_df, teams_df)
    row = standings.iloc[0]

    assert row["wins"] == 7
    assert row["losses"] == 6
    assert row["ties"] == 0
    assert row["points_for"] == 999.42
    assert row["points_against"] == 888.15


def test_build_standings_tiebreak_uses_points_for_when_win_pct_ties() -> None:
    """Two teams tied on win_pct (0.5) rank by descending points_for.

    Team A: 5-5-0 (10 games), win_pct = 5/10 = 0.5, fpts = 1000.0.
    Team B: 5-5-0 (10 games), win_pct = 5/10 = 0.5, fpts = 950.0.
    A has more points_for, so A ranks 1 and B ranks 2 -- despite an
    identical win_pct, they are NOT considered tied in the standings rank
    because the tiebreak (points_for) resolves the order.
    """
    rosters_df = _rosters_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "wins": 5,
                "losses": 5,
                "ties": 0,
                "fpts": 1000.0,
                "fpts_against": 900.0,
                "players": [],
                "starters": [],
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "wins": 5,
                "losses": 5,
                "ties": 0,
                "fpts": 950.0,
                "fpts_against": 900.0,
                "players": [],
                "starters": [],
            },
        ]
    )
    teams_df = _teams_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "display_name": "Alice",
                "team_name": "Team Alice",
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "display_name": "Bob",
                "team_name": "Team Bob",
            },
        ]
    )

    standings = build_standings(rosters_df, teams_df)

    assert list(standings["roster_id"]) == [1, 2]
    row_a = standings.loc[standings["roster_id"] == 1].iloc[0]
    row_b = standings.loc[standings["roster_id"] == 2].iloc[0]
    assert row_a["win_pct"] == pytest.approx(row_b["win_pct"])
    assert row_a["rank"] == 1
    assert row_b["rank"] == 2


def test_build_standings_rank_ties_when_win_pct_and_points_for_both_equal() -> None:
    """Standard competition ("1224") ranking when two teams are fully tied.

    Team C: 6-4-0 (10 games), win_pct = 0.6 -> ranks above A/B.
    Team A: 5-5-0 (10 games), win_pct = 0.5, fpts = 1000.0.
    Team B: 5-5-0 (10 games), win_pct = 0.5, fpts = 1000.0.
        A and B are fully tied (win_pct AND points_for) -> share rank 2.
    Team D: 3-7-0 (10 games), win_pct = 0.3 -> ranks below A/B.
        Because two teams share rank 2, D's rank skips to 4 (not 3), per
        standard competition ranking.
    """
    rosters_df = _rosters_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "wins": 5,
                "losses": 5,
                "ties": 0,
                "fpts": 1000.0,
                "fpts_against": 900.0,
                "players": [],
                "starters": [],
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "wins": 5,
                "losses": 5,
                "ties": 0,
                "fpts": 1000.0,
                "fpts_against": 950.0,
                "players": [],
                "starters": [],
            },
            {
                "roster_id": 3,
                "owner_id": "u3",
                "wins": 6,
                "losses": 4,
                "ties": 0,
                "fpts": 900.0,
                "fpts_against": 850.0,
                "players": [],
                "starters": [],
            },
            {
                "roster_id": 4,
                "owner_id": "u4",
                "wins": 3,
                "losses": 7,
                "ties": 0,
                "fpts": 800.0,
                "fpts_against": 950.0,
                "players": [],
                "starters": [],
            },
        ]
    )
    teams_df = _teams_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "display_name": "Alice",
                "team_name": "Team Alice",
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "display_name": "Bob",
                "team_name": "Team Bob",
            },
            {
                "roster_id": 3,
                "owner_id": "u3",
                "display_name": "Cara",
                "team_name": "Team Cara",
            },
            {
                "roster_id": 4,
                "owner_id": "u4",
                "display_name": "Dana",
                "team_name": "Team Dana",
            },
        ]
    )

    standings = build_standings(rosters_df, teams_df)

    rank_by_roster = dict(zip(standings["roster_id"], standings["rank"]))
    assert rank_by_roster[3] == 1
    assert rank_by_roster[1] == 2
    assert rank_by_roster[2] == 2
    assert rank_by_roster[4] == 4


def test_build_standings_zero_games_team_has_zero_win_pct() -> None:
    """A team with wins=losses=ties=0 gets win_pct=0.0, not a ZeroDivisionError/NaN."""
    rosters_df = _rosters_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "wins": 0,
                "losses": 0,
                "ties": 0,
                "fpts": 0.0,
                "fpts_against": 0.0,
                "players": [],
                "starters": [],
            }
        ]
    )
    teams_df = _teams_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "display_name": "Alice",
                "team_name": "Team Alice",
            }
        ]
    )

    standings = build_standings(rosters_df, teams_df)

    assert standings.iloc[0]["win_pct"] == 0.0
    assert standings.iloc[0]["rank"] == 1


def test_build_standings_empty_inputs_produce_empty_frame_with_columns() -> None:
    rosters_df = _rosters_df([])
    teams_df = _teams_df([])

    standings = build_standings(rosters_df, teams_df)

    assert standings.empty
    assert list(standings.columns) == STANDINGS_COLUMNS


def test_build_standings_from_league_snapshot_fixtures(load_sleeper_fixture) -> None:
    """Integration check: standings reconcile to LeagueSnapshot's rosters_df.

    Fixture roster 1: wins=5, losses=3, ties=0, fpts=1050.42,
        fpts_against=980.15 -> win_pct = 5/8 = 0.625, point_diff = 70.27.
    Fixture roster 2: wins=4, losses=4, ties=0, fpts=975.30,
        fpts_against=968.88 -> win_pct = 4/8 = 0.5, point_diff = 6.42.
    Roster 1 has the higher win_pct, so it ranks 1st; roster 2 ranks 2nd.
    """
    from fantasy_analyzer.league import build_league_snapshot

    raw_league = load_sleeper_fixture("league.json")
    raw_users = load_sleeper_fixture("users.json")
    raw_rosters = load_sleeper_fixture("rosters.json")
    player_catalog = load_sleeper_fixture("players.json")

    snapshot = build_league_snapshot(raw_league, raw_users, raw_rosters, player_catalog)
    standings = build_standings(snapshot.rosters_df, snapshot.teams_df)

    assert list(standings.columns) == STANDINGS_COLUMNS
    assert len(standings) == len(raw_rosters)

    row_1 = standings.loc[standings["roster_id"] == 1].iloc[0]
    assert row_1["wins"] == 5
    assert row_1["losses"] == 3
    assert row_1["ties"] == 0
    assert row_1["points_for"] == pytest.approx(1050.42)
    assert row_1["points_against"] == pytest.approx(980.15)
    assert row_1["win_pct"] == pytest.approx(0.625)
    assert row_1["point_diff"] == pytest.approx(70.27)
    assert row_1["rank"] == 1

    row_2 = standings.loc[standings["roster_id"] == 2].iloc[0]
    assert row_2["win_pct"] == pytest.approx(0.5)
    assert row_2["rank"] == 2

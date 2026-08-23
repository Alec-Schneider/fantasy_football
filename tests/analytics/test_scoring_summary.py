"""Tests for league scoring summary metrics (FFA-021).

These tests operate on hand-built ``rosters_df``/``teams_df`` inputs -- no
HTTP calls, no fixtures with opaque values -- so that the expected
``points_per_game``/``avg_margin``/``scoring_rank`` numbers can be verified
by hand arithmetic in each test's comments, per AGENTS.md's analytics-ticket
requirement for a hand-checkable toy example.
"""

import pandas as pd
import pytest

from fantasy_analyzer.analytics import build_scoring_summary
from fantasy_analyzer.analytics.standings import SCORING_SUMMARY_COLUMNS


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


def test_build_scoring_summary_toy_example_hand_computed() -> None:
    """Three-team toy example with points_per_game/avg_margin computed by hand.

    Team A (roster 1): 8-4-1 (13 games), fpts=1300.0, fpts_against=1100.0
        points_per_game         = 1300.0 / 13 = 100.0
        points_against_per_game = 1100.0 / 13 = 84.61538461538461
        avg_margin               = (1300.0 - 1100.0) / 13
                                  = 200.0 / 13 = 15.384615384615385
    Team B (roster 2): 6-6-1 (13 games), fpts=1170.0, fpts_against=1170.0
        points_per_game         = 1170.0 / 13 = 90.0
        points_against_per_game = 1170.0 / 13 = 90.0
        avg_margin               = 0.0 / 13 = 0.0
    Team C (roster 3): 4-9-0 (13 games), fpts=910.0, fpts_against=1080.0
        points_per_game         = 910.0 / 13 = 70.0
        points_against_per_game = 1080.0 / 13 = 83.07692307692308
        avg_margin               = (910.0 - 1080.0) / 13
                                  = -170.0 / 13 = -13.076923076923077

    scoring_rank is by cumulative points_for descending: A (1300) > B (1170)
    > C (910) -> no ties, so scoring_rank = 1, 2, 3 respectively.
    """
    rosters_df = _rosters_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "wins": 8,
                "losses": 4,
                "ties": 1,
                "fpts": 1300.0,
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
                "fpts": 1170.0,
                "fpts_against": 1170.0,
                "players": [],
                "starters": [],
            },
            {
                "roster_id": 3,
                "owner_id": "u3",
                "wins": 4,
                "losses": 9,
                "ties": 0,
                "fpts": 910.0,
                "fpts_against": 1080.0,
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

    summary = build_scoring_summary(rosters_df, teams_df)

    assert list(summary.columns) == SCORING_SUMMARY_COLUMNS
    assert "high_score" not in summary.columns
    assert "low_score" not in summary.columns
    assert list(summary["roster_id"]) == [1, 2, 3]

    row_a = summary.loc[summary["roster_id"] == 1].iloc[0]
    assert row_a["points_per_game"] == pytest.approx(100.0)
    assert row_a["points_against_per_game"] == pytest.approx(84.61538461538461)
    assert row_a["avg_margin"] == pytest.approx(15.384615384615385)
    assert row_a["scoring_rank"] == 1

    row_b = summary.loc[summary["roster_id"] == 2].iloc[0]
    assert row_b["points_per_game"] == pytest.approx(90.0)
    assert row_b["points_against_per_game"] == pytest.approx(90.0)
    assert row_b["avg_margin"] == pytest.approx(0.0)
    assert row_b["scoring_rank"] == 2

    row_c = summary.loc[summary["roster_id"] == 3].iloc[0]
    assert row_c["points_per_game"] == pytest.approx(70.0)
    assert row_c["points_against_per_game"] == pytest.approx(83.07692307692308)
    assert row_c["avg_margin"] == pytest.approx(-13.076923076923077)
    assert row_c["scoring_rank"] == 3


def test_build_scoring_summary_sorted_by_points_per_game_descending() -> None:
    """Rows are sorted by descending points_per_game, not by roster_id order.

    Team A (roster 1): fpts=800.0 over 10 games -> points_per_game = 80.0.
    Team B (roster 2): fpts=1000.0 over 10 games -> points_per_game = 100.0.
    B should sort ahead of A despite roster_id being higher.
    """
    rosters_df = _rosters_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "wins": 5,
                "losses": 5,
                "ties": 0,
                "fpts": 800.0,
                "fpts_against": 800.0,
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
                "fpts_against": 800.0,
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

    summary = build_scoring_summary(rosters_df, teams_df)

    assert list(summary["roster_id"]) == [2, 1]
    assert summary.iloc[0]["points_per_game"] == pytest.approx(100.0)
    assert summary.iloc[1]["points_per_game"] == pytest.approx(80.0)


def test_build_scoring_summary_scoring_rank_ties_when_points_for_equal() -> None:
    """Standard competition ("1224") ranking when two teams' points_for tie.

    Team C: fpts = 1200.0 -> scoring_rank 1.
    Team A: fpts = 1000.0 -> tied with Team B on points_for -> both rank 2.
    Team B: fpts = 1000.0 -> tied with Team A on points_for -> both rank 2.
    Team D: fpts = 800.0 -> ranks below A/B, skips to 4 (not 3), because two
        teams share rank 2.
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
                "wins": 4,
                "losses": 6,
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
                "fpts": 1200.0,
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

    summary = build_scoring_summary(rosters_df, teams_df)

    rank_by_roster = dict(zip(summary["roster_id"], summary["scoring_rank"]))
    assert rank_by_roster[3] == 1
    assert rank_by_roster[1] == 2
    assert rank_by_roster[2] == 2
    assert rank_by_roster[4] == 4


def test_build_scoring_summary_zero_games_team_has_zero_rate_metrics() -> None:
    """A team with wins=losses=ties=0 gets 0.0 for all per-game metrics.

    This is the explicit missing-value rule, not a ZeroDivisionError/NaN --
    consistent with build_standings' zero-games win_pct treatment.
    """
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

    summary = build_scoring_summary(rosters_df, teams_df)
    row = summary.iloc[0]

    assert row["points_per_game"] == 0.0
    assert row["points_against_per_game"] == 0.0
    assert row["avg_margin"] == 0.0
    assert row["scoring_rank"] == 1


def test_build_scoring_summary_empty_inputs_produce_empty_frame_with_columns() -> None:
    rosters_df = _rosters_df([])
    teams_df = _teams_df([])

    summary = build_scoring_summary(rosters_df, teams_df)

    assert summary.empty
    assert list(summary.columns) == SCORING_SUMMARY_COLUMNS


def test_build_scoring_summary_from_league_snapshot_fixtures(
    load_sleeper_fixture,
) -> None:
    """Integration check: scoring summary reconciles to LeagueSnapshot's rosters_df.

    Fixture roster 1: wins=5, losses=3, ties=0 (8 games), fpts=1050.42,
        fpts_against=980.15
        -> points_per_game = 1050.42 / 8 = 131.3025
        -> points_against_per_game = 980.15 / 8 = 122.51875
        -> avg_margin = (1050.42 - 980.15) / 8 = 70.27 / 8 = 8.78375
    Fixture roster 2: wins=4, losses=4, ties=0 (8 games), fpts=975.30,
        fpts_against=968.88
        -> points_per_game = 975.30 / 8 = 121.9125
    Roster 1 has the higher cumulative fpts, so it gets scoring_rank 1.
    """
    from fantasy_analyzer.league import build_league_snapshot

    raw_league = load_sleeper_fixture("league.json")
    raw_users = load_sleeper_fixture("users.json")
    raw_rosters = load_sleeper_fixture("rosters.json")
    player_catalog = load_sleeper_fixture("players.json")

    snapshot = build_league_snapshot(raw_league, raw_users, raw_rosters, player_catalog)
    summary = build_scoring_summary(snapshot.rosters_df, snapshot.teams_df)

    assert list(summary.columns) == SCORING_SUMMARY_COLUMNS
    assert len(summary) == len(raw_rosters)

    row_1 = summary.loc[summary["roster_id"] == 1].iloc[0]
    assert row_1["points_per_game"] == pytest.approx(1050.42 / 8)
    assert row_1["points_against_per_game"] == pytest.approx(980.15 / 8)
    assert row_1["avg_margin"] == pytest.approx((1050.42 - 980.15) / 8)
    assert row_1["scoring_rank"] == 1

    row_2 = summary.loc[summary["roster_id"] == 2].iloc[0]
    assert row_2["points_per_game"] == pytest.approx(975.30 / 8)

"""Tests for building the canonical season matchup DataFrame (FFA-033).

All tests operate on the pure, no-network :func:`build_season_matchup_df`
against hand-built ``MatchupOutcome``/``teams_df`` inputs, so the expected
owner/winner/loser/margin values can be verified by hand per AGENTS.md's
analytics-ticket requirement for a hand-checkable toy example.
"""

import pandas as pd

from fantasy_analyzer.matchups import MatchupOutcome, build_season_matchup_df
from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS


def _outcome(
    roster_1_id: int = 1,
    roster_2_id: int | None = 2,
    points_1: float | None = 100.0,
    points_2: float | None = 90.0,
    winner_roster_id: int | None = 1,
    loser_roster_id: int | None = 2,
    is_tie: bool = False,
    margin: float | None = 10.0,
    point_differential: float | None = 10.0,
    matchup_id: int | None = 1,
    week: int = 1,
    is_playoff: bool = False,
    season: str | None = "2025",
) -> MatchupOutcome:
    return MatchupOutcome(
        season=season,
        week=week,
        is_playoff=is_playoff,
        matchup_id=matchup_id,
        roster_1_id=roster_1_id,
        roster_2_id=roster_2_id,
        points_1=points_1,
        points_2=points_2,
        winner_roster_id=winner_roster_id,
        loser_roster_id=loser_roster_id,
        is_tie=is_tie,
        margin=margin,
        point_differential=point_differential,
    )


def _teams_df(rows: list[dict]) -> pd.DataFrame:
    columns = ["roster_id", "owner_id", "display_name", "team_name"]
    return pd.DataFrame(rows, columns=columns)


def test_toy_example_hand_computed() -> None:
    """One matchup, roster 1 beats roster 2, both owners known.

    roster_1_id=1 (owner "Alec") scores 123.45, roster_2_id=2 (owner "Mike")
    scores 110.2. point_differential = 13.25, margin = 13.25, winner = 1
    (roster ID, not owner label -- see module docstring).
    """
    outcome = _outcome(
        roster_1_id=1,
        roster_2_id=2,
        points_1=123.45,
        points_2=110.2,
        winner_roster_id=1,
        loser_roster_id=2,
        margin=13.25,
        point_differential=13.25,
    )
    teams_df = _teams_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "display_name": "Alec",
                "team_name": "Alec",
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "display_name": "Mike",
                "team_name": "Mike",
            },
        ]
    )

    df = build_season_matchup_df([outcome], teams_df)

    assert list(df.columns) == SEASON_MATCHUP_COLUMNS
    assert len(df) == 1
    row = df.iloc[0]
    assert row["season"] == "2025"
    assert row["week"] == 1
    assert not row["is_playoff"]
    assert row["matchup_id"] == 1
    assert row["roster_1_id"] == 1
    assert row["roster_2_id"] == 2
    assert row["owner_1"] == "Alec"
    assert row["owner_2"] == "Mike"
    assert row["points_1"] == 123.45
    assert row["points_2"] == 110.2
    assert row["winner"] == 1
    assert row["loser"] == 2
    assert not row["is_tie"]
    assert row["margin"] == 13.25
    assert row["point_differential"] == 13.25


def test_tie_has_no_winner_or_loser_but_is_tie_true() -> None:
    outcome = _outcome(
        points_1=100.0,
        points_2=100.0,
        winner_roster_id=None,
        loser_roster_id=None,
        is_tie=True,
        margin=0.0,
        point_differential=0.0,
    )
    teams_df = _teams_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "display_name": "Alec",
                "team_name": "Alec",
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "display_name": "Mike",
                "team_name": "Mike",
            },
        ]
    )

    df = build_season_matchup_df([outcome], teams_df)

    row = df.iloc[0]
    assert row["is_tie"]
    assert row["winner"] is None
    assert row["loser"] is None
    assert row["owner_1"] == "Alec"
    assert row["owner_2"] == "Mike"


def test_bye_has_no_second_roster_owner_or_outcome() -> None:
    """A bye entry (see pairing.py) has roster_2_id/points_2/outcome all None."""
    outcome = _outcome(
        roster_1_id=7,
        roster_2_id=None,
        points_1=55.5,
        points_2=None,
        winner_roster_id=None,
        loser_roster_id=None,
        is_tie=False,
        margin=None,
        point_differential=None,
        matchup_id=None,
    )
    teams_df = _teams_df(
        [{"roster_id": 7, "owner_id": "u7", "display_name": "Joe", "team_name": "Joe"}]
    )

    df = build_season_matchup_df([outcome], teams_df)

    row = df.iloc[0]
    assert row["roster_2_id"] is None
    assert row["owner_1"] == "Joe"
    assert row["owner_2"] is None
    assert row["points_2"] is None
    assert row["winner"] is None
    assert row["loser"] is None
    assert row["margin"] is None
    assert row["point_differential"] is None


def test_unmapped_roster_id_gets_none_owner_rather_than_raising() -> None:
    """roster_id 99 has no row in teams_df -- should not crash the join."""
    outcome = _outcome(roster_1_id=99, roster_2_id=2)
    teams_df = _teams_df(
        [
            {
                "roster_id": 2,
                "owner_id": "u2",
                "display_name": "Mike",
                "team_name": "Mike",
            }
        ]
    )

    df = build_season_matchup_df([outcome], teams_df)

    row = df.iloc[0]
    assert row["owner_1"] is None
    assert row["owner_2"] == "Mike"


def test_empty_teams_df_gets_none_owners_rather_than_raising() -> None:
    outcome = _outcome()
    teams_df = _teams_df([])

    df = build_season_matchup_df([outcome], teams_df)

    row = df.iloc[0]
    assert row["owner_1"] is None
    assert row["owner_2"] is None


def test_empty_outcomes_returns_empty_dataframe_with_expected_columns() -> None:
    df = build_season_matchup_df([], _teams_df([]))

    assert df.empty
    assert list(df.columns) == SEASON_MATCHUP_COLUMNS


def test_row_order_matches_input_outcome_order() -> None:
    outcomes = [
        _outcome(roster_1_id=1, roster_2_id=2, week=1, matchup_id=1),
        _outcome(roster_1_id=1, roster_2_id=3, week=2, matchup_id=5),
    ]
    teams_df = _teams_df(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "display_name": "Alec",
                "team_name": "Alec",
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "display_name": "Mike",
                "team_name": "Mike",
            },
            {
                "roster_id": 3,
                "owner_id": "u3",
                "display_name": "Joe",
                "team_name": "Joe",
            },
        ]
    )

    df = build_season_matchup_df(outcomes, teams_df)

    assert list(df["week"]) == [1, 2]
    assert list(df["owner_2"]) == ["Mike", "Joe"]


def test_playoff_flag_is_carried_through() -> None:
    outcome = _outcome(is_playoff=True, week=16)
    df = build_season_matchup_df([outcome], _teams_df([]))

    assert df.iloc[0]["is_playoff"]
    assert df.iloc[0]["week"] == 16

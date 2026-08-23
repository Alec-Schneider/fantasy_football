"""Tests for reconciling matchup-derived totals to standings (FFA-034).

All tests operate on hand-built ``season_matchup_df``/``rosters_df``/
``teams_df`` inputs -- no HTTP calls, no fixtures with opaque values -- so
the expected derived wins/losses/ties/points_for/points_against numbers can
be verified by hand arithmetic in each test's comments, per AGENTS.md's
analytics-ticket requirement for a hand-checkable toy example.
"""

import pandas as pd
import pytest

from fantasy_analyzer.analytics import build_standings
from fantasy_analyzer.matchups import (
    DERIVED_TOTALS_COLUMNS,
    POINTS_TOLERANCE,
    RECONCILIATION_COLUMNS,
    derive_roster_totals,
    reconcile_matchups_to_standings,
)
from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS


def _matchup_row(
    roster_1_id: int,
    roster_2_id: int | None,
    points_1: float | None,
    points_2: float | None,
    winner: int | None,
    loser: int | None,
    is_tie: bool = False,
    is_playoff: bool = False,
    week: int = 1,
    matchup_id: int | None = 1,
    season: str = "2025",
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
        "owner_1": None,
        "owner_2": None,
        "points_1": points_1,
        "points_2": points_2,
        "winner": winner,
        "loser": loser,
        "is_tie": is_tie,
        "margin": margin,
        "point_differential": point_differential,
    }


def _season_matchup_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=SEASON_MATCHUP_COLUMNS)
    return pd.DataFrame(rows, columns=SEASON_MATCHUP_COLUMNS)


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


def _roster_row(
    roster_id: int, wins: int, losses: int, ties: int, fpts: float, fpts_against: float
) -> dict:
    return {
        "roster_id": roster_id,
        "owner_id": f"u{roster_id}",
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "fpts": fpts,
        "fpts_against": fpts_against,
        "players": [],
        "starters": [],
    }


def _empty_standings_df() -> pd.DataFrame:
    """A ``STANDINGS_COLUMNS``-shaped but empty standings DataFrame.

    Reconciliation only reads ``["roster_id", "wins", "losses", "ties",
    "points_for", "points_against"]`` from a standings DataFrame, so an
    empty frame with just those columns is sufficient here.
    """
    return pd.DataFrame(
        columns=["roster_id", "wins", "losses", "ties", "points_for", "points_against"]
    )


def _team_row(roster_id: int, name: str) -> dict:
    return {
        "roster_id": roster_id,
        "owner_id": f"u{roster_id}",
        "display_name": name,
        "team_name": name,
    }


def _toy_season_matchup_rows() -> list[dict]:
    """Three-roster, two-week toy season used across several tests below.

    Week 1 (regular season):
      - matchup_id=1: roster 1 (120.0) beats roster 2 (100.0).
      - roster 3 has a bye (90.0 points, no opponent).

    Week 2 (playoff, ``is_playoff=True``):
      - matchup_id=2: roster 1 (110.0) ties roster 3 (110.0).
      - roster 2 has a bye (95.0 points, no opponent).

    Hand-computed cumulative totals (see module docstring's per-field
    logic in ``reconciliation.py``):

    roster 1: wins=1, losses=0, ties=1
        points_for = 120.0 (week1) + 110.0 (week2) = 230.0
        points_against = 100.0 (week1, roster 2's points) +
                          110.0 (week2, roster 3's points) = 210.0
    roster 2: wins=0, losses=1, ties=0
        points_for = 100.0 (week1) + 95.0 (week2 bye) = 195.0
        points_against = 120.0 (week1, roster 1's points)
    roster 3: wins=0, losses=0, ties=1
        points_for = 90.0 (week1 bye) + 110.0 (week2) = 200.0
        points_against = 110.0 (week2, roster 1's points)
    """
    return [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=120.0,
            points_2=100.0,
            winner=1,
            loser=2,
            week=1,
            matchup_id=1,
            is_playoff=False,
        ),
        _matchup_row(
            roster_1_id=3,
            roster_2_id=None,
            points_1=90.0,
            points_2=None,
            winner=None,
            loser=None,
            week=1,
            matchup_id=None,
            is_playoff=False,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=3,
            points_1=110.0,
            points_2=110.0,
            winner=None,
            loser=None,
            is_tie=True,
            week=2,
            matchup_id=2,
            is_playoff=True,
        ),
        _matchup_row(
            roster_1_id=2,
            roster_2_id=None,
            points_1=95.0,
            points_2=None,
            winner=None,
            loser=None,
            week=2,
            matchup_id=None,
            is_playoff=True,
        ),
    ]


def test_derive_roster_totals_toy_example_hand_computed() -> None:
    """derive_roster_totals matches the hand-computed totals in the toy example."""
    df = derive_roster_totals(_season_matchup_df(_toy_season_matchup_rows()))

    assert list(df.columns) == DERIVED_TOTALS_COLUMNS
    assert len(df) == 3

    row_1 = df.loc[df["roster_id"] == 1].iloc[0]
    assert row_1["wins"] == 1
    assert row_1["losses"] == 0
    assert row_1["ties"] == 1
    assert row_1["points_for"] == pytest.approx(230.0)
    assert row_1["points_against"] == pytest.approx(210.0)

    row_2 = df.loc[df["roster_id"] == 2].iloc[0]
    assert row_2["wins"] == 0
    assert row_2["losses"] == 1
    assert row_2["ties"] == 0
    assert row_2["points_for"] == pytest.approx(195.0)
    assert row_2["points_against"] == pytest.approx(120.0)

    row_3 = df.loc[df["roster_id"] == 3].iloc[0]
    assert row_3["wins"] == 0
    assert row_3["losses"] == 0
    assert row_3["ties"] == 1
    assert row_3["points_for"] == pytest.approx(200.0)
    assert row_3["points_against"] == pytest.approx(110.0)


def test_reconcile_matches_when_standings_agree_with_derived_totals() -> None:
    """Reconciliation reports a full match when standings mirror the toy example."""
    season_matchup_df = _season_matchup_df(_toy_season_matchup_rows())
    rosters_df = _rosters_df(
        [
            _roster_row(1, wins=1, losses=0, ties=1, fpts=230.0, fpts_against=210.0),
            _roster_row(2, wins=0, losses=1, ties=0, fpts=195.0, fpts_against=120.0),
            _roster_row(3, wins=0, losses=0, ties=1, fpts=200.0, fpts_against=110.0),
        ]
    )
    teams_df = _teams_df(
        [
            _team_row(1, "Alice"),
            _team_row(2, "Bob"),
            _team_row(3, "Cara"),
        ]
    )
    standings_df = build_standings(rosters_df, teams_df)

    result = reconcile_matchups_to_standings(season_matchup_df, standings_df)

    assert list(result.columns) == RECONCILIATION_COLUMNS
    assert len(result) == 3
    assert result["reconciled"].all()
    assert result["wins_match"].all()
    assert result["losses_match"].all()
    assert result["ties_match"].all()
    assert result["points_for_match"].all()
    assert result["points_against_match"].all()

    row_1 = result.loc[result["roster_id"] == 1].iloc[0]
    assert row_1["derived_wins"] == row_1["sleeper_wins"] == 1
    assert row_1["wins_diff"] == 0
    assert row_1["derived_points_for"] == pytest.approx(230.0)
    assert row_1["sleeper_points_for"] == pytest.approx(230.0)
    assert row_1["points_for_diff"] == pytest.approx(0.0)


def test_reconcile_points_within_floating_point_tolerance_still_matches() -> None:
    """A sub-tolerance floating-point difference in points still reports a match."""
    season_matchup_df = _season_matchup_df(_toy_season_matchup_rows())
    rosters_df = _rosters_df(
        [
            _roster_row(
                1,
                wins=1,
                losses=0,
                ties=1,
                fpts=230.0 + (POINTS_TOLERANCE / 10),
                fpts_against=210.0,
            ),
            _roster_row(2, wins=0, losses=1, ties=0, fpts=195.0, fpts_against=120.0),
            _roster_row(3, wins=0, losses=0, ties=1, fpts=200.0, fpts_against=110.0),
        ]
    )
    teams_df = _teams_df(
        [_team_row(1, "Alice"), _team_row(2, "Bob"), _team_row(3, "Cara")]
    )
    standings_df = build_standings(rosters_df, teams_df)

    result = reconcile_matchups_to_standings(season_matchup_df, standings_df)

    row_1 = result.loc[result["roster_id"] == 1].iloc[0]
    assert row_1["points_for_match"]
    assert row_1["reconciled"]


def test_reconcile_flags_a_genuine_wins_discrepancy() -> None:
    """A deliberate mismatch (Sleeper wins=2, derived data only supports wins=1)
    is reported as a discrepancy, not silently passed.
    """
    season_matchup_df = _season_matchup_df(_toy_season_matchup_rows())
    rosters_df = _rosters_df(
        [
            # Sleeper says roster 1 has 2 wins; the matchup data only
            # supports 1 win (see the toy example docstring).
            _roster_row(1, wins=2, losses=0, ties=1, fpts=230.0, fpts_against=210.0),
            _roster_row(2, wins=0, losses=1, ties=0, fpts=195.0, fpts_against=120.0),
            _roster_row(3, wins=0, losses=0, ties=1, fpts=200.0, fpts_against=110.0),
        ]
    )
    teams_df = _teams_df(
        [_team_row(1, "Alice"), _team_row(2, "Bob"), _team_row(3, "Cara")]
    )
    standings_df = build_standings(rosters_df, teams_df)

    result = reconcile_matchups_to_standings(season_matchup_df, standings_df)

    row_1 = result.loc[result["roster_id"] == 1].iloc[0]
    assert row_1["derived_wins"] == 1
    assert row_1["sleeper_wins"] == 2
    assert row_1["wins_diff"] == -1
    assert not row_1["wins_match"]
    assert not row_1["reconciled"]

    # Other rosters, and other metrics for roster 1, are unaffected.
    row_2 = result.loc[result["roster_id"] == 2].iloc[0]
    assert row_2["reconciled"]
    assert row_1["points_for_match"]


def test_playoff_rows_are_included_in_derived_totals() -> None:
    """Excluding playoff rows produces a spurious mismatch against Sleeper's
    cumulative (regular season + playoff) standings counters -- proving that
    reconciliation must include playoff rows, per the module docstring.
    """
    all_rows = _toy_season_matchup_rows()
    regular_season_only = _season_matchup_df(
        [row for row in all_rows if not row["is_playoff"]]
    )

    rosters_df = _rosters_df(
        [
            _roster_row(1, wins=1, losses=0, ties=1, fpts=230.0, fpts_against=210.0),
            _roster_row(2, wins=0, losses=1, ties=0, fpts=195.0, fpts_against=120.0),
            _roster_row(3, wins=0, losses=0, ties=1, fpts=200.0, fpts_against=110.0),
        ]
    )
    teams_df = _teams_df(
        [_team_row(1, "Alice"), _team_row(2, "Bob"), _team_row(3, "Cara")]
    )
    standings_df = build_standings(rosters_df, teams_df)

    # Using every row (including the playoff week) reconciles cleanly.
    full_result = reconcile_matchups_to_standings(
        _season_matchup_df(all_rows), standings_df
    )
    assert full_result["reconciled"].all()

    # Dropping the playoff row leaves roster 1 and roster 3's tie
    # unaccounted for -- their derived ties/points no longer match
    # Sleeper's cumulative (regular season + playoff) standings.
    partial_result = reconcile_matchups_to_standings(regular_season_only, standings_df)
    row_1 = partial_result.loc[partial_result["roster_id"] == 1].iloc[0]
    row_3 = partial_result.loc[partial_result["roster_id"] == 3].iloc[0]
    assert not row_1["ties_match"]
    assert not row_3["ties_match"]
    assert not row_1["reconciled"]
    assert not row_3["reconciled"]


def test_bye_row_contributes_only_points_for_no_points_against_or_record() -> None:
    """A single bye row: points_for gets the bye score, everything else stays 0."""
    season_matchup_df = _season_matchup_df(
        [
            _matchup_row(
                roster_1_id=7,
                roster_2_id=None,
                points_1=55.5,
                points_2=None,
                winner=None,
                loser=None,
                matchup_id=None,
            )
        ]
    )

    totals = derive_roster_totals(season_matchup_df)

    assert len(totals) == 1
    row = totals.iloc[0]
    assert row["roster_id"] == 7
    assert row["points_for"] == pytest.approx(55.5)
    assert row["points_against"] == 0.0
    assert row["wins"] == 0
    assert row["losses"] == 0
    assert row["ties"] == 0

    rosters_df = _rosters_df(
        [_roster_row(7, wins=0, losses=0, ties=0, fpts=55.5, fpts_against=0.0)]
    )
    teams_df = _teams_df([_team_row(7, "Joe")])
    standings_df = build_standings(rosters_df, teams_df)

    result = reconcile_matchups_to_standings(season_matchup_df, standings_df)
    assert result.iloc[0]["reconciled"]


def test_reconcile_empty_season_matchup_df_defaults_derived_totals_to_zero() -> None:
    """No matchup data at all: derived totals default to 0, not NaN.

    If Sleeper's standings are non-zero, this is correctly flagged as a
    mismatch rather than silently skipped.
    """
    rosters_df = _rosters_df(
        [_roster_row(1, wins=3, losses=2, ties=0, fpts=400.0, fpts_against=350.0)]
    )
    teams_df = _teams_df([_team_row(1, "Alice")])
    standings_df = build_standings(rosters_df, teams_df)

    result = reconcile_matchups_to_standings(_season_matchup_df([]), standings_df)

    row = result.iloc[0]
    assert row["derived_wins"] == 0
    assert row["derived_points_for"] == 0.0
    assert row["sleeper_wins"] == 3
    assert not row["wins_match"]
    assert not row["reconciled"]


def test_reconcile_empty_standings_df_leaves_sleeper_values_unknown() -> None:
    """No standings data at all: Sleeper-side values are NaN, not defaulted.

    Every match flag is False -- an unknown value can never be "within
    tolerance."
    """
    season_matchup_df = _season_matchup_df(_toy_season_matchup_rows())
    standings_df = _empty_standings_df()

    result = reconcile_matchups_to_standings(season_matchup_df, standings_df)

    assert len(result) == 3
    assert not result["wins_match"].any()
    assert not result["points_for_match"].any()
    assert not result["reconciled"].any()
    assert result["sleeper_wins"].isna().all()


def test_reconcile_both_inputs_empty_returns_empty_frame_with_columns() -> None:
    result = reconcile_matchups_to_standings(
        _season_matchup_df([]), _empty_standings_df()
    )

    assert result.empty
    assert list(result.columns) == RECONCILIATION_COLUMNS


def test_derive_roster_totals_empty_input_returns_empty_frame_with_columns() -> None:
    df = derive_roster_totals(_season_matchup_df([]))

    assert df.empty
    assert list(df.columns) == DERIVED_TOTALS_COLUMNS


def test_reconcile_roster_absent_from_standings_is_unmatched_not_skipped() -> None:
    """A roster present in the matchup data but missing from standings_df
    entirely is still reported (with unknown/NaN Sleeper values), not
    silently dropped from the reconciliation output.
    """
    season_matchup_df = _season_matchup_df(
        [
            _matchup_row(
                roster_1_id=1,
                roster_2_id=2,
                points_1=100.0,
                points_2=90.0,
                winner=1,
                loser=2,
            )
        ]
    )
    # standings_df only has roster 1 -- roster 2 is missing entirely.
    rosters_df = _rosters_df(
        [_roster_row(1, wins=1, losses=0, ties=0, fpts=100.0, fpts_against=90.0)]
    )
    teams_df = _teams_df([_team_row(1, "Alice")])
    standings_df = build_standings(rosters_df, teams_df)

    result = reconcile_matchups_to_standings(season_matchup_df, standings_df)

    assert len(result) == 2
    row_2 = result.loc[result["roster_id"] == 2].iloc[0]
    assert row_2["derived_losses"] == 1
    assert pd.isna(row_2["sleeper_losses"])
    assert not row_2["losses_match"]
    assert not row_2["reconciled"]

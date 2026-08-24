"""Tests for the league-specific fantasy scoring engine (FFA-063).

Every test here is pure/offline -- pandas arithmetic on hand-built
DataFrames, no HTTP and no dependency on Sleeper or nflverse being
reachable. The toy examples are computed by hand in each test's docstring
or inline comment so the expected ``fantasy_points`` value can be verified
without trusting the implementation under test.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from fantasy_analyzer.players.provider import PLAYER_WEEK_IDENTITY_COLUMNS
from fantasy_analyzer.players.scoring import (
    SCORING_KEY_TO_STAT_COLUMNS,
    ScoringResult,
    calculate_fantasy_points,
)

#: The real scoring_settings block from tests/fixtures/sleeper/league.json,
#: used as the "actual league configuration" for several tests below.
FIXTURE_SCORING_SETTINGS = {
    "pass_yd": 0.04,
    "pass_td": 4,
    "pass_int": -2,
    "rush_yd": 0.1,
    "rush_td": 6,
    "rec": 0.5,
    "rec_yd": 0.1,
    "rec_td": 6,
    "fum_lost": -2,
}


def _stat_row(**overrides: object) -> dict:
    """Build one player-week row with identity columns plus zeroed raw stats."""
    row: dict = {column: None for column in PLAYER_WEEK_IDENTITY_COLUMNS}
    row.update(
        season=2025,
        week=1,
        player_name="Test Player",
        position="QB",
    )
    for stat_column in (
        "completions",
        "attempts",
        "passing_yards",
        "passing_tds",
        "interceptions",
        "sacks",
        "sack_fumbles_lost",
        "carries",
        "rushing_yards",
        "rushing_tds",
        "rushing_fumbles_lost",
        "receptions",
        "targets",
        "receiving_yards",
        "receiving_tds",
        "receiving_fumbles_lost",
    ):
        row[stat_column] = 0
    row.update(overrides)
    return row


# -------------------------
# Hand-checkable toy example
# -------------------------


def test_toy_example_matches_hand_computed_total() -> None:
    """One row, the real fixture scoring_settings, arithmetic checked by hand.

    passing_yards=300 * 0.04       = 12.0
    passing_tds=3    * 4           = 12.0
    interceptions=1  * -2          = -2.0
    rushing_yards=20 * 0.1         =  2.0
    rushing_tds=0    * 6           =  0.0
    rushing_fumbles_lost=1 * -2    = -2.0 (fum_lost; the other two fumble
                                            columns are 0)
    Total                          = 22.0
    """
    stats = pd.DataFrame(
        [
            _stat_row(
                passing_yards=300,
                passing_tds=3,
                interceptions=1,
                rushing_yards=20,
                rushing_fumbles_lost=1,
            )
        ]
    )

    result = calculate_fantasy_points(stats, FIXTURE_SCORING_SETTINGS)

    assert result.unsupported_scoring_keys == []
    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(22.0)


# -------------------------
# Representative categories, one at a time
# -------------------------


@pytest.mark.parametrize(
    "stat_column,stat_value,scoring_key,weight,expected_points",
    [
        ("passing_yards", 250, "pass_yd", 0.04, 10.0),
        ("passing_tds", 2, "pass_td", 4, 8.0),
        ("interceptions", 1, "pass_int", -2, -2.0),
        ("rushing_yards", 80, "rush_yd", 0.1, 8.0),
        ("rushing_tds", 1, "rush_td", 6, 6.0),
        ("receptions", 5, "rec", 0.5, 2.5),
        ("receiving_yards", 60, "rec_yd", 0.1, 6.0),
        ("receiving_tds", 1, "rec_td", 6, 6.0),
    ],
)
def test_single_category_matches_hand_computed_value(
    stat_column: str,
    stat_value: float,
    scoring_key: str,
    weight: float,
    expected_points: float,
) -> None:
    stats = pd.DataFrame([_stat_row(**{stat_column: stat_value})])

    result = calculate_fantasy_points(stats, {scoring_key: weight})

    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(expected_points)
    assert result.unsupported_scoring_keys == []


def test_fum_lost_sums_across_every_fumble_lost_column() -> None:
    """fum_lost applies uniformly to sack/rush/receiving fumbles lost, summed.

    1 + 1 + 1 = 3 fumbles lost, each worth -2 => -6.0 total.
    """
    stats = pd.DataFrame(
        [
            _stat_row(
                sack_fumbles_lost=1,
                rushing_fumbles_lost=1,
                receiving_fumbles_lost=1,
            )
        ]
    )

    result = calculate_fantasy_points(stats, {"fum_lost": -2})

    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(-6.0)


def test_multiple_categories_sum_together() -> None:
    """4 completions * 0.5 + 10 receptions * 1.0 = 12.0."""
    stats = pd.DataFrame([_stat_row(completions=4, receptions=10)])

    result = calculate_fantasy_points(stats, {"pass_cmp": 0.5, "rec": 1.0})

    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(12.0)


# -------------------------
# Missing values
# -------------------------


def test_nan_stat_value_contributes_zero_not_nan() -> None:
    stats = pd.DataFrame([_stat_row(receiving_yards=50)])
    stats.loc[0, "passing_yards"] = float("nan")

    result = calculate_fantasy_points(stats, {"pass_yd": 0.04, "rec_yd": 0.1})

    points = result.points_df.loc[0, "fantasy_points"]
    assert not math.isnan(points)
    # passing_yards (NaN) contributes 0; receiving_yards=50 * 0.1 = 5.0.
    assert points == pytest.approx(5.0)


def test_stat_column_entirely_absent_contributes_zero() -> None:
    """A mapped scoring key whose stat column isn't in the frame at all."""
    stats = pd.DataFrame([{"season": 2025, "week": 1, "receptions": 3}])

    result = calculate_fantasy_points(stats, {"pass_int": -2, "rec": 0.5})

    # pass_int has no interceptions column present -> 0 contribution.
    # rec: 3 * 0.5 = 1.5.
    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(1.5)
    assert result.unsupported_scoring_keys == []


# -------------------------
# Unsupported scoring keys
# -------------------------


def test_unsupported_key_is_surfaced_not_silently_dropped() -> None:
    stats = pd.DataFrame([_stat_row(receptions=4)])

    result = calculate_fantasy_points(
        stats, {"rec": 0.5, "bonus_rec_te": 0.5, "pass_2pt": 2}
    )

    assert result.unsupported_scoring_keys == ["bonus_rec_te", "pass_2pt"]
    # Only the supported "rec" key contributes: 4 * 0.5 = 2.0.
    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(2.0)


def test_unsupported_key_alone_yields_zero_points_for_every_row() -> None:
    stats = pd.DataFrame([_stat_row(), _stat_row()])

    result = calculate_fantasy_points(stats, {"some_unknown_idp_key": 1.0})

    assert result.unsupported_scoring_keys == ["some_unknown_idp_key"]
    assert (result.points_df["fantasy_points"] == 0.0).all()


def test_every_key_in_scoring_key_to_stat_columns_is_recognized() -> None:
    """Sanity check: the documented mapping table round-trips as supported."""
    stats = pd.DataFrame([_stat_row()])
    scoring_settings = {key: 1.0 for key in SCORING_KEY_TO_STAT_COLUMNS}

    result = calculate_fantasy_points(stats, scoring_settings)

    assert result.unsupported_scoring_keys == []


# -------------------------
# Ties
# -------------------------


def test_identical_rows_produce_exactly_equal_fantasy_points() -> None:
    stats = pd.DataFrame(
        [
            _stat_row(passing_yards=300, passing_tds=2),
            _stat_row(passing_yards=300, passing_tds=2),
        ]
    )

    result = calculate_fantasy_points(stats, {"pass_yd": 0.04, "pass_td": 4})

    points = result.points_df["fantasy_points"]
    assert points.iloc[0] == points.iloc[1]


# -------------------------
# Empty input
# -------------------------


def test_empty_dataframe_in_yields_empty_dataframe_out() -> None:
    stats = pd.DataFrame(columns=PLAYER_WEEK_IDENTITY_COLUMNS + ["passing_yards"])

    result = calculate_fantasy_points(stats, FIXTURE_SCORING_SETTINGS)

    assert result.points_df.empty
    assert "fantasy_points" in result.points_df.columns
    assert result.unsupported_scoring_keys == []


def test_empty_scoring_settings_yields_zero_points_for_every_row() -> None:
    stats = pd.DataFrame([_stat_row(passing_yards=300)])

    result = calculate_fantasy_points(stats, {})

    assert result.points_df.loc[0, "fantasy_points"] == 0.0
    assert result.unsupported_scoring_keys == []


# -------------------------
# Return shape
# -------------------------


def test_result_is_a_scoring_result_preserving_original_columns() -> None:
    stats = pd.DataFrame([_stat_row(passing_yards=100)])

    result = calculate_fantasy_points(stats, {"pass_yd": 0.04})

    assert isinstance(result, ScoringResult)
    for column in stats.columns:
        assert column in result.points_df.columns
    assert list(result.points_df.columns[: len(stats.columns)]) == list(stats.columns)
    assert list(result.points_df.columns)[-1] == "fantasy_points"

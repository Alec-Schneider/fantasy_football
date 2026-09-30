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
    TEAM_DEFENSE_KEY_TO_STAT_COLUMNS,
    ScoringResult,
    calculate_fantasy_points,
    calculate_team_defense_points,
    points_allowed_tier,
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
        "passing_interceptions",
        "sacks_suffered",
        "sack_fumbles_lost",
        "passing_2pt_conversions",
        "carries",
        "rushing_yards",
        "rushing_tds",
        "rushing_fumbles_lost",
        "rushing_2pt_conversions",
        "receptions",
        "targets",
        "receiving_yards",
        "receiving_tds",
        "receiving_fumbles_lost",
        "receiving_2pt_conversions",
        "fg_made_0_19",
        "fg_made_20_29",
        "fg_made_30_39",
        "fg_made_40_49",
        "fg_made_50_59",
        "fg_made_60_",
        "fg_missed",
        "pat_made",
        "pat_missed",
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
    passing_interceptions=1 * -2   = -2.0
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
                passing_interceptions=1,
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
        ("passing_interceptions", 1, "pass_int", -2, -2.0),
        ("sacks_suffered", 2, "pass_sack", -1, -2.0),
        ("passing_2pt_conversions", 1, "pass_2pt", 2, 2.0),
        ("rushing_yards", 80, "rush_yd", 0.1, 8.0),
        ("rushing_tds", 1, "rush_td", 6, 6.0),
        ("rushing_2pt_conversions", 1, "rush_2pt", 2, 2.0),
        ("receptions", 5, "rec", 0.5, 2.5),
        ("receiving_yards", 60, "rec_yd", 0.1, 6.0),
        ("receiving_tds", 1, "rec_td", 6, 6.0),
        ("receiving_2pt_conversions", 1, "rec_2pt", 2, 2.0),
        ("fg_made_0_19", 1, "fgm_0_19", 3, 3.0),
        ("fg_made_20_29", 1, "fgm_20_29", 3, 3.0),
        ("fg_made_30_39", 1, "fgm_30_39", 3, 3.0),
        ("fg_made_40_49", 1, "fgm_40_49", 4, 4.0),
        ("fg_missed", 2, "fgmiss", -1, -2.0),
        ("pat_made", 3, "xpm", 1, 3.0),
        ("pat_missed", 1, "xpmiss", -1, -1.0),
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


def test_fgm_50p_sums_the_50_59_and_60_plus_bands() -> None:
    """Sleeper's fgm_50p merges nflverse's separate 50-59/60+ FG bands.

    1 made 50-59 + 1 made 60+ = 2 made kicks in the 50p tier, each worth 5
    => 10.0 total.
    """
    stats = pd.DataFrame([_stat_row(fg_made_50_59=1, fg_made_60_=1)])

    result = calculate_fantasy_points(stats, {"fgm_50p": 5})

    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(10.0)


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

    # pass_int has no passing_interceptions column present -> 0 contribution.
    # rec: 3 * 0.5 = 1.5.
    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(1.5)
    assert result.unsupported_scoring_keys == []


# -------------------------
# Unsupported scoring keys
# -------------------------


def test_unsupported_key_is_surfaced_not_silently_dropped() -> None:
    stats = pd.DataFrame([_stat_row(receptions=4)])

    result = calculate_fantasy_points(
        stats, {"rec": 0.5, "bonus_rec_te": 0.5, "pts_allow_0": 10}
    )

    assert result.unsupported_scoring_keys == ["bonus_rec_te", "pts_allow_0"]
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


# -------------------------
# FFA-112: mappings verified against Sleeper's own players_points
# -------------------------


@pytest.mark.parametrize(
    ("stat_column", "scoring_key", "weight"),
    [
        ("fg_made_50_59", "fgm_50_59", 5),
        ("fg_made_60_", "fgm_60p", 6),
        ("fg_made", "fgm", 3),
        ("special_teams_tds", "st_td", 6),
        ("fumble_recovery_tds", "fum_rec_td", 6),
    ],
)
def test_ffa112_single_column_keys(
    stat_column: str, scoring_key: str, weight: float
) -> None:
    """Keys added by FFA-112: 2 events * weight, no other key contributing."""
    stats = pd.DataFrame([_stat_row(**{stat_column: 2})])

    result = calculate_fantasy_points(stats, {scoring_key: weight})

    assert result.unsupported_scoring_keys == []
    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(2 * weight)


def test_split_long_field_goal_bands_score_each_band_separately() -> None:
    """A league scoring 50-59 at 5 and 60+ at 6 (Zipline's settings).

    One 55-yarder (5) + one 61-yarder (6) = 11.0. Before FFA-112 both keys
    were unmapped and this kicker scored 0.0 for them.
    """
    stats = pd.DataFrame([_stat_row(fg_made_50_59=1, fg_made_60_=1)])

    result = calculate_fantasy_points(stats, {"fgm_50_59": 5, "fgm_60p": 6})

    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(11.0)


def test_blocked_kicks_count_as_misses() -> None:
    """Sleeper charges a blocked FG to fgmiss and a blocked PAT to xpmiss.

    fg_missed=1 + fg_blocked=1 -> 2 misses * -1 = -2.0
    pat_missed=0 + pat_blocked=1 -> 1 miss * -1 = -1.0
    Total -3.0.
    """
    stats = pd.DataFrame([_stat_row(fg_missed=1, fg_blocked=1, pat_blocked=1)])

    result = calculate_fantasy_points(stats, {"fgmiss": -1, "xpmiss": -1})

    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(-3.0)


def test_blocked_kick_columns_absent_keeps_the_old_behavior() -> None:
    """A provider frame without fg_blocked/pat_blocked scores as before."""
    stats = pd.DataFrame([_stat_row(fg_missed=2, pat_missed=1)])
    assert "fg_blocked" not in stats.columns

    result = calculate_fantasy_points(stats, {"fgmiss": -1, "xpmiss": -1})

    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(-3.0)


def test_fum_lost_prefers_fumbles_lost_total_when_present() -> None:
    """A muffed punt is in fumbles_lost_total but in no scrimmage column.

    Scrimmage columns sum to 1; the total is 2 -> 2 * -2 = -4.0.
    """
    stats = pd.DataFrame([_stat_row(rushing_fumbles_lost=1, fumbles_lost_total=2)])

    result = calculate_fantasy_points(stats, {"fum_lost": -2})

    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(-4.0)


def test_fum_lost_falls_back_to_component_sum_row_by_row() -> None:
    """A NaN total on one row falls back to that row's component sum."""
    stats = pd.DataFrame(
        [
            _stat_row(sack_fumbles_lost=1, rushing_fumbles_lost=1),
            _stat_row(receiving_fumbles_lost=1, fumbles_lost_total=3),
        ]
    )
    stats.loc[0, "fumbles_lost_total"] = float("nan")

    result = calculate_fantasy_points(stats, {"fum_lost": -1})

    assert list(result.points_df["fantasy_points"]) == pytest.approx([-2.0, -3.0])


@pytest.mark.parametrize(
    ("rushing_yards", "expected"),
    [(199, 0.0), (200, 2.0), (251, 2.0)],
)
def test_threshold_bonus_is_paid_once_at_the_threshold(
    rushing_yards: int, expected: float
) -> None:
    """bonus_rush_yd_200: a step, not a rate -- paid once at >= 200 yards."""
    stats = pd.DataFrame([_stat_row(rushing_yards=rushing_yards)])

    result = calculate_fantasy_points(stats, {"bonus_rush_yd_200": 2})

    assert result.unsupported_scoring_keys == []
    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(expected)


def test_threshold_bonus_on_missing_stat_is_not_paid() -> None:
    stats = pd.DataFrame([_stat_row()])
    stats.loc[0, "passing_yards"] = float("nan")

    result = calculate_fantasy_points(stats, {"bonus_pass_yd_400": 2})

    assert result.points_df.loc[0, "fantasy_points"] == 0.0


def test_unverified_bonus_keys_stay_unsupported() -> None:
    """Touchdown-length and banded yardage bonuses are surfaced, not guessed."""
    stats = pd.DataFrame([_stat_row(rushing_yards=150)])

    result = calculate_fantasy_points(
        stats, {"rush_td_50p": 1, "bonus_rush_yd_100": 1, "bonus_rec_te": 0.5}
    )

    assert result.unsupported_scoring_keys == [
        "bonus_rec_te",
        "bonus_rush_yd_100",
        "rush_td_50p",
    ]
    assert result.points_df.loc[0, "fantasy_points"] == 0.0


# -------------------------
# FFA-112: team DEF scoring
# -------------------------

#: The three leagues' DEF settings share these values (NWC zeroes ff,
#: def_st_ff and blk_kick; the other two weight them 1/1/2).
DEF_SETTINGS = {
    "sack": 1,
    "int": 2,
    "fum_rec": 2,
    "def_st_fum_rec": 1,
    "ff": 1,
    "def_st_ff": 1,
    "def_td": 6,
    "def_st_td": 6,
    "safe": 2,
    "blk_kick": 2,
    "st_td": 6,
    "st_ff": 1,
    "st_fum_rec": 1,
    "pts_allow_0": 10,
    "pts_allow_1_6": 7,
    "pts_allow_7_13": 4,
    "pts_allow_14_20": 1,
    "pts_allow_21_27": 0,
    "pts_allow_28_34": -1,
    "pts_allow_35p": -4,
    "pass_yd": 0.04,
    "rec": 0.5,
}


def _defense_row(**overrides: float) -> dict:
    row = {
        column: 0.0
        for columns in TEAM_DEFENSE_KEY_TO_STAT_COLUMNS.values()
        for column in columns
    }
    row["def_points_allowed"] = 21.0
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("pts_allow_0", (0.0, 0.0)),
        ("pts_allow_7_13", (7.0, 13.0)),
        ("pts_allow_35p", (35.0, math.inf)),
        ("pts_allow", None),
        ("yds_allow_0_100", None),
    ],
)
def test_points_allowed_tier_parsing(key: str, expected: object) -> None:
    assert points_allowed_tier(key) == expected


def test_team_defense_toy_example_matches_hand_computed_total() -> None:
    """3 sacks (3) + 1 INT (2) + 1 scrimmage recovery (2) + 1 ST recovery (1)
    + 2 forced fumbles (2) + 1 defensive TD (6) + 1 blocked kick (2)
    + 10 points allowed -> the 7-13 tier (4) = 22.0.

    The st_* keys in the settings pay individual players, never the DEF.
    """
    frame = pd.DataFrame(
        [
            _defense_row(
                sacks=3,
                interceptions=1,
                fumble_recoveries=1,
                st_fumble_recoveries=1,
                forced_fumbles=2,
                def_tds=1,
                blocked_kicks=1,
                def_points_allowed=10,
            )
        ]
    )

    result = calculate_team_defense_points(frame, DEF_SETTINGS)

    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(22.0)
    assert result.unsupported_scoring_keys == []


@pytest.mark.parametrize(
    ("allowed", "expected"),
    [
        (0, 10.0),
        (1, 7.0),
        (6, 7.0),
        (7, 4.0),
        (13, 4.0),
        (14, 1.0),
        (20, 1.0),
        (21, 0.0),
        (27, 0.0),
        (28, -1.0),
        (34, -1.0),
        (35, -4.0),
        (52, -4.0),
    ],
)
def test_points_allowed_tier_boundaries_are_inclusive(
    allowed: int, expected: float
) -> None:
    frame = pd.DataFrame([_defense_row(def_points_allowed=allowed)])

    result = calculate_team_defense_points(frame, DEF_SETTINGS)

    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(expected)


def test_team_defense_missing_points_allowed_falls_in_no_tier() -> None:
    frame = pd.DataFrame([_defense_row(sacks=2, def_points_allowed=float("nan"))])

    result = calculate_team_defense_points(frame, DEF_SETTINGS)

    assert result.points_df.loc[0, "fantasy_points"] == pytest.approx(2.0)


def test_team_defense_reports_only_defense_family_gaps() -> None:
    """yds_allow_* and def_2pt are DEF keys this engine cannot score;
    pass_yd/rec are player keys and simply do not apply to a DEF row."""
    frame = pd.DataFrame([_defense_row()])

    result = calculate_team_defense_points(
        frame, {**DEF_SETTINGS, "yds_allow_0_100": 5, "def_2pt": 2}
    )

    assert result.unsupported_scoring_keys == ["def_2pt", "yds_allow_0_100"]


def test_identical_defense_rows_tie_exactly() -> None:
    frame = pd.DataFrame([_defense_row(sacks=4), _defense_row(sacks=4)])

    points = calculate_team_defense_points(frame, DEF_SETTINGS).points_df[
        "fantasy_points"
    ]

    assert points.iloc[0] == points.iloc[1]

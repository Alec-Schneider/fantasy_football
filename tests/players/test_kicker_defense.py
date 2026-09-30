"""Tests for kicker and team-defense projections (FFA-112).

Everything runs on small in-memory frames -- no nflverse download, no
Sleeper call. The integration tests use a four-team synthetic league whose
every projection is computed by hand in the test docstrings.

The synthetic world, 2025 and 2026 weeks 1-3 identically:

- Games each week: AAA (home) 9 - BBB 6, CCC (home) 3 - DDD 12, every
  point a 30-39 yard field goal (3 points each).
- BBB's quarterback is sacked twice a game; nobody else is.
- 2026 week 4 (unplayed): AAA hosts CCC, total 44, AAA favored by 4, so
  AAA's implied total is 24 and CCC's 20. BBB and DDD are on bye.
- 2026 week 5 (unplayed): AAA-CCC and BBB-DDD again, no lines.

With ``fgm_30_39 = 3``, kickers score their team's points: AAA's 9,
BBB's 6, CCC's 3, DDD's 12 per game -- positional mean 7.5. Defenses score
their points-allowed tier plus sacks: AAA 7 + 2 = 9, BBB 4, CCC 4, DDD 7 --
positional mean 6.0.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.players.kicker_defense import (
    KICKER_DEFENSE_PROJECTION_COLUMNS,
    KICKER_DEFENSE_WEEK_COLUMNS,
    KickerDefenseParameters,
    build_kicker_defense_projections,
    build_kicker_weeks,
    build_team_week_schedule,
    fit_kicker_defense_parameters,
    normalize_player_name,
    positional_means,
    project_ppg,
    resolve_kicker_gsis_ids,
    run_kicker_defense_backtest,
    summarize_to_date,
)
from fantasy_analyzer.players.roster_fit import optimal_lineup
from fantasy_analyzer.players.waiver_rankings import FREE_AGENT_PROJECTION_COLUMNS

SETTINGS = {
    "fgm_30_39": 3,
    "xpm": 1,
    "sack": 1,
    "pts_allow_0": 10,
    "pts_allow_1_6": 7,
    "pts_allow_7_13": 4,
    "pts_allow_14_20": 1,
    "pts_allow_21_27": 0,
    "pts_allow_28_34": -1,
    "pts_allow_35p": -4,
}

#: Round numbers so every projection below is hand-checkable.
TOY_PARAMETERS = KickerDefenseParameters(
    n0={"K": 3.0, "DEF": 3.0},
    prior_games={"K": 3.0, "DEF": 3.0},
    implied_total_slope={"K": 0.5, "DEF": -0.5},
    implied_total_center=22.0,
)

#: Team -> (its kicker's GSIS id, display name, field goals per game).
KICKERS = {
    "AAA": ("00-K1", "Kyle Kicksworth", 3),
    "BBB": ("00-K2", "Kris O'Booter", 2),
    "CCC": ("00-K4", "Carl Toe", 1),
    "DDD": ("00-K3", "Dan Boot", 4),
}


def _season_rows(season: int, weeks: range) -> list[dict]:
    rows = []
    for week in weeks:
        for team, (gsis, name, field_goals) in KICKERS.items():
            rows.append(
                {
                    "season": season,
                    "week": week,
                    "season_type": "REG",
                    "player_id": gsis,
                    "player_display_name": name,
                    "position": "K",
                    "position_group": "SPEC",
                    "team": team,
                    "fg_made": field_goals,
                    "fg_made_30_39": field_goals,
                    "pat_made": 0,
                }
            )
        rows.append(
            {
                "season": season,
                "week": week,
                "season_type": "REG",
                "player_id": f"QB-BBB-{season}",
                "player_display_name": "Bea Quarterback",
                "position": "QB",
                "position_group": "QB",
                "team": "BBB",
                "sacks_suffered": 2,
            }
        )
    return rows


def _games() -> pd.DataFrame:
    rows = []
    for season in (2025, 2026):
        for week in (1, 2, 3):
            rows.append(("AAA", "BBB", 9.0, 6.0, None, None, season, week))
            rows.append(("CCC", "DDD", 3.0, 12.0, None, None, season, week))
    rows.append(("AAA", "CCC", None, None, 4.0, 44.0, 2026, 4))
    rows.append(("AAA", "CCC", None, None, None, None, 2026, 5))
    rows.append(("BBB", "DDD", None, None, None, None, 2026, 5))
    return pd.DataFrame(
        [
            {
                "season": season,
                "week": week,
                "game_type": "REG",
                "home_team": home,
                "away_team": away,
                "home_score": home_score,
                "away_score": away_score,
                "spread_line": spread,
                "total_line": total,
            }
            for home, away, home_score, away_score, spread, total, season, week in rows
        ]
    )


@pytest.fixture
def raw_stats_by_season() -> dict[int, pd.DataFrame]:
    current = pd.DataFrame(_season_rows(2026, range(1, 4)))
    # A week-4 stat line that must be ignored at cutoff 3.
    late = current[(current["week"] == 3) & (current["player_id"] == "00-K1")].copy()
    late["week"] = 4
    late[["fg_made", "fg_made_30_39"]] = 10
    return {
        2025: pd.DataFrame(_season_rows(2025, range(1, 4))),
        2026: pd.concat([current, late], ignore_index=True),
    }


@pytest.fixture
def catalog() -> dict:
    teams = {"AAA": "Alpha", "BBB": "Beta", "CCC": "Gamma", "DDD": "Delta"}
    entries = {
        code: {
            "position": "DEF",
            "team": code,
            "first_name": city,
            "last_name": "Squad",
        }
        for code, city in teams.items()
    }
    entries.update(
        {
            "1001": {"position": "K", "team": "AAA", "full_name": "Kyle Kicksworth"},
            # No crosswalk entry: resolved by name ("Jr." and the apostrophe
            # normalize away).
            "1002": {"position": "K", "team": "BBB", "full_name": "Kris O'Booter Jr."},
            # A kicker nflverse has never seen.
            "1003": {"position": "K", "team": "CCC", "full_name": "Newbie Leg"},
            # Unsigned: excluded unless explicitly requested.
            "1004": {"position": "K", "team": None, "full_name": "Cut Kicker"},
            "2001": {"position": "WR", "team": "AAA", "full_name": "Not A Kicker"},
        }
    )
    return entries


@pytest.fixture
def crosswalk() -> pd.DataFrame:
    return pd.DataFrame({"sleeper_player_id": ["1001"], "gsis_id": ["00-K1"]})


@pytest.fixture
def projections(
    catalog: dict, raw_stats_by_season: dict, crosswalk: pd.DataFrame
) -> pd.DataFrame:
    return build_kicker_defense_projections(
        catalog,
        SETTINGS,
        season=2026,
        cutoff_week=3,
        upcoming_week=4,
        raw_stats_by_season=raw_stats_by_season,
        games=_games(),
        crosswalk=crosswalk,
        parameters=TOY_PARAMETERS,
        season_end_week=5,
    )


# -------------------------
# The estimator
# -------------------------


def test_project_ppg_matches_the_documented_worked_example() -> None:
    """g=3 at 12.0, m=17 at 9.0, mean 8.0, n0=20, k=50 -> 8.7424."""
    result = project_ppg(
        pd.Series([3.0]),
        pd.Series([12.0]),
        pd.Series([9.0]),
        pd.Series([17.0]),
        pd.Series([8.0]),
        pd.Series([20.0]),
        pd.Series([50.0]),
    ).iloc[0]

    assert result["prior_resolved_ppg"] == pytest.approx((17 * 9 + 50 * 8) / 67)
    assert result["blend_weight"] == pytest.approx(3 / 23)
    assert result["projected_ppg"] == pytest.approx(8.7424, abs=1e-4)


def test_a_hot_kicker_on_a_thin_prior_is_shrunk_hard() -> None:
    """Three games at 12.0 on a five-game 10.8 prior, mean 7.6, fitted
    defaults (n0=20, k=50)::

        prior = (5 * 10.8 + 50 * 7.6) / 55 = 7.8909
        proj  = 3/23 * 12 + 20/23 * 7.8909 = 8.4269

    The raw 12.0 would top any board; the projection sits under 1 ppg
    above the positional mean.
    """
    result = project_ppg(
        pd.Series([3.0]),
        pd.Series([12.0]),
        pd.Series([10.8]),
        pd.Series([5.0]),
        pd.Series([7.6]),
        pd.Series([20.0]),
        pd.Series([50.0]),
    ).iloc[0]

    assert result["projected_ppg"] == pytest.approx(8.4269, abs=1e-4)


def test_missing_prior_and_no_games_both_fall_back_to_the_positional_mean() -> None:
    """No prior season: prior = mean. No games: weight 0, so projection = prior."""
    result = project_ppg(
        pd.Series([2.0, 0.0]),
        pd.Series([14.0, float("nan")]),
        pd.Series([float("nan"), float("nan")]),
        pd.Series([0.0, 0.0]),
        pd.Series([7.6, 7.6]),
        pd.Series([20.0, 20.0]),
        pd.Series([50.0, 50.0]),
    )

    assert list(result["prior_resolved_ppg"]) == pytest.approx([7.6, 7.6])
    assert result.loc[0, "projected_ppg"] == pytest.approx((2 * 14 + 20 * 7.6) / 22)
    assert result.loc[1, "blend_weight"] == 0.0
    assert result.loc[1, "projected_ppg"] == pytest.approx(7.6)


def test_identical_inputs_project_identically() -> None:
    result = project_ppg(
        *(pd.Series([value, value]) for value in (3.0, 9.0, 8.0, 10.0, 7.5)),
        pd.Series([20.0, 20.0]),
        pd.Series([50.0, 50.0]),
    )

    assert result.loc[0, "projected_ppg"] == result.loc[1, "projected_ppg"]


def _weeks(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": season,
                "week": week,
                "player_id": player_id,
                "player_name": player_id,
                "position": position,
                "team": "AAA",
                "opponent": "BBB",
                "fantasy_points": points,
            }
            for season, week, player_id, position, points in rows
        ],
        columns=KICKER_DEFENSE_WEEK_COLUMNS,
    )


def test_summarize_to_date_counts_only_weeks_through_the_cutoff() -> None:
    weeks = _weeks(
        [
            (2025, 1, "a", "K", 4.0),
            (2025, 2, "a", "K", 8.0),
            (2026, 1, "a", "K", 10.0),
            (2026, 2, "a", "K", 2.0),
            (2026, 3, "a", "K", 6.0),
            (2026, 4, "a", "K", 6.0),
            (2026, 5, "a", "K", 99.0),
        ]
    )

    summary = summarize_to_date(weeks, 2026, 4).loc["a"]

    assert summary["games_to_date"] == 4
    assert summary["ppg_to_date"] == pytest.approx(6.0)
    # Last three games played: weeks 2-4.
    assert summary["last3_ppg"] == pytest.approx((2 + 6 + 6) / 3)
    assert summary["prior_season_ppg"] == pytest.approx(6.0)
    assert summary["prior_season_games"] == 2


def test_positional_mean_falls_back_to_the_prior_season_before_week_one() -> None:
    weeks = _weeks([(2025, 1, "a", "K", 4.0), (2025, 1, "b", "K", 8.0)])

    means = positional_means(summarize_to_date(weeks, 2026, 0))

    assert means == {"K": pytest.approx(6.0)}


# -------------------------
# Identity
# -------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ka'imi Fairbairn", "kaimi fairbairn"),
        ("Joey Slye Jr.", "joey slye"),
        ("Jean-Claude Écarté III", "jean claude ecarte"),
        (None, ""),
    ],
)
def test_normalize_player_name(raw: object, expected: str) -> None:
    assert normalize_player_name(raw) == expected


def test_resolve_kicker_ids_uses_crosswalk_then_name(
    catalog: dict, raw_stats_by_season: dict, crosswalk: pd.DataFrame
) -> None:
    kicker_weeks = build_kicker_weeks(raw_stats_by_season[2026], SETTINGS)

    resolved = resolve_kicker_gsis_ids(catalog, kicker_weeks, crosswalk)

    assert resolved == {"1001": "00-K1", "1002": "00-K2"}


def test_resolve_kicker_ids_breaks_a_name_tie_by_team_or_gives_up() -> None:
    weeks = pd.DataFrame(
        {
            "player_id": ["00-A", "00-B"],
            "player_name": ["Sam Leg", "Sam Leg"],
            "team": ["AAA", "BBB"],
        }
    )
    catalog = {
        "1": {"position": "K", "team": "BBB", "full_name": "Sam Leg"},
        "2": {"position": "K", "team": "CCC", "full_name": "Sam Leg"},
    }

    assert resolve_kicker_gsis_ids(catalog, weeks) == {"1": "00-B"}


# -------------------------
# build_kicker_defense_projections
# -------------------------


def test_one_row_per_kicker_and_defense_with_the_documented_columns(
    projections: pd.DataFrame,
) -> None:
    assert list(projections.columns) == KICKER_DEFENSE_PROJECTION_COLUMNS
    assert projections.columns[: len(FREE_AGENT_PROJECTION_COLUMNS)].tolist() == (
        FREE_AGENT_PROJECTION_COLUMNS
    )
    assert sorted(projections["player_id"]) == [
        "1001",
        "1002",
        "1003",
        "AAA",
        "BBB",
        "CCC",
        "DDD",
    ]
    assert projections["player_id"].is_unique


def test_kicker_projection_hand_checked(projections: pd.DataFrame) -> None:
    """Kyle Kicksworth (AAA): 9.0 ppg in 3 games (the week-4 line of 30 is
    after the cutoff), prior 9.0 over 3, positional mean 7.5, n0 = k = 3::

        prior = (3 * 9 + 3 * 7.5) / 6 = 8.25
        proj  = 0.5 * 9 + 0.5 * 8.25  = 8.625
        week  = 8.625 + 0.5 * (24 - 22) = 9.625   (AAA implied 24)
    """
    row = projections.set_index("player_id").loc["1001"]

    assert row["games_to_date"] == 3
    assert row["ppg_to_date"] == pytest.approx(9.0)
    assert row["projected_ppg"] == pytest.approx(8.625)
    assert row["week_opponent"] == "CCC"
    assert bool(row["week_is_home"]) is True
    assert row["week_implied_points"] == pytest.approx(24.0)
    assert row["week_projected_points"] == pytest.approx(9.625)
    assert row["confidence_tier"] == "medium"
    assert row["remaining_games"] == 2
    assert row["projected_ros_points"] == pytest.approx(8.625 * 2)


def test_name_resolved_kicker_on_bye_projects_zero_this_week(
    projections: pd.DataFrame,
) -> None:
    """Kris O'Booter (BBB) resolves by name. prior = (18 + 22.5) / 6 = 6.75;
    proj = 0.5 * 6 + 0.5 * 6.75 = 6.375. BBB is on bye in week 4."""
    row = projections.set_index("player_id").loc["1002"]

    assert row["gsis_id"] == "00-K2"
    assert bool(row["has_crosswalk"]) is True
    assert row["projected_ppg"] == pytest.approx(6.375)
    assert pd.isna(row["week_opponent"])
    assert row["week_projected_points"] == 0.0
    assert row["bye_week"] == 4


def test_unresolvable_kicker_gets_the_positional_mean(
    projections: pd.DataFrame,
) -> None:
    """Newbie Leg (CCC): no history -> 7.5; CCC implied 20 -> 7.5 - 1.0."""
    row = projections.set_index("player_id").loc["1003"]

    assert bool(row["has_crosswalk"]) is False
    assert row["games_to_date"] == 0
    assert row["projected_ppg"] == pytest.approx(7.5)
    assert row["confidence_tier"] == "low"
    assert row["week_projected_points"] == pytest.approx(6.5)


def test_defense_projection_uses_the_opponents_implied_total(
    projections: pd.DataFrame,
) -> None:
    """AAA DEF: 9.0 ppg (tier 1-6 = 7, plus BBB's 2 sacks) over 3 games,
    prior 9.0 over 3, positional mean 6.0::

        prior = (27 + 18) / 6 = 7.5 ; proj = 0.5 * 9 + 0.5 * 7.5 = 8.25
        week  = 8.25 - 0.5 * (20 - 22) = 9.25   (opponent CCC implied 20)
    """
    defense = projections.set_index("player_id")

    assert defense.loc["AAA", "full_name"] == "Alpha Squad"
    assert defense.loc["AAA", "ppg_to_date"] == pytest.approx(9.0)
    assert defense.loc["AAA", "projected_ppg"] == pytest.approx(8.25)
    assert defense.loc["AAA", "week_projected_points"] == pytest.approx(9.25)
    assert defense.loc["DDD", "week_projected_points"] == 0.0


def test_teamless_kicker_only_when_requested(
    catalog: dict, raw_stats_by_season: dict
) -> None:
    result = build_kicker_defense_projections(
        catalog,
        SETTINGS,
        2026,
        3,
        4,
        raw_stats_by_season,
        _games(),
        parameters=TOY_PARAMETERS,
        season_end_week=5,
        include_player_ids=["1004"],
    ).set_index("player_id")

    assert result.loc["1004", "week_projected_points"] == 0.0
    assert pd.isna(result.loc["1004", "team"])


def test_projection_frame_drops_into_the_lineup_solver(
    projections: pd.DataFrame,
) -> None:
    roster = projections[projections["player_id"].isin(["1001", "1003", "AAA", "BBB"])]

    solution = optimal_lineup(
        roster, ["K", "DEF", "BN"], ppg_column="week_projected_points"
    )

    assert solution.starters == frozenset({"1001", "AAA"})
    assert solution.points_per_game == pytest.approx(9.625 + 9.25)


def test_missing_prior_season_data_is_not_an_error(
    catalog: dict, raw_stats_by_season: dict
) -> None:
    only_current = {2026: raw_stats_by_season[2026]}

    result = build_kicker_defense_projections(
        catalog,
        SETTINGS,
        2026,
        3,
        4,
        only_current,
        _games(),
        parameters=TOY_PARAMETERS,
        season_end_week=5,
    ).set_index("player_id")

    # No prior: prior = positional mean 6.0; proj = 0.5 * 9 + 0.5 * 6.0.
    assert result.loc["AAA", "prior_season_games"] == 0
    assert result.loc["AAA", "projected_ppg"] == pytest.approx(7.5)


# -------------------------
# Fitting and backtest
# -------------------------


def _planted_world() -> tuple[pd.DataFrame, dict[int, pd.DataFrame]]:
    """Kicker points = 0.5 * implied team total; implied rotates weekly."""
    teams = ["T1", "T2", "T3", "T4"]
    weeks_rows, schedule_rows = [], []
    for season in range(2016, 2021):
        for week in range(1, 18):
            for index, team in enumerate(teams):
                implied = 16.0 + 4.0 * ((index + week + season) % 4)
                schedule_rows.append(
                    {
                        "season": season,
                        "week": week,
                        "team": team,
                        "opponent": teams[index ^ 1],
                        "is_home": index % 2 == 0,
                        "implied_team_total": implied,
                        "total_line": 2 * implied,
                        "spread_line": 0.0,
                    }
                )
                weeks_rows.append(
                    {
                        "season": season,
                        "week": week,
                        "player_id": f"k-{team}",
                        "player_name": team,
                        "position": "K",
                        "team": team,
                        "opponent": teams[index ^ 1],
                        "fantasy_points": 0.5 * implied,
                    }
                )
    schedule = pd.DataFrame(schedule_rows)
    return pd.DataFrame(weeks_rows), {
        season: frame for season, frame in schedule.groupby("season")
    }


def test_fit_recovers_a_planted_implied_total_effect() -> None:
    weeks, schedules = _planted_world()

    parameters = fit_kicker_defense_parameters(
        weeks, schedules, [2017, 2018, 2019], n0_grid=(3.0,), prior_games_grid=(3.0,)
    )

    assert parameters.implied_total_slope["K"] == pytest.approx(0.5, abs=0.05)
    assert parameters.implied_total_center == pytest.approx(22.0)


def test_backtest_scores_every_method_on_held_out_seasons() -> None:
    weeks, schedules = _planted_world()

    results = run_kicker_defense_backtest(
        weeks,
        schedules,
        [2019, 2020],
        first_fit_season=2017,
        n0_grid=(3.0, 12.0),
        prior_games_grid=(3.0,),
    )

    assert set(results["season"]) == {2019, 2020}
    assert set(results["horizon"]) == {"ros", "next_week"}
    next_week = results[results["horizon"] == "next_week"].set_index(
        ["season", "method"]
    )
    # With the planted effect, the market adjustment must beat the plain
    # shrinkage projection on the held-out weeks.
    for season in (2019, 2020):
        assert (
            next_week.loc[(season, "shrinkage_plus_implied"), "mae"]
            < next_week.loc[(season, "shrinkage"), "mae"]
        )
    assert (results["n"] > 0).all()


def test_team_week_schedule_folds_historical_codes() -> None:
    games = pd.DataFrame(
        [
            {
                "season": 2019,
                "week": 1,
                "game_type": "REG",
                "home_team": "OAK",
                "away_team": "LA",
                "home_score": 1.0,
                "away_score": 0.0,
                "spread_line": 3.0,
                "total_line": 40.0,
            }
        ]
    )

    schedule = build_team_week_schedule(games, 2019).set_index("team")

    assert set(schedule.index) == {"LV", "LAR"}
    assert schedule.loc["LV", "implied_team_total"] == pytest.approx(21.5)

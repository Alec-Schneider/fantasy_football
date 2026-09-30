"""Tests for the empirical-Bayes rest-of-season projection (FFA-090).

Every claim is checked against a hand-computed toy example, per AGENTS.md's
analytics Definition of Done. No network.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fantasy_analyzer.players.ros_backtest import (
    ROS_METRIC_COLUMNS,
    RosEvaluationSet,
)
from fantasy_analyzer.players.ros_projection import (
    DEFAULT_N0,
    PROJECTION_COLUMN,
    ShrinkageParameters,
    add_ros_projection,
    fit_shrinkage,
    project_ppg,
    run_shrinkage_backtest,
)


def _evaluation_frame(rows: list[dict]) -> pd.DataFrame:
    """A minimal evaluation frame carrying only what the model reads."""
    defaults = {
        "season": 2025,
        "cutoff_week": 4,
        "player_name": "Somebody",
        "position": "WR",
        "points_to_date": 0.0,
        "last3_ppg": 0.0,
        "position_mean_ppg": 0.0,
        "remaining_games": 8,
        "ros_points": 0.0,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _weeks(rows: list[tuple], season: int = 2025) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": season,
                "week": week,
                "player_id": player,
                "player_name": player.title(),
                "position": position,
                "fantasy_points": points,
            }
            for player, position, week, points in rows
        ]
    )


# --------------------------------------------------------------------------
# project_ppg
# --------------------------------------------------------------------------


def test_projection_matches_the_hand_computed_blend() -> None:
    """4 games played, n0 = 4, observed 20, prior 10.

    w = 4 / (4 + 4) = 0.5
    projected = 0.5 * 20 + 0.5 * 10 = 15.0
    """
    frame = _evaluation_frame(
        [
            {
                "player_id": "a",
                "games_to_date": 4,
                "ppg_to_date": 20.0,
                "prior_season_ppg": 10.0,
                "ros_ppg": 0.0,
            }
        ]
    )
    parameters = ShrinkageParameters(n0_by_position={"WR": 4.0})

    assert project_ppg(frame, parameters).iloc[0] == pytest.approx(15.0)


def test_more_games_played_moves_the_projection_toward_the_observation() -> None:
    """Same player, same prior, three sample sizes.

    n0 = 2, observed 20, prior 10:
      2 games  -> w = 2/4  = 0.5   -> 15.0
      6 games  -> w = 6/8  = 0.75  -> 17.5
      18 games -> w = 18/20 = 0.9  -> 19.0
    """
    frame = _evaluation_frame(
        [
            {
                "player_id": name,
                "games_to_date": games,
                "ppg_to_date": 20.0,
                "prior_season_ppg": 10.0,
                "ros_ppg": 0.0,
            }
            for name, games in [("a", 2), ("b", 6), ("c", 18)]
        ]
    )
    projected = project_ppg(frame, ShrinkageParameters(n0_by_position={"WR": 2.0}))

    assert list(projected.round(6)) == pytest.approx([15.0, 17.5, 19.0])


def test_a_player_with_no_prior_falls_back_to_the_positional_mean() -> None:
    """The rookie case, and it must not be a zero prior.

    Positional mean of ppg_to_date over the two rows = (20 + 10) / 2 = 15.
    The rookie has 2 games and n0 = 2, so w = 0.5:
      projected = 0.5 * 10 + 0.5 * 15 = 12.5
    A zero prior would have given 0.5 * 10 + 0.5 * 0 = 5.0.
    """
    frame = _evaluation_frame(
        [
            {
                "player_id": "veteran",
                "games_to_date": 4,
                "ppg_to_date": 20.0,
                "prior_season_ppg": 18.0,
                "ros_ppg": 0.0,
            },
            {
                "player_id": "rookie",
                "games_to_date": 2,
                "ppg_to_date": 10.0,
                "prior_season_ppg": np.nan,
                "ros_ppg": 0.0,
            },
        ]
    )
    projected = project_ppg(frame, ShrinkageParameters(n0_by_position={"WR": 2.0}))

    assert projected.iloc[1] == pytest.approx(12.5)
    assert projected.iloc[1] > 5.0


def test_projection_is_never_null_for_an_observed_player() -> None:
    """Even with every prior missing, the fallback resolves."""
    frame = _evaluation_frame(
        [
            {
                "player_id": name,
                "games_to_date": 3,
                "ppg_to_date": points,
                "prior_season_ppg": np.nan,
                "ros_ppg": 0.0,
            }
            for name, points in [("a", 12.0), ("b", 6.0)]
        ]
    )
    assert project_ppg(frame, ShrinkageParameters(n0_by_position={})).notna().all()


def test_each_position_uses_its_own_fitted_constant() -> None:
    """RB n0 = 1 and TE n0 = 9, same observation and prior.

    observed 20, prior 10, 3 games:
      RB w = 3/4  = 0.75 -> 17.5
      TE w = 3/12 = 0.25 -> 12.5
    """
    frame = _evaluation_frame(
        [
            {
                "player_id": "rb",
                "position": "RB",
                "games_to_date": 3,
                "ppg_to_date": 20.0,
                "prior_season_ppg": 10.0,
                "ros_ppg": 0.0,
            },
            {
                "player_id": "te",
                "position": "TE",
                "games_to_date": 3,
                "ppg_to_date": 20.0,
                "prior_season_ppg": 10.0,
                "ros_ppg": 0.0,
            },
        ]
    )
    projected = project_ppg(
        frame, ShrinkageParameters(n0_by_position={"RB": 1.0, "TE": 9.0})
    )

    assert projected.iloc[0] == pytest.approx(17.5)
    assert projected.iloc[1] == pytest.approx(12.5)


def test_an_unfitted_position_uses_the_default() -> None:
    parameters = ShrinkageParameters(n0_by_position={"WR": 1.0})

    assert parameters.n0_for("WR") == pytest.approx(1.0)
    assert parameters.n0_for("K") == pytest.approx(DEFAULT_N0)
    assert parameters.n0_for(None) == pytest.approx(DEFAULT_N0)


def test_projecting_an_empty_frame_returns_an_empty_series() -> None:
    empty = project_ppg(pd.DataFrame(), ShrinkageParameters(n0_by_position={}))
    assert empty.empty


# --------------------------------------------------------------------------
# add_ros_projection
# --------------------------------------------------------------------------


def test_add_projection_writes_the_column_without_mutating_the_input() -> None:
    frame = _evaluation_frame(
        [
            {
                "player_id": "a",
                "games_to_date": 4,
                "ppg_to_date": 20.0,
                "prior_season_ppg": 10.0,
                "ros_ppg": 15.0,
            }
        ]
    )
    original = RosEvaluationSet(evaluation_df=frame)
    updated = add_ros_projection(
        original, ShrinkageParameters(n0_by_position={"WR": 4.0})
    )

    assert PROJECTION_COLUMN in updated.evaluation_df.columns
    assert PROJECTION_COLUMN not in original.evaluation_df.columns
    assert updated.evaluation_df[PROJECTION_COLUMN].iloc[0] == pytest.approx(15.0)


def test_add_projection_carries_exclusion_counts_through() -> None:
    original = RosEvaluationSet(
        evaluation_df=_evaluation_frame(
            [
                {
                    "player_id": "a",
                    "games_to_date": 4,
                    "ppg_to_date": 20.0,
                    "prior_season_ppg": 10.0,
                    "ros_ppg": 15.0,
                }
            ]
        ),
        excluded_no_games_to_date=7,
        excluded_too_few_remaining=3,
    )
    updated = add_ros_projection(original, ShrinkageParameters(n0_by_position={}))

    assert updated.excluded_no_games_to_date == 7
    assert updated.excluded_too_few_remaining == 3


def test_add_projection_on_an_empty_set_is_a_no_op() -> None:
    empty = RosEvaluationSet(evaluation_df=pd.DataFrame())
    assert add_ros_projection(empty, ShrinkageParameters(n0_by_position={})) is empty


# --------------------------------------------------------------------------
# fit_shrinkage
# --------------------------------------------------------------------------


@pytest.fixture
def prior_heavy_weeks() -> pd.DataFrame:
    """A league where the prior season predicts the rest perfectly.

    Each player scores at his prior-season rate for the rest of the season,
    but his first four weeks are pure noise in the opposite direction. A
    correct fit should therefore choose a LARGE n0 -- hold the prior.
    """
    rows = []
    for index in range(40):
        prior_rate = 5.0 + index * 0.5
        noise_rate = 30.0 - prior_rate
        rows += [(f"p{index}", "WR", week, noise_rate) for week in range(1, 5)]
        rows += [(f"p{index}", "WR", week, prior_rate) for week in range(5, 13)]
    current = _weeks(rows, season=2025)

    prior_rows = []
    for index in range(40):
        prior_rate = 5.0 + index * 0.5
        prior_rows += [(f"p{index}", "WR", week, prior_rate) for week in range(1, 13)]
    return pd.concat([current, _weeks(prior_rows, season=2024)], ignore_index=True)


def test_fit_prefers_a_large_n0_when_the_prior_predicts_best(
    prior_heavy_weeks: pd.DataFrame,
) -> None:
    parameters = fit_shrinkage(
        prior_heavy_weeks,
        fit_seasons=[2025],
        cutoff_weeks=[4],
        season_end_week=12,
        min_rows=10,
    )
    assert parameters.n0_by_position["WR"] >= 10.0


def test_fit_prefers_a_small_n0_when_the_season_to_date_predicts_best() -> None:
    """The mirror case: the current season is the signal, the prior is noise.

    A correct fit chooses a SMALL n0 -- discard the prior quickly.
    """
    rows, prior_rows = [], []
    for index in range(40):
        rate = 5.0 + index * 0.5
        rows += [(f"p{index}", "WR", week, rate) for week in range(1, 13)]
        prior_rows += [(f"p{index}", "WR", week, 30.0 - rate) for week in range(1, 13)]
    weeks = pd.concat(
        [_weeks(rows, season=2025), _weeks(prior_rows, season=2024)],
        ignore_index=True,
    )
    parameters = fit_shrinkage(
        weeks, fit_seasons=[2025], cutoff_weeks=[4], season_end_week=12, min_rows=10
    )

    assert parameters.n0_by_position["WR"] <= 1.0


def test_fit_records_the_seasons_it_used(prior_heavy_weeks: pd.DataFrame) -> None:
    """The property that makes a reported accuracy number honest."""
    parameters = fit_shrinkage(
        prior_heavy_weeks,
        fit_seasons=[2025],
        cutoff_weeks=[4],
        season_end_week=12,
        min_rows=10,
    )
    assert parameters.fit_seasons == (2025,)
    assert parameters.fit_mae["WR"] >= 0.0


def test_a_position_with_too_few_rows_is_left_unfitted(
    prior_heavy_weeks: pd.DataFrame,
) -> None:
    parameters = fit_shrinkage(
        prior_heavy_weeks,
        fit_seasons=[2025],
        cutoff_weeks=[4],
        season_end_week=12,
        min_rows=10_000,
    )
    assert parameters.n0_by_position == {}
    assert parameters.n0_for("WR") == pytest.approx(DEFAULT_N0)


def test_fitting_with_no_usable_seasons_falls_back_cleanly() -> None:
    parameters = fit_shrinkage(
        _weeks([("a", "WR", 1, 10.0)]), fit_seasons=[1999], cutoff_weeks=[4]
    )
    assert parameters.n0_by_position == {}
    assert parameters.fit_seasons == (1999,)


def test_an_empty_grid_is_rejected(prior_heavy_weeks: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="n0_grid must not be empty"):
        fit_shrinkage(
            prior_heavy_weeks, fit_seasons=[2025], cutoff_weeks=[4], n0_grid=()
        )


def test_a_non_positive_n0_candidate_is_rejected(
    prior_heavy_weeks: pd.DataFrame,
) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        fit_shrinkage(
            prior_heavy_weeks,
            fit_seasons=[2025],
            cutoff_weeks=[4],
            n0_grid=(0.0, 2.0),
        )


def test_ties_on_the_grid_resolve_to_the_smallest_n0() -> None:
    """Observed and prior identical, so every n0 gives the same error."""
    rows, prior_rows = [], []
    for index in range(40):
        rate = 5.0 + index * 0.5
        rows += [(f"p{index}", "WR", week, rate) for week in range(1, 13)]
        prior_rows += [(f"p{index}", "WR", week, rate) for week in range(1, 13)]
    weeks = pd.concat(
        [_weeks(rows, season=2025), _weeks(prior_rows, season=2024)],
        ignore_index=True,
    )
    parameters = fit_shrinkage(
        weeks,
        fit_seasons=[2025],
        cutoff_weeks=[4],
        season_end_week=12,
        min_rows=10,
        n0_grid=(1.0, 2.0, 4.0),
    )

    assert parameters.n0_by_position["WR"] == pytest.approx(1.0)


# --------------------------------------------------------------------------
# run_shrinkage_backtest
# --------------------------------------------------------------------------


def test_backtest_never_fits_on_the_season_it_scores() -> None:
    """The leakage guard: a season with too little history is skipped."""
    rows = []
    for season in (2020, 2021, 2022):
        for index in range(30):
            rate = 5.0 + index * 0.5
            rows.append(
                _weeks(
                    [(f"p{index}", "WR", week, rate) for week in range(1, 13)],
                    season=season,
                )
            )
    weeks = pd.concat(rows, ignore_index=True)

    results = run_shrinkage_backtest(
        weeks,
        seasons=[2020, 2021, 2022],
        cutoff_weeks=[4],
        min_fit_seasons=3,
        season_end_week=12,
    )
    # No season has three predecessors within this range, so nothing is scored.
    assert results.empty
    assert list(results.columns) == ROS_METRIC_COLUMNS


def test_backtest_scores_the_projection_alongside_the_baselines() -> None:
    rows = []
    for season in range(2018, 2024):
        for index in range(30):
            rate = 5.0 + index * 0.5
            rows.append(
                _weeks(
                    [(f"p{index}", "WR", week, rate) for week in range(1, 13)],
                    season=season,
                )
            )
    weeks = pd.concat(rows, ignore_index=True)

    results = run_shrinkage_backtest(
        weeks,
        seasons=list(range(2018, 2024)),
        cutoff_weeks=[4],
        min_fit_seasons=3,
        season_end_week=12,
        by_position=False,
    )

    assert PROJECTION_COLUMN in set(results["prediction"])
    assert "ppg_to_date" in set(results["prediction"])
    # 2018-2020 lack three predecessors; 2021-2023 are scored.
    assert sorted(results["season"].unique()) == [2021, 2022, 2023]


def test_backtest_projection_is_perfect_on_a_deterministic_league() -> None:
    """When every player scores a constant rate, the blend must be exact."""
    rows = []
    for season in range(2018, 2024):
        for index in range(30):
            rate = 5.0 + index * 0.5
            rows.append(
                _weeks(
                    [(f"p{index}", "WR", week, rate) for week in range(1, 13)],
                    season=season,
                )
            )
    weeks = pd.concat(rows, ignore_index=True)

    results = run_shrinkage_backtest(
        weeks,
        seasons=list(range(2018, 2024)),
        cutoff_weeks=[4],
        min_fit_seasons=3,
        season_end_week=12,
        by_position=False,
    )
    projection = results[results["prediction"] == PROJECTION_COLUMN]

    assert projection["mae"].max() == pytest.approx(0.0, abs=1e-9)
    assert projection["spearman"].min() == pytest.approx(1.0)


# --------------------------------------------------------------------------
# FFA-101 -- persisting a fitted parameter set
# --------------------------------------------------------------------------


def test_shrinkage_parameters_round_trip(tmp_path) -> None:
    from fantasy_analyzer.players.ros_projection import (
        load_shrinkage_parameters,
        save_shrinkage_parameters,
    )

    parameters = ShrinkageParameters(
        n0_by_position={"RB": 2.0, "WR": 2.0, "TE": 2.5, "QB": 4.0},
        default_n0=3.0,
        fit_seasons=(2016, 2017, 2018),
        fit_mae={"RB": 3.25, "WR": 2.75},
    )
    path = save_shrinkage_parameters(parameters, tmp_path / "nested" / "params.json")
    assert path.exists()

    loaded = load_shrinkage_parameters(path)
    assert loaded is not None
    assert loaded.n0_by_position == parameters.n0_by_position
    assert loaded.default_n0 == 3.0
    assert loaded.fit_seasons == (2016, 2017, 2018)
    assert loaded.fit_mae == {"RB": 3.25, "WR": 2.75}
    # The round-tripped set must behave identically, not merely compare equal.
    assert loaded.n0_for("TE") == 2.5
    assert loaded.n0_for("K") == 3.0


def test_load_shrinkage_parameters_missing_file_returns_none(tmp_path) -> None:
    from fantasy_analyzer.players.ros_projection import load_shrinkage_parameters

    assert load_shrinkage_parameters(tmp_path / "nope.json") is None


def test_load_shrinkage_parameters_corrupt_file_returns_none(tmp_path) -> None:
    """A corrupt fit and a missing fit both mean "use the default".

    Neither should take down a ranking, so both return None rather than
    raising -- see the function's docstring.
    """
    from fantasy_analyzer.players.ros_projection import load_shrinkage_parameters

    path = tmp_path / "params.json"
    path.write_text("{ this is not json")
    assert load_shrinkage_parameters(path) is None

    path.write_text('{"n0_by_position": {"RB": "not-a-number"}}')
    assert load_shrinkage_parameters(path) is None


def test_load_shrinkage_parameters_partial_file_uses_defaults(tmp_path) -> None:
    from fantasy_analyzer.players.ros_projection import (
        DEFAULT_N0,
        load_shrinkage_parameters,
    )

    path = tmp_path / "params.json"
    path.write_text('{"n0_by_position": {"RB": 2.0}}')
    loaded = load_shrinkage_parameters(path)
    assert loaded is not None
    assert loaded.n0_for("RB") == 2.0
    assert loaded.n0_for("WR") == DEFAULT_N0
    assert loaded.fit_seasons == ()


def test_save_shrinkage_parameters_accepts_numpy_scalars(tmp_path) -> None:
    """A parameter set built from a DataFrame carries numpy scalars.

    ``fit_seasons`` in practice comes straight from
    ``scored["season"].unique()``, which yields ``numpy.int64`` --
    rejected outright by ``json.dumps``. Regression test: the first real
    run of ``scripts/fit_shrinkage_parameters.py`` died here after a
    25-minute fit.
    """
    import numpy as np

    from fantasy_analyzer.players.ros_projection import (
        load_shrinkage_parameters,
        save_shrinkage_parameters,
    )

    parameters = ShrinkageParameters(
        n0_by_position={"RB": np.float64(2.0)},
        default_n0=np.float64(3.0),
        fit_seasons=tuple(np.int64(season) for season in (2016, 2017)),
        fit_mae={"RB": np.float64(3.25)},
    )
    path = save_shrinkage_parameters(parameters, tmp_path / "params.json")

    loaded = load_shrinkage_parameters(path)
    assert loaded is not None
    assert loaded.fit_seasons == (2016, 2017)
    assert isinstance(loaded.fit_seasons[0], int)
    assert loaded.n0_for("RB") == 2.0


# --------------------------------------------------------------------------
# fit_shrinkage_on_rows / resolve_prior_by_cell (FFA-111 refactor)
# --------------------------------------------------------------------------


def test_fit_on_rows_matches_fit_shrinkage(prior_heavy_weeks: pd.DataFrame) -> None:
    """The split-out grid search is the same fit, on pre-built rows."""
    from fantasy_analyzer.players.ros_backtest import build_ros_evaluation_set
    from fantasy_analyzer.players.ros_projection import fit_shrinkage_on_rows

    seasons = sorted(prior_heavy_weeks["season"].unique())[1:]
    expected = fit_shrinkage(
        prior_heavy_weeks, seasons, [4], min_rows=1, season_end_week=8
    )
    rows = pd.concat(
        [
            build_ros_evaluation_set(
                prior_heavy_weeks,
                season,
                4,
                prior_season_weeks=prior_heavy_weeks,
                season_end_week=8,
            ).evaluation_df
            for season in seasons
        ],
        ignore_index=True,
    )
    actual = fit_shrinkage_on_rows(rows, seasons, min_rows=1)
    assert actual.n0_by_position == expected.n0_by_position
    assert actual.fit_mae == pytest.approx(expected.fit_mae)
    assert actual.fit_seasons == expected.fit_seasons


def test_fit_on_rows_ignores_rows_outside_the_fit_seasons() -> None:
    from fantasy_analyzer.players.ros_projection import fit_shrinkage_on_rows

    frame = _evaluation_frame(
        [
            {
                "player_id": "a",
                "games_to_date": 2,
                "ppg_to_date": 10.0,
                "prior_season_ppg": 10.0,
                "ros_ppg": 10.0,
                "season": 2030,
            }
        ]
    )
    fitted = fit_shrinkage_on_rows(frame, [2024], min_rows=1)
    assert fitted.n0_by_position == {}
    assert fitted.fit_seasons == (2024,)


def test_resolve_prior_by_cell_never_pools_across_cells() -> None:
    """Each cell's fallback is its own positional mean: 10.0 and 30.0.

    Pooled across cells it would be 20.0 for both -- one season's scoring
    leaking into another's prior.
    """
    from fantasy_analyzer.players.ros_projection import resolve_prior_by_cell

    frame = _evaluation_frame(
        [
            {
                "player_id": "a",
                "season": 2024,
                "games_to_date": 1,
                "ppg_to_date": 10.0,
                "prior_season_ppg": np.nan,
                "ros_ppg": 0.0,
            },
            {
                "player_id": "b",
                "season": 2025,
                "games_to_date": 1,
                "ppg_to_date": 30.0,
                "prior_season_ppg": np.nan,
                "ros_ppg": 0.0,
            },
            {
                "player_id": "c",
                "season": 2025,
                "games_to_date": 1,
                "ppg_to_date": 30.0,
                "prior_season_ppg": 12.0,
                "ros_ppg": 0.0,
            },
        ]
    )
    resolved = resolve_prior_by_cell(frame)
    assert resolved.tolist() == pytest.approx([10.0, 30.0, 12.0])

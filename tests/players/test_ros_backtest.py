"""Tests for the rest-of-season backtest harness (FFA-089).

Every metric is verified against a hand-computed toy example, per AGENTS.md's
analytics Definition of Done. No network: all frames are built in memory.

The toy league used by most tests below spans one season, weeks 1-8, with
``season_end_week=8`` so the arithmetic stays checkable by hand.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fantasy_analyzer.players.ros_backtest import (
    DEFAULT_BASELINES,
    ROS_EVALUATION_COLUMNS,
    ROS_METRIC_COLUMNS,
    build_ros_evaluation_set,
    build_scored_player_weeks,
    filter_to_waiver_population,
    run_ros_backtest,
    score_baselines,
    score_ros_predictions,
)


def _weeks(rows: list[tuple]) -> pd.DataFrame:
    """Build a scored-player-week frame from (player, week, points) tuples."""
    return pd.DataFrame(
        [
            {
                "season": 2025,
                "week": week,
                "player_id": player,
                "player_name": player.title(),
                "position": position,
                "fantasy_points": points,
            }
            for player, position, week, points in rows
        ]
    )


@pytest.fixture
def toy_weeks() -> pd.DataFrame:
    """Three WRs over weeks 1-8.

    ``alpha``  weeks 1-4 at 10 points, weeks 5-8 at 20  -> ppg_to_date 10, ros 20
    ``bravo``  weeks 1-4 at 20 points, weeks 5-8 at 10  -> ppg_to_date 20, ros 10
    ``charlie`` weeks 1-4 at 15 points, weeks 5-8 at 15 -> ppg_to_date 15, ros 15
    """
    rows = []
    for week in range(1, 5):
        rows += [
            ("alpha", "WR", week, 10.0),
            ("bravo", "WR", week, 20.0),
            ("charlie", "WR", week, 15.0),
        ]
    for week in range(5, 9):
        rows += [
            ("alpha", "WR", week, 20.0),
            ("bravo", "WR", week, 10.0),
            ("charlie", "WR", week, 15.0),
        ]
    return _weeks(rows)


# --------------------------------------------------------------------------
# build_scored_player_weeks
# --------------------------------------------------------------------------


def test_scores_raw_stats_with_league_settings() -> None:
    """Hand-check: 8 receptions, 120 yards, 1 TD in half-PPR.

    0.5 * 8 + 0.1 * 120 + 6 * 1 = 4 + 12 + 6 = 22.0
    """
    raw = pd.DataFrame(
        [
            {
                "season": 2025,
                "week": 2,
                "season_type": "REG",
                "player_id": "00-0036900",
                "player_display_name": "Ja'Marr Chase",
                "position": "WR",
                "receptions": 8,
                "receiving_yards": 120,
                "receiving_tds": 1,
                "target_share": 0.25,
            }
        ]
    )
    scored = build_scored_player_weeks(
        [raw], {"rec": 0.5, "rec_yd": 0.1, "rec_td": 6}
    )

    assert len(scored) == 1
    assert scored.iloc[0]["fantasy_points"] == pytest.approx(22.0)
    assert scored.iloc[0]["player_id"] == "00-0036900"
    assert scored.iloc[0]["target_share"] == pytest.approx(0.25)


def test_postseason_rows_are_excluded() -> None:
    raw = pd.DataFrame(
        [
            {
                "season": 2025,
                "week": 19,
                "season_type": "POST",
                "player_id": "x",
                "player_display_name": "Playoff Guy",
                "position": "WR",
                "receiving_yards": 100,
            }
        ]
    )
    assert build_scored_player_weeks([raw], {"rec_yd": 0.1}).empty


def test_rows_without_a_player_id_are_dropped() -> None:
    raw = pd.DataFrame(
        [
            {
                "season": 2025,
                "week": 1,
                "season_type": "REG",
                "player_id": None,
                "player_display_name": "Unknown",
                "position": "WR",
                "receiving_yards": 50,
            }
        ]
    )
    assert build_scored_player_weeks([raw], {"rec_yd": 0.1}).empty


def test_empty_input_returns_empty_frame_not_an_error() -> None:
    result = build_scored_player_weeks([], {"rec": 1})
    assert result.empty
    assert "fantasy_points" in result.columns


# --------------------------------------------------------------------------
# build_ros_evaluation_set
# --------------------------------------------------------------------------


def test_evaluation_set_computes_hand_checked_features(
    toy_weeks: pd.DataFrame,
) -> None:
    """Cutoff at week 4 of the toy league.

    alpha: 4 games, 40 points -> ppg_to_date 10; rest 80/4 -> ros_ppg 20
    bravo: 4 games, 80 points -> ppg_to_date 20; rest 40/4 -> ros_ppg 10
    """
    result = build_ros_evaluation_set(
        toy_weeks, season=2025, cutoff_week=4, season_end_week=8
    )
    frame = result.evaluation_df.set_index("player_id")

    assert list(result.evaluation_df.columns) == ROS_EVALUATION_COLUMNS
    assert frame.loc["alpha", "games_to_date"] == 4
    assert frame.loc["alpha", "points_to_date"] == pytest.approx(40.0)
    assert frame.loc["alpha", "ppg_to_date"] == pytest.approx(10.0)
    assert frame.loc["alpha", "remaining_games"] == 4
    assert frame.loc["alpha", "ros_ppg"] == pytest.approx(20.0)
    assert frame.loc["bravo", "ppg_to_date"] == pytest.approx(20.0)
    assert frame.loc["bravo", "ros_ppg"] == pytest.approx(10.0)


def test_last3_ppg_uses_only_the_last_three_weeks_played(
    toy_weeks: pd.DataFrame,
) -> None:
    """A player whose week 4 spikes: last-3 differs from season-to-date.

    delta scores 0, 0, 0, 40 in weeks 1-4.
    ppg_to_date = 40 / 4 = 10. last3_ppg = (0 + 0 + 40) / 3 = 13.333...
    """
    spike = _weeks(
        [("delta", "WR", 1, 0.0), ("delta", "WR", 2, 0.0), ("delta", "WR", 3, 0.0)]
        + [("delta", "WR", 4, 40.0)]
        + [("delta", "WR", week, 5.0) for week in range(5, 9)]
    )
    result = build_ros_evaluation_set(
        pd.concat([toy_weeks, spike], ignore_index=True),
        season=2025,
        cutoff_week=4,
        season_end_week=8,
    )
    delta = result.evaluation_df.set_index("player_id").loc["delta"]

    assert delta["ppg_to_date"] == pytest.approx(10.0)
    assert delta["last3_ppg"] == pytest.approx(40.0 / 3)


def test_missing_weeks_are_absent_not_zero() -> None:
    """A player who misses weeks is averaged over weeks played, not elapsed.

    echo plays weeks 1 and 3 only, 12 points each: ppg_to_date = 12, not 8.
    """
    rows = [("echo", "WR", 1, 12.0), ("echo", "WR", 3, 12.0)]
    rows += [("echo", "WR", week, 6.0) for week in range(5, 9)]
    result = build_ros_evaluation_set(
        _weeks(rows), season=2025, cutoff_week=4, season_end_week=8
    )
    echo = result.evaluation_df.set_index("player_id").loc["echo"]

    assert echo["games_to_date"] == 2
    assert echo["ppg_to_date"] == pytest.approx(12.0)


def test_prior_season_ppg_is_read_from_the_previous_season(
    toy_weeks: pd.DataFrame,
) -> None:
    prior = _weeks([("alpha", "WR", week, 8.0) for week in range(1, 5)])
    prior["season"] = 2024

    result = build_ros_evaluation_set(
        pd.concat([toy_weeks, prior], ignore_index=True),
        season=2025,
        cutoff_week=4,
        season_end_week=8,
        prior_season_weeks=prior,
    )
    frame = result.evaluation_df.set_index("player_id")

    assert frame.loc["alpha", "prior_season_ppg"] == pytest.approx(8.0)
    # A player with no prior season is NaN, not zero -- the rookie case.
    assert pd.isna(frame.loc["bravo", "prior_season_ppg"])


def test_prior_season_column_is_nan_when_no_prior_frame_is_given(
    toy_weeks: pd.DataFrame,
) -> None:
    result = build_ros_evaluation_set(
        toy_weeks, season=2025, cutoff_week=4, season_end_week=8
    )
    assert result.evaluation_df["prior_season_ppg"].isna().all()


def test_min_remaining_games_filters_and_is_counted(
    toy_weeks: pd.DataFrame,
) -> None:
    """A player hurt after the cutoff is excluded, and the count says so."""
    hurt = _weeks(
        [("foxtrot", "WR", week, 10.0) for week in range(1, 5)]
        + [("foxtrot", "WR", 5, 10.0)]
    )
    result = build_ros_evaluation_set(
        pd.concat([toy_weeks, hurt], ignore_index=True),
        season=2025,
        cutoff_week=4,
        season_end_week=8,
        min_remaining_games=4,
    )

    assert "foxtrot" not in set(result.evaluation_df["player_id"])
    assert result.excluded_too_few_remaining == 1


def test_player_with_no_games_before_the_cutoff_is_counted_separately() -> None:
    """A midseason call-up is unobservable at decision time."""
    late = _weeks([("golf", "WR", week, 10.0) for week in range(5, 9)])
    early = _weeks(
        [("hotel", "WR", week, 10.0) for week in range(1, 9)]
    )
    result = build_ros_evaluation_set(
        pd.concat([early, late], ignore_index=True),
        season=2025,
        cutoff_week=4,
        season_end_week=8,
    )

    assert "golf" not in set(result.evaluation_df["player_id"])
    assert result.excluded_no_games_to_date == 1


def test_cutoff_at_or_past_season_end_yields_an_empty_set(
    toy_weeks: pd.DataFrame,
) -> None:
    """Nothing remains to predict -- expected, not an error."""
    result = build_ros_evaluation_set(
        toy_weeks, season=2025, cutoff_week=8, season_end_week=8
    )
    assert result.evaluation_df.empty
    assert list(result.evaluation_df.columns) == ROS_EVALUATION_COLUMNS


def test_week_18_is_excluded_from_the_target_by_default() -> None:
    """Regular-season behavior is explicit: the default ends at week 17."""
    rows = [("india", "WR", week, 10.0) for week in range(1, 5)]
    rows += [("india", "WR", week, 10.0) for week in range(5, 18)]
    rows += [("india", "WR", 18, 100.0)]
    result = build_ros_evaluation_set(_weeks(rows), season=2025, cutoff_week=4)
    india = result.evaluation_df.set_index("player_id").loc["india"]

    assert india["remaining_games"] == 13
    assert india["ros_ppg"] == pytest.approx(10.0)


def test_unknown_season_yields_an_empty_set(toy_weeks: pd.DataFrame) -> None:
    result = build_ros_evaluation_set(toy_weeks, season=1999, cutoff_week=4)
    assert result.evaluation_df.empty


def test_cutoff_week_below_one_is_rejected(toy_weeks: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="cutoff_week must be >= 1"):
        build_ros_evaluation_set(toy_weeks, season=2025, cutoff_week=0)


def test_position_label_survives_reclassification() -> None:
    """A player listed at two positions takes the majority label."""
    rows = [("juliet", "RB", week, 10.0) for week in range(1, 4)]
    rows += [("juliet", "WR", 4, 10.0)]
    rows += [("juliet", "RB", week, 10.0) for week in range(5, 9)]
    result = build_ros_evaluation_set(
        _weeks(rows), season=2025, cutoff_week=4, season_end_week=8
    )
    assert result.evaluation_df.iloc[0]["position"] == "RB"


# --------------------------------------------------------------------------
# score_ros_predictions
# --------------------------------------------------------------------------


def test_metrics_match_a_hand_computed_example() -> None:
    """Three players, predictions off by +2, -1, and 0.

    errors: +2, -1, 0
    mae        = (2 + 1 + 0) / 3 = 1.0
    rmse       = sqrt((4 + 1 + 0) / 3) = sqrt(5/3) = 1.290994...
    mean_error = (2 - 1 + 0) / 3 = 0.333...
    Predicted order (desc) is a, b, c; actual order is a, b, c -- so a
    perfectly monotone ranking: spearman = 1.0
    """
    frame = pd.DataFrame(
        {
            "player_id": ["a", "b", "c"],
            "ros_ppg": [20.0, 15.0, 10.0],
            "guess": [22.0, 14.0, 10.0],
        }
    )
    metrics = score_ros_predictions(frame, "guess", top_n=2)

    assert metrics["n"] == 3
    assert metrics["mae"] == pytest.approx(1.0)
    assert metrics["rmse"] == pytest.approx(np.sqrt(5 / 3))
    assert metrics["mean_error"] == pytest.approx(1 / 3)
    assert metrics["spearman"] == pytest.approx(1.0)
    assert metrics["top_n_hit_rate"] == pytest.approx(1.0)


def test_a_perfectly_inverted_ranking_scores_minus_one() -> None:
    frame = pd.DataFrame(
        {
            "player_id": ["a", "b", "c"],
            "ros_ppg": [20.0, 15.0, 10.0],
            "guess": [1.0, 2.0, 3.0],
        }
    )
    metrics = score_ros_predictions(frame, "guess", top_n=1)

    assert metrics["spearman"] == pytest.approx(-1.0)
    assert metrics["top_n_hit_rate"] == pytest.approx(0.0)


def test_ties_in_the_prediction_use_average_ranks() -> None:
    """Two players tied in the prediction, distinct in the outcome.

    Predicted ranks (ascending, average method): a and b tie at 1.5, c is 3.
    Actual ranks ascending: c=1, b=2, a=3.
    Pearson over (1.5, 1.5, 3) vs (3, 2, 1) = -0.866025...
    """
    frame = pd.DataFrame(
        {
            "player_id": ["a", "b", "c"],
            "ros_ppg": [20.0, 15.0, 10.0],
            "guess": [5.0, 5.0, 9.0],
        }
    )
    metrics = score_ros_predictions(frame, "guess", top_n=1)
    expected = pd.Series([1.5, 1.5, 3.0]).corr(pd.Series([3.0, 2.0, 1.0]))

    assert metrics["spearman"] == pytest.approx(expected)


def test_a_constant_prediction_has_undefined_rank_correlation() -> None:
    """The null model within a position: no variance, so no correlation."""
    frame = pd.DataFrame(
        {
            "player_id": ["a", "b", "c"],
            "ros_ppg": [20.0, 15.0, 10.0],
            "guess": [15.0, 15.0, 15.0],
        }
    )
    metrics = score_ros_predictions(frame, "guess", top_n=1)

    assert np.isnan(metrics["spearman"])
    assert metrics["mae"] == pytest.approx(10 / 3)


def test_rows_with_a_null_prediction_are_excluded_not_imputed() -> None:
    """A model that declines to predict a player is not charged for him."""
    frame = pd.DataFrame(
        {
            "player_id": ["a", "b", "c"],
            "ros_ppg": [20.0, 15.0, 10.0],
            "guess": [20.0, np.nan, 10.0],
        }
    )
    metrics = score_ros_predictions(frame, "guess", top_n=2)

    assert metrics["n"] == 2
    assert metrics["mae"] == pytest.approx(0.0)


def test_all_null_predictions_yield_nan_metrics_and_zero_n() -> None:
    frame = pd.DataFrame(
        {
            "player_id": ["a", "b"],
            "ros_ppg": [20.0, 15.0],
            "guess": [np.nan, np.nan],
        }
    )
    metrics = score_ros_predictions(frame, "guess")

    assert metrics["n"] == 0
    assert np.isnan(metrics["mae"])
    assert np.isnan(metrics["spearman"])


def test_hit_rate_is_undefined_on_a_slate_shorter_than_top_n() -> None:
    frame = pd.DataFrame(
        {"player_id": ["a", "b"], "ros_ppg": [20.0, 15.0], "guess": [20.0, 15.0]}
    )
    assert np.isnan(score_ros_predictions(frame, "guess", top_n=5)["top_n_hit_rate"])


def test_hit_rate_counts_the_overlap() -> None:
    """Top 2 predicted are a, b; top 2 actual are a, c -> 1 of 2 = 0.5."""
    frame = pd.DataFrame(
        {
            "player_id": ["a", "b", "c", "d"],
            "ros_ppg": [30.0, 5.0, 20.0, 1.0],
            "guess": [30.0, 25.0, 10.0, 1.0],
        }
    )
    assert score_ros_predictions(frame, "guess", top_n=2)[
        "top_n_hit_rate"
    ] == pytest.approx(0.5)


def test_hit_rate_ties_break_deterministically_by_player_id() -> None:
    """Equal predictions: the lower player_id is taken, on both sides."""
    frame = pd.DataFrame(
        {
            "player_id": ["a", "b", "c"],
            "ros_ppg": [10.0, 10.0, 1.0],
            "guess": [7.0, 7.0, 1.0],
        }
    )
    first = score_ros_predictions(frame, "guess", top_n=1)["top_n_hit_rate"]
    shuffled = frame.iloc[[2, 1, 0]].reset_index(drop=True)
    second = score_ros_predictions(shuffled, "guess", top_n=1)["top_n_hit_rate"]

    assert first == pytest.approx(1.0)
    assert first == second


def test_scoring_an_absent_column_raises() -> None:
    frame = pd.DataFrame({"player_id": ["a"], "ros_ppg": [1.0]})
    with pytest.raises(KeyError, match="nope"):
        score_ros_predictions(frame, "nope")


# --------------------------------------------------------------------------
# score_baselines / filter_to_waiver_population / run_ros_backtest
# --------------------------------------------------------------------------


def test_score_baselines_covers_every_default_and_pools_positions(
    toy_weeks: pd.DataFrame,
) -> None:
    evaluation_set = build_ros_evaluation_set(
        toy_weeks, season=2025, cutoff_week=4, season_end_week=8
    )
    metrics = score_baselines(evaluation_set, top_n=2)

    assert list(metrics.columns) == ROS_METRIC_COLUMNS
    assert set(metrics["prediction"]) == set(DEFAULT_BASELINES)
    assert set(metrics["position"]) == {"ALL", "WR"}


def test_score_baselines_on_an_empty_set_returns_an_empty_frame() -> None:
    evaluation_set = build_ros_evaluation_set(
        _weeks([("a", "WR", 1, 1.0)]), season=2025, cutoff_week=4
    )
    metrics = score_baselines(evaluation_set)

    assert metrics.empty
    assert list(metrics.columns) == ROS_METRIC_COLUMNS


def test_ppg_to_date_is_a_perfectly_inverted_predictor_in_the_toy_league(
    toy_weeks: pd.DataFrame,
) -> None:
    """The toy league is built so season-to-date scoring is exactly backwards.

    alpha/bravo swap halves, so ppg_to_date ranks bravo > charlie > alpha
    while ros_ppg ranks alpha > charlie > bravo: spearman = -1.
    """
    evaluation_set = build_ros_evaluation_set(
        toy_weeks, season=2025, cutoff_week=4, season_end_week=8
    )
    metrics = score_baselines(evaluation_set, predictions=["ppg_to_date"], top_n=1)
    pooled = metrics[metrics["position"] == "ALL"].iloc[0]

    assert pooled["spearman"] == pytest.approx(-1.0)
    assert pooled["n"] == 3


def test_waiver_filter_keeps_the_below_median_scorers(
    toy_weeks: pd.DataFrame,
) -> None:
    """Median ppg_to_date is charlie's 15; alpha (10) and charlie are kept."""
    evaluation_set = build_ros_evaluation_set(
        toy_weeks, season=2025, cutoff_week=4, season_end_week=8
    )
    filtered = filter_to_waiver_population(evaluation_set)

    assert set(filtered.evaluation_df["player_id"]) == {"alpha", "charlie"}
    # Exclusion counts describe how the input was built, so they carry through.
    assert (
        filtered.excluded_too_few_remaining
        == evaluation_set.excluded_too_few_remaining
    )


def test_waiver_filter_recomputes_the_null_model(toy_weeks: pd.DataFrame) -> None:
    """position_mean_ppg must describe the retained population.

    Retained ros_ppg values are alpha 20 and charlie 15, mean 17.5 -- not
    the full-population mean of (20 + 10 + 15) / 3 = 15.
    """
    evaluation_set = build_ros_evaluation_set(
        toy_weeks, season=2025, cutoff_week=4, season_end_week=8
    )
    filtered = filter_to_waiver_population(evaluation_set)

    assert filtered.evaluation_df["position_mean_ppg"].unique() == pytest.approx(
        [17.5]
    )


def test_waiver_filter_rejects_an_out_of_range_quantile(
    toy_weeks: pd.DataFrame,
) -> None:
    evaluation_set = build_ros_evaluation_set(
        toy_weeks, season=2025, cutoff_week=4, season_end_week=8
    )
    with pytest.raises(ValueError, match=r"quantile must be in \[0, 1\]"):
        filter_to_waiver_population(evaluation_set, quantile=1.5)


def test_run_backtest_stacks_every_cell(toy_weeks: pd.DataFrame) -> None:
    results = run_ros_backtest(
        toy_weeks,
        seasons=[2025],
        cutoff_weeks=[2, 4],
        predictions=["ppg_to_date"],
        season_end_week=8,
        by_position=False,
        top_n=1,
    )

    assert list(results.columns) == ROS_METRIC_COLUMNS
    assert sorted(results["cutoff_week"]) == [2, 4]
    assert set(results["position"]) == {"ALL"}


def test_run_backtest_over_no_evaluable_cells_returns_an_empty_frame(
    toy_weeks: pd.DataFrame,
) -> None:
    results = run_ros_backtest(
        toy_weeks, seasons=[1999], cutoff_weeks=[4], season_end_week=8
    )
    assert results.empty
    assert list(results.columns) == ROS_METRIC_COLUMNS

"""Tests for the opportunity-first usage projection (FFA-111).

Everything runs on small hand-built frames -- no network, no caches. The
toy example is the module docstring's worked example; every number in it is
checked here by hand arithmetic.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from fantasy_analyzer.players.usage_projection import (
    BASE_STATS,
    MODELED_POSITIONS,
    OPPORTUNITY_QUALITY_COLUMNS,
    RATE_DEFINITIONS,
    STAT_LINE_COLUMNS,
    VOLUME_STATS,
    RateParameters,
    UsageModelParameters,
    VolumeParameters,
    blend_projections,
    build_absent_prior_cohort,
    build_opportunity_quality_features,
    build_usage_features,
    build_usage_panel,
    build_usage_targets,
    expected_points,
    fit_blend_weights,
    fit_usage_components,
    load_usage_model_parameters,
    project_usage,
    run_usage_backtest,
    save_usage_model_parameters,
    score_stat_line,
    shrink_rate,
    shrink_volume,
)

HALF_PPR = {"rec": 0.5, "rec_yd": 0.1, "rec_td": 6.0, "rush_yd": 0.1, "rush_td": 6.0}
PPR = {**HALF_PPR, "rec": 1.0}

_ZERO_STATS = {
    "attempts": 0,
    "completions": 0,
    "passing_yards": 0,
    "passing_tds": 0,
    "passing_interceptions": 0,
    "sacks_suffered": 0,
    "sack_fumbles_lost": 0,
    "passing_2pt_conversions": 0,
    "carries": 0,
    "rushing_yards": 0,
    "rushing_tds": 0,
    "rushing_fumbles_lost": 0,
    "rushing_2pt_conversions": 0,
    "targets": 0,
    "receptions": 0,
    "receiving_yards": 0,
    "receiving_tds": 0,
    "receiving_fumbles_lost": 0,
    "receiving_2pt_conversions": 0,
}


def _week(
    player_id: str,
    season: int,
    week: int,
    position: str = "WR",
    points: float = 0.0,
    **stats: float,
) -> dict:
    row = {
        "season": season,
        "week": week,
        "player_id": player_id,
        "player_name": player_id,
        "position": position,
        "fantasy_points": points,
        **_ZERO_STATS,
    }
    row.update(stats)
    return row


def _toy_weeks() -> pd.DataFrame:
    """The worked example: WR ``w1``, three 2025 games, four 2024 games."""
    rows = [
        _week(
            "w1", 2025, 1, targets=10, receptions=6, receiving_yards=80, receiving_tds=1
        ),
        _week("w1", 2025, 2, targets=6, receptions=4, receiving_yards=40),
        _week("w1", 2025, 3, targets=2, receptions=2, receiving_yards=30),
        # After the cutoff: must never influence a week-3 projection.
        _week(
            "w1",
            2025,
            4,
            targets=40,
            receptions=40,
            receiving_yards=900,
            receiving_tds=9,
        ),
    ]
    rows += [
        _week("w1", 2024, week, targets=5, receptions=3, receiving_yards=30)
        for week in range(1, 5)
    ]
    return pd.DataFrame(rows)


def _toy_parameters(**overrides) -> UsageModelParameters:
    """Hand-set constants for the worked example (not fitted)."""
    zero_volume = VolumeParameters(1.0, 0.0, 0.0, 0.0, 0.0)
    volume = {
        "targets": VolumeParameters(
            n0=1.0,
            prior_weight=0.5,
            recency_weight=0.5,
            baseline=8.0,
            no_prior_baseline=4.0,
        ),
        "carries": zero_volume,
        "attempts": zero_volume,
    }
    rates = {
        rate: RateParameters(k=1e6, prior_weight=0.0, mean=0.0)
        for rate in RATE_DEFINITIONS
    }
    rates["catch_rate"] = RateParameters(k=12.0, prior_weight=0.0, mean=0.5)
    rates["receiving_yards_per_target"] = RateParameters(
        k=12.0, prior_weight=0.0, mean=7.5
    )
    rates["receiving_td_rate"] = RateParameters(k=182.0, prior_weight=0.0, mean=0.04)
    fields = dict(
        volume={"WR": volume},
        rates={"WR": rates},
        blend_weight={"WR": 0.75},
        absent_prior_stat_line={
            "WR": {
                **{column: 0.0 for column in STAT_LINE_COLUMNS},
                "targets": 2.0,
                "receptions": 1.0,
                "receiving_yards": 10.0,
            }
        },
    )
    fields.update(overrides)
    return UsageModelParameters(**fields)


# --------------------------------------------------------------------------
# The worked example
# --------------------------------------------------------------------------


def test_toy_example_volume_rates_and_points_by_hand() -> None:
    """Every number in the module docstring's worked example.

    Targets: season mean (10+6+2)/3 = 6, last-2 mean (6+2)/2 = 4, rho=0.5 ->
    observed 5. Prior 5/game over 4 games at weight 0.5 -> 2 pseudo-games.
    Baseline 8 at n0 = 1. (3*5 + 2*5 + 1*8) / (3 + 2 + 1) = 33/6 = 5.5.

    Catch rate (12 + 12*0.5) / (18 + 12) = 0.6.
    Yards/target (150 + 12*7.5) / (18 + 12) = 8.0.
    TD rate (1 + 182*0.04) / (18 + 182) = 8.28/200 = 0.0414 -- the observed
    1/18 = 0.056 is pulled most of the way to the 0.04 positional mean.

    Stat line per game: 5.5 targets, 3.3 receptions, 44 yards, 0.2277 TD.
    Half-PPR: 0.5*3.3 + 0.1*44 + 6*0.2277 = 1.65 + 4.4 + 1.3662 = 7.4162.
    Full PPR adds another 0.5*3.3 = 1.65: 9.0662.
    """
    features = build_usage_features(_toy_weeks(), 2025, 3)
    half = project_usage(features, _toy_parameters(), HALF_PPR).loc["w1"]
    full = project_usage(features, _toy_parameters(), PPR).loc["w1"]

    assert half["projected_targets_per_game"] == pytest.approx(5.5)
    assert half["catch_rate"] == pytest.approx(0.6)
    assert half["receiving_yards_per_target"] == pytest.approx(8.0)
    assert half["receiving_td_rate"] == pytest.approx(0.0414)
    assert half["receptions"] == pytest.approx(3.3)
    assert half["receiving_yards"] == pytest.approx(44.0)
    assert half["receiving_tds"] == pytest.approx(0.2277)
    assert half["usage_projected_ppg"] == pytest.approx(7.4162)
    assert full["usage_projected_ppg"] == pytest.approx(9.0662)
    assert not half["usage_absent_prior"]


def test_toy_example_blend_by_hand() -> None:
    """0.75 * 7.4162 + 0.25 * 10.0 = 8.06215, labelled ``"blend"``."""
    parameters = _toy_parameters()
    features = build_usage_features(_toy_weeks(), 2025, 3)
    usage = project_usage(features, parameters, HALF_PPR)["usage_projected_ppg"]
    final, model = blend_projections(
        pd.Series(["WR"]), pd.Series([10.0]), pd.Series([usage.loc["w1"]]), parameters
    )
    assert final.iloc[0] == pytest.approx(8.06215)
    assert model.iloc[0] == "blend"


def test_features_never_read_past_the_cutoff() -> None:
    """Week 4's 40 targets must not move a week-3 feature (no leakage)."""
    weeks = _toy_weeks()
    features = build_usage_features(weeks, 2025, 3).loc["w1"]
    assert features["games_to_date"] == 3
    assert features["targets_to_date"] == 18
    assert features["targets_recent"] == pytest.approx(4.0)
    assert features["prior_games"] == 4
    assert features["targets_prior"] == 20

    past_only = weeks[(weeks["season"] < 2025) | (weeks["week"] <= 3)]
    without_future = build_usage_features(past_only, 2025, 3)
    pd.testing.assert_frame_equal(
        build_usage_features(weeks, 2025, 3), without_future, check_like=True
    )


def test_targets_are_regular_season_rest_of_season_only() -> None:
    weeks = pd.concat(
        [_toy_weeks(), pd.DataFrame([_week("w1", 2025, 18, targets=99)])],
        ignore_index=True,
    )
    targets = build_usage_targets(weeks, 2025, 3, season_end_week=17).loc["w1"]
    assert targets["ros_games"] == 1
    assert targets["targets_ros"] == 40


# --------------------------------------------------------------------------
# Shrinkage primitives: missing values and edge cases
# --------------------------------------------------------------------------


def test_shrink_volume_zero_games_uses_prior_and_baseline() -> None:
    values = VolumeParameters(
        n0=2.0,
        prior_weight=0.5,
        recency_weight=0.5,
        baseline=6.0,
        no_prior_baseline=3.0,
    )
    # No games, NaN observed/recent: (0 + 0.5*4*10 + 2*6) / (0 + 2 + 2) = 32/4.
    result = shrink_volume(
        np.array([0.0]),
        np.array([np.nan]),
        np.array([np.nan]),
        np.array([4.0]),
        np.array([10.0]),
        np.array([6.0]),
        values,
    )
    assert result[0] == pytest.approx(8.0)


def test_shrink_volume_snap_term_and_missing_snap_share() -> None:
    values = VolumeParameters(
        n0=1.0,
        prior_weight=0.0,
        recency_weight=0.0,
        baseline=4.0,
        no_prior_baseline=4.0,
        snap_n0=2.0,
        snap_slope=10.0,
    )
    arrays = (
        np.array([2.0, 2.0]),
        np.array([6.0, 6.0]),
        np.array([6.0, 6.0]),
        np.array([0.0, 0.0]),
        np.array([0.0, 0.0]),
        np.array([4.0, 4.0]),
    )
    result = shrink_volume(*arrays, values, snap_share=np.array([0.9, np.nan]))
    # With snaps: (2*6 + 2*(10*0.9) + 1*4) / (2 + 2 + 1) = 34/5.
    assert result[0] == pytest.approx(6.8)
    # Missing snap share drops the term: (12 + 4) / 3.
    assert result[1] == pytest.approx(16 / 3)


def test_shrink_rate_with_no_opportunities_is_the_target() -> None:
    values = RateParameters(k=0.0, prior_weight=0.0, mean=0.62)
    zero = np.array([0.0])
    assert shrink_rate(zero, zero, zero, zero, values)[0] == pytest.approx(0.62)


def test_shrink_rate_expected_target() -> None:
    """The target becomes the player's expected rate, itself shrunk.

    Expected: (3 + 20*0.05) / (40 + 20) = 4/60. Estimate:
    (2 + 60 * 4/60) / (40 + 60) = 6/100.
    """
    values = RateParameters(k=60.0, prior_weight=0.0, mean=0.05, expected_k=20.0)
    result = shrink_rate(
        np.array([2.0]),
        np.array([40.0]),
        np.array([0.0]),
        np.array([0.0]),
        values,
        expected=(np.array([3.0]), np.array([40.0]), np.array([0.0]), np.array([0.0])),
    )
    assert result[0] == pytest.approx(0.06)


def test_score_stat_line_keeps_missing_rows_missing() -> None:
    line = pd.DataFrame(
        [
            {"receptions": 2.0, "receiving_yards": 20.0},
            {"receptions": np.nan, "receiving_yards": np.nan},
        ]
    )
    points = score_stat_line(line, HALF_PPR)
    assert points.iloc[0] == pytest.approx(3.0)
    assert np.isnan(points.iloc[1])


def test_missing_stat_columns_give_empty_features() -> None:
    bare = pd.DataFrame(
        [
            {
                "season": 2025,
                "week": 1,
                "player_id": "x",
                "position": "WR",
                "fantasy_points": 3.0,
            }
        ]
    )
    assert build_usage_features(bare, 2025, 1).empty


# --------------------------------------------------------------------------
# FFA-104: absent prior, including ties
# --------------------------------------------------------------------------


def test_absent_prior_players_share_the_fitted_line_and_tie() -> None:
    """Zero games and < 4 prior games -> the absent-prior line, exactly.

    Two such WRs (one with no prior at all, one with a one-game prior) get
    identical projections: 0.5*1 + 0.1*10 = 1.5 half-PPR points. A WR with
    a four-game prior and no games is *not* absent: his prior is trusted.
    """
    weeks = pd.DataFrame(
        [
            _week("w1", 2025, 1, targets=5, receptions=3, receiving_yards=30),
            _week("thin", 2024, 18, targets=12, receptions=10, receiving_yards=200),
        ]
        + [
            _week("vet", 2024, week, targets=8, receptions=5, receiving_yards=60)
            for week in range(1, 5)
        ]
    )
    features = build_usage_features(weeks, 2025, 1)
    features.loc["ghost"] = features.loc["thin"] * 0
    features.loc["ghost", "position"] = "WR"
    projected = project_usage(features, _toy_parameters(), HALF_PPR)

    assert projected.loc["thin", "usage_absent_prior"]
    assert projected.loc["ghost", "usage_absent_prior"]
    assert projected.loc["thin", "usage_projected_ppg"] == pytest.approx(1.5)
    assert (
        projected.loc["ghost", "usage_projected_ppg"]
        == projected.loc["thin", "usage_projected_ppg"]
    )
    assert not projected.loc["vet", "usage_absent_prior"]
    assert projected.loc["vet", "usage_projected_ppg"] > 1.5


def test_absent_prior_cohort_selection() -> None:
    """Later-playing players with no games to date and < 4 prior games only."""
    rows = []
    for week in range(4, 9):  # debuts after a week-3 cutoff
        rows.append(_week("rookie", 2025, week, points=4.0, targets=4))
        rows.append(_week("returner", 2025, week, points=9.0, targets=7))
    rows += [_week("returner", 2024, week) for week in range(1, 6)]  # trusted prior
    rows += [_week("cameo", 2025, 5, points=20.0)]  # too few remaining games
    rows += [_week("starter", 2025, week, points=10.0) for week in range(1, 9)]
    cohort = build_absent_prior_cohort(pd.DataFrame(rows), 2025, 3)

    assert cohort["player_id"].tolist() == ["rookie"]
    assert cohort.iloc[0]["ros_ppg"] == pytest.approx(4.0)
    assert cohort.iloc[0]["targets_ros"] == 20


# --------------------------------------------------------------------------
# Blending
# --------------------------------------------------------------------------


def test_blend_falls_back_and_labels() -> None:
    parameters = _toy_parameters(blend_weight={"WR": 1.0, "RB": 0.0, "TE": 0.5})
    positions = pd.Series(["WR", "RB", "TE", "TE", "K", "WR"])
    eb = pd.Series([10.0, 10.0, 10.0, 10.0, 7.0, np.nan])
    usage = pd.Series([6.0, 6.0, 6.0, np.nan, np.nan, np.nan])
    final, model = blend_projections(positions, eb, usage, parameters)

    assert final.tolist()[:5] == pytest.approx([6.0, 10.0, 8.0, 10.0, 7.0])
    assert np.isnan(final.iloc[5])
    assert model.tolist() == ["usage", "eb", "blend", "eb", "eb", None]


def test_fit_blend_weights_extremes_and_ties() -> None:
    positions = pd.Series(["WR"] * 40 + ["TE"] * 40)
    actual = pd.Series(np.linspace(1, 20, 80))
    # WR: usage is exact -> weight 1. TE: EB is exact -> weight 0.
    usage = actual.where(positions == "WR", actual + 3.0)
    eb = actual.where(positions == "TE", actual - 3.0)
    weights, metrics = fit_blend_weights(positions, eb, usage, actual)
    assert weights == {"TE": 0.0, "WR": 1.0}
    assert metrics["WR"]["mae_usage"] == pytest.approx(0.0)

    # Identical predictions: every weight ties, so the smallest (EB) wins.
    tied, _ = fit_blend_weights(positions, actual + 1.0, actual + 1.0, actual)
    assert tied == {"TE": 0.0, "WR": 0.0}


# --------------------------------------------------------------------------
# Opportunity quality (snap share, xFP)
# --------------------------------------------------------------------------


def _usage_rows() -> pd.DataFrame:
    base = {
        "ep_rec_fantasy_points_exp": np.nan,
        "ep_rush_fantasy_points_exp": np.nan,
        "ep_total_fantasy_points_exp_team": np.nan,
    }
    rows = [
        {
            "season": 2025,
            "week": 1,
            "gsis_id": "g1",
            "offense_snaps": 40,
            "offense_snap_pct": 0.5,
            "ep_rec_attempt": 5.0,
            "ep_receptions_exp": 4.0,
            "ep_rec_yards_gained_exp": 50.0,
            "ep_rec_touchdown_exp": 0.5,
            **base,
            "ep_rec_fantasy_points_exp": 16.0,
            "ep_rush_fantasy_points_exp": 0.0,
            "ep_total_fantasy_points_exp_team": 80.0,
        },
        {
            "season": 2025,
            "week": 2,
            "gsis_id": "g1",
            "offense_snaps": 60,
            "offense_snap_pct": 0.75,
            **base,
        },  # snaps, no charted opportunity: xFP contributes nothing
        {
            "season": 2025,
            "week": 3,
            "gsis_id": "g1",
            "offense_snaps": 80,
            "offense_snap_pct": 1.0,
            **base,
        },
        {
            "season": 2025,
            "week": 4,
            "gsis_id": "g1",
            "offense_snaps": 0,
            "offense_snap_pct": 0.0,
            "ep_rec_attempt": 30.0,
            **base,
        },  # after the cutoff
    ]
    return pd.DataFrame(rows)


def test_opportunity_quality_features_by_hand() -> None:
    """Snap share mean(0.5, 0.75, 1.0) = 0.75; last-2 mean(0.75, 1.0) = 0.875.

    xFP (half-PPR): 0.5*4 + 0.1*50 + 6*0.5 = 10.0; full PPR 12.0. xFP share
    16/80 = 0.2. Week 4 is past the cutoff and is ignored.
    """
    usage = _usage_rows()
    half = build_opportunity_quality_features(usage, 2025, 3, HALF_PPR).loc["g1"]
    full = build_opportunity_quality_features(usage, 2025, 3, PPR).loc["g1"]

    assert list(build_opportunity_quality_features(usage, 2025, 3, PPR).columns) == (
        OPPORTUNITY_QUALITY_COLUMNS
    )
    assert half["snap_share"] == pytest.approx(0.75)
    assert half["snap_share_last2"] == pytest.approx(0.875)
    assert half["snap_games_to_date"] == 3
    assert half["xfp_to_date"] == pytest.approx(10.0)
    assert full["xfp_to_date"] == pytest.approx(12.0)
    assert half["xfp_share"] == pytest.approx(0.2)
    assert half["exp_targets_to_date"] == pytest.approx(5.0)


def test_expected_points_is_nan_for_snap_only_rows() -> None:
    points = expected_points(_usage_rows(), PPR)
    assert points.iloc[0] == pytest.approx(12.0)
    assert np.isnan(points.iloc[1])


def test_opportunity_quality_features_absent_usage() -> None:
    assert build_opportunity_quality_features(None, 2025, 3, PPR).empty
    assert build_opportunity_quality_features(pd.DataFrame(), 2025, 3, PPR).empty


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def test_parameters_round_trip_with_fallback(tmp_path) -> None:
    fallback = _toy_parameters()
    parameters = _toy_parameters(fit_seasons=(2015, 2016), no_snap_fallback=fallback)
    path = save_usage_model_parameters(parameters, tmp_path / "usage.json")
    loaded = load_usage_model_parameters(path)

    assert loaded == parameters
    assert loaded.for_snap_data(False) == fallback
    assert loaded.for_snap_data(True) == parameters
    assert json.loads(path.read_text())["fit_seasons"] == [2015, 2016]


def test_load_missing_or_corrupt_returns_none(tmp_path) -> None:
    assert load_usage_model_parameters(tmp_path / "absent.json") is None
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json")
    assert load_usage_model_parameters(corrupt) is None


# --------------------------------------------------------------------------
# Fitting and the rolling-origin backtest on a synthetic corpus
# --------------------------------------------------------------------------


def _synthetic_corpus(seasons=range(2016, 2021), players: int = 40) -> pd.DataFrame:
    """WRs with persistent target volume and a *common* TD rate.

    Targets per game are player-specific and stable, so volume should trust
    the observed data; every player's true TD rate is the same 5%, so the TD
    fit should regress (almost) completely to the mean.
    """
    rng = np.random.default_rng(111)
    true_targets = rng.uniform(2, 10, size=players)
    rows = []
    for season in seasons:
        for index in range(players):
            for week in range(1, 18):
                targets = int(rng.poisson(true_targets[index]))
                receptions = int(rng.binomial(targets, 0.65))
                yards = float(receptions * 12)
                tds = int(rng.binomial(targets, 0.05))
                points = 0.5 * receptions + 0.1 * yards + 6 * tds
                rows.append(
                    _week(
                        f"p{index}",
                        season,
                        week,
                        points=points,
                        targets=targets,
                        receptions=receptions,
                        receiving_yards=yards,
                        receiving_tds=tds,
                    )
                )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def synthetic_panel():
    corpus = _synthetic_corpus()
    panel = build_usage_panel(corpus, range(2017, 2021), [3, 6])
    return corpus, panel


def test_fit_recovers_stable_volume_and_regresses_noise(synthetic_panel) -> None:
    _, panel = synthetic_panel
    parameters = fit_usage_components(panel, [2017, 2018, 2019])
    assert parameters.positions() == ("WR",)
    td = parameters.rates["WR"]["receiving_td_rate"]
    catch = parameters.rates["WR"]["catch_rate"]
    assert td.mean == pytest.approx(0.05, abs=0.01)
    # A common true rate: the TD rate regresses (almost) completely, and
    # regresses harder than the catch rate, whose binomial noise is smaller.
    assert td.k >= 1000
    assert catch.k >= 100
    assert td.k > catch.k
    # Persistent volume: trust the player's own data, prior season included.
    targets = parameters.volume["WR"]["targets"]
    assert targets.n0 <= 2.0
    assert targets.prior_weight >= 0.5
    assert set(parameters.volume["WR"]) == set(VOLUME_STATS)


def test_rolling_backtest_never_sees_later_seasons(synthetic_panel) -> None:
    """Perturbing 2020 must not change the 2019 row: fits use earlier seasons only."""
    corpus, panel = synthetic_panel
    cohort = pd.DataFrame()
    first = run_usage_backtest(panel, cohort, [2019, 2020], HALF_PPR, min_fit_seasons=2)
    assert set(first["prediction"]) >= {
        "projected_ppg",
        "usage_projected_ppg",
        "blended_projected_ppg",
        "ppg_to_date",
    }
    assert set(first["season"]) == {2019, 2020}

    shocked = panel.copy()
    later = shocked["season"] == 2020
    shocked.loc[later, "ros_ppg"] = shocked.loc[later, "ros_ppg"] * 3 + 5
    second = run_usage_backtest(
        shocked, cohort, [2019, 2020], HALF_PPR, min_fit_seasons=2
    )
    pd.testing.assert_frame_equal(
        first[first["season"] == 2019].reset_index(drop=True),
        second[second["season"] == 2019].reset_index(drop=True),
    )


def test_modeled_positions_and_stats_are_consistent() -> None:
    assert MODELED_POSITIONS == ("QB", "RB", "WR", "TE")
    for numerator, denominators in RATE_DEFINITIONS.values():
        assert numerator in BASE_STATS
        assert set(denominators) <= set(VOLUME_STATS)


def test_fumbles_follow_the_scoring_engines_total_when_present() -> None:
    """``fumbles_lost_total`` wins where non-null; the 3-column sum otherwise.

    Mirrors ``scoring.PREFERRED_TOTAL_COLUMNS["fum_lost"]``: week 1 has a
    muffed-punt fumble only the total counts (2 vs 1); week 2's total is
    missing, so the scrimmage columns (1) count.
    """
    weeks = pd.DataFrame(
        [
            _week("w1", 2025, 1, rushing_fumbles_lost=1, fumbles_lost_total=2),
            _week("w1", 2025, 2, receiving_fumbles_lost=1, fumbles_lost_total=np.nan),
        ]
    )
    features = build_usage_features(weeks, 2025, 2).loc["w1"]
    assert features["fumbles_lost_to_date"] == 3

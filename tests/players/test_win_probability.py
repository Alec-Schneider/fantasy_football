"""Tests for the win-probability model (FFA-114). No network, no real files."""

import math

import pandas as pd
import pytest

from fantasy_analyzer.players.win_probability import (
    WinProbabilityParameters,
    load_win_probability_parameters,
    player_score_sd,
    save_win_probability_parameters,
    team_score_sd,
    win_probability,
)


def _params(
    form="constant", multiplier=1.0, coefficients=None, default=6.0, calibrated=True
):
    return WinProbabilityParameters(
        form=form,
        coefficients=coefficients or {"QB": 10.0, "RB": 8.0, "DEF": 4.0},
        default_coefficient=default,
        margin_sd_multiplier=multiplier,
        calibrated=calibrated,
        metadata={"n": 3},
    )


def test_equal_teams_are_a_coin_flip():
    assert win_probability(100.0, 12.0, 100.0, 12.0, _params()) == pytest.approx(0.5)


def test_hand_computed_probability():
    # margin 10, sd 10 and 10 -> spread sqrt(200) = 14.1421, z = 0.70711,
    # Phi(0.70711) = 0.76025 from a normal table.
    p = win_probability(110.0, 10.0, 100.0, 10.0, _params())
    assert p == pytest.approx(0.76025, abs=1e-4)


def test_symmetry_sums_to_one():
    parameters = _params(multiplier=1.3)
    a = win_probability(105.0, 9.0, 98.0, 14.0, parameters)
    b = win_probability(98.0, 14.0, 105.0, 9.0, parameters)
    assert a + b == pytest.approx(1.0)
    assert a > 0.5 > b


def test_lambda_widens_the_margin_sd():
    # Same z = 10 / (2 * 14.1421) = 0.35355 -> Phi = 0.63816 at lambda = 2.
    p1 = win_probability(110.0, 10.0, 100.0, 10.0, _params(multiplier=1.0))
    p2 = win_probability(110.0, 10.0, 100.0, 10.0, _params(multiplier=2.0))
    assert p2 == pytest.approx(0.63816, abs=1e-4)
    assert 0.5 < p2 < p1


def test_no_variance_left_is_the_sign_of_the_margin():
    parameters = _params()
    assert win_probability(101.0, 0.0, 100.0, 0.0, parameters) == 1.0
    assert win_probability(99.0, 0.0, 100.0, 0.0, parameters) == 0.0
    assert win_probability(100.0, 0.0, 100.0, 0.0, parameters) == 0.5


def test_one_sided_variance_is_still_a_normal_probability():
    # Only the opponent has variance: spread = 10, z = 1, Phi(1) = 0.84134.
    p = win_probability(110.0, 0.0, 100.0, 10.0, _params())
    assert p == pytest.approx(0.84134, abs=1e-4)


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        win_probability(float("nan"), 1.0, 0.0, 1.0, _params())
    with pytest.raises(ValueError):
        win_probability(1.0, -1.0, 0.0, 1.0, _params())
    with pytest.raises(ValueError):
        _params(multiplier=0.0)
    with pytest.raises(ValueError):
        WinProbabilityParameters("bogus", {}, 1.0, 1.0, True)


def test_only_pending_rows_count_toward_team_sd():
    lineup = pd.DataFrame(
        {
            "position": ["QB", "RB", "RB"],
            "projection": [20.0, 12.0, 9.0],
            "pending": [True, False, True],
        }
    )
    # QB 10 and the pending RB 8: sqrt(100 + 64) = 12.8062; the played RB adds 0.
    assert team_score_sd(lineup, _params()) == pytest.approx(math.sqrt(164))
    all_final = lineup.assign(pending=False)
    assert team_score_sd(all_final, _params()) == 0.0
    assert team_score_sd(lineup.iloc[0:0], _params()) == 0.0


def test_team_sd_custom_columns_and_missing_pending_flag():
    lineup = pd.DataFrame(
        {"pos": ["QB", "QB"], "proj": [1.0, 1.0], "live": [True, None]}
    )
    sd = team_score_sd(
        lineup,
        _params(),
        position_column="pos",
        projection_column="proj",
        pending_column="live",
    )
    assert sd == pytest.approx(10.0)  # the None flag is not pending


def test_dst_alias_and_unknown_position():
    parameters = _params()
    assert player_score_sd("DST", 7.0, parameters) == 4.0
    assert player_score_sd("D/ST", 7.0, parameters) == 4.0
    assert player_score_sd("XYZ", 7.0, parameters) == 6.0
    assert player_score_sd(None, 7.0, parameters) == 6.0  # type: ignore[arg-type]


def test_sqrt_form_scales_with_the_projection():
    parameters = _params(form="sqrt", coefficients={"WR": 2.0}, default=3.0)
    assert player_score_sd("WR", 9.0, parameters) == pytest.approx(6.0)
    assert player_score_sd("TE", 16.0, parameters) == pytest.approx(12.0)  # default


def test_nan_and_negative_projection_are_floored_under_sqrt():
    parameters = _params(form="sqrt", coefficients={"WR": 2.0}, default=3.0)
    # Floor of 1.0 point -> 2 * sqrt(1) = 2, never 0 and never NaN.
    assert player_score_sd("WR", float("nan"), parameters) == pytest.approx(2.0)
    assert player_score_sd("WR", -5.0, parameters) == pytest.approx(2.0)
    assert player_score_sd("WR", None, parameters) == pytest.approx(2.0)  # type: ignore[arg-type]
    # The constant form ignores the projection altogether.
    assert player_score_sd("QB", float("nan"), _params()) == 10.0


def test_save_load_round_trip(tmp_path):
    parameters = _params(form="sqrt", multiplier=1.37, calibrated=False)
    path = save_win_probability_parameters(parameters, tmp_path / "sub" / "wp.json")
    assert path.exists()
    loaded = load_win_probability_parameters(path)
    assert loaded == parameters


def test_load_missing_or_corrupt_file_is_none(tmp_path):
    assert load_win_probability_parameters(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_win_probability_parameters(bad) is None
    partial = tmp_path / "partial.json"
    partial.write_text('{"form": "constant"}')
    assert load_win_probability_parameters(partial) is None

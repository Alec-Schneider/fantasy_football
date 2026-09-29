"""Tests for waiver-wire value ranking (FFA-092).

All tests operate on hand-built free-agent pools and small in-memory
scored-player-week frames -- no HTTP calls, no live nflverse/Sleeper access
-- so the shrinkage blend, replacement level, and VORP ranking can all be
verified by hand arithmetic. The toy scenario mirrors the module
docstring's worked example.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from fantasy_analyzer.players.free_agents import FREE_AGENT_POOL_COLUMNS
from fantasy_analyzer.players.ros_projection import ShrinkageParameters
from fantasy_analyzer.players.waiver_rankings import (
    FREE_AGENT_PROJECTION_COLUMNS,
    OPPORTUNITY_SUMMARY_COLUMNS,
    WAIVER_WIRE_RANKING_COLUMNS,
    build_free_agent_ros_projections,
    build_projection_performance_frame,
    build_waiver_wire_rankings,
    confidence_tier,
)

PARAMETERS = ShrinkageParameters(n0_by_position={"WR": 3.0}, default_n0=3.0)


def _pool_row(
    player_id: str,
    position: str,
    gsis_id: str | None,
    has_crosswalk: bool,
    full_name: str = "Player",
    team: str = "SF",
    status: str = "Active",
    player_owned_avg: float | None = None,
) -> dict:
    return {
        "player_id": player_id,
        "full_name": full_name,
        "position": position,
        "team": team,
        "status": status,
        "gsis_id": gsis_id,
        "has_crosswalk": has_crosswalk,
        "player_owned_avg": player_owned_avg,
    }


def _free_agent_pool(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=FREE_AGENT_POOL_COLUMNS)
    frame["has_crosswalk"] = frame["has_crosswalk"].astype(bool)
    frame["player_owned_avg"] = frame["player_owned_avg"].astype("float64")
    return frame


def _week_row(gsis_id: str, season: int, week: int, points: float) -> dict:
    return {
        "season": season,
        "week": week,
        "player_id": gsis_id,
        "player_name": "NFL Player",
        "position": "WR",
        "fantasy_points": points,
    }


# The toy scenario: three WR free agents with a crosswalk match and one
# without. See the module docstring's worked example for WR_A.
POOL = _free_agent_pool(
    [
        _pool_row("10", "WR", "gwa", True, full_name="WR A", player_owned_avg=12.0),
        _pool_row("11", "WR", "gwb", True, full_name="WR B", player_owned_avg=3.0),
        _pool_row("12", "WR", "gwc", True, full_name="WR C", player_owned_avg=1.0),
        _pool_row("13", "WR", None, False, full_name="WR D (no crosswalk)"),
    ]
)

SCORED_WEEKS = pd.DataFrame(
    [
        _week_row("gwa", 2025, 1, 8.0),
        _week_row("gwa", 2025, 2, 12.0),
        _week_row("gwa", 2025, 3, 10.0),
        _week_row("gwa", 2025, 4, 6.0),
        # gwb and gwc: no rows this season -- zero games to date.
    ]
)

PRIOR_SEASON_WEEKS = pd.DataFrame(
    [
        # Four identical weeks: gwb's prior ppg is 5.0 either way, but four
        # games clears DEFAULT_MIN_PRIOR_GAMES so the prior is *trusted*
        # and the toy arithmetic below is the pure blend. See
        # test_thin_prior_season_falls_back_to_positional_mean for the
        # under-sampled case.
        _week_row("gwb", 2024, 1, 5.0),
        _week_row("gwb", 2024, 2, 5.0),
        _week_row("gwb", 2024, 3, 5.0),
        _week_row("gwb", 2024, 4, 5.0),
        # gwc has no prior-season row either -- falls back to the
        # positional mean among free agents with games to date.
    ]
)


# --------------------------------------------------------------------------
# confidence_tier
# --------------------------------------------------------------------------


def test_confidence_tier_thresholds() -> None:
    assert confidence_tier(0) == "low"
    assert confidence_tier(2) == "low"
    assert confidence_tier(3) == "medium"
    assert confidence_tier(7) == "medium"
    assert confidence_tier(8) == "high"
    assert confidence_tier(100) == "high"


def test_confidence_tier_undefined_games_to_date() -> None:
    assert confidence_tier(None) is None
    assert confidence_tier(float("nan")) is None


# --------------------------------------------------------------------------
# build_free_agent_ros_projections
# --------------------------------------------------------------------------


def test_empty_pool_returns_empty_frame() -> None:
    result = build_free_agent_ros_projections(
        _free_agent_pool([]), SCORED_WEEKS, 2025, 4, PARAMETERS
    )
    assert result.empty
    assert list(result.columns) == FREE_AGENT_PROJECTION_COLUMNS


def test_cutoff_week_below_one_raises() -> None:
    with pytest.raises(ValueError, match="cutoff_week"):
        build_free_agent_ros_projections(POOL, SCORED_WEEKS, 2025, 0, PARAMETERS)


def test_toy_projection_matches_module_docstring_worked_example() -> None:
    """WR A: 4 games at 9.0 ppg, alone in the observed pool.

    w = 4 / (4 + 3) = 4/7. With only WR_A having games this season, the
    positional-mean fallback for his own (absent) prior equals his own
    ppg_to_date (9.0), so ``projected_ppg`` collapses to 9.0 regardless of
    the weight -- exactly the module docstring's worked example.
    """
    result = build_free_agent_ros_projections(
        POOL, SCORED_WEEKS, 2025, 4, PARAMETERS, prior_season_weeks=PRIOR_SEASON_WEEKS
    )
    assert len(result) == 4

    wa = result.loc[result["player_id"] == "10"].iloc[0]
    assert wa["games_to_date"] == pytest.approx(4.0)
    assert wa["ppg_to_date"] == pytest.approx(9.0)
    assert wa["prior_resolved_ppg"] == pytest.approx(9.0)
    assert wa["blend_weight"] == pytest.approx(4.0 / 7.0)
    assert wa["projected_ppg"] == pytest.approx(9.0)
    assert wa["remaining_games"] == pytest.approx(13.0)
    assert wa["projected_ros_points"] == pytest.approx(117.0)
    assert wa["confidence_tier"] == "medium"


def test_zero_games_free_agent_uses_prior_season():
    result = build_free_agent_ros_projections(
        POOL, SCORED_WEEKS, 2025, 4, PARAMETERS, prior_season_weeks=PRIOR_SEASON_WEEKS
    )
    wb = result.loc[result["player_id"] == "11"].iloc[0]
    assert wb["games_to_date"] == pytest.approx(0.0)
    assert pd.isna(wb["ppg_to_date"])
    assert wb["prior_season_ppg"] == pytest.approx(5.0)
    assert wb["prior_resolved_ppg"] == pytest.approx(5.0)
    assert wb["blend_weight"] == pytest.approx(0.0)
    assert wb["projected_ppg"] == pytest.approx(5.0)
    assert wb["projected_ros_points"] == pytest.approx(65.0)
    assert wb["confidence_tier"] == "low"


def test_zero_games_no_prior_falls_back_to_positional_mean_of_observed_free_agents():
    result = build_free_agent_ros_projections(
        POOL, SCORED_WEEKS, 2025, 4, PARAMETERS, prior_season_weeks=PRIOR_SEASON_WEEKS
    )
    wc = result.loc[result["player_id"] == "12"].iloc[0]
    assert wc["games_to_date"] == pytest.approx(0.0)
    assert pd.isna(wc["prior_season_ppg"])
    # Fallback: mean ppg_to_date among free agents with >= 1 game this
    # season, which is WR_A alone at 9.0.
    assert wc["prior_resolved_ppg"] == pytest.approx(9.0)
    assert wc["projected_ppg"] == pytest.approx(9.0)
    assert wc["confidence_tier"] == "low"


def test_no_crosswalk_free_agent_gets_null_projection_not_dropped():
    result = build_free_agent_ros_projections(
        POOL, SCORED_WEEKS, 2025, 4, PARAMETERS, prior_season_weeks=PRIOR_SEASON_WEEKS
    )
    assert len(result) == 4
    wd = result.loc[result["player_id"] == "13"].iloc[0]
    assert pd.isna(wd["games_to_date"])
    assert pd.isna(wd["ppg_to_date"])
    assert pd.isna(wd["projected_ppg"])
    assert pd.isna(wd["projected_ros_points"])
    assert wd["confidence_tier"] is None
    # remaining_games is a pure schedule fact -- still populated.
    assert wd["remaining_games"] == pytest.approx(13.0)


def test_season_end_week_controls_remaining_games() -> None:
    result = build_free_agent_ros_projections(
        POOL, SCORED_WEEKS, 2025, 4, PARAMETERS, season_end_week=10
    )
    wa = result.loc[result["player_id"] == "10"].iloc[0]
    assert wa["remaining_games"] == pytest.approx(6.0)


def test_cutoff_at_or_past_season_end_gives_zero_remaining_games() -> None:
    result = build_free_agent_ros_projections(
        POOL, SCORED_WEEKS, 2025, 17, PARAMETERS, season_end_week=17
    )
    assert (result["remaining_games"] == 0.0).all()


# --------------------------------------------------------------------------
# build_waiver_wire_rankings
# --------------------------------------------------------------------------

ROSTER_POSITIONS = ["QB", "RB", "WR", "BN"]
NUM_TEAMS = 3


def test_empty_pool_returns_empty_ranking_frame() -> None:
    result = build_waiver_wire_rankings(
        _free_agent_pool([]),
        SCORED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
    )
    assert result.empty
    assert list(result.columns) == WAIVER_WIRE_RANKING_COLUMNS


def test_toy_waiver_ranking_vorp_and_ties() -> None:
    """Field of 3 WRs with a projection (A, B, C); starter cutoff clamps to 3.

    Replacement = the worst of the three by projected ppg -- WR_B at 5.0
    ppg. ``points_above_replacement = total - 5.0 * 13``:

        WR_A: 117 - 65 = 52     WR_B: 65 - 65 = 0     WR_C: 117 - 65 = 52

    WR_A and WR_C tie for rank 1 (standard competition ranking); WR_B is
    rank 3. WR_D has no crosswalk and so no projection at all -- he is
    excluded from the VORP computation entirely and gets ``NaN`` in every
    VORP column and ``waiver_rank``, sorting last, per the "null, not
    dropped" convention.
    """
    result = build_waiver_wire_rankings(
        POOL,
        SCORED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
    )
    assert len(result) == 4

    by_id = {row["player_id"]: row for _, row in result.iterrows()}

    assert by_id["10"]["replacement_ppg"] == pytest.approx(5.0)
    assert by_id["10"]["points_above_replacement"] == pytest.approx(52.0)
    assert by_id["12"]["points_above_replacement"] == pytest.approx(52.0)
    assert by_id["11"]["points_above_replacement"] == pytest.approx(0.0)

    assert by_id["10"]["waiver_rank"] == pytest.approx(1.0)
    assert by_id["12"]["waiver_rank"] == pytest.approx(1.0)
    assert by_id["11"]["waiver_rank"] == pytest.approx(3.0)
    assert math.isnan(by_id["13"]["waiver_rank"])

    # Explanatory columns survive the merge.
    assert by_id["10"]["blend_weight"] == pytest.approx(4.0 / 7.0)
    assert by_id["10"]["confidence_tier"] == "medium"
    assert by_id["11"]["confidence_tier"] == "low"

    # Unranked player (no crosswalk) sorts last.
    assert result.iloc[-1]["player_id"] == "13"

    # player_owned_avg carried through from the pool.
    assert by_id["10"]["player_owned_avg"] == pytest.approx(12.0)


def test_no_projectable_players_returns_all_null_vorp() -> None:
    only_no_crosswalk = _free_agent_pool(
        [_pool_row("99", "WR", None, False, full_name="Nobody")]
    )
    result = build_waiver_wire_rankings(
        only_no_crosswalk,
        SCORED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
    )
    assert len(result) == 1
    assert math.isnan(result.iloc[0]["waiver_rank"])
    assert math.isnan(result.iloc[0]["points_above_replacement"])


# --------------------------------------------------------------------------
# build_projection_performance_frame
# --------------------------------------------------------------------------


def test_build_projection_performance_frame_shape_and_values() -> None:
    waiver_df = build_waiver_wire_rankings(
        POOL,
        SCORED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
    )
    performance_df = build_projection_performance_frame(waiver_df, season=2025)

    assert set(
        [
            "season",
            "sleeper_player_id",
            "player_name",
            "position",
            "nfl_team",
            "games_played",
            "points_per_game",
            "total_points",
        ]
    ).issubset(performance_df.columns)
    assert (performance_df["season"] == 2025).all()

    wa = performance_df.loc[performance_df["sleeper_player_id"] == "10"].iloc[0]
    assert wa["games_played"] == pytest.approx(13.0)
    assert wa["points_per_game"] == pytest.approx(9.0)
    assert wa["total_points"] == pytest.approx(117.0)

    # No-crosswalk player is included, not dropped -- NaN points_per_game.
    wd = performance_df.loc[performance_df["sleeper_player_id"] == "13"].iloc[0]
    assert pd.isna(wd["points_per_game"])


def test_build_projection_performance_frame_empty_input() -> None:
    result = build_projection_performance_frame(pd.DataFrame(), season=2025)
    assert result.empty
    assert "sleeper_player_id" in result.columns


# --------------------------------------------------------------------------
# FFA-096 -- minimum prior-season games guard
# --------------------------------------------------------------------------


def _thin_prior_pool() -> pd.DataFrame:
    """WR A (4 games this season) plus WR E, whose only prior game was huge."""
    return _free_agent_pool(
        [
            _pool_row("10", "WR", "gwa", True, full_name="WR A"),
            _pool_row("14", "WR", "gwe", True, full_name="WR E (one prior game)"),
        ]
    )


THIN_PRIOR_WEEKS = pd.DataFrame([_week_row("gwe", 2024, 18, 30.0)])


def test_thin_prior_season_falls_back_to_positional_mean() -> None:
    """A one-game prior is reported but not trusted (FFA-096).

    WR E has no 2025 games, so ``w = 0`` exactly and his projection *is*
    his resolved prior. His raw prior is 30.0 ppg off a single week-18
    2024 appearance -- the Phil Mafah case from
    :data:`DEFAULT_MIN_PRIOR_GAMES`'s docstring. With the guard at its
    default of 4 games, the resolved prior falls back to the positional
    mean among WRs with games to date, which is WR A's 9.0 ppg.

    The raw figures survive in the output so a board can show why: the
    guard nulls the *resolved* prior, never the reported one.
    """
    result = build_free_agent_ros_projections(
        _thin_prior_pool(),
        SCORED_WEEKS,
        2025,
        4,
        PARAMETERS,
        prior_season_weeks=THIN_PRIOR_WEEKS,
    )
    we = result.loc[result["player_id"] == "14"].iloc[0]

    assert we["prior_season_ppg"] == pytest.approx(30.0)
    assert we["prior_season_games"] == pytest.approx(1.0)
    assert we["blend_weight"] == pytest.approx(0.0)
    assert we["prior_resolved_ppg"] == pytest.approx(9.0)
    assert we["projected_ppg"] == pytest.approx(9.0)


def test_min_prior_games_zero_restores_the_untrusted_prior() -> None:
    """``min_prior_games=0`` disables the guard entirely."""
    result = build_free_agent_ros_projections(
        _thin_prior_pool(),
        SCORED_WEEKS,
        2025,
        4,
        PARAMETERS,
        prior_season_weeks=THIN_PRIOR_WEEKS,
        min_prior_games=0,
    )
    we = result.loc[result["player_id"] == "14"].iloc[0]
    assert we["prior_resolved_ppg"] == pytest.approx(30.0)
    assert we["projected_ppg"] == pytest.approx(30.0)


def test_min_prior_games_guard_applies_to_players_with_games_to_date() -> None:
    """The guard also reaches the blended population, not just zero-game rows.

    WR A has 4 games at 9.0 ppg and (here) a single 30.0-ppg prior game.
    Guarded, his prior resolves to the positional mean -- which, with WR A
    the only WR who has played, is his own 9.0 -- so the blend is
    ``0.5714 * 9.0 + 0.4286 * 9.0 = 9.0``. Unguarded the prior is trusted
    and the blend pulls upward: ``0.5714 * 9.0 + 0.4286 * 30.0 = 18.0``.
    """
    pool = _free_agent_pool([_pool_row("10", "WR", "gwa", True, full_name="WR A")])
    prior = pd.DataFrame([_week_row("gwa", 2024, 18, 30.0)])

    guarded = build_free_agent_ros_projections(
        pool, SCORED_WEEKS, 2025, 4, PARAMETERS, prior_season_weeks=prior
    ).iloc[0]
    assert guarded["projected_ppg"] == pytest.approx(9.0)

    unguarded = build_free_agent_ros_projections(
        pool,
        SCORED_WEEKS,
        2025,
        4,
        PARAMETERS,
        prior_season_weeks=prior,
        min_prior_games=0,
    ).iloc[0]
    assert unguarded["projected_ppg"] == pytest.approx((4 / 7) * 9.0 + (3 / 7) * 30.0)


def test_min_prior_games_rejects_negative() -> None:
    with pytest.raises(ValueError, match="min_prior_games"):
        build_free_agent_ros_projections(
            POOL, SCORED_WEEKS, 2025, 4, PARAMETERS, min_prior_games=-1
        )


# --------------------------------------------------------------------------
# FFA-095 -- replacement level measured over a league-wide population
# --------------------------------------------------------------------------


ROSTERED_POOL = _free_agent_pool(
    [
        _pool_row("20", "WR", "gws1", True, full_name="Rostered WR 1"),
        _pool_row("21", "WR", "gws2", True, full_name="Rostered WR 2"),
        _pool_row("22", "WR", "gws3", True, full_name="Rostered WR 3"),
    ]
)

ROSTERED_WEEKS = pd.concat(
    [
        SCORED_WEEKS,
        pd.DataFrame(
            [
                _week_row("gws1", 2025, 1, 20.0),
                _week_row("gws2", 2025, 1, 18.0),
                _week_row("gws3", 2025, 1, 16.0),
            ]
        ),
    ],
    ignore_index=True,
)


def test_replacement_population_raises_the_bar_and_is_not_returned() -> None:
    """Rostered players set the replacement level, then leave (FFA-095).

    Without ``replacement_population`` the starter cutoff lands inside the
    free-agent pool alone. With it, three strong rostered WRs enter the
    ranking population, push the last startable WR upward, and are then
    dropped from the output -- only the four free agents come back.
    """
    wire_only = build_waiver_wire_rankings(
        POOL,
        ROSTERED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
    )
    league_wide = build_waiver_wire_rankings(
        POOL,
        ROSTERED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
        replacement_population=ROSTERED_POOL,
    )

    # Same players out, every time: the rostered three never appear.
    assert set(league_wide["player_id"]) == set(POOL["player_id"])
    assert set(wire_only["player_id"]) == set(POOL["player_id"])

    wire_bar = wire_only["replacement_ppg"].dropna().iloc[0]
    league_bar = league_wide["replacement_ppg"].dropna().iloc[0]
    assert league_bar > wire_bar

    # WR B is the one player whose *projection* is population-independent:
    # zero games to date plus a trusted four-game prior means his
    # projected_ppg is 5.0 either way, with no positional-mean fallback
    # involved. So his ppg_above_replacement must drop by exactly the shift
    # in the bar, isolating the replacement-level change from the
    # fallback-prior change documented in the module docstring.
    wire_b = wire_only.loc[wire_only["player_id"] == "11"].iloc[0]
    league_b = league_wide.loc[league_wide["player_id"] == "11"].iloc[0]
    assert wire_b["projected_ppg"] == pytest.approx(5.0)
    assert league_b["projected_ppg"] == pytest.approx(5.0)
    assert wire_b["ppg_above_replacement"] - league_b[
        "ppg_above_replacement"
    ] == pytest.approx(league_bar - wire_bar)


def test_replacement_population_widens_the_fallback_prior() -> None:
    """The positional-mean fallback becomes league-wide too (FFA-095).

    WR C has neither games this season nor a prior season, so his
    projection *is* the positional mean. Over the wire alone that mean is
    WR A's 9.0; adding three rostered WRs at 20/18/16 raises it. This is
    the documented knock-on effect of supplying a replacement_population,
    not an accident -- once the frame of reference is the league, an
    unknown player is measured against the league's average, not the
    wire's.
    """
    wire_only = build_waiver_wire_rankings(
        POOL,
        ROSTERED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
    )
    league_wide = build_waiver_wire_rankings(
        POOL,
        ROSTERED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
        replacement_population=ROSTERED_POOL,
    )

    wire_c = wire_only.loc[wire_only["player_id"] == "12"].iloc[0]
    league_c = league_wide.loc[league_wide["player_id"] == "12"].iloc[0]

    assert wire_c["prior_resolved_ppg"] == pytest.approx(9.0)
    # mean(9.0, 20.0, 18.0, 16.0) -- WR A plus the three rostered WRs.
    assert league_c["prior_resolved_ppg"] == pytest.approx(15.75)
    assert league_c["projected_ppg"] == pytest.approx(15.75)


def test_replacement_population_reranks_only_free_agents() -> None:
    """``waiver_rank`` stays a dense 1..n over the claimable players."""
    result = build_waiver_wire_rankings(
        POOL,
        ROSTERED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
        replacement_population=ROSTERED_POOL,
    )
    ranked = result["waiver_rank"].dropna()
    assert ranked.min() == 1.0
    # Competition ranking, so the set of ranks is a prefix-with-ties, never
    # a sparse remnant of a league-wide rank (which would start above 1).
    assert ranked.max() <= len(ranked)


def test_empty_replacement_population_matches_the_default() -> None:
    baseline = build_waiver_wire_rankings(
        POOL,
        SCORED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
    )
    explicit_empty = build_waiver_wire_rankings(
        POOL,
        SCORED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
        replacement_population=_free_agent_pool([]),
    )
    pd.testing.assert_frame_equal(baseline, explicit_empty)


# --------------------------------------------------------------------------
# FFA-098 -- season-to-date opportunity summary
# --------------------------------------------------------------------------


OPPORTUNITY_WEEKS = pd.DataFrame(
    [
        {
            **_week_row("gwa", 2025, 1, 8.0),
            "targets": 10.0,
            "carries": 1.0,
            "target_share": 0.30,
            "air_yards_share": 0.40,
            "wopr": 0.6,
            "racr": 0.8,
            "receiving_air_yards": 100.0,
            "receiving_epa": 4.0,
            "rushing_epa": 1.0,
            "passing_epa": 0.0,
        },
        {
            # A zero-target week the player *did* play: it must pull the
            # per-game rate down, not be skipped.
            **_week_row("gwa", 2025, 2, 0.0),
            "targets": 0.0,
            "carries": 3.0,
            "target_share": 0.10,
            "air_yards_share": 0.20,
            "wopr": 0.2,
            "racr": 0.4,
            "receiving_air_yards": 0.0,
            "receiving_epa": -2.0,
            "rushing_epa": 1.0,
            "passing_epa": 0.0,
        },
    ]
)


def test_opportunity_columns_are_per_game_summaries() -> None:
    """Rate columns average; volume columns divide by games played."""
    pool = _free_agent_pool([_pool_row("10", "WR", "gwa", True, full_name="WR A")])
    result = build_free_agent_ros_projections(
        pool, OPPORTUNITY_WEEKS, 2025, 4, PARAMETERS
    ).iloc[0]

    assert result["games_to_date"] == pytest.approx(2.0)

    # Rates: mean of the two weeks.
    assert result["target_share"] == pytest.approx(0.20)
    assert result["air_yards_share"] == pytest.approx(0.30)
    assert result["wopr"] == pytest.approx(0.40)
    assert result["racr"] == pytest.approx(0.60)

    # Volumes: total / games_to_date, so the 0-target week counts.
    assert result["targets_per_game"] == pytest.approx(5.0)
    assert result["carries_per_game"] == pytest.approx(2.0)
    assert result["air_yards_per_game"] == pytest.approx(50.0)
    assert result["receiving_epa_per_game"] == pytest.approx(1.0)
    assert result["rushing_epa_per_game"] == pytest.approx(1.0)
    assert result["passing_epa_per_game"] == pytest.approx(0.0)


def test_opportunity_columns_null_when_source_absent() -> None:
    """An older cache with no usage columns yields NaN, not a missing column."""
    result = build_free_agent_ros_projections(
        POOL, SCORED_WEEKS, 2025, 4, PARAMETERS, prior_season_weeks=PRIOR_SEASON_WEEKS
    )
    for column in OPPORTUNITY_SUMMARY_COLUMNS:
        assert column in result.columns
        assert result[column].isna().all()


def test_opportunity_columns_null_for_unplayed_and_uncrosswalked() -> None:
    pool = _free_agent_pool(
        [
            _pool_row("10", "WR", "gwa", True, full_name="WR A"),
            _pool_row("12", "WR", "gwc", True, full_name="WR C (no games)"),
            _pool_row("13", "WR", None, False, full_name="WR D (no crosswalk)"),
        ]
    )
    result = build_free_agent_ros_projections(
        pool, OPPORTUNITY_WEEKS, 2025, 4, PARAMETERS
    ).set_index("player_id")

    assert result.loc["10", "targets_per_game"] == pytest.approx(5.0)
    assert pd.isna(result.loc["12", "targets_per_game"])
    assert pd.isna(result.loc["13", "targets_per_game"])


def test_opportunity_columns_survive_into_the_ranking() -> None:
    pool = _free_agent_pool([_pool_row("10", "WR", "gwa", True, full_name="WR A")])
    result = build_waiver_wire_rankings(
        pool, OPPORTUNITY_WEEKS, 2025, 4, ROSTER_POSITIONS, NUM_TEAMS, PARAMETERS
    )
    assert set(OPPORTUNITY_SUMMARY_COLUMNS).issubset(WAIVER_WIRE_RANKING_COLUMNS)
    assert result.iloc[0]["target_share"] == pytest.approx(0.20)
